"""
Простой S3 загрузчик без Django зависимостей.
"""

import os
import re
import hashlib
import mimetypes
from typing import Dict, Optional, Tuple
import logging

try:
    import boto3
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

logger = logging.getLogger(__name__)


class SimpleS3Uploader:
    """Простой загрузчик изображений в S3 используя boto3."""
    
    def __init__(self, 
                 access_key: Optional[str] = None,
                 secret_key: Optional[str] = None,
                 bucket_name: Optional[str] = None,
                 region: str = 'us-east-1',
                 endpoint_url: Optional[str] = None,
                 folder_prefix: str = 'markdown-images'):
        """
        Инициализация S3 клиента.
        
        Args:
            access_key: AWS Access Key (если None - из окружения)
            secret_key: AWS Secret Key (если None - из окружения)
            bucket_name: Имя S3 bucket
            region: AWS регион
            endpoint_url: Custom S3 endpoint (для S3-совместимых сервисов)
            folder_prefix: Префикс папки в bucket
        """
        if not HAS_BOTO3:
            raise ImportError("Установите boto3: pip install boto3")
            
        # Получаем credentials
        self.access_key = access_key or os.environ.get('AWS_ACCESS_KEY_ID')
        self.secret_key = secret_key or os.environ.get('AWS_SECRET_ACCESS_KEY')
        self.bucket_name = bucket_name or os.environ.get('AWS_STORAGE_BUCKET_NAME')
        self.region = region or os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
        self.endpoint_url = endpoint_url or os.environ.get('AWS_S3_ENDPOINT_URL')
        
        # Убираем кавычки если есть
        if self.endpoint_url and self.endpoint_url.startswith('"'):
            self.endpoint_url = self.endpoint_url.strip('"')
        
        if not all([self.access_key, self.secret_key, self.bucket_name]):
            raise ValueError("Необходимы AWS credentials и bucket name")
            
        self.folder_prefix = folder_prefix
        
        # Создаем S3 клиент
        from botocore.config import Config
        
        # Для Beget и других S3-совместимых сервисов используем signature v2
        config = Config(
            signature_version='s3',  # v2 для совместимости
            s3={'addressing_style': 'path'}
        )
        
        client_params = {
            'aws_access_key_id': self.access_key,
            'aws_secret_access_key': self.secret_key,
            'region_name': self.region,
            'config': config
        }
        
        if self.endpoint_url:
            client_params['endpoint_url'] = self.endpoint_url
            client_params['verify'] = False  # Для самоподписанных сертификатов
            
        self.s3_client = boto3.client('s3', **client_params)
        
        # Проверяем доступ к bucket
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"S3 bucket '{self.bucket_name}' доступен")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                raise ValueError(f"Bucket '{self.bucket_name}' не найден")
            elif error_code == '403':
                # Для Beget S3 head_bucket может возвращать 403
                # Пропускаем эту проверку
                logger.warning(f"S3 bucket check returned 403, skipping (Beget S3 compatibility)")
            else:
                raise ValueError(f"Ошибка доступа к bucket: {error_code}")
                
    def upload_image(self, image_path: str, task_id: str) -> Optional[str]:
        """
        Загружает изображение в S3.
        
        Args:
            image_path: Путь к изображению
            task_id: ID задачи для организации
            
        Returns:
            Публичный URL изображения или None при ошибке
        """
        # Используем новую модульную функцию
        from app.services.s3_uploader import upload_to_s3, generate_s3_key
        
        # Генерируем S3 ключ
        prefix = f"{self.folder_prefix}/{task_id}"
        s3_key = generate_s3_key(image_path, prefix=prefix, add_hash=True)
        
        # Загружаем файл
        url = upload_to_s3(image_path, s3_key, bucket_name=self.bucket_name, make_public=True)
        
        if url:
            logger.info(f"Изображение загружено через модульную функцию: {image_path} -> {url}")
        else:
            logger.error(f"Не удалось загрузить изображение: {image_path}")
            
        return url
            
    def process_markdown(self, markdown_content: str, 
                        images_dir: str, task_id: str) -> Tuple[str, Dict[str, str]]:
        """
        Обрабатывает Markdown, загружая изображения в S3.
        
        Args:
            markdown_content: Содержимое Markdown
            images_dir: Директория с изображениями
            task_id: ID задачи
            
        Returns:
            (обновленный markdown, словарь путь -> url)
        """
        # Паттерн для поиска изображений
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
                
            # Полный путь
            # Если путь начинается с images/, убираем это, так как images_dir уже содержит это
            if image_path.startswith('images/'):
                image_path = image_path[7:]  # Убираем 'images/'
            full_path = os.path.join(images_dir, image_path)
            
            # Если уже загружали - используем кэш
            if full_path in uploaded_images:
                s3_url = uploaded_images[full_path]
            else:
                # Загружаем в S3
                s3_url = self.upload_image(full_path, task_id)
                if s3_url:
                    uploaded_images[full_path] = s3_url
                else:
                    # Оставляем как есть если не удалось
                    return match.group(0)
                    
            # Возвращаем обновленную ссылку
            return f'![{alt_text}]({s3_url})'
            
        # Заменяем все ссылки
        updated_content = re.sub(image_pattern, replace_image, markdown_content)
        
        return updated_content, uploaded_images


def create_s3_markdown(markdown_path: str, images_dir: str, 
                      task_id: str, s3_config: Dict) -> Optional[str]:
    """
    Создает Markdown с изображениями в S3.
    
    Args:
        markdown_path: Путь к Markdown файлу
        images_dir: Директория с изображениями
        task_id: ID задачи
        s3_config: Конфигурация S3
        
    Returns:
        Путь к обновленному файлу или None
    """
    if not HAS_BOTO3:
        logger.warning("boto3 не установлен, S3 загрузка недоступна")
        return None
        
    try:
        # Читаем Markdown
        with open(markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Создаем uploader
        uploader = SimpleS3Uploader(**s3_config)
        
        # Обрабатываем
        updated_content, uploaded = uploader.process_markdown(
            content, images_dir, task_id
        )
        
        if uploaded:
            # Сохраняем результат
            output_path = markdown_path.replace('.md', '_s3.md')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
                
            logger.info(f"Создан S3 Markdown: {output_path}")
            logger.info(f"Загружено изображений: {len(uploaded)}")
            return output_path
        else:
            logger.info("Нет изображений для загрузки")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка создания S3 Markdown: {e}")
        return None