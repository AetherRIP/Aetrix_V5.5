"""Re-marking a refused run: link, guards, and engine pinning.

These tests use the real service, API and job runner against PostgreSQL.  They
do not execute a marking pipeline, so they prove nothing about whether a
recovery yields a complete result set - only that the refused run is preserved,
the preconditions hold, repeats collapse onto one job, and a worker running a
different engine refuses the job instead of switching methodology.
"""

from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.core.ids import utcnow
from app.core.security import Principal
from app.correction.guard import RESULT_SOURCE_REFUSED
from app.db.models import CorrectionJob, JobApproval, QuestionResult
from app.db.repositories import JobRepository
from app.jobs.runner import JobRunner
from app.jobs.service import JobService
from app.jobs.states import JobState
from app.schemas.api import RecoveryRequest
from pydantic import ValidationError
from sqlalchemy import func, select


def principal_for(user) -> Principal:
    return Principal(
        user_id=user.id, tenant_id=user.tenant_id, subject=user.subject, role=user.role
    )


def service(db_session) -> JobService:
    return JobService(db_session, get_settings())


def _job(
    db_session,
    paper,
    identity,
    *,
    key: str,
    state: JobState = JobState.REVIEW_REQUIRED,
    result_source: str | None = RESULT_SOURCE_REFUSED,
    engine_name: str | None = "aetrix_v5_5",
) -> CorrectionJob:
    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        idempotency_key=key,
        request_hash="a" * 64,
        state=state.value,
        progress=0.0,
        attempts=0,
        max_attempts=3,
        engine_name=engine_name,
        engine_version="5.5.0" if engine_name else None,
        result_source=result_source,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _rows(db_session, job_id) -> int:
    return int(
        db_session.scalar(
            select(func.count()).select_from(QuestionResult).where(QuestionResult.job_id == job_id)
        )
        or 0
    )


def test_a_refused_run_is_re_marked_as_a_new_linked_job(
    client, paper, identity, db_session, auth_headers
) -> None:
    source = _job(db_session, paper, identity, key="refused-source-0001")

    response = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "the engine refused this run and the teacher wants it re-marked"},
        headers=auth_headers(identity.user_a),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["id"] != str(source.id)
    assert body["state"] == "CREATED"
    assert body["recovery_of_job_id"] == str(source.id)
    assert body["requested_engine_name"] == "aetrix_v5_5"
    # Nothing has marked the new job yet, so it must not claim an engine result.
    assert body["engine_name"] is None
    assert body["result_source"] is None


def test_recovery_leaves_the_refused_run_untouched(
    client, paper, identity, db_session, auth_headers
) -> None:
    source = _job(db_session, paper, identity, key="refused-source-0002")
    before = (
        source.state,
        source.result_source,
        source.engine_name,
        source.engine_version,
        source.record_version,
    )

    client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "re-mark the refused run"},
        headers=auth_headers(identity.user_a),
    )

    db_session.expire_all()
    reloaded = db_session.get(CorrectionJob, source.id)
    assert reloaded is not None
    assert (
        reloaded.state,
        reloaded.result_source,
        reloaded.engine_name,
        reloaded.engine_version,
        reloaded.record_version,
    ) == before
    # The refusal is not a source of marks: the recovery starts empty.
    assert _rows(db_session, reloaded.id) == 0


def test_a_repeated_request_returns_the_recovery_in_progress(
    client, paper, identity, db_session, auth_headers
) -> None:
    source = _job(db_session, paper, identity, key="refused-source-0003")

    first = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "re-mark the refused run"},
        headers=auth_headers(identity.user_a),
    )
    second = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "re-mark the refused run again"},
        headers=auth_headers(identity.user_a),
    )

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(JobRepository(db_session).recoveries_of(identity.tenant_a.id, source.id)) == 1


def test_two_service_calls_collapse_onto_one_recovery(
    paper, identity, db_session
) -> None:
    """A double click in two sessions must not fan out into two jobs."""

    source = _job(db_session, paper, identity, key="refused-source-0004")
    actor = principal_for(identity.user_a)
    payload = RecoveryRequest(reason="re-mark the refused run")

    first = service(db_session).recover(actor, source.id, payload)
    second = service(db_session).recover(actor, source.id, payload)

    assert first.created is True
    assert second.created is False
    assert first.job.id == second.job.id


def test_a_second_refused_attempt_gets_its_own_job(
    client, paper, identity, db_session, auth_headers
) -> None:
    source = _job(db_session, paper, identity, key="refused-source-0005")
    first = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "first re-mark attempt"},
        headers=auth_headers(identity.user_a),
    )
    assert first.status_code == 202
    first_id = first.json()["id"]

    # The recovery itself was refused: it becomes its own piece of evidence.
    attempt = db_session.get(CorrectionJob, first_id)
    assert attempt is not None
    attempt.state = JobState.REVIEW_REQUIRED.value
    attempt.result_source = RESULT_SOURCE_REFUSED
    attempt.engine_name = "aetrix_v5_5"
    attempt.engine_version = "5.5.0"
    db_session.commit()

    second = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "second re-mark attempt"},
        headers=auth_headers(identity.user_a),
    )

    assert second.status_code == 202
    assert second.json()["id"] not in {str(source.id), first_id}
    assert second.json()["recovery_of_job_id"] == str(source.id)
    assert len(JobRepository(db_session).recoveries_of(identity.tenant_a.id, source.id)) == 2


def test_only_a_refused_run_can_be_re_marked(
    client, paper, identity, db_session, auth_headers
) -> None:
    source = _job(
        db_session,
        paper,
        identity,
        key="not-refused-0001",
        result_source=None,
    )

    response = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "try to re-mark a non-refused run"},
        headers=auth_headers(identity.user_a),
    )

    assert response.status_code == 409
    assert "JOB_NOT_RECOVERABLE" in str(response.json())


def test_an_approved_run_cannot_be_re_marked(
    client, paper, identity, db_session, auth_headers
) -> None:
    source = _job(db_session, paper, identity, key="approved-0001")
    db_session.add(
        JobApproval(
            tenant_id=identity.tenant_a.id,
            job_id=source.id,
            approved_by=identity.user_a.id,
            approved_by_label="teacher-a",
            approved_at=utcnow(),
            approved_marks=10,
            total_marks=10,
        )
    )
    db_session.commit()

    response = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "try to re-mark an approved run"},
        headers=auth_headers(identity.user_a),
    )

    assert response.status_code == 409
    assert "approved" in str(response.json()).lower()


def test_recovery_is_tenant_scoped(client, paper, identity, db_session, auth_headers) -> None:
    source = _job(db_session, paper, identity, key="tenant-scope-0001")

    response = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "another tenant tries to re-mark this run"},
        headers=auth_headers(identity.user_b),
    )

    assert response.status_code == 404
    assert len(JobRepository(db_session).recoveries_of(identity.tenant_a.id, source.id)) == 0


def test_a_viewer_cannot_re_mark(client, paper, identity, db_session, auth_headers) -> None:
    source = _job(db_session, paper, identity, key="viewer-0001")

    response = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "a viewer tries to re-mark this run"},
        headers=auth_headers(identity.viewer),
    )

    assert response.status_code == 403
    assert len(JobRepository(db_session).recoveries_of(identity.tenant_a.id, source.id)) == 0


def test_the_guard_still_applies_to_a_recovery(
    client, paper, identity, db_session, auth_headers
) -> None:
    """A recovery is a normal job: it cannot be approved without decided marks."""

    source = _job(db_session, paper, identity, key="guard-applies-0001")
    created = client.post(
        f"/api/v1/corrections/{source.id}/recover",
        json={"reason": "re-mark the refused run"},
        headers=auth_headers(identity.user_a),
    )
    assert created.status_code == 202

    approval = client.post(
        f"/api/v1/corrections/{created.json()['id']}/approve",
        json={"note": None, "expected_record_version": 0},
        headers=auth_headers(identity.user_a),
    )

    assert approval.status_code == 409
    assert "RESULT_NOT_READY" in str(approval.json())


class _OtherEnginePipeline:
    """Stands in for a worker started with a different engine selected."""

    name = "aetrix_v5_5"

    def run(self, *args, **kwargs):  # pragma: no cover - the refusal comes first
        raise AssertionError("a mismatched engine must not run the pipeline")


def test_a_job_pinned_to_another_engine_is_not_marked(
    paper, identity, db_session, session_factory
) -> None:
    job = _job(
        db_session, paper, identity, key="pin-0001", state=JobState.CREATED, result_source=None
    )
    job.engine_name = None
    job.engine_version = None
    job.requested_engine_name = "aetrix_legacy"
    job.requested_engine_version = "legacy"
    db_session.commit()

    runner = JobRunner(
        session_factory=session_factory,
        pipeline=_OtherEnginePipeline(),  # type: ignore[arg-type]
        settings=get_settings(),
        worker_id="pin-worker",
    )
    assert runner.run_once() == str(job.id)

    db_session.expire_all()
    reloaded = db_session.get(CorrectionJob, job.id)
    assert reloaded is not None
    assert reloaded.state == JobState.FAILED.value
    assert reloaded.error_code == "ENGINE_MISMATCH"
    assert reloaded.retryable is False
    # The pin is intact and nothing was written under the other engine.
    assert reloaded.requested_engine_name == "aetrix_legacy"
    assert reloaded.engine_name is None
    assert _rows(db_session, reloaded.id) == 0


def test_a_half_marked_legacy_job_is_not_relabelled(
    paper, identity, db_session, session_factory
) -> None:
    """A retry of a job legacy already started must not run under 5.5."""

    job = _job(
        db_session,
        paper,
        identity,
        key="pin-0002",
        state=JobState.FAILED,
        result_source=None,
        engine_name="aetrix_legacy",
    )
    job.engine_version = "legacy"

    runner = JobRunner(
        session_factory=session_factory,
        pipeline=_OtherEnginePipeline(),  # type: ignore[arg-type]
        settings=get_settings(),
        worker_id="pin-worker",
    )
    assert runner.run_once() == str(job.id)

    db_session.expire_all()
    reloaded = db_session.get(CorrectionJob, job.id)
    assert reloaded is not None
    assert reloaded.error_code == "ENGINE_MISMATCH"
    assert reloaded.engine_name == "aetrix_legacy"
    assert reloaded.engine_version == "legacy"


@pytest.mark.parametrize("reason", ["short", "    "])
def test_a_reason_is_required(reason: str) -> None:
    with pytest.raises(ValidationError):
        RecoveryRequest(reason=reason)
