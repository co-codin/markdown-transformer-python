from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging

from app.api.database import task_db
from app.api.routes import router
from app.config.settings import DEBUG
from app.services.queue_worker import QueueWorkerPool

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Document to Markdown Converter",
    description="Service for converting various document formats to Markdown",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

# Глобальная переменная для пула воркеров
worker_pool = None

@app.on_event("startup")
async def startup_event():
    global worker_pool
    
    # Инициализация базы данных
    await task_db.init_db()
    
    # Очищаем зависшие задачи от предыдущего запуска сервера
    cleaned = await task_db.cleanup_stale_processing_tasks()
    if cleaned > 0:
        logger.info(f"🧹 Очищено {cleaned} зависших задач от предыдущего запуска")
    
    # ИСПРАВЛЕНО: Используем существующий метод release_stale_tasks
    # Освобождаем задачи из PROCESSING обратно в QUEUED для повторной обработки
    reset_count = await task_db.release_stale_tasks(0)  # 0 секунд = немедленное освобождение
    if reset_count > 0:
        logger.info(f"🔄 Сброшено {reset_count} задач из PROCESSING в QUEUED")
    
    # Запускаем пул воркеров для обработки очереди
    worker_pool = QueueWorkerPool(
        db_manager=task_db,
        num_workers=3,  # Количество воркеров
        poll_interval=1.0,  # Интервал опроса очереди (секунды)
        stale_timeout=300,  # Таймаут для зависших задач (5 минут)
        stale_check_interval=60  # Интервал проверки зависших задач (1 минута)
    )
    
    # Запускаем воркеры с обработкой ошибок для продакшена
    try:
        await worker_pool.start()
        logger.info("✅ Пул воркеров успешно запущен")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске пула воркеров: {e}")
        # В продакшене можно добавить fallback стратегию или уведомление
        raise
    
@app.on_event("shutdown")
async def shutdown_event():
    global worker_pool
    
    if worker_pool:
        logger.info("⏹️ Останавливаем пул воркеров...")
        try:
            await worker_pool.stop()
            logger.info("✅ Пул воркеров остановлен")
        except Exception as e:
            logger.error(f"❌ Ошибка при остановке пула воркеров: {e}")

@app.get("/")
async def root():
    return {
        "service": "Document to Markdown Converter",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Document to Markdown Converter",
        "version": "1.0.0"
    }