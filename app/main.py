import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.compile_cache import CompileCache
from app.compile_coordinator import CompileCoordinator
from app.compile_orchestrator import CompileOrchestrator
from app.config import get_settings
from app.models import (
    CompileRequest,
    CompileSuccessResponse,
    CompileErrorResponse,
    HealthResponse,
    LatestPdfResponse,
    SharePdfResponse,
)
from app.workdir_cache import WorkdirCache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_compile_semaphore: asyncio.Semaphore | None = None
_compile_orchestrator: CompileOrchestrator | None = None


def get_compile_semaphore() -> asyncio.Semaphore:
    """Get or create the compile semaphore."""
    global _compile_semaphore
    if _compile_semaphore is None:
        settings = get_settings()
        _compile_semaphore = asyncio.Semaphore(settings.max_concurrent_compiles)
        logger.info(f"Initialized compile semaphore with {settings.max_concurrent_compiles} slots")
    return _compile_semaphore


def get_compile_orchestrator() -> CompileOrchestrator:
    global _compile_orchestrator
    if _compile_orchestrator is None:
        settings = get_settings()
        _compile_orchestrator = CompileOrchestrator(
            settings=settings,
            compile_semaphore=get_compile_semaphore(),
            compile_cache=CompileCache(max_entries=settings.compile_cache_max_entries),
            workdir_cache=WorkdirCache(
                root_dir=settings.workdir_cache_root,
                max_projects=settings.workdir_cache_max_projects,
            ),
            coordinator=CompileCoordinator(),
        )
    return _compile_orchestrator


async def _warmup_compiler() -> None:
    """Optional warmup compile to reduce cold-start penalties."""
    from app.compile import run_compile

    settings = get_settings()
    warmup_tex = r"\documentclass{article}\begin{document}warmup\end{document}"
    try:
        await run_compile(
            tex_content=warmup_tex,
            timeout_seconds=min(settings.compile_timeout_seconds, 5),
            max_log_chars=1024,
        )
        logger.info("Compiler warmup completed")
    except Exception as exc:
        logger.warning("Compiler warmup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_compile_semaphore()
    get_compile_orchestrator()
    if get_settings().enable_startup_warmup:
        await _warmup_compiler()
    yield


app = FastAPI(
    title="TexForge Compiler Service",
    description="LaTeX to PDF compilation service for TexForge",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "https://texforge-frontend-lsmd.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse()


@app.post("/compile", response_model=Union[CompileSuccessResponse, CompileErrorResponse])
async def compile_tex(request: CompileRequest):
    request_id = f"req-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    logger.info(f"[{request_id}] Compile request for project_id={request.project_id}")
    orchestrator = get_compile_orchestrator()
    return await orchestrator.compile(request=request, request_id=request_id)


@app.get("/projects/{project_id}/latest-pdf", response_model=LatestPdfResponse)
async def get_latest_project_pdf(project_id: str):
    from app.supabase_client import get_latest_successful_compile, create_signed_url

    settings = get_settings()
    latest_compile = await get_latest_successful_compile(project_id)
    if not latest_compile:
        return LatestPdfResponse()

    pdf_path = latest_compile.get("pdf_path")
    compiled_at = latest_compile.get("compiled_at")
    if not pdf_path:
        return LatestPdfResponse(compiled_at=compiled_at)

    pdf_url = await create_signed_url(pdf_path, expires_in=settings.signed_url_ttl_seconds)
    if not pdf_url:
        return LatestPdfResponse(compiled_at=compiled_at)

    return LatestPdfResponse(
        pdf_url=pdf_url,
        compiled_at=compiled_at,
    )


@app.get("/shares/{token}", response_model=SharePdfResponse)
async def get_shared_project_pdf(token: str):
    from app.supabase_client import get_share_project, get_latest_successful_compile, create_signed_url

    settings = get_settings()
    share_project = await get_share_project(token)
    if not share_project:
        raise HTTPException(status_code=404, detail="Share not found")

    latest_compile = await get_latest_successful_compile(share_project["project_id"])
    if not latest_compile:
        return SharePdfResponse(project_name=share_project["project_name"])

    pdf_path = latest_compile.get("pdf_path")
    compiled_at = latest_compile.get("compiled_at")
    if not pdf_path:
        return SharePdfResponse(
            project_name=share_project["project_name"],
            compiled_at=compiled_at,
        )

    pdf_url = await create_signed_url(pdf_path, expires_in=settings.signed_url_ttl_seconds)
    return SharePdfResponse(
        project_name=share_project["project_name"],
        pdf_url=pdf_url or None,
        compiled_at=compiled_at,
    )
