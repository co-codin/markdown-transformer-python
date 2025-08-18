from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, PlainTextResponse
from typing import Optional
import uuid
import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import zipfile
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
import asyncio
import hashlib
import aiofiles
import io
from fastapi.responses import JSONResponse

from app.api.schemas import (
    ConversionResponse, TaskStatusResponse, SupportedFormatsResponse,
    StatusEnum, PendingTask, PendingTasksResponse, HealthResponse
)
from app.api.database import task_db
from app.config.settings import (
    SUPPORTED_FORMATS, MARKER_FORMATS, PDF_BRIDGE_FORMATS,
    MAX_FILE_SIZE, UPLOAD_DIR, RESULTS_DIR
)
from app.utils.file_utils import (
    create_result_zip, cleanup_task_files, get_file_extension, is_format_supported,
    sanitize_filename  # Для безопасной обработки имен файлов
)

logger = logging.getLogger(__name__)



# Конвертеры теперь импортируются в QueueWorker, здесь не нужны


router = APIRouter()

# Семафор перенесен в QueueWorkerPool




# Функция process_conversion удалена - обработка теперь в QueueWorker


async def calculate_file_hash(file_content: bytes) -> str:
    """Вычислить SHA256 hash файла."""
    return hashlib.sha256(file_content).hexdigest()


@router.post("/convert", response_model=ConversionResponse)
async def convert_document(
    file: UploadFile = File(...)
):
    """
    Upload a document for conversion to Markdown.
    
    Supported formats: doc, docx, odt, rtf, epub, html, htm, pptx, pdf, xls, xlsx
    
    Parameters:
    - file: Document file to convert
    """
    try:
        # ✅ Быстрая валидация ДО загрузки
        if not is_format_supported(file.filename, SUPPORTED_FORMATS):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format. Supported: {', '.join(SUPPORTED_FORMATS)}"
            )
        
        # ✅ Генерируем ID и создаем папку сразу
        task_id = uuid.uuid4()
        task_dir = os.path.join(UPLOAD_DIR, str(task_id))
        os.makedirs(task_dir, exist_ok=True)
        
        safe_filename = sanitize_filename(file.filename)
        file_path = os.path.join(task_dir, safe_filename)
        
        # ✅ НАСТОЯЩИЙ стриминг - сохраняем сразу на диск
        total_size = 0
        hash_obj = hashlib.sha256()
        
        async with aiofiles.open(file_path, 'wb') as f:
            while chunk := await file.read(8192):  # 8KB chunks
                chunk_size = len(chunk)
                total_size += chunk_size
                
                # Проверяем размер на лету
                if total_size > MAX_FILE_SIZE:
                    await f.close()
                    os.remove(file_path)  # Удаляем частично загруженный файл
                    shutil.rmtree(task_dir, ignore_errors=True)
                    raise HTTPException(
                        status_code=400,
                        detail=f"File too large. Max: {MAX_FILE_SIZE / 1024 / 1024} MB"
                    )
                
                # Считаем hash на лету
                hash_obj.update(chunk)
                
                # Сохраняем chunk
                await f.write(chunk)
        
        file_hash = hash_obj.hexdigest()
        logger.info(f"Uploaded {total_size / 1024 / 1024:.1f}MB, hash: {file_hash[:8]}...")
        
        # ✅ Проверяем кеш
        cached_task = await task_db.get_task_by_hash(file_hash)
        if cached_task and cached_task.get('result_path'):
            if os.path.exists(cached_task['result_path']):
                logger.info(f"Cache hit for {file_hash[:8]}")
                # Удаляем только что загруженный файл (он дубликат)
                os.remove(file_path)
                shutil.rmtree(task_dir, ignore_errors=True)
                return ConversionResponse(
                    task_id=uuid.UUID(cached_task['id']),
                    status=StatusEnum.COMPLETED,
                    message='Using cached result'
                )
        
        original_filename = file.filename
        
        # ✅ Обработка ZIP БЕЗ перезагрузки
        if get_file_extension(file.filename) == 'zip':
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    # Ищем документы
                    docs = [n for n in zf.namelist() 
                           if get_file_extension(n) in [fmt for fmt in SUPPORTED_FORMATS if fmt != 'zip']
                           and not n.startswith('__MACOSX/')
                           and '/' not in n]  # только в корне архива
                    
                    if len(docs) == 0:
                        raise HTTPException(
                            status_code=400,
                            detail="ZIP архив пустой или не содержит поддерживаемых документов в корне"
                        )
                    elif len(docs) > 1:
                        raise HTTPException(
                            status_code=400,
                            detail=f"В ZIP архиве найдено {len(docs)} документов. Поддерживается только ОДИН документ."
                        )
                    
                    # Извлекаем документ
                    doc_content = zf.read(docs[0])
                    original_filename = os.path.basename(docs[0])
                    
                    # Пересчитываем hash для извлеченного документа
                    file_hash = hashlib.sha256(doc_content).hexdigest()
                    
                    # Проверяем кеш для извлеченного документа
                    cached_task = await task_db.get_task_by_hash(file_hash)
                    if cached_task and cached_task.get('result_path'):
                        if os.path.exists(cached_task['result_path']):
                            logger.info(f"Cache hit for extracted doc {file_hash[:8]}")
                            os.remove(file_path)
                            shutil.rmtree(task_dir, ignore_errors=True)
                            return ConversionResponse(
                                task_id=uuid.UUID(cached_task['id']),
                                status=StatusEnum.COMPLETED,
                                message='Using cached result'
                            )
                    
                    # Сохраняем извлеченный документ
                    new_file_path = os.path.join(task_dir, sanitize_filename(original_filename))
                    async with aiofiles.open(new_file_path, 'wb') as f:
                        await f.write(doc_content)
                    
                    # Удаляем ZIP, оставляем только документ
                    os.remove(file_path)
                    file_path = new_file_path
                    
                    logger.info(f"Extracted from ZIP: {original_filename}")
                    
            except zipfile.BadZipFile:
                raise HTTPException(
                    status_code=400,
                    detail="Поврежденный ZIP архив"
                )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ошибка обработки ZIP: {str(e)}"
                )
        
        # ✅ Создаем задачу
        await task_db.create_task(
            str(task_id),
            {
                'original_filename': original_filename,
                'status': StatusEnum.QUEUED,
                'message': 'Файл загружен и добавлен в очередь на обработку',
                'progress': 0,
                'file_hash': file_hash
            }
        )
        
        # Конвертация будет выполнена QueueWorker автоматически
        
        return ConversionResponse(
            task_id=task_id,
            status=StatusEnum.QUEUED,
            message='Файл загружен и добавлен в очередь на обработку'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: uuid.UUID):
    """Get conversion task status."""
    task = await task_db.get_task(str(task_id))
    if not task:
        raise HTTPException(
            status_code=404, 
            detail=f"Task {task_id} not found"
        )
    
    # Check if S3 is enabled
    from app.config.s3_config import is_s3_enabled
    
    response = TaskStatusResponse(
        task_id=task_id,
        status=task['status'],
        progress=task.get('progress', 0),
        message=task['message'],
        created_at=str(datetime.fromtimestamp(task['created_at'])),
        s3_enabled=is_s3_enabled()
    )
    
    # Add download URL if completed
    if task['status'] == StatusEnum.COMPLETED:
        response.result_url = f"/api/v1/download/{task_id}"
    
    return response


async def cleanup_after_download(task_id: str):
    """Background task to cleanup files after download."""
    try:
        # Wait a bit to ensure download completed
        await asyncio.sleep(2)
        
        # Mark as downloaded
        await task_db.update_task(task_id, {"downloaded": True})
        
        # Cleanup files
        cleanup_task_files(task_id, UPLOAD_DIR, RESULTS_DIR)
        
        # Delete task from database
        await task_db.delete_task(task_id)
        
        logger.info(f"Cleaned up files and database record for task {task_id}")
        
    except Exception as e:
        logger.error(f"Error cleaning up task {task_id}: {e}")


@router.get("/download/{task_id}")
async def download_result(task_id: uuid.UUID, background_tasks: BackgroundTasks):
    """Download conversion result."""
    task = await task_db.get_task(str(task_id))
    if not task:
        raise HTTPException(
            status_code=404, 
            detail=f"Task {task_id} not found"
        )
    
    if task['status'] != StatusEnum.COMPLETED:
        raise HTTPException(
            status_code=400, 
            detail="Task not completed yet"
        )
    
    # Проверяем, есть ли S3 URL
    s3_url = task.get('s3_url')
    
    if s3_url:
        # Если есть S3 URL, возвращаем его как plain text
        logger.info(f"Returning S3 URL for task {task_id}: {s3_url}")
        # Schedule cleanup
        background_tasks.add_task(cleanup_after_download, str(task_id))
        return JSONResponse(content={"s3_url": s3_url}, status_code=200)
    
    # Иначе возвращаем локальный файл
    result_path = task.get('result_path')
    if not result_path or not os.path.exists(result_path):
        raise HTTPException(
            status_code=404, 
            detail="Result file not found"
        )
    
    # Schedule cleanup
    background_tasks.add_task(cleanup_after_download, str(task_id))
    
    return FileResponse(
        result_path,
        filename=os.path.basename(result_path),
        media_type="application/zip"
    )


@router.get("/formats", response_model=SupportedFormatsResponse)
async def get_supported_formats():
    """Get list of supported formats."""
    return SupportedFormatsResponse(
        formats=SUPPORTED_FORMATS
    )


@router.get("/tasks/pending", response_model=PendingTasksResponse)
async def get_pending_tasks():
    """Get all pending (not downloaded) tasks."""
    try:
        db_tasks = await task_db.get_pending_tasks()
        
        tasks = []
        for db_task in db_tasks:
            tasks.append(PendingTask(
                task_id=uuid.UUID(db_task['id']),
                original_filename=db_task['original_filename'],
                status=db_task['status'],
                created_at=str(datetime.fromtimestamp(db_task['created_at'])),
                progress=db_task.get('progress', 0),
                downloaded=bool(db_task['downloaded'])
            ))
        
        return PendingTasksResponse(
            tasks=tasks,
            total=len(tasks)
        )
        
    except Exception as e:
        logger.error(f"Error getting pending tasks: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving tasks: {str(e)}"
        )


@router.get("/queue/stats")
async def get_queue_statistics():
    """Get queue statistics."""
    try:
        stats = await task_db.get_queue_statistics()
        return {
            "status": "success",
            "statistics": stats
        }
    except Exception as e:
        logger.error(f"Error getting queue statistics: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving queue statistics: {str(e)}"
        )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check service health."""
    health_status = {
        "status": "healthy",
        "version": "1.0.0",
        "database": False,
        "s3_enabled": False,
        "s3_connected": None,
        "supported_formats": len(SUPPORTED_FORMATS),
        "pending_tasks": 0
    }
    
    try:
        # Проверка базы данных
        pending_tasks = await task_db.get_pending_tasks()
        health_status["database"] = True
        health_status["pending_tasks"] = len(pending_tasks)
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        health_status["status"] = "degraded"
        
    # Проверка S3
    from app.config.s3_config import is_s3_enabled
    health_status["s3_enabled"] = is_s3_enabled()
    
    if health_status["s3_enabled"]:
        try:
            # Проверяем подключение к S3
            import boto3
            from botocore.config import Config
            import os
            
            config = Config(signature_version='s3')
            s3_client = boto3.client(
                's3',
                aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                endpoint_url=os.environ.get('AWS_S3_ENDPOINT_URL', '').strip('"'),
                region_name=os.environ.get('AWS_S3_REGION_NAME', 'ru1'),
                config=config,
                verify=False
            )
            
            bucket_name = os.environ.get('AWS_STORAGE_BUCKET_NAME')
            s3_client.head_bucket(Bucket=bucket_name)
            health_status["s3_connected"] = True
        except Exception as e:
            logger.warning(f"S3 connection check failed: {e}")
            health_status["s3_connected"] = False
            # S3 необязателен, поэтому не меняем общий статус
    
    return HealthResponse(**health_status)