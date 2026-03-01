import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio

from app.compile import run_compile
from app.models import ErrorType


@pytest.fixture
def simple_tex():
    return r"""
\documentclass{article}
\begin{document}
Hello, World!
\end{document}
"""


class TestRunCompile:
    @pytest.mark.asyncio
    async def test_successful_compile_returns_pdf_bytes(self, simple_tex):
        """Test that successful compile returns PDF bytes."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"Output log", None))
        mock_process.returncode = 0
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with patch("os.path.exists", return_value=True):
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock())
                    mock_open.return_value.__exit__ = MagicMock(return_value=False)
                    mock_open.return_value.__enter__.return_value.read = MagicMock(
                        return_value=b"%PDF-1.4 fake pdf content"
                    )
                    mock_open.return_value.__enter__.return_value.write = MagicMock()

                    with patch("shutil.rmtree"):
                        result = await run_compile(
                            tex_content=simple_tex,
                            timeout_seconds=15,
                            max_log_chars=20000,
                        )

        assert result["success"] is True
        assert result["error_type"] is None
        assert "Output log" in result["full_log"]

    @pytest.mark.asyncio
    async def test_compile_failure_returns_error(self, simple_tex):
        """Test that failed compile returns error with log."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"LaTeX Error: Something went wrong", None))
        mock_process.returncode = 1
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with patch("os.path.exists", return_value=False):
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock())
                    mock_open.return_value.__exit__ = MagicMock(return_value=False)
                    mock_open.return_value.__enter__.return_value.write = MagicMock()

                    with patch("shutil.rmtree"):
                        result = await run_compile(
                            tex_content=simple_tex,
                            timeout_seconds=15,
                            max_log_chars=20000,
                        )

        assert result["success"] is False
        assert result["error_type"] == ErrorType.LATEX_COMPILE_ERROR
        assert "Something went wrong" in result["full_log"]

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_error(self, simple_tex):
        """Test that timeout returns timeout error."""
        mock_process = AsyncMock()

        async def slow_communicate():
            await asyncio.sleep(100)
            return (b"", None)

        mock_process.communicate = slow_communicate
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()
        mock_process.returncode = -9

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.__enter__.return_value.write = MagicMock()

                with patch("shutil.rmtree"):
                    result = await run_compile(
                        tex_content=simple_tex,
                        timeout_seconds=0.1,
                        max_log_chars=20000,
                    )

        assert result["success"] is False
        assert result["error_type"] == ErrorType.TIMEOUT
        assert "timed out" in result["full_log"].lower()

    @pytest.mark.asyncio
    async def test_log_truncation_applied(self, simple_tex):
        """Test that long logs are truncated in truncated_log but not full_log."""
        long_log = "x" * 50000
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(long_log.encode(), None))
        mock_process.returncode = 1
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with patch("os.path.exists", return_value=False):
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock())
                    mock_open.return_value.__exit__ = MagicMock(return_value=False)
                    mock_open.return_value.__enter__.return_value.write = MagicMock()

                    with patch("shutil.rmtree"):
                        result = await run_compile(
                            tex_content=simple_tex,
                            timeout_seconds=15,
                            max_log_chars=1000,
                        )

        assert len(result["full_log"]) == 50000
        assert len(result["truncated_log"]) < 50000
        assert "truncated" in result["truncated_log"].lower()
