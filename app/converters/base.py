from abc import ABC, abstractmethod
from typing import Tuple, Optional, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)


class BaseConverter(ABC):
    def __init__(self, s3_config: Optional[Dict[str, Any]] = None):
        """
        Инициализация конвертера.
        
        Args:
            s3_config: Конфигурация для S3 загрузки изображений (опционально)
                      {"bucket_name": "...", "folder_prefix": "...", "enabled": True}
        """
        self.s3_config = s3_config or {}
        self.s3_enabled = self.s3_config.get('enabled', False)
        
    @abstractmethod
    async def convert(self, input_path: str, output_dir: str) -> Tuple[str, Optional[str]]:
        """
        Convert document to markdown.
        
        Args:
            input_path: Path to input file
            output_dir: Directory for output files
            
        Returns:
            Tuple of (markdown_path, images_dir_path or None)
        """
        pass
    
    @staticmethod
    def ensure_images_dir(output_dir: str) -> str:
        """Create and return images directory path."""
        images_dir = os.path.join(output_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        return images_dir
        
    def process_with_s3(self, markdown_path: str, images_dir: Optional[str], 
                       task_id: str) -> str:
        """
        Обрабатывает Markdown с загрузкой изображений в S3.
        
        Args:
            markdown_path: Путь к Markdown файлу
            images_dir: Директория с изображениями
            task_id: ID задачи
            
        Returns:
            Путь к обработанному файлу (может быть тот же или новый)
        """
        if not self.s3_enabled or not images_dir:
            return markdown_path
            
        try:
            from .s3_image_uploader import create_s3_enabled_markdown
            
            # Получаем конфигурацию без флага enabled
            config = {k: v for k, v in self.s3_config.items() if k != 'enabled'}
            
            # Создаем версию с S3 ссылками
            s3_markdown_path = create_s3_enabled_markdown(
                markdown_path, images_dir, task_id, config
            )
            
            return s3_markdown_path
            
        except ImportError:
            logger.warning("S3 модуль недоступен, используем локальные изображения")
            return markdown_path
        except Exception as e:
            logger.error(f"Ошибка при обработке S3: {e}")
            return markdown_path