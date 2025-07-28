from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.database import task_db
from app.api.routes import router
from app.config.settings import DEBUG

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

@app.on_event("startup")
async def startup_event():
    await task_db.init_db()
    
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