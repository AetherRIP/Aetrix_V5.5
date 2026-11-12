"""The ``mathchecker_v5`` engine slot: selectable, registered, not implemented.

The name is accepted by configuration and by the registry so the selection can
be rehearsed and recorded, but selecting it must fail loudly rather than mark
with half a pipeline.  A paper marked by an incomplete engine would look like a
finished result; an unmarked job that says why is the honest outcome.

The V5 implementation itself lives in ``app.correction.aetrix`` and is
registered under the name ``aetrix_v5_5``.  This older slot is kept so a
deployment that selected it fails loudly instead of marking with a half-built
pipeline.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.config import Settings
from ...db.models import CorrectionJob
from ...jobs.pipeline import PipelineOutcome


class EngineNotImplemented(RuntimeError):
    """Raised when a registered engine has no implementation in this build."""


class MathCheckerEngine:
    name = "mathchecker_v5"
    version = "5.0.0"

    def run(
        self, job: CorrectionJob, session: Session, settings: Settings
    ) -> PipelineOutcome:
        del job, session, settings
        raise EngineNotImplemented(
            "The mathchecker_v5 engine is registered but not implemented in this "
            "build, so nothing was marked. Select aetrix_legacy, the working engine."
        )
