import pytest
from unittest.mock import AsyncMock, patch

from app.main import _warmup_compiler


@pytest.mark.asyncio
async def test_warmup_compiler_runs_compile():
    with patch("app.compile.run_compile", new=AsyncMock(return_value={"success": True})) as mock_compile:
        await _warmup_compiler()
    mock_compile.assert_awaited()


@pytest.mark.asyncio
async def test_warmup_compiler_swallows_errors():
    with patch("app.compile.run_compile", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await _warmup_compiler()
