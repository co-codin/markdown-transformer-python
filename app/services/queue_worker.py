"""
Queue Worker - Фоновый обработчик задач из очереди SQLite.
Реализует Pure SQLite Queue архитектуру без in-memory компонентов.
"""

import asyncio
import logging
import os
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

from app.api.database import TaskDatabase
from app.converters.base import BaseConverter
from app.converters.marker_converter import MarkerConverter
from app.converters.pdf_bridge_converter import PdfBridgeConverter
from app.config.settings import (
    UPLOAD_DIR, RESULTS_DIR, S3_ENABLED,
    AWS_STORAGE_BUCKET_NAME, S3_FOLDER_PREFIX,
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_S3_REGION_NAME, AWS_S3_ENDPOINT_URL
)

# КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #1: Импортируем РЕАЛЬНЫЕ функции
from app.utils.file_utils import create_result_zip  # Реальная функция создания ZIP
from app.services.s3_uploader import upload_result_to_s3  # Реальная функция загрузки в S3

logger = logging.getLogger(__name__)

# ИСПРАВЛЕНИЕ #5: ThreadPoolExecutor для синхронных операций
executor = ThreadPoolExecutor(max_workers=4)


def secure_filename(filename: str) -> str:
    """
    Защищает имя файла от path traversal атак.
    
    Args:
        filename: Исходное имя файла
        
    Returns:
        Безопасное имя файла
    """
    # Берем только имя файла без пути
    filename = os.path.basename(filename)
    # Удаляем опасные символы
    filename = filename.replace("..", "")
    filename = filename.replace("/", "_")
    filename = filename.replace("\\", "_")
    return filename


def calculate_file_hash(file_path: str) -> str:
    """
    Вычисляет SHA256 хэш файла для кеширования.
    
    Args:
        file_path: Путь к файлу
        
    Returns:
        SHA256 хэш файла
    """
    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


# ИСПРАВЛЕНИЕ #5: Асинхронные обертки для синхронных функций
async def async_create_result_zip(markdown_path: str, images_dir: Optional[str], output_path: str) -> str:
    """
    Асинхронная обертка для синхронной функции create_result_zip.
    
    Args:
        markdown_path: Путь к markdown файлу
        images_dir: Путь к папке с изображениями
        output_path: Путь для сохранения ZIP
        
    Returns:
        Путь к созданному ZIP файлу
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor,
        create_result_zip,
        markdown_path,
        images_dir,
        output_path
    )


async def async_upload_result_to_s3(
    zip_path: str,
    original_filename: str,
    task_id: str,
    bucket_name: Optional[str] = None
) -> Optional[str]:
    """
    Асинхронная обертка для синхронной функции upload_result_to_s3.
    
    Args:
        zip_path: Путь к ZIP файлу
        original_filename: Оригинальное имя файла
        task_id: ID задачи
        bucket_name: Имя S3 bucket
        
    Returns:
        URL загруженного файла или None
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor,
        upload_result_to_s3,
        zip_path,
        original_filename,
        task_id,
        bucket_name
    )


async def async_calculate_file_hash(file_path: str) -> str:
    """
    Асинхронная обертка для вычисления хэша файла.
    
    Args:
        file_path: Путь к файлу
        
    Returns:
        SHA256 хэш файла
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, calculate_file_hash, file_path)


class ConverterFactory:
    """Фабрика для создания конвертеров по расширению файла."""
    
    CONVERTERS = {
        '.pdf': MarkerConverter,
        '.epub': MarkerConverter,
        '.doc': PdfBridgeConverter,
        '.docx': PdfBridgeConverter,
        '.odt': PdfBridgeConverter,
        '.rtf': PdfBridgeConverter,
        '.xls': PdfBridgeConverter,
        '.xlsx': PdfBridgeConverter,
        '.pptx': PdfBridgeConverter,
    }
    
    @classmethod
    def get_converter(cls, file_extension: str) -> BaseConverter:
        """
        Возвращает экземпляр конвертера для данного расширения.
        
        Args:
            file_extension: Расширение файла (с точкой)
            
        Returns:
            Экземпляр конвертера
            
        Raises:
            ValueError: Если формат не поддерживается
        """
        converter_class = cls.CONVERTERS.get(file_extension.lower())
        if not converter_class:
            raise ValueError(f"Неподдерживаемый формат: {file_extension}")
        # Конвертеры не принимают s3_config - создаем без параметров
        return converter_class()


class QueueWorker:
    """Воркер для обработки задач из очереди SQLite."""
    
    def __init__(self, 
                 worker_id: str,
                 db_manager: TaskDatabase,
                 poll_interval: float = 1.0,
                 stale_timeout: int = 300,
                 libreoffice_semaphore: Optional[asyncio.Semaphore] = None):
        """
        Инициализация воркера.
        
        Args:
            worker_id: Уникальный ID воркера
            db_manager: Менеджер базы данных
            poll_interval: Интервал опроса очереди в секундах
            stale_timeout: Таймаут для освобождения зависших задач (секунды)
            libreoffice_semaphore: Семафор для ограничения LibreOffice процессов
        """
        self.worker_id = worker_id
        self.db = db_manager
        self.poll_interval = poll_interval
        self.stale_timeout = stale_timeout
        self.running = False
        self.current_task_id: Optional[str] = None
        self.libreoffice_semaphore = libreoffice_semaphore
        
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #4: Убираем локальный кеш - используем БД
        # self.file_cache удален - будем использовать get_task_by_hash из БД
    
    async def start(self):
        """Запускает воркер."""
        self.running = True
        logger.info(f"Воркер {self.worker_id} запущен")
        
        try:
            while self.running:
                try:
                    # Получаем следующую задачу из очереди
                    task = await self.db.get_next_queued_task(self.worker_id)
                    
                    if task:
                        self.current_task_id = task['id']
                        await self._process_task(task)
                        self.current_task_id = None
                    else:
                        # Нет задач - ждем
                        await asyncio.sleep(self.poll_interval)
                        
                except Exception as e:
                    logger.error(f"Ошибка в цикле воркера {self.worker_id}: {e}")
                    await asyncio.sleep(self.poll_interval)
                    
        except asyncio.CancelledError:
            logger.info(f"Воркер {self.worker_id} остановлен")
            raise
    
    async def stop(self):
        """Останавливает воркер."""
        self.running = False
        
        # Освобождаем текущую задачу, если есть
        if self.current_task_id:
            await self.db.update_task(
                self.current_task_id,
                {
                    'status': 'queued',
                    'worker_id': None,
                    'processing_started': None
                }
            )
    
    async def _process_task(self, task: Dict[str, Any]):
        """
        Обрабатывает одну задачу.
        
        Args:
            task: Данные задачи из БД
        """
        task_id = task['id']
        logger.info(f"Воркер {self.worker_id} начал обработку задачи {task_id}")
        
        try:
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #4: Используем БД для проверки кеша
            file_hash = task.get('file_hash')
            if file_hash:
                cached_task = await self.db.get_task_by_hash(file_hash)
                if cached_task and cached_task.get('result_path'):
                    if os.path.exists(cached_task['result_path']):
                        logger.info(f"Используем кешированный результат для {task_id}")
                        
                        await self.db.update_task(
                            task_id,
                            {
                                'status': 'completed',
                                'result_path': cached_task['result_path'],
                                's3_url': cached_task.get('s3_url'),
                                'progress': 100,
                                'message': 'Использован кешированный результат'
                            }
                        )
                        return
            
            # Пути файлов
            upload_path = os.path.join(UPLOAD_DIR, task_id)
            result_dir = os.path.join(RESULTS_DIR, task_id)
            
            # Находим загруженный файл
            original_filename = task.get('original_filename', '')
            safe_filename = secure_filename(original_filename)
            input_file = os.path.join(upload_path, safe_filename)
            
            if not os.path.exists(input_file):
                raise FileNotFoundError(f"Файл не найден: {input_file}")
            
            # Вычисляем хэш, если его нет
            if not file_hash:
                file_hash = await async_calculate_file_hash(input_file)
                await self.db.update_task(task_id, {'file_hash': file_hash})
            
            # Создаем директорию для результатов
            os.makedirs(result_dir, exist_ok=True)
            
            # Определяем тип конвертера
            file_extension = Path(original_filename).suffix.lower()
            converter = ConverterFactory.get_converter(file_extension)
            
            # Обновляем прогресс
            await self.db.update_task(task_id, {'progress': 30, 'message': 'Начата конвертация'})
            
            # Выполняем конвертацию (с семафором для LibreOffice если нужно)
            if isinstance(converter, PdfBridgeConverter) and self.libreoffice_semaphore:
                logger.info(f"Воркер {self.worker_id}: захват LibreOffice семафора для задачи {task_id}")
                async with self.libreoffice_semaphore:
                    markdown_path, images_dir = await converter.convert(input_file, result_dir)
                logger.info(f"Воркер {self.worker_id}: освобождение LibreOffice семафора для задачи {task_id}")
            else:
                markdown_path, images_dir = await converter.convert(input_file, result_dir)
            
            # Обновляем прогресс
            await self.db.update_task(task_id, {'progress': 70, 'message': 'Создание результата'})
            
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Создаем ZIP с правильным путем
            # Имя ZIP файла должно быть основано на оригинальном имени
            base_name = Path(original_filename).stem
            extension = Path(original_filename).suffix.lstrip('.')  # Убираем точку из расширения
            if extension:
                zip_filename = f"{base_name}_{extension}_result.zip"
            else:
                zip_filename = f"{base_name}_result.zip"
            zip_path = os.path.join(result_dir, zip_filename)
            
            # ZEN ИСПРАВЛЕНИЕ #3: Обработка runtime ошибок для надежности
            actual_zip_path = None
            s3_url = None
            
            try:
                # Создаем ZIP архив (используем реальную функцию)
                actual_zip_path = await async_create_result_zip(
                    markdown_path,
                    images_dir,
                    zip_path
                )
                logger.info(f"ZIP архив создан: {actual_zip_path}")
                
                # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #1: Правильная S3 интеграция
                if S3_ENABLED:
                    try:
                        logger.info(f"Загружаем результат в S3 для задачи {task_id}")
                        s3_url = await async_upload_result_to_s3(
                            actual_zip_path,
                            original_filename,
                            task_id,
                            AWS_STORAGE_BUCKET_NAME
                        )
                        
                        if s3_url:
                            logger.info(f"Результат загружен в S3: {s3_url}")
                        else:
                            logger.warning(f"Не удалось загрузить в S3 для задачи {task_id}")
                            
                    except Exception as s3_error:
                        logger.error(f"Ошибка S3 для задачи {task_id}: {s3_error}")
                        # S3 необязателен, продолжаем с локальным файлом
                
                # Обновляем задачу как выполненную
                await self.db.update_task(
                    task_id,
                    {
                        'status': 'completed',
                        'result_path': actual_zip_path,  # Прямой путь к ZIP файлу
                        's3_url': s3_url,
                        'progress': 100,
                        'message': 'Конвертация завершена успешно'
                    }
                )
                
                logger.info(f"Задача {task_id} успешно выполнена воркером {self.worker_id}")
                
            except Exception as processing_error:
                # ZEN ИСПРАВЛЕНИЕ #3: Обработка ошибок создания ZIP и S3
                error_msg = f"Ошибка создания результата: {str(processing_error)}"
                logger.error(f"Ошибка в создании результата для задачи {task_id}: {error_msg}")
                logger.error(traceback.format_exc())
                
                # Обновляем статус как неудачный
                await self.db.update_task(
                    task_id,
                    {
                        'status': 'failed',
                        'message': error_msg,
                        'progress': 0
                    }
                )
                
                # Очищаем частично созданные файлы
                if actual_zip_path and os.path.exists(actual_zip_path):
                    try:
                        os.remove(actual_zip_path)
                    except Exception as cleanup_error:
                        logger.error(f"Ошибка очистки файла {actual_zip_path}: {cleanup_error}")
            
        except Exception as e:
            error_msg = f"Ошибка обработки: {str(e)}"
            logger.error(f"Ошибка в задаче {task_id}: {error_msg}")
            logger.error(traceback.format_exc())
            
            await self.db.update_task(
                task_id,
                {
                    'status': 'failed',
                    'message': error_msg,
                    'progress': 0
                }
            )


class QueueWorkerPool:
    """Пул воркеров для обработки очереди."""
    
    def __init__(self, 
                 db_manager: TaskDatabase,
                 num_workers: int = 3,
                 poll_interval: float = 1.0,
                 stale_timeout: int = 300,
                 stale_check_interval: int = 60):
        """
        Инициализация пула воркеров.
        
        Args:
            db_manager: Менеджер базы данных
            num_workers: Количество воркеров
            poll_interval: Интервал опроса очереди
            stale_timeout: Таймаут для зависших задач
            stale_check_interval: Интервал проверки зависших задач
        """
        self.db = db_manager
        self.num_workers = num_workers
        self.poll_interval = poll_interval
        self.stale_timeout = stale_timeout
        self.stale_check_interval = stale_check_interval
        
        self.workers = []
        self.worker_tasks = []
        self.stale_task = None
        self.running = False
        self.libreoffice_semaphore = asyncio.Semaphore(2)  # Лимит параллельных LibreOffice процессов
        
        # ZEN ИСПРАВЛЕНИЕ #2: Блокировка для предотвращения race conditions в кешировании
        self.processing_lock = asyncio.Lock()
    
    async def start(self):
        """Запускает пул воркеров."""
        self.running = True
        
        # Создаем и запускаем воркеры
        for i in range(self.num_workers):
            worker_id = f"worker_{i+1}"
            worker = QueueWorker(
                worker_id=worker_id,
                db_manager=self.db,
                poll_interval=self.poll_interval,
                stale_timeout=self.stale_timeout,
                libreoffice_semaphore=self.libreoffice_semaphore
            )
            self.workers.append(worker)
            
            task = asyncio.create_task(worker.start())
            self.worker_tasks.append(task)
        
        # Запускаем проверку зависших задач
        self.stale_task = asyncio.create_task(self._release_stale_tasks())
        
        logger.info(f"Запущен пул из {self.num_workers} воркеров")
    
    async def stop(self):
        """Останавливает пул воркеров."""
        self.running = False
        
        # Останавливаем воркеры
        for worker in self.workers:
            await worker.stop()
        
        # Отменяем задачи
        for task in self.worker_tasks:
            task.cancel()
        
        if self.stale_task:
            self.stale_task.cancel()
        
        # Ждем завершения
        await asyncio.gather(*self.worker_tasks, self.stale_task, return_exceptions=True)
        
        # ZEN ИСПРАВЛЕНИЕ #4: Graceful shutdown executor
        executor.shutdown(wait=True)
        
        logger.info("Пул воркеров остановлен")
    
    async def _release_stale_tasks(self):
        """
        Периодически освобождает зависшие задачи.
        Выполняется только в одном экземпляре для всего пула!
        """
        while self.running:
            try:
                released = await self.db.release_stale_tasks(self.stale_timeout)
                if released > 0:
                    logger.info(f"Освобождено {released} зависших задач")
                    
            except Exception as e:
                logger.error(f"Ошибка при освобождении зависших задач: {e}")
            
            await asyncio.sleep(self.stale_check_interval)