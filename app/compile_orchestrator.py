import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Union

from fastapi import HTTPException

from app.compile import run_compile
from app.compile_cache import CompileCache, CompileCacheEntry, build_compile_key
from app.compile_coordinator import CompileCoordinator
from app.config import Settings
from app.engine_strategy import (
    ENGINE_LATEXMK,
    choose_engine_plan,
    should_fallback_from_pdflatex,
)
from app.models import (
    CompileErrorResponse,
    CompileRequest,
    CompileSuccessResponse,
    ErrorType,
)
from app.security import validate_tex_content
from app.storage_paths import artifact_pdf_path, latest_pdf_path
from app.supabase_client import (
    create_signed_url,
    get_compile_artifact,
    get_project_tex,
    save_compile_result,
    upload_pdf,
    upsert_compile_artifact,
)
from app.timing import TimingRecorder
from app.workdir_cache import WorkdirCache

logger = logging.getLogger(__name__)


class CompileOrchestrator:
    def __init__(
        self,
        settings: Settings,
        compile_semaphore: asyncio.Semaphore,
        compile_cache: CompileCache,
        workdir_cache: WorkdirCache,
        coordinator: CompileCoordinator,
    ):
        self.settings = settings
        self.compile_semaphore = compile_semaphore
        self.compile_cache = compile_cache
        self.workdir_cache = workdir_cache
        self.coordinator = coordinator

    async def compile(
        self,
        request: CompileRequest,
        request_id: str,
    ) -> Union[CompileSuccessResponse, CompileErrorResponse]:
        compiled_at = datetime.now(timezone.utc)
        timings = TimingRecorder()

        with timings.stage("fetch"):
            if request.tex is not None:
                tex_content = request.tex
            else:
                tex_content = await get_project_tex(request.project_id)

        if tex_content is None:
            response = CompileErrorResponse(
                error_type=ErrorType.PROJECT_NOT_FOUND,
                log="Project not found or has no tex content",
                compiled_at=compiled_at,
            )
            self._log_request(request_id, request.project_id, response, timings, cache_hit=False)
            return response

        if request.tex is not None and not tex_content.strip():
            error_message = "TeX content cannot be empty"
            with timings.stage("db_save"):
                await save_compile_result(
                    project_id=request.project_id,
                    status="error",
                    log=error_message,
                    pdf_path=None,
                )
            response = CompileErrorResponse(
                error_type=ErrorType.VALIDATION_ERROR,
                log=error_message,
                compiled_at=compiled_at,
            )
            self._log_request(request_id, request.project_id, response, timings, cache_hit=False)
            return response

        with timings.stage("validate"):
            validation_error = validate_tex_content(tex_content, self.settings.max_tex_size_bytes)
        if validation_error:
            error_type, message = validation_error
            with timings.stage("db_save"):
                await save_compile_result(
                    project_id=request.project_id,
                    status="error",
                    log=message,
                    pdf_path=None,
                )
            response = CompileErrorResponse(
                error_type=error_type,
                log=message,
                compiled_at=compiled_at,
            )
            self._log_request(request_id, request.project_id, response, timings, cache_hit=False)
            return response

        engine_plan = choose_engine_plan(self.settings.enable_adaptive_engine)
        strategy_flags = self._strategy_flags(engine_plan.engine, engine_plan.pdflatex_passes)
        compile_key = build_compile_key(
            project_id=request.project_id,
            tex_content=tex_content,
            engine=engine_plan.engine,
            flags=strategy_flags,
        )

        if request.force and self.settings.enable_compile_cache:
            await self.compile_cache.invalidate_project(request.project_id)

        cache_entry = await self._lookup_cache(
            compile_key=compile_key,
            project_id=request.project_id,
            strategy_flags=strategy_flags,
            engine=engine_plan.engine,
            request_force=request.force,
            timings=timings,
        )
        if cache_entry is not None:
            pdf_url = await self._get_or_refresh_signed_url(cache_entry, timings)
            if not pdf_url:
                response = CompileErrorResponse(
                    error_type=ErrorType.STORAGE_ERROR,
                    log="Failed to create signed URL for cached PDF",
                    compiled_at=compiled_at,
                )
                self._log_request(request_id, request.project_id, response, timings, cache_hit=True)
                return response
            with timings.stage("db_save"):
                await save_compile_result(
                    project_id=request.project_id,
                    status="success",
                    log="Compile cache hit",
                    pdf_path=cache_entry.pdf_path,
                )
            response = CompileSuccessResponse(
                pdf_url=pdf_url,
                compiled_at=compiled_at,
            )
            self._log_request(request_id, request.project_id, response, timings, cache_hit=True)
            return response

        async def execute_compile() -> dict:
            queue_start = time.perf_counter()
            try:
                async with asyncio.timeout(self.settings.semaphore_wait_timeout_seconds):
                    await self.compile_semaphore.acquire()
            except asyncio.TimeoutError as exc:
                raise HTTPException(
                    status_code=429,
                    detail="Too many concurrent compile requests. Try again later.",
                ) from exc

            timings.add_duration("queue_wait", time.perf_counter() - queue_start)
            try:
                return await self._compile_and_store(
                    request=request,
                    tex_content=tex_content,
                    compile_key=compile_key,
                    engine_name=engine_plan.engine,
                    pdflatex_passes=engine_plan.pdflatex_passes,
                    allow_fallback=engine_plan.allow_fallback,
                    strategy_flags=strategy_flags,
                    timings=timings,
                )
            finally:
                self.compile_semaphore.release()

        try:
            if self.settings.enable_compile_coalescing:
                payload, _ = await self.coordinator.run(
                    project_id=request.project_id,
                    key=compile_key,
                    create_task=execute_compile,
                )
            else:
                payload = await execute_compile()
        except asyncio.CancelledError:
            response = CompileErrorResponse(
                error_type=ErrorType.CANCELLED,
                log="Compile request was cancelled due to a newer request",
                compiled_at=compiled_at,
            )
            self._log_request(request_id, request.project_id, response, timings, cache_hit=False)
            return response

        if payload["success"]:
            response = CompileSuccessResponse(
                pdf_url=payload["pdf_url"],
                compiled_at=compiled_at,
            )
            self._log_request(request_id, request.project_id, response, timings, cache_hit=False)
            return response

        response = CompileErrorResponse(
            error_type=payload["error_type"],
            log=payload["log"],
            compiled_at=compiled_at,
        )
        self._log_request(request_id, request.project_id, response, timings, cache_hit=False)
        return response

    async def _lookup_cache(
        self,
        *,
        compile_key: str,
        project_id: str,
        strategy_flags: str,
        engine: str,
        request_force: bool,
        timings: TimingRecorder,
    ) -> CompileCacheEntry | None:
        if not self.settings.enable_compile_cache or request_force:
            return None

        with timings.stage("cache_lookup"):
            cache_entry = await self.compile_cache.get(compile_key)
            if cache_entry is not None:
                return cache_entry

            artifact = await get_compile_artifact(compile_key)
            if artifact and artifact.get("pdf_path"):
                cache_entry = CompileCacheEntry(
                    key=compile_key,
                    pdf_path=artifact["pdf_path"],
                    project_id=artifact.get("project_id", project_id),
                    engine=artifact.get("engine", engine),
                    flags=artifact.get("flags", strategy_flags),
                    created_at=time.time(),
                )
                await self.compile_cache.set(cache_entry)
                return cache_entry
        return None

    async def _compile_and_store(
        self,
        *,
        request: CompileRequest,
        tex_content: str,
        compile_key: str,
        engine_name: str,
        pdflatex_passes: int,
        allow_fallback: bool,
        strategy_flags: str,
        timings: TimingRecorder,
    ) -> dict:
        with timings.stage("compile"):
            result = await self._run_compile_for_project(
                project_id=request.project_id,
                tex_content=tex_content,
                engine_name=engine_name,
                pdflatex_passes=pdflatex_passes,
            )

            if (
                not result["success"]
                and allow_fallback
                and should_fallback_from_pdflatex(result["error_type"])
            ):
                fallback_result = await self._run_compile_for_project(
                    project_id=request.project_id,
                    tex_content=tex_content,
                    engine_name=ENGINE_LATEXMK,
                    pdflatex_passes=1,
                )
                if fallback_result["success"]:
                    fallback_result["fallback_used"] = True
                result = fallback_result

        if not result["success"]:
            with timings.stage("db_save"):
                await save_compile_result(
                    project_id=request.project_id,
                    status="error",
                    log=result["full_log"],
                    pdf_path=None,
                )
            return {
                "success": False,
                "error_type": result["error_type"],
                "log": result["truncated_log"],
            }

        artifact_path = artifact_pdf_path(request.project_id, compile_key)
        latest_path = latest_pdf_path(request.project_id)
        with timings.stage("upload"):
            artifact_upload_ok = await upload_pdf(result["pdf_bytes"], artifact_path)
            latest_upload_ok = await upload_pdf(result["pdf_bytes"], latest_path)

        if not artifact_upload_ok or not latest_upload_ok:
            with timings.stage("db_save"):
                await save_compile_result(
                    project_id=request.project_id,
                    status="error",
                    log="Failed to upload PDF to storage",
                    pdf_path=None,
                )
            return {
                "success": False,
                "error_type": ErrorType.STORAGE_ERROR,
                "log": "Failed to upload PDF to storage",
            }

        with timings.stage("db_save"):
            await save_compile_result(
                project_id=request.project_id,
                status="success",
                log=result["full_log"],
                pdf_path=latest_path,
            )
            if self.settings.enable_compile_cache:
                await upsert_compile_artifact(
                    compile_key=compile_key,
                    project_id=request.project_id,
                    pdf_path=artifact_path,
                    engine=result["engine_used"],
                    flags=strategy_flags,
                )

        cache_entry = CompileCacheEntry(
            key=compile_key,
            pdf_path=artifact_path,
            project_id=request.project_id,
            engine=result["engine_used"],
            flags=strategy_flags,
            created_at=time.time(),
        )
        if self.settings.enable_compile_cache:
            await self.compile_cache.set(cache_entry)

        pdf_url = await self._get_or_refresh_signed_url(cache_entry, timings)
        if not pdf_url:
            return {
                "success": False,
                "error_type": ErrorType.STORAGE_ERROR,
                "log": "Failed to create signed URL for PDF",
            }

        return {
            "success": True,
            "pdf_url": pdf_url,
        }

    async def _run_compile_for_project(
        self,
        *,
        project_id: str,
        tex_content: str,
        engine_name: str,
        pdflatex_passes: int,
    ):
        if self.settings.enable_workdir_cache:
            async with self.workdir_cache.lease(project_id) as workdir:
                return await run_compile(
                    tex_content=tex_content,
                    timeout_seconds=self.settings.compile_timeout_seconds,
                    max_log_chars=self.settings.max_log_response_chars,
                    engine=engine_name,
                    pdflatex_passes=pdflatex_passes,
                    working_dir=str(workdir),
                    cleanup_workdir=False,
                )
        return await run_compile(
            tex_content=tex_content,
            timeout_seconds=self.settings.compile_timeout_seconds,
            max_log_chars=self.settings.max_log_response_chars,
            engine=engine_name,
            pdflatex_passes=pdflatex_passes,
        )

    async def _get_or_refresh_signed_url(self, cache_entry: CompileCacheEntry, timings: TimingRecorder) -> str:
        if self.settings.enable_reuse_signed_url and cache_entry.is_signed_url_valid():
            return cache_entry.signed_url or ""

        with timings.stage("sign"):
            signed_url = await create_signed_url(
                cache_entry.pdf_path,
                expires_in=self.settings.signed_url_ttl_seconds,
            )
        if signed_url:
            cache_entry.signed_url = signed_url
            cache_entry.signed_url_expires_at = time.time() + self.settings.signed_url_ttl_seconds
            if self.settings.enable_compile_cache:
                await self.compile_cache.set(cache_entry)
        return signed_url

    def _strategy_flags(self, engine_name: str, pdflatex_passes: int) -> str:
        if engine_name == ENGINE_LATEXMK:
            return "latexmk"
        return f"pdflatex:{pdflatex_passes}:fallback-latexmk"

    def _log_request(
        self,
        request_id: str,
        project_id: str,
        response: Union[CompileSuccessResponse, CompileErrorResponse],
        timings: TimingRecorder,
        *,
        cache_hit: bool,
    ) -> None:
        timing_data = timings.as_ms()
        logger.info(
            "[%s] compile_result project_id=%s status=%s cache_hit=%s timings=%s",
            request_id,
            project_id,
            response.status,
            cache_hit,
            timing_data,
        )
