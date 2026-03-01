import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from typing import TypedDict, Optional

from app.models import ErrorType
from app.security import truncate_log

logger = logging.getLogger(__name__)


class CompileResult(TypedDict):
    success: bool
    error_type: Optional[ErrorType]
    full_log: str
    truncated_log: str
    pdf_bytes: Optional[bytes]


async def run_compile(
    tex_content: str,
    timeout_seconds: int,
    max_log_chars: int,
) -> CompileResult:
    """
    Compile LaTeX content to PDF in a sandboxed temp directory.
    
    Returns a CompileResult dict with success status, logs, and PDF bytes if successful.
    """
    compile_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp(prefix=f"compile-{compile_id}-")
    tex_path = os.path.join(temp_dir, "main.tex")
    pdf_path = os.path.join(temp_dir, "main.pdf")

    logger.info(f"[{compile_id}] Starting compile in {temp_dir}")

    try:
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)

        cmd = [
            "latexmk",
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-no-shell-escape",
            "main.tex",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=temp_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds,
                )
                full_log = stdout.decode("utf-8", errors="replace")
                exit_code = process.returncode

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"[{compile_id}] Compile timeout after {timeout_seconds}s")
                return CompileResult(
                    success=False,
                    error_type=ErrorType.TIMEOUT,
                    full_log=f"Compile timed out after {timeout_seconds} seconds",
                    truncated_log=f"Compile timed out after {timeout_seconds} seconds",
                    pdf_bytes=None,
                )

        except Exception as e:
            logger.error(f"[{compile_id}] Failed to run latexmk: {e}")
            return CompileResult(
                success=False,
                error_type=ErrorType.LATEX_COMPILE_ERROR,
                full_log=f"Failed to start compiler: {str(e)}",
                truncated_log=f"Failed to start compiler: {str(e)}",
                pdf_bytes=None,
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
            )
        else:
            return CompileResult(
                success=False,
                error_type=ErrorType.LATEX_COMPILE_ERROR,
                full_log=full_log,
                truncated_log=truncate_log(full_log, max_log_chars),
                pdf_bytes=None,
            )

    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"[{compile_id}] Cleaned up {temp_dir}")
        except Exception as e:
            logger.warning(f"[{compile_id}] Failed to cleanup {temp_dir}: {e}")
