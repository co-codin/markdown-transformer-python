"""
Модуль для загрузки изображений в S3 и замены локальных путей на URL.
"""

import os
import re
import hashlib
import mimetypes
from typing import Dict, Optional, Tuple
from pathlib import Path
import logging

try:
    from storages.backends.s3boto3 import S3Boto3Storage
    HAS_S3 = True
except ImportError:
    HAS_S3 = False

logger = logging.getLogger(__name__)


class S3ImageUploader:
    """Загружает изображения в S3 и заменяет пути в Markdown."""
    
    def __init__(self, bucket_name: Optional[str] = None, 
                 folder_prefix: str = "markdown-images",
                 public_read: bool = True):
        """
        Инициализация загрузчика.
        
        Args:
            bucket_name: Имя S3 bucket (если None - из настроек)
            folder_prefix: Префикс папки в S3
            public_read: Делать ли файлы публично доступными
        """
        if not HAS_S3:
            raise ImportError("Установите django-storages и boto3 для работы с S3")
            
        self.storage = S3Boto3Storage()
        if bucket_name:
            self.storage.bucket_name = bucket_name
            
        self.folder_prefix = folder_prefix
        self.public_read = public_read
        
    def upload_image(self, image_path: str, task_id: str) -> Optional[str]:
        """
        Загружает изображение в S3.
        
        Args:
            image_path: Путь к изображению
            task_id: ID задачи для организации файлов
            
        Returns:
            URL изображения в S3 или None при ошибке
        """
        if not os.path.exists(image_path):
            logger.error(f"Изображение не найдено: {image_path}")
            return None
            
        try:
            # Читаем файл
            with open(image_path, 'rb') as f:
                content = f.read()
                
            # Генерируем уникальное имя на основе содержимого
            file_hash = hashlib.md5(content).hexdigest()[:8]
            filename = os.path.basename(image_path)
            name, ext = os.path.splitext(filename)
            
            # Формируем путь в S3
            s3_filename = f"{self.folder_prefix}/{task_id}/{name}_{file_hash}{ext}"
            
            # Определяем content type
            content_type, _ = mimetypes.guess_type(image_path)
            if not content_type:
                content_type = 'application/octet-stream'
                
            # Загружаем в S3
            from django.core.files.base import ContentFile
            s3_path = self.storage.save(
                s3_filename, 
                ContentFile(content),
                max_length=len(s3_filename)
            )
            
            # Получаем публичный URL
            s3_url = self.storage.url(s3_path)
            
            logger.info(f"Изображение загружено: {image_path} -> {s3_url}")
            return s3_url
            
        except Exception as e:
            logger.error(f"Ошибка загрузки изображения {image_path}: {e}")
            return None
            
    def process_markdown_with_s3(self, markdown_content: str, 
                                images_dir: str, task_id: str) -> Tuple[str, Dict[str, str]]:
        """
        Обрабатывает Markdown, загружая изображения в S3.
        
        Args:
            markdown_content: Содержимое Markdown
            images_dir: Директория с изображениями
            task_id: ID задачи
            
        Returns:
            (обновленный markdown, словарь старый_путь -> s3_url)
        """
        # Находим все ссылки на изображения
        image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        uploaded_images = {}
        
        def replace_image(match):
            alt_text = match.group(1)
            image_path = match.group(2)
            
            # Пропускаем внешние URL
            if image_path.startswith(('http://', 'https://', '//')):
                return match.group(0)
                
            # Нормализуем путь
            if image_path.startswith('./'):
                image_path = image_path[2:]
                
            # Полный путь к изображению
            full_path = os.path.join(images_dir, image_path)
            
            # Если уже загружали - используем существующий URL
            if full_path in uploaded_images:
                s3_url = uploaded_images[full_path]
            else:
                # Загружаем в S3
                s3_url = self.upload_image(full_path, task_id)
                if s3_url:
                    uploaded_images[full_path] = s3_url
                else:
                    # Если не удалось загрузить - оставляем как есть
                    return match.group(0)
                    
            # Возвращаем обновленную ссылку
            return f'![{alt_text}]({s3_url})'
            
        # Заменяем все ссылки на изображения
        updated_markdown = re.sub(image_pattern, replace_image, markdown_content)
        
        return updated_markdown, uploaded_images


def create_s3_enabled_markdown(markdown_path: str, images_dir: str, 
                              task_id: str, s3_config: Optional[Dict] = None) -> str:
    """
    Создает Markdown с изображениями в S3.
    
    Args:
        markdown_path: Путь к исходному Markdown
        images_dir: Директория с изображениями
        task_id: ID задачи
        s3_config: Конфигурация S3 (опционально)
        
    Returns:
        Путь к обновленному Markdown файлу
    """
    if not HAS_S3:
        logger.warning("S3 не настроен, изображения останутся локальными")
        return markdown_path
        
    try:
        # Читаем исходный Markdown
        with open(markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Создаем загрузчик
        config = s3_config or {}
        uploader = S3ImageUploader(**config)
        
        # Обрабатываем содержимое
        updated_content, uploaded = uploader.process_markdown_with_s3(
            content, images_dir, task_id
        )
        
        if uploaded:
            # Сохраняем обновленный файл
            output_path = markdown_path.replace('.md', '_s3.md')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
                
            logger.info(f"Создан Markdown с S3 изображениями: {output_path}")
            logger.info(f"Загружено изображений: {len(uploaded)}")
            return output_path
        else:
            logger.info("Нет изображений для загрузки в S3")
            return markdown_path
            
    except Exception as e:
        logger.error(f"Ошибка при создании S3 Markdown: {e}")
        return markdown_path