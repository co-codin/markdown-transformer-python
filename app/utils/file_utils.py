import os
import string  # Для безопасной валидации имен файлов
import zipfile
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def create_result_zip(markdown_path: str, images_dir: Optional[str], output_path: str) -> str:
    """
    Create a ZIP archive with markdown file and images directory.
    
    Args:
        markdown_path: Path to markdown file
        images_dir: Path to images directory (optional)
        output_path: Path for output ZIP file
        
    Returns:
        Path to created ZIP file
    """
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add markdown file
        zipf.write(markdown_path, "document.md")
        
        # Add images if present
        if images_dir and os.path.exists(images_dir):
            for root, dirs, files in os.walk(images_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, os.path.dirname(images_dir))
                    zipf.write(file_path, arcname)
    
    logger.info(f"Created result ZIP: {output_path}")
    return output_path


def cleanup_task_files(task_id: str, upload_dir: str, results_dir: str):
    """
    Clean up all files associated with a task.
    
    Args:
        task_id: Task ID
        upload_dir: Upload directory path
        results_dir: Results directory path
    """
    errors = []
    
    # Remove upload directory
    upload_path = os.path.join(upload_dir, task_id)
    if os.path.exists(upload_path):
        try:
            shutil.rmtree(upload_path)
            # Проверяем что папка действительно удалена
            if os.path.exists(upload_path):
                logger.error(f"Upload directory still exists after deletion: {upload_path}")
                errors.append(f"Upload dir not deleted: {upload_path}")
            else:
                logger.info(f"Successfully removed upload directory: {upload_path}")
        except Exception as e:
            logger.error(f"Failed to remove upload directory {upload_path}: {e}")
            errors.append(f"Upload dir error: {e}")
    
    # Remove results directory
    results_path = os.path.join(results_dir, task_id)
    if os.path.exists(results_path):
        try:
            shutil.rmtree(results_path)
            # Проверяем что папка действительно удалена
            if os.path.exists(results_path):
                logger.error(f"Results directory still exists after deletion: {results_path}")
                errors.append(f"Results dir not deleted: {results_path}")
            else:
                logger.info(f"Successfully removed results directory: {results_path}")
        except Exception as e:
            logger.error(f"Failed to remove results directory {results_path}: {e}")
            errors.append(f"Results dir error: {e}")
    
    if errors:
        logger.error(f"Cleanup errors for task {task_id}: {'; '.join(errors)}")


def get_file_extension(filename: str) -> str:
    """Get file extension in lowercase without dot."""
    return Path(filename).suffix.lower().lstrip('.')


def is_format_supported(filename: str, supported_formats: list) -> bool:
    """Check if file format is supported."""
    ext = get_file_extension(filename)
    return ext in supported_formats

def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal attacks.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename safe for filesystem operations
    """
    # Get just the filename, removing any path components
    filename = os.path.basename(filename)
    
    # Remove potentially dangerous characters
    # Allow only alphanumeric, dots, hyphens, underscores
    safe_chars = set(string.ascii_letters + string.digits + '.-_')
    
    # Keep the extension
    name, ext = os.path.splitext(filename)
    
    # Clean the name part
    clean_name = ''.join(c if c in safe_chars else '_' for c in name)
    
    # Ensure name is not empty
    if not clean_name:
        clean_name = 'document'
    
    # Limit length
    if len(clean_name) > 100:
        clean_name = clean_name[:100]
    
    return clean_name + ext
