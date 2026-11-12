"""The Aetrix V5.5 engine: the only correction engine in this build.

The adapter's only jobs are provenance and delegation: it stamps which engine and
model produced the run, then hands the claimed job to ``AetrixPipeline``, which
owns per-question marking, evidence, integrity, recovery, the independent double
check and the result guard.

There is no other engine to choose and no fallback.  A job recorded as created or
marked by a different engine — a historical ``aetrix_legacy`` row, for instance —
is refused rather than re-marked, because changing the engine under a paper has
to be a deliberate, separately recorded decision.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.config import CORRECTION_ENGINE_NAME, CORRECTION_ENGINE_VERSION, Settings
from ...core.errors import AppError, ErrorCode
from ...db.models import CorrectionJob
from ...jobs.pipeline import PipelineOutcome
from ..aetrix.pipeline import AetrixPipeline
from .protocol import engine_attribution_conflict


class AetrixEngine:
    """The correction engine, behind the seam the runner already speaks."""

    #: Stable identifier recorded on every job this engine marks.
    name = CORRECTION_ENGINE_NAME
    #: Engine revision, recorded beside the name so a result can be placed.
    version = CORRECTION_ENGINE_VERSION

    def __init__(self, pipeline: AetrixPipeline | None = None) -> None:
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
            # Only fill an empty attribution: overwriting one would make a
            # resumed job claim it was always marked by this engine.
            current.engine_name = current.engine_name or self.name
            current.engine_version = current.engine_version or self.version
            current.result_source = current.result_source or "AI_PRIMARY"
            current.primary_model = current.primary_model or settings.provider.model_primary
            if settings.marking.double_check_enabled:
                # The second examiner is a different model, and the job records
                # which one, so a disagreement can be read in context.
                current.secondary_model = (
                    current.secondary_model or settings.provider.model_review
                )
            session.commit()

        pipeline = self._pipeline or AetrixPipeline()
        return pipeline.run(job, session, settings)
