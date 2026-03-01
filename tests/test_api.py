import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import ErrorType


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestCompileEndpoint:
    @pytest.fixture
    def mock_supabase(self):
        with patch("app.supabase_client.get_project_tex") as mock_get_tex, \
             patch("app.supabase_client.save_compile_result") as mock_save, \
             patch("app.supabase_client.upload_pdf") as mock_upload, \
             patch("app.supabase_client.create_signed_url") as mock_sign:
            mock_get_tex.return_value = r"\documentclass{article}\begin{document}Test\end{document}"
            mock_save.return_value = True
            mock_upload.return_value = True
            mock_sign.return_value = "https://storage.supabase.co/signed/url"
            yield {
                "get_tex": mock_get_tex,
                "save": mock_save,
                "upload": mock_upload,
                "sign": mock_sign,
            }

    def test_compile_with_inline_tex_success(self, client, mock_supabase):
        """Test compile with tex provided in request body."""
        simple_tex = r"\documentclass{article}\begin{document}Hello\end{document}"

        with patch("app.compile.run_compile") as mock_compile:
            async def mock_run(*args, **kwargs):
                return {
                    "success": True,
                    "error_type": None,
                    "full_log": "Compile log",
                    "truncated_log": "Compile log",
                    "pdf_bytes": b"%PDF-1.4 content",
                }
            mock_compile.side_effect = mock_run

            response = client.post("/compile", json={
                "project_id": "550e8400-e29b-41d4-a716-446655440000",
                "tex": simple_tex,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "pdf_url" in data
        assert "compiled_at" in data

    def test_compile_validation_error_size(self, client, mock_supabase):
        """Test that oversized tex returns validation error."""
        large_tex = "x" * 2_000_000  # 2MB

        response = client.post("/compile", json={
            "project_id": "550e8400-e29b-41d4-a716-446655440000",
            "tex": large_tex,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error_type"] == "validation_error"

    def test_compile_dangerous_content_rejected(self, client, mock_supabase):
        """Test that dangerous content is rejected."""
        dangerous_tex = r"\write18{rm -rf /}"

        response = client.post("/compile", json={
            "project_id": "550e8400-e29b-41d4-a716-446655440000",
            "tex": dangerous_tex,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error_type"] == "dangerous_content"

    def test_compile_latex_error(self, client, mock_supabase):
        """Test that LaTeX errors are returned properly."""
        bad_tex = r"\documentclass{article}\begin{document}\badcommand\end{document}"

        with patch("app.compile.run_compile") as mock_compile:
            async def mock_run(*args, **kwargs):
                return {
                    "success": False,
                    "error_type": ErrorType.LATEX_COMPILE_ERROR,
                    "full_log": "! Undefined control sequence.",
                    "truncated_log": "! Undefined control sequence.",
                    "pdf_bytes": None,
                }
            mock_compile.side_effect = mock_run

            response = client.post("/compile", json={
                "project_id": "550e8400-e29b-41d4-a716-446655440000",
                "tex": bad_tex,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error_type"] == "latex_compile_error"
        assert "Undefined" in data["log"]

    def test_compile_project_not_found(self, client):
        """Test that missing project returns error."""
        with patch("app.supabase_client.get_project_tex") as mock_get_tex:
            mock_get_tex.return_value = None

            response = client.post("/compile", json={
                "project_id": "nonexistent-project-id",
            })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error_type"] == "project_not_found"

    def test_compile_storage_error(self, client, mock_supabase):
        """Test that storage upload failure returns error."""
        simple_tex = r"\documentclass{article}\begin{document}Test\end{document}"
        mock_supabase["upload"].return_value = False

        with patch("app.compile.run_compile") as mock_compile:
            async def mock_run(*args, **kwargs):
                return {
                    "success": True,
                    "error_type": None,
                    "full_log": "Compile log",
                    "truncated_log": "Compile log",
                    "pdf_bytes": b"%PDF-1.4 content",
                }
            mock_compile.side_effect = mock_run

            response = client.post("/compile", json={
                "project_id": "550e8400-e29b-41d4-a716-446655440000",
                "tex": simple_tex,
            })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["error_type"] == "storage_error"
