"""The correction-engine contract.

An engine is handed a claimed job, its own session and the resolved settings,
and returns the same ``PipelineOutcome`` the job runner already understands.
Nothing else changes for the runner: it still owns the lease, the heartbeat and
the terminal transition.

The type is deliberately narrow.  An engine may not transition a job, approve a
result, or reach for a tenant it was not given; the only way it affects the
platform is the persisted question results it writes for the claimed job.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from ...core.config import Settings
from ...db.models import CorrectionJob
from ...jobs.pipeline import PipelineOutcome


def engine_attribution_conflict(recorded: str | None, name: str) -> bool:
    """True when a job was created for an engine other than this one.

    Re-marking a paper under a different engine is a deliberate act, never a
    side effect of which worker happened to claim the job.
    """

    return bool(recorded) and recorded != name


@runtime_checkable
class CorrectionEngine(Protocol):
    #: Stable identifier recorded on every job the engine marks.
    name: str
    #: Engine revision recorded alongside it, so a result says what produced it.
    version: str

    def run(
        self, job: CorrectionJob, session: Session, settings: Settings
    ) -> PipelineOutcome: ...
