"""Historical provenance survives the move to one engine.

ADR-004 removes the other engines and the selection switch.  It does not rewrite
what any stored row says: a job marked by ``aetrix_legacy`` still reports that
name and version, a job pinned to ``mathchecker_v5`` still says so, and an
``engine_runs`` row keeps the engine and prompt it recorded.  A new execution
records the one surviving engine.
"""

from __future__ import annotations

import uuid

from app.core.config import CORRECTION_ENGINE_NAME
from app.correction import runs
from app.db.models import CorrectionJob, EngineRun
from sqlalchemy import select


def _job(
    db_session,
    paper,
    identity,
    *,
    engine_name: str | None,
    engine_version: str | None,
    requested_engine_name: str | None = None,
    requested_engine_version: str | None = None,
    state: str = "COMPLETED",
) -> CorrectionJob:
    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        idempotency_key=f"historical-{uuid.uuid4().hex[:12]}",
        request_hash="a" * 64,
        state=state,
        engine_name=engine_name,
        engine_version=engine_version,
        requested_engine_name=requested_engine_name,
        requested_engine_version=requested_engine_version,
        result_source="AI_PRIMARY" if engine_name else None,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_a_historical_legacy_run_is_read_unchanged(
    client, auth_headers, paper, identity, db_session
) -> None:
    job = _job(
        db_session, paper, identity, engine_name="aetrix_legacy", engine_version="1.0.0"
    )
    db_session.add(
        EngineRun(
            tenant_id=identity.tenant_a.id,
            job_id=job.id,
            engine_name="aetrix_legacy",
            engine_version="1.0.0",
            prompt_version="question_marking:v1",
            stage=runs.STAGE_MARKING,
            outcome=runs.OUTCOME_OK,
            detail={},
        )
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/corrections/{job.id}", headers=auth_headers(identity.user_a)
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["engine_name"], body["engine_version"]) == ("aetrix_legacy", "1.0.0")

    stored = db_session.scalar(select(EngineRun).where(EngineRun.job_id == job.id))
    assert stored is not None
    assert (stored.engine_name, stored.prompt_version) == (
        "aetrix_legacy",
        "question_marking:v1",
    )


def test_a_historical_placeholder_selection_is_read_unchanged(
    client, auth_headers, paper, identity, db_session
) -> None:
    job = _job(
        db_session,
        paper,
        identity,
        engine_name=None,
        engine_version=None,
        requested_engine_name="mathchecker_v5",
        requested_engine_version="5.0.0",
        state="FAILED",
    )

    response = client.get(
        f"/api/v1/corrections/{job.id}", headers=auth_headers(identity.user_a)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["engine_name"] is None
    assert body["requested_engine_name"] == "mathchecker_v5"


def test_a_new_execution_records_the_one_engine(db_session, paper, identity) -> None:
    job = _job(
        db_session,
        paper,
        identity,
        engine_name=None,
        engine_version=None,
        state="CREATED",
    )

    row = runs.record_run(
        db_session,
        job=job,
        stage=runs.STAGE_MARKING,
        outcome=runs.OUTCOME_OK,
    )
    db_session.commit()

    assert row.engine_name == CORRECTION_ENGINE_NAME == "aetrix_v5_5"
    stored = db_session.get(EngineRun, row.id)
    assert stored is not None
    assert stored.engine_name == "aetrix_v5_5"
