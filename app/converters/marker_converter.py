"""
Конвертер на основе Marker для точной конвертации PDF в Markdown.

Marker обеспечивает высокое качество конвертации с правильным распознаванием:
- Маркированных и нумерованных списков
- Таблиц
- Математических формул
- Заголовков и структуры документа
"""

import os
import sys
import tempfile
import logging
import subprocess
import json
import shutil
import warnings
from pathlib import Path
from typing import List, Tuple, Optional, Dict

# Storage service import moved to where it's used
from .base import BaseConverter

# Suppress NCX warnings from ebooklib that can cause issues in Docker
warnings.filterwarnings('ignore', message='.*NCX.*', module='ebooklib')
warnings.filterwarnings('ignore', category=UserWarning, module='ebooklib')

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
                # Убеждаемся, что используем CPU device
                import os
                os.environ.setdefault('TORCH_DEVICE', 'cpu')
                os.environ.setdefault('CUDA_VISIBLE_DEVICES', '')
                
                from marker.models import create_model_dict
                self._model_dict = create_model_dict()
                logger.info("Marker models loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Marker models: {e}")
                # В Docker контейнере попробуем принудительно указать путь к моделям
                if os.path.exists("/.dockerenv"):
                    logger.warning("Running in Docker - attempting alternative model loading")
                    try:
                        # Попробуем загрузить модели из альтернативных путей
                        model_paths = [
                            "/root/.cache/huggingface/hub",
                            "/root/.cache/marker/models",
                            "/root/.cache/datalab/models"
                        ]
                        for path in model_paths:
                            if os.path.exists(path):
                                logger.info(f"Found model cache at: {path}")
                                os.environ['HF_HOME'] = os.path.dirname(path)
                                break
                        # Повторная попытка загрузки
                        self._model_dict = create_model_dict()
                        logger.info("Marker models loaded successfully on retry")
                    except Exception as retry_e:
                        logger.error(f"Retry failed: {retry_e}")
                        raise
                else:
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
                # Подготавливаем окружение с правильным PATH
                # Это решает проблему с uvicorn reload=True, который теряет venv
                env = os.environ.copy()
                
                # Проверяем, работаем ли мы в Docker
                if not os.path.exists("/.dockerenv"):
                    # Локальная разработка - добавляем bin директорию venv в PATH
                    venv_bin = os.path.join(sys.prefix, "bin")
                    if os.path.exists(venv_bin):
                        env['PATH'] = f"{venv_bin}:{env.get('PATH', '')}"
                        logger.debug(f"Added venv bin to PATH: {venv_bin}")
                
                # Используем обычное имя команды - она найдется через PATH
                cmd = [
                    "marker_single",
                    input_path,
                    "--output_dir", temp_dir,
                    "--output_format", "markdown",  # Явно указываем формат вывода
                ]
                
                logger.info(f"Running command: {' '.join(cmd)}")
                logger.debug(f"Using PATH: {env.get('PATH', 'default')}")
                
                # Запускаем процесс конвертации с модифицированным окружением
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env  # Передаем окружение с правильным PATH
                )
                
                # Добавляем таймаут 300 секунд (5 минут) для предотвращения зависания
                try:
                    stdout, stderr = process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    logger.error(f"Marker timeout after 300s for {input_path}")
                    process.kill()
                    # Ждем завершения процесса после kill
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        stdout, stderr = "", "Process terminated due to timeout"
                    raise Exception(f"Marker conversion timeout after 300 seconds")
                
                # ВАЖНО: Проверяем только код возврата, а не наличие stderr
                # Многие программы выводят предупреждения в stderr, но это не означает ошибку
                if process.returncode != 0:
                    # Только если код возврата не 0, считаем это ошибкой
                    logger.error(f"Marker failed with code {process.returncode}: {stderr}")
                    # Очищаем stderr от известных безопасных предупреждений для сообщения об ошибке
                    stderr_lines = stderr.strip().split('\n') if stderr else []
                    real_errors = []
                    for line in stderr_lines:
                        # Пропускаем известные предупреждения
                        if 'UserWarning: In the future version we will turn default option ignore_ncx' in line:
                            continue
                        if 'ebooklib/epub.py' in line and 'UserWarning' in line:
                            continue
                        if 'FutureWarning: This search incorrectly ignores the root element' in line:
                            continue
                        if not line.strip():
                            continue
                        real_errors.append(line)
                    
                    error_msg = chr(10).join(real_errors) if real_errors else stderr
                    raise Exception(f"Marker conversion failed: {error_msg}")
                
                # Логируем stderr только если это не просто предупреждения
                if stderr:
                    # Фильтруем известные безопасные предупреждения
                    stderr_lines = stderr.strip().split('\n')
                    real_errors = []
                    for line in stderr_lines:
                        # Пропускаем известные предупреждения от ebooklib
                        if 'UserWarning: In the future version we will turn default option ignore_ncx' in line:
                            continue
                        if 'ebooklib/epub.py' in line and 'UserWarning' in line:
                            continue
                        if 'FutureWarning: This search incorrectly ignores the root element' in line:
                            continue
                        # Пропускаем пустые строки
                        if not line.strip():
                            continue
                        real_errors.append(line)
                    
                    # Логируем только реальные ошибки
                    if real_errors:
                        logger.warning(f"Marker stderr (non-critical): {chr(10).join(real_errors)}")
                
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