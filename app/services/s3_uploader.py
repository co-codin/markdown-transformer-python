"""
Модульный S3 загрузчик с простым API.
"""

import os
import hashlib
import mimetypes
import logging
from typing import Optional, Dict
from dotenv import load_dotenv

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()


def upload_to_s3(
    file_path: str,
    s3_key: str,
    bucket_name: Optional[str] = None,
    make_public: bool = True
) -> Optional[str]:
    """
    Загружает файл в S3 и возвращает публичный URL.
    
    Args:
        file_path: Путь к локальному файлу
        s3_key: Ключ (путь) в S3 bucket
        bucket_name: Имя bucket (если None - из окружения)
        make_public: Сделать файл публично доступным
        
    Returns:
        URL загруженного файла или None при ошибке
    """
    if not HAS_BOTO3:
        logger.error("boto3 не установлен")
        return None
        
    if not os.path.exists(file_path):
        logger.error(f"Файл не найден: {file_path}")
        return None
        
    # Получаем конфигурацию
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    bucket_name = bucket_name or os.environ.get('AWS_STORAGE_BUCKET_NAME')
    region = os.environ.get('AWS_S3_REGION_NAME', 'ru1')
    endpoint_url = os.environ.get('AWS_S3_ENDPOINT_URL')
    
    # Убираем кавычки из endpoint_url
    if endpoint_url and endpoint_url.startswith('"'):
        endpoint_url = endpoint_url.strip('"')
    
    if not all([access_key, secret_key, bucket_name]):
        logger.error("Отсутствуют S3 credentials")
        return None
        
    try:
        # Конфигурация для Beget S3
        config = Config(
            signature_version='s3',  # v2 для Beget
            s3={'addressing_style': 'path'}
        )
        
        # Создаем клиент
        client_params = {
            'aws_access_key_id': access_key,
            'aws_secret_access_key': secret_key,
            'region_name': region,
            'config': config
        }
        
        if endpoint_url:
            client_params['endpoint_url'] = endpoint_url
            client_params['verify'] = False  # Для самоподписанных сертификатов
            
        s3_client = boto3.client('s3', **client_params)
        
        # Читаем файл
        with open(file_path, 'rb') as f:
            file_content = f.read()
            
        # Определяем content type
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'application/octet-stream'
            
        # Параметры загрузки
        put_params = {
            'Bucket': bucket_name,
            'Key': s3_key,
            'Body': file_content,
            'ContentType': content_type
        }
        
        if make_public:
            put_params['ACL'] = 'public-read'
            
        # Загружаем файл
        logger.info(f"Загружаем {file_path} в s3://{bucket_name}/{s3_key}")
        s3_client.put_object(**put_params)
        
        # Формируем URL
        if endpoint_url:
            url = f"{endpoint_url.rstrip('/')}/{bucket_name}/{s3_key}"
        else:
            url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"
            
        logger.info(f"Файл загружен: {url}")
        return url
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"S3 ошибка {error_code}: {e}")
        return None
    except Exception as e:
        logger.error(f"Ошибка загрузки в S3: {e}")
        return None


def generate_s3_key(file_path: str, prefix: str = "", add_hash: bool = True) -> str:
    """
    Генерирует уникальный S3 ключ для файла.
    
    Args:
        file_path: Путь к файлу
        prefix: Префикс для ключа (например, "markdown-images/task-123")
        add_hash: Добавить хеш к имени файла для уникальности
        
    Returns:
        S3 ключ
    """
    filename = os.path.basename(file_path)
    
    if add_hash:
        # Читаем файл для хеша
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()[:8]
        
        name, ext = os.path.splitext(filename)
        filename = f"{name}_{file_hash}{ext}"
    
    if prefix:
        return f"{prefix.rstrip('/')}/{filename}"
    else:
        return filename


def check_s3_file_exists(s3_key: str, bucket_name: Optional[str] = None) -> bool:
    """
    Проверяет существование файла в S3.
    
    Args:
        s3_key: Ключ файла в S3
        bucket_name: Имя bucket (если None - из окружения)
        
    Returns:
        True если файл существует
    """
    if not HAS_BOTO3:
        return False
        
    bucket_name = bucket_name or os.environ.get('AWS_STORAGE_BUCKET_NAME')
    if not bucket_name:
        return False
        
    try:
        # Создаем клиент (упрощенно, без повторения всей логики)
        s3_client = boto3.client('s3')
        s3_client.head_object(Bucket=bucket_name, Key=s3_key)
        return True
    except:
        return False


def get_s3_url(s3_key: str, bucket_name: Optional[str] = None) -> str:
    """
    Формирует URL для S3 объекта.
    
    Args:
        s3_key: Ключ файла в S3
        bucket_name: Имя bucket (если None - из окружения)
        
    Returns:
        URL файла
    """
    bucket_name = bucket_name or os.environ.get('AWS_STORAGE_BUCKET_NAME')
    endpoint_url = os.environ.get('AWS_S3_ENDPOINT_URL')
    region = os.environ.get('AWS_S3_REGION_NAME', 'ru1')
    
    if endpoint_url and endpoint_url.startswith('"'):
        endpoint_url = endpoint_url.strip('"')
    
    if endpoint_url:
        return f"{endpoint_url.rstrip('/')}/{bucket_name}/{s3_key}"
    else:
        return f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"