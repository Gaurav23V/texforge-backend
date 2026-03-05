import pytest
from unittest.mock import AsyncMock, patch

from app.supabase_client import (
    create_signed_url,
    get_project_tex,
    get_compile_artifact,
    upsert_compile_artifact,
    save_compile_result,
    upload_pdf,
)
import app.supabase_client as supabase_client


@pytest.mark.asyncio
async def test_get_project_tex_uses_to_thread():
    response = type("R", (), {"data": {"tex": "hello"}})()
    with patch("app.supabase_client.asyncio.to_thread", new=AsyncMock(return_value=response)) as mock_to_thread:
        tex = await get_project_tex("project-1")

    assert tex == "hello"
    mock_to_thread.assert_awaited()


@pytest.mark.asyncio
async def test_save_compile_result_uses_to_thread():
    with patch("app.supabase_client.asyncio.to_thread", new=AsyncMock(return_value=None)) as mock_to_thread:
        ok = await save_compile_result("project-1", "success", "log", "path.pdf")

    assert ok is True
    mock_to_thread.assert_awaited()


@pytest.mark.asyncio
async def test_upload_and_signed_url_use_to_thread():
    with patch("app.supabase_client.asyncio.to_thread", new=AsyncMock(return_value=None)) as mock_to_thread:
        upload_ok = await upload_pdf(b"pdf-bytes", "path.pdf")
    assert upload_ok is True
    mock_to_thread.assert_awaited()

    signed_response = {"signedURL": "https://signed.example/path.pdf"}
    with patch("app.supabase_client.asyncio.to_thread", new=AsyncMock(return_value=signed_response)) as mock_to_thread:
        url = await create_signed_url("path.pdf")
    assert url == "https://signed.example/path.pdf"
    mock_to_thread.assert_awaited()


@pytest.mark.asyncio
async def test_missing_compile_artifacts_table_is_gracefully_disabled():
    supabase_client._compile_artifacts_table_available = None

    with patch(
        "app.supabase_client.asyncio.to_thread",
        new=AsyncMock(side_effect=Exception("PGRST205 compile_artifacts")),
    ):
        artifact = await get_compile_artifact("k1")

    assert artifact is None
    assert supabase_client._compile_artifacts_table_available is False

    with patch("app.supabase_client.asyncio.to_thread", new=AsyncMock()) as mock_to_thread:
        ok = await upsert_compile_artifact("k1", "p1", "path.pdf", "latexmk", "flags")

    assert ok is True
    mock_to_thread.assert_not_awaited()
