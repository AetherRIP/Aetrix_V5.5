"""Registered correction engines.

Three names exist.  ``aetrix_legacy`` is the shipped default: it delegates to
the pre-existing per-question pipeline.  ``aetrix_v5_5`` is the reviewed V5
engine, which adds mark integrity, targeted recovery, the independent double
check and the result guard.  ``mathchecker_v5`` is registered and selectable but
raises ``EngineNotImplemented``, so a deployment can record the intended engine
without a half-built pipeline ever writing a mark.

The registry refuses an unknown name instead of falling back, because a
deployment that asks for an engine this build does not contain must fail loudly
rather than mark papers with something the operator did not select.
"""

from __future__ import annotations

from collections.abc import Callable

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from .engine import AetrixEngine, CorrectionEngine, LegacyEngine, MathCheckerEngine

#: Every engine this build admits.  Presence is the contract, and the settings
#: type pins the same three names.
_ENGINES: dict[str, Callable[[], CorrectionEngine]] = {
    AetrixEngine.name: AetrixEngine,
    LegacyEngine.name: LegacyEngine,
    MathCheckerEngine.name: MathCheckerEngine,
}


def engine_names() -> tuple[str, ...]:
    return tuple(sorted(_ENGINES))


def build_engine(settings: Settings) -> CorrectionEngine:
    """Return the configured engine, or refuse to guess."""

    configured = settings.engine.correction_engine
    factory = _ENGINES.get(configured)
    if factory is None:
        raise AppError(
            ErrorCode.CONFIGURATION_ERROR,
            f"Unknown correction engine {configured!r}. Nothing was marked. "
            f"This build contains only {', '.join(engine_names())}.",
            details={"configured": configured, "known": list(engine_names())},
        )
    return factory()
