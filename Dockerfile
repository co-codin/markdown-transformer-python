# Use python slim with marker-pdf
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    # For LibreOffice PDF bridge conversion
    libreoffice \
    # Required for image processing
    libmagic1 \
    # Build dependencies for marker-pdf
    build-essential \
    # Dependencies for weasyprint
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    --no-install-recommends \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
# ВАЖНО: Сначала устанавливаем CPU-версию PyTorch, чтобы marker-pdf не тянул CUDA
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    # Теперь устанавливаем остальные зависимости
    pip install --no-cache-dir -r requirements.txt && \
    # Устанавливаем weasyprint для marker-pdf (нужен для EPUB, XLSX, PPTX)
    pip install --no-cache-dir weasyprint && \
    # Устанавливаем дополнительные зависимости для Marker
    pip install --no-cache-dir python-pptx openpyxl ebooklib

# Copy application code
COPY app/ ./app/

# Create directories for temporary files, logs and data
RUN mkdir -p temp/uploads temp/results logs data

# Копируем предварительно скачанные модели Marker из директории проекта
# Точно такой же путь как в локальной системе
COPY --chown=root:root marker_models /root/.cache/datalab/models

# Минимальные переменные окружения для CPU-only режима
ENV TORCH_DEVICE=cpu \
    NO_CUDA=1

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "app/main.py"]