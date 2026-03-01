import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Union

from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.models import (
    CompileRequest,
    CompileSuccessResponse,
    CompileErrorResponse,
    CompileStatus,
    ErrorType,
    HealthResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_compile_semaphore: asyncio.Semaphore | None = None


def get_compile_semaphore() -> asyncio.Semaphore:
    """Get or create the compile semaphore."""
    global _compile_semaphore
    if _compile_semaphore is None:
        settings = get_settings()
        _compile_semaphore = asyncio.Semaphore(settings.max_concurrent_compiles)
        logger.info(f"Initialized compile semaphore with {settings.max_concurrent_compiles} slots")
    return _compile_semaphore


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_compile_semaphore()
    yield


app = FastAPI(
    title="TexForge Compiler Service",
    description="LaTeX to PDF compilation service for TexForge",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse()


@app.post("/compile", response_model=Union[CompileSuccessResponse, CompileErrorResponse])
async def compile_tex(request: CompileRequest):
    from app.security import validate_tex_content
    from app.compile import run_compile
    from app.supabase_client import get_project_tex, save_compile_result, upload_pdf, create_signed_url

    settings = get_settings()
    request_id = f"req-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    logger.info(f"[{request_id}] Compile request for project_id={request.project_id}")

    semaphore = get_compile_semaphore()
    try:
        async with asyncio.timeout(settings.semaphore_wait_timeout_seconds):
            await semaphore.acquire()
    except asyncio.TimeoutError:
        logger.warning(f"[{request_id}] Semaphore wait timeout - too many concurrent compiles")
        raise HTTPException(status_code=429, detail="Too many concurrent compile requests. Try again later.")

    try:
        compiled_at = datetime.now(timezone.utc)

        if request.tex is not None:
            tex_content = request.tex
        else:
            tex_content = await get_project_tex(request.project_id)
            if tex_content is None:
                return CompileErrorResponse(
                    error_type=ErrorType.PROJECT_NOT_FOUND,
                    log="Project not found or has no tex content",
                    compiled_at=compiled_at,
                )

        validation_error = validate_tex_content(tex_content, settings.max_tex_size_bytes)
        if validation_error:
            error_type, message = validation_error
            await save_compile_result(
                project_id=request.project_id,
                status="error",
                log=message,
                pdf_path=None,
            )
            return CompileErrorResponse(
                error_type=error_type,
                log=message,
                compiled_at=compiled_at,
            )

        result = await run_compile(
            tex_content=tex_content,
            timeout_seconds=settings.compile_timeout_seconds,
            max_log_chars=settings.max_log_response_chars,
        )

        if result["success"]:
            pdf_path = f"{request.project_id}/latest.pdf"
            upload_success = await upload_pdf(result["pdf_bytes"], pdf_path)

            if not upload_success:
                await save_compile_result(
                    project_id=request.project_id,
                    status="error",
                    log="Failed to upload PDF to storage",
                    pdf_path=None,
                )
                return CompileErrorResponse(
                    error_type=ErrorType.STORAGE_ERROR,
                    log="Failed to upload PDF to storage",
                    compiled_at=compiled_at,
                )

            await save_compile_result(
                project_id=request.project_id,
                status="success",
                log=result["full_log"],
                pdf_path=pdf_path,
            )

            pdf_url = await create_signed_url(pdf_path)
            logger.info(f"[{request_id}] Compile successful for project_id={request.project_id}")

            return CompileSuccessResponse(
                pdf_url=pdf_url,
                compiled_at=compiled_at,
            )
        else:
            await save_compile_result(
                project_id=request.project_id,
                status="error",
                log=result["full_log"],
                pdf_path=None,
            )

            logger.info(f"[{request_id}] Compile failed for project_id={request.project_id}: {result['error_type']}")

            return CompileErrorResponse(
                error_type=result["error_type"],
                log=result["truncated_log"],
                compiled_at=compiled_at,
            )

    finally:
        semaphore.release()
