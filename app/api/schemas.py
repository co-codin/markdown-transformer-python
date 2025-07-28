from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from uuid import UUID
from enum import Enum
from datetime import datetime


class StatusEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ConversionRequest(BaseModel):
    file_format: Optional[str] = Field(None, description="Expected file format (auto-detected if not provided)")


class ConversionResponse(BaseModel):
    task_id: UUID
    status: StatusEnum
    message: str


class TaskStatusResponse(BaseModel):
    task_id: UUID
    status: StatusEnum
    progress: int = Field(0, ge=0, le=100)
    message: str
    result_url: Optional[str] = None
    created_at: Optional[str] = None
    s3_enabled: Optional[bool] = None
    s3_images_count: Optional[int] = None
    type_result: Optional[str] = None
    

class SupportedFormatsResponse(BaseModel):
    formats: List[str]
    

class ErrorResponse(BaseModel):
    detail: str
    

class PendingTask(BaseModel):
    task_id: UUID
    original_filename: str
    status: StatusEnum
    created_at: str
    progress: int
    downloaded: bool
    

class PendingTasksResponse(BaseModel):
    tasks: List[PendingTask]
    total: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str = "1.0.0"
    database: bool
    s3_enabled: bool
    s3_connected: Optional[bool] = None
    supported_formats: int
    pending_tasks: int