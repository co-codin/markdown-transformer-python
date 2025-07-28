"""
PDF Bridge Converter - конвертирует документы через промежуточный PDF.
Использует LibreOffice для конвертации в PDF, затем MarkerConverter для извлечения контента.
"""

import os
import subprocess
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple
import asyncio
from asyncio import Lock

from app.config.settings import LIBREOFFICE_TIMEOUT_DEFAULT, LIBREOFFICE_TIMEOUT_COMPLEX

logger = logging.getLogger(__name__)

# Глобальная блокировка для LibreOffice
_libreoffice_lock = Lock()


class PdfBridgeConverter:
    """
    Конвертер, который использует промежуточную конвертацию в PDF
    для форматов, которые плохо обрабатываются напрямую.
    """
    
    # Поддерживаемые форматы (только те, которые не поддерживаются Marker напрямую)
    SUPPORTED_FORMATS = {'.doc', '.odt', '.rtf', '.xls'}
    
    def __init__(self):
        """Инициализация конвертера."""
        self.name = "PdfBridgeConverter"
        # Импортируем MarkerConverter для обработки PDF
        try:
            from app.converters.marker_converter import MarkerConverter
            self.marker_converter = MarkerConverter()
            self.marker_available = True
        except ImportError:
            self.marker_available = False
            logger.error("MarkerConverter not available for PDF processing")
    
    def ensure_images_dir(self, output_dir: str) -> str:
        """Ensure images directory exists and return its path."""
        images_dir = os.path.join(output_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        return images_dir
        
    def can_convert(self, file_extension: str) -> bool:
        """Проверяет, может ли конвертер обработать данный формат."""
        return file_extension.lower() in self.SUPPORTED_FORMATS
    
    async def convert_to_pdf_with_libreoffice(self, input_path: str, output_dir: str) -> Optional[str]:
        """
        Конвертирует документ в PDF с помощью LibreOffice.
        
        Args:
            input_path: Путь к исходному файлу
            output_dir: Директория для сохранения PDF
            
        Returns:
            Путь к созданному PDF файлу или None в случае ошибки
        """
        input_file = Path(input_path)
        output_file = Path(output_dir) / f"{input_file.stem}_temp.pdf"
        
        logger.info(f"Acquiring LibreOffice lock for {input_file.name}...")
        async with _libreoffice_lock:
            logger.info(f"Lock acquired, starting LibreOffice conversion for {input_file.name}")
            
            try:
                # Команда для конвертации с помощью LibreOffice
                cmd = [
                    'libreoffice', '--headless', '--convert-to', 'pdf',
                    '--outdir', output_dir, str(input_file)
                ]
                
                logger.info(f"Converting to PDF with LibreOffice: {' '.join(cmd)}")
                
                # Выбираем таймаут в зависимости от расширения файла
                file_ext = input_file.suffix.lower()
                if file_ext in ['.pdf', '.epub']:
                    timeout_seconds = LIBREOFFICE_TIMEOUT_COMPLEX
                else:
                    timeout_seconds = LIBREOFFICE_TIMEOUT_DEFAULT
                logger.info(f"Using timeout: {timeout_seconds}s for {file_ext} file")
                
                # Запускаем процесс конвертации асинхронно
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Ждем завершения с выбранным таймаутом
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), 
                        timeout=timeout_seconds
                    )
                except asyncio.TimeoutError:
                    logger.error(f"LibreOffice conversion timeout after {timeout_seconds}s for {input_file.name}")
                    process.kill()
                    await process.wait()
                    return None
                
                if process.returncode != 0:
                    logger.error(f"LibreOffice conversion failed: {stderr.decode()}")
                    return None
                
                # LibreOffice часто выдает предупреждения в stderr, даже при успешной конвертации
                if stderr:
                    stderr_text = stderr.decode()
                    # Игнорируем известное предупреждение о javaldx
                    if "failed to launch javaldx" not in stderr_text.lower():
                        logger.warning(f"LibreOffice stderr output: {stderr_text}")
                
                # LibreOffice создает файл с тем же именем, но расширением .pdf
                expected_pdf = Path(output_dir) / f"{input_file.stem}.pdf"
                if expected_pdf.exists():
                    logger.info(f"PDF created successfully: {expected_pdf}")
                    return str(expected_pdf)
                else:
                    logger.error(f"Expected PDF not found: {expected_pdf}")
                    return None
                    
            except Exception as e:
                logger.error(f"Error converting to PDF: {str(e)}")
                return None
    
    async def convert(self, input_path: str, output_dir: str) -> Tuple[str, Optional[str]]:
        """
        Конвертирует документ в Markdown через промежуточный PDF.
        
        Args:
            input_path: Путь к входному файлу
            output_dir: Директория для сохранения результатов
            
        Returns:
            Кортеж (путь к markdown файлу, путь к директории с изображениями или None)
        """
        if not self.marker_available:
            raise RuntimeError("MarkerConverter not available for PDF processing")
            
        logger.info(f"Starting PDF bridge conversion of {input_path}")
        
        # Создаем директории
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Создаем временную директорию для PDF
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Шаг 1: Конвертируем в PDF
                logger.info("Step 1: Converting to PDF with LibreOffice...")
                pdf_path = await self.convert_to_pdf_with_libreoffice(input_path, temp_dir)
                
                if not pdf_path:
                    raise RuntimeError("Failed to convert document to PDF")
                
                # Шаг 2: Конвертируем PDF в Markdown с помощью MarkerConverter
                logger.info("Step 2: Converting PDF to Markdown with MarkerConverter...")
                markdown_path, images_dir = await self.marker_converter.convert(pdf_path, str(output_dir))
                
                logger.info(f"PDF bridge conversion completed successfully")
                return markdown_path, images_dir
                
            except Exception as e:
                logger.error(f"Error during PDF bridge conversion: {str(e)}")
                raise RuntimeError(f"PDF bridge conversion failed: {str(e)}")