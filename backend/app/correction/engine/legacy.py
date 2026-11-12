"""The pre-existing marking pipeline, behind the engine seam.

``aetrix_legacy`` is the default engine and the only one that marks.  It
delegates to ``QuestionMarkingPipeline`` unchanged, so every existing behaviour
— per-question idempotency, review escalation, retryable provider errors — is
exactly what it was before the seam existed.

The adapter adds two things around that unchanged pipeline:

* **provenance** — the job records the engine name and version that produced it;
* **the explicit processing state** — a session hook fills ``processing_state``
  (and the per-question ``engine_version``) in the same flush that writes
  ``status``, using the one shared mapping in ``app.correction.processing``.
  Neither changes an award, and there is no post-run window in which a committed
  row has a status without a state.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.errors import AppError, ErrorCode
from ...db.models import CorrectionJob
from ...jobs.pipeline import PipelineOutcome
from ...marking.pipeline import QuestionMarkingPipeline
from .protocol import engine_attribution_conflict
from .state_hook import install_processing_state_hook


class LegacyEngine:
    #: Stable identifier recorded on every job this engine marks.
    name = "aetrix_legacy"
    #: Engine revision, recorded beside the name so a result can be placed.
    version = "1.0.0"

    def __init__(self, pipeline: QuestionMarkingPipeline | None = None) -> None:
        #: Injected by tests; production builds one per call, which is cheap
        #: because the pipeline holds no connection of its own.
        self._pipeline = pipeline

    def run(
        self, job: CorrectionJob, session: Session, settings: Settings
    ) -> PipelineOutcome:
        current = session.get(CorrectionJob, job.id)
        if current is not None:
            if engine_attribution_conflict(current.engine_name, self.name):
                raise AppError(
                    ErrorCode.CONFIGURATION_ERROR,
                    f"This job was created for {current.engine_name!r} but this worker "
                    f"runs {self.name!r}. Nothing was marked; re-marking under another "
                    "engine has to be a deliberate, separately recorded decision.",
                    details={
                        "recorded_engine": current.engine_name,
                        "worker_engine": self.name,
                    },
                )
            current.engine_name = current.engine_name or self.name
            current.engine_version = current.engine_version or self.version
            current.result_source = current.result_source or "AI_PRIMARY"
            current.primary_model = current.primary_model or settings.provider.model_primary
            session.commit()

        # Installed before the pipeline marks anything: every question result it
        # flushes — on success or before a failure — carries a state.
        install_processing_state_hook(session, engine_version=self.version)

        pipeline = self._pipeline or QuestionMarkingPipeline()
        return pipeline.run(job, session, settings)
