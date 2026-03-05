from app.engine_strategy import (
    ENGINE_LATEXMK,
    ENGINE_PDFLATEX,
    choose_engine_plan,
    should_fallback_from_pdflatex,
)
from app.models import ErrorType


def test_choose_engine_plan_prefers_pdflatex_when_enabled():
    plan = choose_engine_plan(adaptive_enabled=True)
    assert plan.engine == ENGINE_PDFLATEX
    assert plan.pdflatex_passes == 2
    assert plan.allow_fallback is True


def test_choose_engine_plan_uses_latexmk_when_disabled():
    plan = choose_engine_plan(adaptive_enabled=False)
    assert plan.engine == ENGINE_LATEXMK
    assert plan.allow_fallback is False


def test_fallback_only_on_compile_errors():
    assert should_fallback_from_pdflatex(ErrorType.LATEX_COMPILE_ERROR) is True
    assert should_fallback_from_pdflatex(ErrorType.COMPILER_UNAVAILABLE) is True
    assert should_fallback_from_pdflatex(ErrorType.TIMEOUT) is False
