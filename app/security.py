import re
from typing import Optional, Tuple

from app.models import ErrorType

DANGEROUS_PATTERNS = [
    (r"\\write18", "Shell escape via \\write18 is not allowed"),
    (r"\\input\s*\{\s*http", "Network input via \\input{http is not allowed"),
    (r"\\include\s*\{\s*http", "Network include via \\include{http is not allowed"),
    (r"\\input\s*\|\s*", "Pipe input is not allowed"),
    (r"\\immediate\\write18", "Immediate shell escape is not allowed"),
]


def contains_dangerous_content(tex: str) -> Optional[str]:
    """
    Check if tex content contains dangerous patterns.
    Returns the warning message if dangerous content is found, None otherwise.
    """
    for pattern, message in DANGEROUS_PATTERNS:
        if re.search(pattern, tex, re.IGNORECASE):
            return message
    return None


def validate_tex_content(tex: str, max_size_bytes: int) -> Optional[Tuple[ErrorType, str]]:
    """
    Validate tex content for size and dangerous patterns.
    Returns (ErrorType, message) tuple if validation fails, None if valid.
    """
    tex_bytes = tex.encode("utf-8")
    if len(tex_bytes) > max_size_bytes:
        return (
            ErrorType.VALIDATION_ERROR,
            f"TeX content exceeds maximum size of {max_size_bytes // 1_000_000}MB",
        )

    dangerous_msg = contains_dangerous_content(tex)
    if dangerous_msg:
        return (ErrorType.DANGEROUS_CONTENT, dangerous_msg)

    return None


def truncate_log(log: str, max_chars: int) -> str:
    """Truncate log to max_chars, adding indicator if truncated."""
    if len(log) <= max_chars:
        return log
    return log[:max_chars] + "\n\n... [log truncated] ..."
