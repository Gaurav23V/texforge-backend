import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from app.models import ErrorType


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_orchestrator_singletons():
    app_main._compile_orchestrator = None
    app_main._compile_semaphore = None
    yield
    app_main._compile_orchestrator = None
    app_main._compile_semaphore = None


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestCompileEndpoint:
    def test_compile_endpoint_uses_orchestrator_success(self, client):
        compiled_at = datetime.now(timezone.utc)
        fake_orchestrator = AsyncMock()
        fake_orchestrator.compile.return_value = {
            "status": "success",
            "pdf_url": "https://signed.example/pdf",
            "compiled_at": compiled_at.isoformat(),
        }

        with patch("app.main.get_compile_orchestrator", return_value=fake_orchestrator):
            response = client.post(
                "/compile",
                json={
                    "project_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tex": r"\documentclass{article}\begin{document}Hello\end{document}",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["pdf_url"] == "https://signed.example/pdf"
        assert "compiled_at" in data

    def test_compile_endpoint_uses_orchestrator_error(self, client):
        compiled_at = datetime.now(timezone.utc)
        fake_orchestrator = AsyncMock()
        fake_orchestrator.compile.return_value = {
            "status": "error",
            "error_type": ErrorType.DANGEROUS_CONTENT,
            "log": "dangerous",
            "compiled_at": compiled_at.isoformat(),
        }

        with patch("app.main.get_compile_orchestrator", return_value=fake_orchestrator):
            response = client.post(
                "/compile",
                json={
                    "project_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tex": r"\write18{ls}",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error_type"] == "dangerous_content"
        assert data["log"] == "dangerous"


class TestLatestPdfEndpoint:
    def test_latest_pdf_returns_signed_url(self, client):
        with patch("app.supabase_client.get_latest_successful_compile", new=AsyncMock(return_value={
            "pdf_path": "project-1/latest.pdf",
            "compiled_at": "2026-03-04T10:00:00Z",
        })), patch("app.supabase_client.create_signed_url", new=AsyncMock(return_value="https://signed.example/latest.pdf")):
            response = client.get("/projects/project-1/latest-pdf")

        assert response.status_code == 200
        data = response.json()
        assert data["pdf_url"] == "https://signed.example/latest.pdf"
        assert data["compiled_at"] == "2026-03-04T10:00:00Z"

    def test_latest_pdf_returns_empty_when_not_found(self, client):
        with patch("app.supabase_client.get_latest_successful_compile", new=AsyncMock(return_value=None)):
            response = client.get("/projects/project-1/latest-pdf")

        assert response.status_code == 200
        data = response.json()
        assert data["pdf_url"] is None
        assert data["compiled_at"] is None
