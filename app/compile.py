import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from typing import TypedDict, Optional

from app.engine_strategy import ENGINE_LATEXMK, ENGINE_PDFLATEX
from app.models import ErrorType
from app.security import truncate_log

logger = logging.getLogger(__name__)


class CompilerBinaryMissingError(Exception):
    def __init__(self, binary_name: str):
        super().__init__(f"Compiler binary not found: {binary_name}")
        self.binary_name = binary_name


class CompileResult(TypedDict):
    success: bool
    error_type: Optional[ErrorType]
    full_log: str
    truncated_log: str
    pdf_bytes: Optional[bytes]
    engine_used: str
    fallback_used: bool


async def run_compile(
    tex_content: str,
    timeout_seconds: int,
    max_log_chars: int,
    *,
    engine: str = ENGINE_LATEXMK,
    pdflatex_passes: int = 1,
    working_dir: Optional[str] = None,
    cleanup_workdir: bool = True,
) -> CompileResult:
    """
    Compile LaTeX content to PDF in a sandboxed temp directory.
    
    Returns a CompileResult dict with success status, logs, and PDF bytes if successful.
    """
    compile_id = str(uuid.uuid4())
    temp_dir = working_dir or tempfile.mkdtemp(prefix=f"compile-{compile_id}-")
    tex_path = os.path.join(temp_dir, "main.tex")
    pdf_path = os.path.join(temp_dir, "main.pdf")

    logger.info(f"[{compile_id}] Starting compile in {temp_dir}")

    try:
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)

        try:
            full_log, exit_code = await _run_engine(
                engine=engine,
                pdflatex_passes=pdflatex_passes,
                cwd=temp_dir,
                timeout_seconds=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[{compile_id}] Compile timeout after {timeout_seconds}s")
            return CompileResult(
                success=False,
                error_type=ErrorType.TIMEOUT,
                full_log=f"Compile timed out after {timeout_seconds} seconds",
                truncated_log=f"Compile timed out after {timeout_seconds} seconds",
                pdf_bytes=None,
                engine_used=engine,
                fallback_used=False,
            )
        except CompilerBinaryMissingError as e:
            logger.error(f"[{compile_id}] Missing compiler binary for {engine}: {e.binary_name}")
            install_hint = (
                "Compiler toolchain is not available. "
                "Install TeX tools (`pdflatex`/`latexmk`) or run the backend with Docker."
            )
            return CompileResult(
                success=False,
                error_type=ErrorType.COMPILER_UNAVAILABLE,
                full_log=f"{install_hint}\nMissing binary: {e.binary_name}",
                truncated_log=f"{install_hint}\nMissing binary: {e.binary_name}",
                pdf_bytes=None,
                engine_used=engine,
                fallback_used=False,
            )
        except Exception as e:
            logger.error(f"[{compile_id}] Failed to run {engine}: {e}")
            return CompileResult(
                success=False,
                error_type=ErrorType.LATEX_COMPILE_ERROR,
                full_log=f"Failed to start compiler: {str(e)}",
                truncated_log=f"Failed to start compiler: {str(e)}",
                pdf_bytes=None,
                engine_used=engine,
                fallback_used=False,
            )

        logger.info(f"[{compile_id}] Compile finished with exit code {exit_code}")

        if exit_code == 0 and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            return CompileResult(
                success=True,
                error_type=None,
                full_log=full_log,
                truncated_log=truncate_log(full_log, max_log_chars),
                pdf_bytes=pdf_bytes,
                engine_used=engine,
                fallback_used=False,
            )
        else:
            return CompileResult(
                success=False,
                error_type=ErrorType.LATEX_COMPILE_ERROR,
                full_log=full_log,
                truncated_log=truncate_log(full_log, max_log_chars),
                pdf_bytes=None,
                engine_used=engine,
                fallback_used=False,
            )

    finally:
        if cleanup_workdir and working_dir is None:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"[{compile_id}] Cleaned up {temp_dir}")
            except Exception as e:
                logger.warning(f"[{compile_id}] Failed to cleanup {temp_dir}: {e}")


async def _run_engine(
    *,
    engine: str,
    pdflatex_passes: int,
    cwd: str,
    timeout_seconds: int,
) -> tuple[str, int]:
    if engine == ENGINE_PDFLATEX:
        return await _run_pdflatex(cwd=cwd, timeout_seconds=timeout_seconds, passes=pdflatex_passes)
    return await _run_latexmk(cwd=cwd, timeout_seconds=timeout_seconds)


async def _run_latexmk(*, cwd: str, timeout_seconds: int) -> tuple[str, int]:
    cmd = [
        "latexmk",
        "-pdf",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-no-shell-escape",
        "main.tex",
    ]
    return await _run_subprocess_with_timeout(cmd=cmd, cwd=cwd, timeout_seconds=timeout_seconds)


async def _run_pdflatex(*, cwd: str, timeout_seconds: int, passes: int) -> tuple[str, int]:
    logs: list[str] = []
    last_exit_code = 1
    for _ in range(max(passes, 1)):
        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-no-shell-escape",
            "main.tex",
        ]
        output, exit_code = await _run_subprocess_with_timeout(cmd=cmd, cwd=cwd, timeout_seconds=timeout_seconds)
        logs.append(output)
        last_exit_code = exit_code
        if exit_code != 0:
            break
    return "\n".join(logs), last_exit_code


async def _run_subprocess_with_timeout(*, cmd: list[str], cwd: str, timeout_seconds: int) -> tuple[str, int]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        missing_binary = str(cmd[0]) if cmd else "unknown"
        raise CompilerBinaryMissingError(missing_binary) from exc

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise

    output = stdout.decode("utf-8", errors="replace")
    return output, process.returncode
