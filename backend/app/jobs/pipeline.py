"""The marking pipeline boundary.

Phase 1 deliberately ships an *unavailable* pipeline.  It does not return an
empty result, a zero score or a canned response: it raises, and the runner parks
the job in ``RETRY_SUSPENDED`` with ``PIPELINE_UNAVAILABLE``.  That is the honest
state of a build before Phases 2-8 exist, and it lets the job infrastructure be
tested without pretending marking has been implemented.

A later phase supplies an object with the same ``run`` contract; the runner does
not change.
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
    """Return the configured pipeline.

    There is intentionally no fallback to a fake implementation.  The real
    pipeline is the production choice; when the provider is not configured it
    raises while marking, which the runner records as a truthful parked job.
    The import is local so the marking package can depend on this module's
    outcome types without a cycle.
    """

    from ..marking.pipeline import QuestionMarkingPipeline

    return QuestionMarkingPipeline()
