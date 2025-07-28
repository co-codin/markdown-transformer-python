"""
Конвертер на основе Marker для точной конвертации PDF в Markdown.

Marker обеспечивает высокое качество конвертации с правильным распознаванием:
- Маркированных и нумерованных списков
- Таблиц
- Математических формул
- Заголовков и структуры документа
"""

import os
import tempfile
import logging
import subprocess
import json
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Dict

# Storage service import moved to where it's used
from .base import BaseConverter

logger = logging.getLogger(__name__)


class MarkerConverter(BaseConverter):
    """Конвертер на основе Marker для PDF файлов."""
    
    def __init__(self):
        """Инициализация конвертера."""
        super().__init__()
        self._model_dict: Optional[Dict] = None
    
    @property
    def model_dict(self) -> Dict:
        """Ленивая загрузка моделей Marker."""
        if self._model_dict is None:
            logger.info("Loading Marker models...")
            try:
                from marker.models import create_model_dict
                self._model_dict = create_model_dict()
                logger.info("Marker models loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Marker models: {e}")
                raise
        return self._model_dict
    
    async def convert(self, input_path: str, output_dir: str, type_result: str = None) -> Tuple[str, Optional[str]]:
        """
        Конвертация документов в Markdown с использованием Marker API.
        
        Args:
            input_path: Путь к входному файлу (PDF, DOCX, PPTX, XLSX, EPUB)
            output_dir: Директория для сохранения результатов
            type_result: Тип результата ("norm" или "test")
            
        Returns:
            Кортеж (путь к markdown файлу, путь к директории с изображениями или None)
        """
        logger.info(f"Converting with Marker API: {input_path}")
        
        try:
            # Используем marker_single CLI для всех форматов
            # Marker автоматически определяет формат файла
            
            # Создаем временную директорию для вывода Marker
            with tempfile.TemporaryDirectory() as temp_dir:
                # Основная команда
                cmd = [
                    "marker_single",
                    input_path,
                    "--output_dir", temp_dir,
                    "--output_format", "markdown",  # Явно указываем формат вывода
                ]
                
                logger.info(f"Running command: {' '.join(cmd)}")
                
                # Запускаем процесс конвертации
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                stdout, stderr = process.communicate()
                
                # Логируем только ошибки
                if stderr and process.returncode != 0:
                    logger.error(f"Marker stderr: {stderr}")
                
                if process.returncode != 0:
                    logger.error(f"Marker failed: {stderr}")
                    raise Exception(f"Marker conversion failed: {stderr}")
                
                logger.info("Marker conversion completed successfully")
                
                
                # Ищем результаты
                base_name = Path(input_path).stem
                md_path = os.path.join(temp_dir, f"{base_name}.md")
                
                if not os.path.exists(md_path):
                    # Проверяем, создал ли Marker директорию с именем файла
                    output_dir_path = os.path.join(temp_dir, base_name)
                    if os.path.isdir(output_dir_path):
                        # Ищем .md файл внутри директории
                        md_path = os.path.join(output_dir_path, f"{base_name}.md")
                        if not os.path.exists(md_path):
                            # Пробуем найти любой .md файл в директории
                            md_files = list(Path(output_dir_path).glob("*.md"))
                            if md_files:
                                md_path = str(md_files[0])
                    
                    # Если все еще не нашли, ищем рекурсивно
                    if not os.path.exists(md_path):
                        md_files = list(Path(temp_dir).rglob("*.md"))
                        if md_files:
                            md_path = str(md_files[0])
                        else:
                            raise Exception("Marker did not produce markdown output")
                
                # Читаем markdown содержимое
                with open(md_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                # Создаем директорию для изображений в выходной папке
                images_dir = os.path.join(output_dir, "images")
                os.makedirs(images_dir, exist_ok=True)
                
                # Ищем и копируем изображения
                final_image_paths = []
                # Marker может создавать изображения в поддиректории
                image_patterns = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", 
                                "*.PNG", "*.JPG", "*.JPEG", "*.GIF", "*.BMP"]
                
                for pattern in image_patterns:
                    for img_file in Path(temp_dir).rglob(pattern):
                        # Копируем изображение в выходную директорию
                        img_name = img_file.name
                        new_img_path = os.path.join(images_dir, img_name)
                        shutil.copy2(str(img_file), new_img_path)
                        final_image_paths.append(new_img_path)
                        
                        # Обновляем путь в markdown
                        text = text.replace(str(img_file.relative_to(temp_dir)), f"./images/{img_name}")
                        text = text.replace(img_name, f"./images/{img_name}")
                
                logger.info(f"Found and copied {len(final_image_paths)} images")
            
            # Сохраняем markdown
            output_path = os.path.join(output_dir, "document.md")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            
            # Возвращаем путь к папке с изображениями или None
            if final_image_paths:
                images_dir_result = images_dir
            else:
                images_dir_result = None
            
            logger.info(f"Marker conversion completed: {len(text)} chars, {len(final_image_paths)} images")
            return output_path, images_dir_result
            
        except Exception as e:
            logger.error(f"Error during Marker conversion: {e}")
            raise