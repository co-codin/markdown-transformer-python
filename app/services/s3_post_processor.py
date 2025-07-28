"""
Постобработка результатов конвертации для загрузки изображений в S3.
"""

import os
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

from app.config.s3_config import get_s3_config, is_s3_enabled
try:
    from app.converters.simple_s3_uploader import create_s3_markdown
except ImportError as e:
    logger.error(f"Failed to import create_s3_markdown: {e}")
    create_s3_markdown = None


def process_result_with_s3(
    task_id: str,
    markdown_path: str,
    images_dir: Optional[str]
) -> Tuple[str, int]:
    """
    Обрабатывает результат конвертации, загружая изображения в S3.
    
    Args:
        task_id: ID задачи
        markdown_path: Путь к Markdown файлу
        images_dir: Директория с изображениями (может быть None)
        
    Returns:
        (путь к финальному markdown, количество загруженных изображений)
    """
    # Если S3 не включен или нет изображений - возвращаем как есть
    if not is_s3_enabled():
        logger.info(f"S3 is not enabled for task {task_id}")
        return markdown_path, 0
        
    if not images_dir or not os.path.exists(images_dir):
        logger.info(f"No images directory for task {task_id}")
        return markdown_path, 0
        
    # Проверяем есть ли изображения
    image_count = 0
    for root, dirs, files in os.walk(images_dir):
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg')):
                image_count += 1
                
    if image_count == 0:
        logger.info(f"No images found for task {task_id}, skipping S3 upload")
        return markdown_path, 0
        
    logger.info(f"Processing {image_count} images for S3 upload (task {task_id})")
    
    try:
        # Получаем конфигурацию S3
        s3_config = get_s3_config()
        if not s3_config:
            logger.warning("S3 config not found, skipping upload")
            return markdown_path, 0
            
        # Убираем флаг enabled из конфига для uploader
        config_for_uploader = {k: v for k, v in s3_config.items() if k != 'enabled'}
        
        # Проверяем что функция импортирована
        if create_s3_markdown is None:
            logger.error("create_s3_markdown function not available")
            return markdown_path, 0
            
        # Создаем Markdown с S3 ссылками
        s3_markdown_path = create_s3_markdown(
            markdown_path, 
            images_dir, 
            task_id,
            config_for_uploader
        )
        
        if s3_markdown_path and os.path.exists(s3_markdown_path):
            logger.info(f"Created S3 markdown: {s3_markdown_path}")
            
            # Заменяем оригинальный файл
            os.replace(s3_markdown_path, markdown_path)
            
            # Можем удалить локальные изображения после загрузки
            # (опционально, сейчас оставляем как backup)
            
            return markdown_path, image_count
        else:
            logger.warning("Failed to create S3 markdown")
            return markdown_path, 0
            
    except Exception as e:
        logger.error(f"Error processing S3 upload: {e}")
        return markdown_path, 0