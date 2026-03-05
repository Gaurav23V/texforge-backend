import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.compile_cache import CompileCache, CompileCacheEntry
from app.compile_coordinator import CompileCoordinator
from app.compile_orchestrator import CompileOrchestrator
from app.config import Settings
from app.models import CompileRequest, ErrorType
from app.workdir_cache import WorkdirCache


def build_orchestrator(tmp_path, **setting_overrides):
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_key="service-role-key",
        **setting_overrides,
    )
    return CompileOrchestrator(
        settings=settings,
        compile_semaphore=asyncio.Semaphore(settings.max_concurrent_compiles),
        compile_cache=CompileCache(max_entries=settings.compile_cache_max_entries),
        workdir_cache=WorkdirCache(root_dir=str(tmp_path), max_projects=10),
        coordinator=CompileCoordinator(),
    )


def successful_compile_result():
    return {
        "success": True,
        "error_type": None,
        "full_log": "ok",
        "truncated_log": "ok",
        "pdf_bytes": b"%PDF-1.4",
        "engine_used": "latexmk",
        "fallback_used": False,
    }


@pytest.mark.asyncio
async def test_inline_tex_priority_skips_db_fetch(tmp_path):
    orchestrator = build_orchestrator(tmp_path, enable_compile_cache=False)
    request = CompileRequest(project_id="project-1", tex=r"\documentclass{article}\begin{document}A\end{document}")

    with patch("app.compile_orchestrator.get_project_tex", new=AsyncMock(return_value="db-tex")) as mock_get_tex, \
         patch("app.compile_orchestrator.run_compile", new=AsyncMock(return_value=successful_compile_result())) as mock_run_compile, \
         patch("app.compile_orchestrator.upload_pdf", new=AsyncMock(return_value=True)), \
         patch("app.compile_orchestrator.save_compile_result", new=AsyncMock(return_value=True)), \
         patch("app.compile_orchestrator.create_signed_url", new=AsyncMock(return_value="https://signed/url")):
        response = await orchestrator.compile(request, "req-1")

    assert response.status == "success"
    mock_get_tex.assert_not_awaited()
    mock_run_compile.assert_awaited()


@pytest.mark.asyncio
async def test_inline_empty_tex_returns_validation_error_without_db_fetch(tmp_path):
    orchestrator = build_orchestrator(tmp_path, enable_compile_cache=False)
    request = CompileRequest(project_id="project-1", tex="   ")

    with patch("app.compile_orchestrator.get_project_tex", new=AsyncMock(return_value="db-tex")) as mock_get_tex, \
         patch("app.compile_orchestrator.save_compile_result", new=AsyncMock(return_value=True)) as mock_save:
        response = await orchestrator.compile(request, "req-2")

    assert response.status == "error"
    assert response.error_type == ErrorType.VALIDATION_ERROR
    mock_get_tex.assert_not_awaited()
    mock_save.assert_awaited()


@pytest.mark.asyncio
async def test_db_fetch_used_when_inline_tex_missing(tmp_path):
    orchestrator = build_orchestrator(tmp_path, enable_compile_cache=False)
    request = CompileRequest(project_id="project-1")

    with patch("app.compile_orchestrator.get_project_tex", new=AsyncMock(return_value=r"\documentclass{article}\begin{document}B\end{document}")) as mock_get_tex, \
         patch("app.compile_orchestrator.run_compile", new=AsyncMock(return_value=successful_compile_result())), \
         patch("app.compile_orchestrator.upload_pdf", new=AsyncMock(return_value=True)), \
         patch("app.compile_orchestrator.save_compile_result", new=AsyncMock(return_value=True)), \
         patch("app.compile_orchestrator.create_signed_url", new=AsyncMock(return_value="https://signed/url")):
        response = await orchestrator.compile(request, "req-3")

    assert response.status == "success"
    mock_get_tex.assert_awaited()


@pytest.mark.asyncio
async def test_cache_hit_skips_compile_and_upload(tmp_path):
    orchestrator = build_orchestrator(tmp_path, enable_compile_cache=True)
    request = CompileRequest(project_id="project-1", tex=r"\documentclass{article}\begin{document}C\end{document}")
    cache_entry = CompileCacheEntry(
        key="k",
        pdf_path="project-1/artifacts/k.pdf",
        project_id="project-1",
        engine="latexmk",
        flags="latexmk",
        signed_url="https://signed/url",
        signed_url_expires_at=time.time() + 60,
    )

    with patch.object(orchestrator, "_lookup_cache", new=AsyncMock(return_value=cache_entry)), \
         patch.object(orchestrator, "_get_or_refresh_signed_url", new=AsyncMock(return_value="https://signed/url")), \
         patch("app.compile_orchestrator.run_compile", new=AsyncMock()) as mock_run_compile, \
         patch("app.compile_orchestrator.upload_pdf", new=AsyncMock()) as mock_upload, \
         patch("app.compile_orchestrator.save_compile_result", new=AsyncMock(return_value=True)):
        response = await orchestrator.compile(request, "req-4")

    assert response.status == "success"
    mock_run_compile.assert_not_awaited()
    mock_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_recompile_bypasses_cache(tmp_path):
    orchestrator = build_orchestrator(tmp_path, enable_compile_cache=True)
    request = CompileRequest(
        project_id="project-1",
        tex=r"\documentclass{article}\begin{document}D\end{document}",
        force=True,
    )
    orchestrator.compile_cache.invalidate_project = AsyncMock(return_value=None)

    with patch("app.compile_orchestrator.run_compile", new=AsyncMock(return_value=successful_compile_result())) as mock_run_compile, \
         patch("app.compile_orchestrator.upload_pdf", new=AsyncMock(return_value=True)), \
         patch("app.compile_orchestrator.save_compile_result", new=AsyncMock(return_value=True)), \
         patch("app.compile_orchestrator.create_signed_url", new=AsyncMock(return_value="https://signed/url")), \
         patch("app.compile_orchestrator.upsert_compile_artifact", new=AsyncMock(return_value=True)):
        response = await orchestrator.compile(request, "req-5")

    assert response.status == "success"
    orchestrator.compile_cache.invalidate_project.assert_awaited_once_with("project-1")
    mock_run_compile.assert_awaited()
