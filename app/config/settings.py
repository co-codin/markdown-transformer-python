import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_ROOT = Path(__file__).resolve().parent.parent

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# File settings
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

# Temporary directories
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "temp", "uploads")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "temp", "results")

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Единый список всех поддерживаемых форматов
# HTML/HTM удалены - требуют специальной обработки с внешними изображениями
# ZIP добавлен для поддержки сжатых документов
SUPPORTED_FORMATS = ["doc", "docx", "epub", "odt", "pdf", "pptx", "rtf", "xls", "xlsx", "zip"]

# Форматы для каждого конвертера (для внутреннего использования)
# MARKER_FORMATS - форматы, которые Marker может обработать напрямую без конвертации в PDF
MARKER_FORMATS = ["pdf", "pptx", "xlsx", "epub"]  # Прямая обработка через Marker
# PDF_BRIDGE_FORMATS - форматы, требующие конвертации через PDF для Marker
PDF_BRIDGE_FORMATS = ["doc", "docx", "odt", "rtf", "xls"]  # Конвертация через LibreOffice → PDF → Marker

# Database
# Use data directory for database to persist between restarts
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "tasks.db")

# Cleanup settings
CLEANUP_DAYS = int(os.getenv("CLEANUP_DAYS", "7"))

# LibreOffice conversion timeouts (in seconds)
LIBREOFFICE_TIMEOUT_DEFAULT = int(os.getenv("LIBREOFFICE_TIMEOUT_DEFAULT", "180"))  # 3 минуты для обычных файлов
LIBREOFFICE_TIMEOUT_COMPLEX = int(os.getenv("LIBREOFFICE_TIMEOUT_COMPLEX", "300"))  # 5 минут для PDF и EPUB