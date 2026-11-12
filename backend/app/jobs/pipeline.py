"""The marking pipeline boundary.

The pipeline is the object the job runner calls.  This build contains one
correction engine — ``aetrix_v5_5`` — and ``build_pipeline`` returns it, always,
with no registry, no configuration switch and no fallback.

``UnavailablePipeline`` is not an engine and is not reachable from configuration:
it is the explicit "nothing to run" object the job-infrastructure tests use.  It
raises, and the runner parks the job in ``RETRY_SUSPENDED`` with
``PIPELINE_UNAVAILABLE``, rather than returning an empty result, a zero score or
a canned response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ..core.config import Settings
from ..db.models import CorrectionJob
from .states import JobState


class PipelineUnavailable(RuntimeError):
    """Raised when the build has no marking pipeline configured."""


class RetryablePipelineError(RuntimeError):
    """A provider or transport failure that should be retried later."""


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    state: JobState
    detail: dict[str, Any] = field(default_factory=dict)


class CorrectionPipeline(Protocol):
    name: str

    def run(self, job: CorrectionJob, session: Session, settings: Settings) -> PipelineOutcome: ...


class UnavailablePipeline:
    name = "unavailable"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or (
            "The marking pipeline is not configured in this build. "
            "Document processing, blueprint extraction, marking and verification "
            "arrive in later phases; this job has not been marked."
        )

    def run(self, job: CorrectionJob, session: Session, settings: Settings) -> PipelineOutcome:
        raise PipelineUnavailable(self.reason)


def build_pipeline(settings: Settings) -> CorrectionPipeline:
    """Return the one correction engine this build contains.

    ``aetrix_v5_5`` is the only engine.  There is intentionally no selection and
    no fallback: an unsupported engine request fails at configuration time, and a
    job recorded under a different engine is refused by the runner, rather than
    being marked with something the operator did not choose.

    ``settings`` is accepted because the worker resolves a single settings object
    for the whole process; the engine reads its own configuration when it runs.
    The import is local so the correction package can depend on this module's
    outcome types without a cycle.
    """

    from ..correction.engine import AetrixEngine

    return AetrixEngine()
