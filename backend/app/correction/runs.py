"""Recording what each execution did.

One row per meaningful stage an engine reached, so a job's history answers "which
engine, which prompt, which stage, and what did it decide" without inferring
anything from the final marks.

The rows are written in the caller's transaction and never transcribe script
content or model output beyond short identifiers and decision codes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db.models import CorrectionJob, EngineRun

#: Stages.  Kept as plain strings so a future engine can add one without a
#: schema change; the review screen only reads what it recognises.
STAGE_MARKING = "MARKING"
STAGE_RECOVERY = "RECOVERY"
STAGE_INTEGRITY = "INTEGRITY"
STAGE_DOUBLE_CHECK = "DOUBLE_CHECK"
STAGE_GUARD = "GUARD"

OUTCOME_OK = "OK"
OUTCOME_REVIEW = "REVIEW_REQUIRED"
OUTCOME_KEPT_EXISTING = "KEPT_EXISTING"
OUTCOME_BLOCKED = "BLOCKED"
OUTCOME_SKIPPED = "SKIPPED"
OUTCOME_FAILED = "FAILED"


def record_run(
    session: Session,
    *,
    job: CorrectionJob,
    stage: str,
    outcome: str,
    detail: dict[str, Any] | None = None,
    prompt_version: str | None = None,
) -> EngineRun:
    """Add one provenance row; the caller commits."""

    row = EngineRun(
        tenant_id=job.tenant_id,
        job_id=job.id,
        engine_name=job.engine_name or "aetrix_legacy",
        engine_version=job.engine_version or "unknown",
        prompt_version=prompt_version or job.engine_version,
        stage=stage,
        outcome=outcome,
        detail=detail or {},
    )
    session.add(row)
    session.flush()
    return row
