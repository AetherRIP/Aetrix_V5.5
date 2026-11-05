from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import utcnow
from app.core.security import Principal
from app.db.models import CorrectionJob, ExamBlueprintVersion, QuestionResult, Submission
from app.db.repositories import JobRepository
from app.jobs.pipeline import UnavailablePipeline
from app.jobs.runner import JobRunner
from app.jobs.service import JobService
from app.schemas.api import CorrectionCreate
from sqlalchemy import func, select


def principal_for(user) -> Principal:
    return Principal(
        user_id=user.id, tenant_id=user.tenant_id, subject=user.subject, role=user.role
    )


def make_payload(paper, key: str = "key-00000001") -> CorrectionCreate:
    return CorrectionCreate(
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        idempotency_key=key,
    )


def service(db_session) -> JobService:
    return JobService(db_session, get_settings())


def test_creation_is_idempotent(paper, identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    first = service(db_session).create(actor, make_payload(paper))
    second = service(db_session).create(actor, make_payload(paper))

    assert first.created is True
    assert second.created is False
    assert first.job.id == second.job.id
    assert first.job.request_hash == second.job.request_hash


def test_same_key_for_a_different_request_is_a_conflict(paper, identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    service(db_session).create(actor, make_payload(paper))

    other = Submission(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        student_ref="student-2",
        status="REGISTERED",
        content_hash="c" * 64,
    )
    db_session.add(other)
    db_session.commit()

    with pytest.raises(AppError) as error:
        service(db_session).create(
            actor,
            CorrectionCreate(
                assignment_id=paper.assignment.id,
                submission_id=other.id,
                idempotency_key="key-00000001",
            ),
        )
    assert error.value.code is ErrorCode.CONFLICT


def test_unapproved_blueprint_cannot_start_a_job(paper, identity, db_session) -> None:
    draft = ExamBlueprintVersion(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        version=2,
        status="DRAFT",
        structure=paper.blueprint.structure,
        total_marks=paper.blueprint.total_marks,
        content_hash="e" * 64,
        created_by=identity.user_a.id,
    )
    db_session.add(draft)
    db_session.flush()
    paper.assignment.blueprint_version_id = draft.id
    db_session.commit()

    with pytest.raises(AppError) as error:
        service(db_session).create(principal_for(identity.user_a), make_payload(paper))
    assert error.value.code is ErrorCode.BLUEPRINT_NOT_APPROVED


def test_claim_is_exclusive_and_expired_leases_are_reclaimed(paper, identity, db_session) -> None:
    job = service(db_session).create(principal_for(identity.user_a), make_payload(paper)).job
    repository = JobRepository(db_session)

    claimed = repository.claim_next(worker_id="worker-1", lease_seconds=60)
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.state == "VALIDATING"
    assert claimed.attempts == 1
    assert claimed.lease_owner == "worker-1"

    assert repository.claim_next(worker_id="worker-2", lease_seconds=60) is None

    db_session.expire_all()
    claimed = db_session.get(CorrectionJob, job.id)
    claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    reclaimed = repository.claim_next(worker_id="worker-2", lease_seconds=60)
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.attempts == 2
    assert reclaimed.lease_owner == "worker-2"


def test_exhausted_attempts_fail_instead_of_reclaiming(paper, identity, db_session) -> None:
    job = service(db_session).create(principal_for(identity.user_a), make_payload(paper)).job
    job.attempts = job.max_attempts
    db_session.commit()

    assert JobRepository(db_session).claim_next(worker_id="worker-1", lease_seconds=60) is None

    db_session.expire_all()
    failed = db_session.get(CorrectionJob, job.id)
    assert failed.state == "FAILED"
    assert failed.error_code == "MAX_ATTEMPTS_EXHAUSTED"


def test_cancel_is_terminal_and_idempotent(paper, identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job

    cancelled = service(db_session).cancel(actor, job.id)
    assert cancelled.state == "CANCELLED"

    again = service(db_session).cancel(actor, job.id)
    assert again.state == "CANCELLED"

    with pytest.raises(AppError) as error:
        service(db_session).retry(actor, job.id)
    assert error.value.code is ErrorCode.JOB_NOT_RETRYABLE


def test_active_cancel_is_finalized_by_the_worker(
    paper, identity, db_session, session_factory
) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job
    JobRepository(db_session).claim_next(worker_id="worker-1", lease_seconds=60)

    cancelled = service(db_session).cancel(actor, job.id)
    assert cancelled.state == "CANCELLED"
    assert cancelled.cancel_requested is True
    assert cancelled.lease_owner is None

    runner = JobRunner(
        session_factory=session_factory,
        pipeline=UnavailablePipeline(),
        settings=get_settings(),
        worker_id="worker-runner",
    )
    assert runner.run_once() is None

    db_session.expire_all()
    assert db_session.get(CorrectionJob, job.id).state == "CANCELLED"


def test_unavailable_pipeline_parks_without_fake_results(
    paper, identity, db_session, session_factory
) -> None:
    job = service(db_session).create(principal_for(identity.user_a), make_payload(paper)).job
    runner = JobRunner(
        session_factory=session_factory,
        pipeline=UnavailablePipeline(),
        settings=get_settings(),
        worker_id="worker-runner",
    )

    assert runner.run_once() == str(job.id)

    db_session.expire_all()
    parked = db_session.get(CorrectionJob, job.id)
    assert parked.state == "RETRY_SUSPENDED"
    assert parked.error_code == "PIPELINE_UNAVAILABLE"
    assert parked.retryable is True
    assert db_session.scalar(select(func.count()).select_from(QuestionResult)) == 0

    # A suspended job is not picked up automatically; it waits for an explicit retry.
    assert runner.run_once() is None


def test_manual_retry_resets_the_attempt_budget(
    paper, identity, db_session, session_factory
) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job
    runner = JobRunner(
        session_factory=session_factory,
        pipeline=UnavailablePipeline(),
        settings=get_settings(),
        worker_id="worker-runner",
    )
    runner.run_once()

    db_session.expire_all()
    retried = service(db_session).retry(actor, job.id)
    assert retried.state == "VALIDATING"
    assert retried.attempts == 0
    assert retried.error_code is None


def test_cross_tenant_job_read_is_not_found(paper, identity, db_session) -> None:
    job = service(db_session).create(principal_for(identity.user_a), make_payload(paper)).job
    with pytest.raises(AppError) as error:
        service(db_session).get(identity.tenant_b.id, job.id)
    assert error.value.code is ErrorCode.NOT_FOUND
