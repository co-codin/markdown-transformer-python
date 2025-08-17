import uvicorn
import logging
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from app import app
from app.config.settings import HOST, PORT, DEBUG

if __name__ == "__main__":
    logging.info("Starting Document to Markdown Converter Service...")
    logging.info(f"Server will be available at: http://{HOST}:{PORT}")
    logging.info(f"API documentation: http://{HOST}:{PORT}/docs")
    
    # Используем один процесс с асинхронной обработкой
    # FastAPI и так обрабатывает запросы параллельно благодаря asyncio
    if DEBUG:
        # В DEBUG режиме используем строку для поддержки reload
        uvicorn.run(
            "app:app",  # Строка импорта для reload
            host=HOST, 
            port=PORT, 
            reload=True,  # Включаем reload в DEBUG
            log_level="info",
            loop="asyncio",  # Явно указываем event loop
            access_log=True  # Включаем логи запросов для отладки
        )
    else:
        # В production используем прямую ссылку без reload
        uvicorn.run(
            app,  # Прямая ссылка на app
            host=HOST, 
            port=PORT, 
            reload=False,  # Выключаем reload
            log_level="info",
            loop="asyncio",  # Явно указываем event loop
            access_log=True  # Включаем логи запросов для отладки
        )