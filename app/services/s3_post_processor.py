"""
Постобработка результатов конвертации для загрузки изображений в S3.
"""

import os
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

from app.config.s3_config import get_s3_config, is_s3_enabled
# try:
#     from app.converters.simple_s3_uploader import create_s3_markdown
# except ImportError as e:
#     logger.error(f"Failed to import create_s3_markdown: {e}")
#     create_s3_markdown = None


def process_result_with_s3(
    task_id: str,
    markdown_path: str,
    images_dir: Optional[str],
    result_zip_path: str,
    original_filename: str
) -> Tuple[str, int]:
    """
    Обрабатывает результат конвертации, загружая ZIP архив в S3.
    
    Args:
        task_id: ID задачи
        markdown_path: Путь к Markdown файлу
        images_dir: Директория с изображениями (может быть None)
        result_zip_path: Путь к ZIP архиву с результатами
        original_filename: Оригинальное имя файла
        
    Returns:
        (S3 URL загруженного файла или None, 0 - для совместимости)
    """
    # Если S3 не включен - возвращаем None
    if not is_s3_enabled():
        logger.info(f"S3 is not enabled for task {task_id}")
        return None, 0
        
    # Проверяем что ZIP файл существует
    if not result_zip_path or not os.path.exists(result_zip_path):
        logger.error(f"ZIP file not found for task {task_id}: {result_zip_path}")
        return None, 0
        
    logger.info(f"Uploading ZIP to S3 for task {task_id}")
    
    try:
        # Импортируем функцию загрузки из s3_uploader
        from app.services.s3_uploader import upload_result_to_s3
        
        # Загружаем ZIP в S3
        s3_url = upload_result_to_s3(
            zip_path=result_zip_path,
            original_filename=original_filename,
            task_id=task_id
        )
        
        if s3_url:
            logger.info(f"Successfully uploaded ZIP to S3: {s3_url}")
            return s3_url, 0  # Возвращаем URL и 0 для совместимости
        else:
            logger.error(f"Failed to upload ZIP to S3 for task {task_id}")
            return None, 0
            
    except Exception as e:
        logger.error(f"Error uploading ZIP to S3: {e}")
        return None, 0