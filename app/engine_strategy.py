from dataclasses import dataclass

from app.models import ErrorType


ENGINE_LATEXMK = "latexmk"
ENGINE_PDFLATEX = "pdflatex"


@dataclass(frozen=True)
class EnginePlan:
    engine: str
    pdflatex_passes: int = 1
    allow_fallback: bool = False


def choose_engine_plan(adaptive_enabled: bool) -> EnginePlan:
    if adaptive_enabled:
        return EnginePlan(
            engine=ENGINE_PDFLATEX,
            pdflatex_passes=2,
            allow_fallback=True,
        )
    return EnginePlan(engine=ENGINE_LATEXMK, allow_fallback=False)


def should_fallback_from_pdflatex(error_type: ErrorType) -> bool:
    return error_type in {
        ErrorType.LATEX_COMPILE_ERROR,
        ErrorType.COMPILER_UNAVAILABLE,
    }
