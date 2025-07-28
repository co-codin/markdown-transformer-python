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
    
    uvicorn.run(
        "app:app", 
        host=HOST, 
        port=PORT, 
        reload=DEBUG,
        log_level="info"
    )