"""
Конфигурация для S3 интеграции (опциональная).
"""

import os
from typing import Optional, Dict, Any


def get_s3_config() -> Optional[Dict[str, Any]]:
    """
    Получает конфигурацию S3 из переменных окружения.
    
    Returns:
        Словарь с конфигурацией или None если S3 не настроен
    """
    # Проверяем обязательные переменные
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    bucket_name = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    
    if not all([access_key, secret_key, bucket_name]):
        return None
        
    # Формируем конфигурацию
    config = {
        'enabled': True,
        'access_key': access_key,
        'secret_key': secret_key,
        'bucket_name': bucket_name,
        'region': os.environ.get('AWS_S3_REGION_NAME', 'us-east-1'),
        'endpoint_url': os.environ.get('AWS_S3_ENDPOINT_URL'),
        'folder_prefix': os.environ.get('S3_FOLDER_PREFIX', 'markdown-images')
    }
    
    return config


def is_s3_enabled() -> bool:
    """Проверяет, включена ли S3 интеграция."""
    return get_s3_config() is not None


# Пример использования в README для S3
S3_SETUP_EXAMPLE = """
# Настройка S3 для хранения изображений

## 1. Установите boto3:
pip install boto3

## 2. Настройте переменные окружения:
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_STORAGE_BUCKET_NAME="your-bucket-name"
export AWS_S3_REGION_NAME="us-east-1"  # опционально
export S3_FOLDER_PREFIX="markdown-images"  # опционально

## 3. Перезапустите сервис

После настройки все изображения из конвертированных документов
будут автоматически загружаться в S3, а в Markdown будут
вставлены прямые ссылки на S3.

## Отключение S3
Просто удалите переменные окружения и перезапустите сервис.
"""