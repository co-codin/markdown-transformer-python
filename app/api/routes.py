from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import FileResponse
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



# Try to import PDF Bridge converter
try:
    from app.converters.pdf_bridge_converter import PdfBridgeConverter
    pdf_bridge_converter = PdfBridgeConverter()
    PDF_BRIDGE_AVAILABLE = True
except ImportError:
    pdf_bridge_converter = None
    PDF_BRIDGE_AVAILABLE = False
    logger.warning("PDF Bridge converter not available.")

# Try to import Marker converter
try:
    from app.converters.marker_converter import MarkerConverter
    marker_converter = MarkerConverter()
    MARKER_AVAILABLE = True
except ImportError:
    marker_converter = None
    MARKER_AVAILABLE = False
    logger.warning("Marker not installed. Enhanced PDF conversion will not be available.")


router = APIRouter()






async def process_conversion(
    task_id: uuid.UUID,
    file_path: str,
    original_filename: str,
    type_result: str = "norm"
):
    """Background task for document conversion."""
    try:
        # Update status
        await task_db.update_task_status(
            str(task_id), 
            StatusEnum.PROCESSING, 
            "Converting document..."
        )
        
        # Determine converter based on file format
        file_ext = get_file_extension(original_filename)
        
        # Логика выбора конвертера:
        # 1. Marker для форматов, которые он поддерживает напрямую
        # 2. PDF Bridge для форматов, требующих конвертации через PDF
        if file_ext in MARKER_FORMATS and MARKER_AVAILABLE:
            converter = marker_converter
            logger.info(f"Using MarkerConverter for {file_ext} (direct conversion)")
        elif file_ext in PDF_BRIDGE_FORMATS and PDF_BRIDGE_AVAILABLE:
            converter = pdf_bridge_converter
            logger.info(f"Using PdfBridgeConverter for {file_ext} (LibreOffice → PDF → Marker)")
        else:
            if not MARKER_AVAILABLE:
                raise ValueError("Marker is not installed. Please install marker-pdf.")
            raise ValueError(f"Unsupported format: {file_ext}")
        
        # Create output directory
        output_dir = os.path.join(RESULTS_DIR, str(task_id))
        os.makedirs(output_dir, exist_ok=True)
        
        # Convert document
        logger.info(f"Converting {original_filename} with {converter.__class__.__name__}, type_result={type_result}")
        markdown_path, images_dir = await converter.convert(file_path, output_dir)
        
        # Обработка с S3 если включено
        logger.info(f"До S3 обработки: markdown_path={markdown_path}, images_dir={images_dir}")
        from app.services.s3_post_processor import process_result_with_s3
        original_markdown_path = markdown_path
        markdown_path, s3_images_count = process_result_with_s3(
            str(task_id),
            markdown_path,
            images_dir
        )
        logger.info(f"После S3 обработки: s3_images_count={s3_images_count}, markdown_path={markdown_path}")
        
        # Update status
        await task_db.update_task_status(
            str(task_id),
            StatusEnum.PROCESSING,
            "Creating archive..."
        )
        
        # Create ZIP archive
        file_ext = get_file_extension(original_filename).replace('.', '')
        zip_filename = f"{Path(original_filename).stem}_{file_ext}_converted.zip"
        zip_path = os.path.join(output_dir, zip_filename)
        
        # В режиме test включаем изображения в архив
        if type_result == "test":
            create_result_zip(markdown_path, images_dir, zip_path)
        else:
            # В режиме norm только markdown
            create_result_zip(markdown_path, None, zip_path)
        
        # Update task as completed
        await task_db.update_task_status(
            str(task_id),
            StatusEnum.COMPLETED,
            'Conversion completed successfully'
        )
        await task_db.update_task_result(
            str(task_id),
            zip_path,
            100
        )
        
        logger.info(f"Task {task_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}")
        await task_db.update_task_status(
            str(task_id),
            StatusEnum.FAILED,
            f'Error: {str(e)}'
        )
        await task_db.update_task_result(
            str(task_id),
            "",
            0
        )


@router.post("/convert", response_model=ConversionResponse)
async def convert_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    type_result: str = Form("norm")
):
    """
    Upload a document for conversion to Markdown.
    
    Supported formats: doc, docx, odt, rtf, epub, html, htm, pptx, pdf, xls, xlsx
    
    Parameters:
    - file: Document file to convert
    - type_result: "norm" (only markdown) or "test" (markdown + images for verification)
    """
    try:
        # Validate format
        if not is_format_supported(file.filename, SUPPORTED_FORMATS):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format. Supported: {', '.join(SUPPORTED_FORMATS)}"
            )
        
        # Check file size
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024} MB"
            )
        
        # Обработка ZIP файлов
        original_filename = file.filename
        file_content = await file.read()
        
        if get_file_extension(file.filename) == 'zip':
            # Создаем временную директорию для распаковки
            with tempfile.TemporaryDirectory() as temp_dir:
                # Сохраняем ZIP
                zip_path = os.path.join(temp_dir, "archive.zip")
                with open(zip_path, "wb") as f:
                    f.write(file_content)
                
                # Распаковываем
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        zf.extractall(temp_dir)
                except zipfile.BadZipFile:
                    raise HTTPException(
                        status_code=400,
                        detail="Поврежденный ZIP архив"
                    )
                
                # Ищем документ в корне архива
                document_found = None
                unsupported_files = []
                
                for item in os.listdir(temp_dir):
                    if item == "archive.zip":
                        continue
                    item_path = os.path.join(temp_dir, item)
                    if os.path.isfile(item_path):
                        ext = get_file_extension(item)
                        # Проверяем только документы (без zip)
                        if ext in [fmt for fmt in SUPPORTED_FORMATS if fmt != 'zip']:
                            if document_found:
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"В ZIP архиве найдено несколько документов: {document_found} и {item}. Поддерживается только ОДИН документ."
                                )
                            document_found = item
                            document_path = item_path
                        else:
                            unsupported_files.append(item)
                
                if not document_found:
                    if unsupported_files:
                        raise HTTPException(
                            status_code=400,
                            detail=f"В ZIP архиве найден файл с неподдерживаемым форматом: {unsupported_files[0]}. Поддерживаемые форматы: {', '.join([fmt for fmt in SUPPORTED_FORMATS if fmt != 'zip'])}"
                        )
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail="ZIP архив пустой или содержит только папки"
                        )
                
                # Читаем содержимое найденного документа
                with open(document_path, "rb") as f:
                    file_content = f.read()
                
                # Обновляем имя файла для дальнейшей обработки
                original_filename = document_found
                logger.info(f"Extracted document from ZIP: {document_found}")
        
        # Generate task ID
        task_id = uuid.uuid4()
        
        # Create task directory
        task_dir = os.path.join(UPLOAD_DIR, str(task_id))
        os.makedirs(task_dir, exist_ok=True)
        
        # Save uploaded file
        # Безопасная обработка имени файла для защиты от path traversal
        safe_filename = sanitize_filename(original_filename)
        file_path = os.path.join(task_dir, safe_filename)
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        # Create task in database
        await task_db.create_task(
            str(task_id),
            {
                'original_filename': original_filename,
                'status': StatusEnum.PENDING,
                'message': 'Task queued for processing',
                'progress': 0,
                'type_result': type_result
            }
        )
        
        # Add background task
        background_tasks.add_task(
            process_conversion,
            task_id,
            file_path,
            original_filename,
            type_result
        )
        
        return ConversionResponse(
            task_id=task_id,
            status=StatusEnum.PENDING,
            message='Task queued for processing'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating task: {e}")
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
        s3_enabled=is_s3_enabled(),
        type_result=task.get('type_result', 'norm')
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