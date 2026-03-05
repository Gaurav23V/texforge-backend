from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class CompileStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ErrorType(str, Enum):
    LATEX_COMPILE_ERROR = "latex_compile_error"
    TIMEOUT = "timeout"
    VALIDATION_ERROR = "validation_error"
    DANGEROUS_CONTENT = "dangerous_content"
    STORAGE_ERROR = "storage_error"
    PROJECT_NOT_FOUND = "project_not_found"
    COMPILER_UNAVAILABLE = "compiler_unavailable"
    CANCELLED = "cancelled"


class CompileRequest(BaseModel):
    project_id: str = Field(..., description="UUID of the project to compile")
    tex: Optional[str] = Field(None, description="Raw LaTeX source (optional, fetched from DB if not provided)")
    force: bool = Field(False, description="Force recompile even if unchanged")


class CompileSuccessResponse(BaseModel):
    status: CompileStatus = CompileStatus.SUCCESS
    pdf_url: str
    compiled_at: datetime


class CompileErrorResponse(BaseModel):
    status: CompileStatus = CompileStatus.ERROR
    error_type: ErrorType
    log: Optional[str] = None
    compiled_at: datetime


class HealthResponse(BaseModel):
    status: str = "ok"


class LatestPdfResponse(BaseModel):
    pdf_url: Optional[str] = None
    compiled_at: Optional[datetime] = None
