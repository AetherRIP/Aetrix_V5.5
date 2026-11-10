from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import utcnow
from app.core.security import Principal
from app.db.models import (
    CorrectionJob,
    Document,
    ExamBlueprintVersion,
    ProviderUsage,
    QuestionResult,
    ReviewDecision,
    Submission,
)
from app.db.repositories import JobRepository
from app.jobs.pipeline import UnavailablePipeline
from app.jobs.runner import JobRunner
from app.jobs.service import JobService
from app.jobs.states import JobState
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


def _move_to_review(db_session, job: CorrectionJob, reasons: list[str]) -> None:
    repository = JobRepository(db_session)
    repository.transition(job, JobState.VALIDATING)
    repository.transition(
        job,
        JobState.REVIEW_REQUIRED,
        detail={"review_reasons": reasons},
    )
    db_session.commit()


def test_detail_returns_submission_document_provider_and_review_context(
    paper, identity, db_session
) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job
    document = Document(
        tenant_id=identity.tenant_a.id,
        submission_id=paper.submission.id,
        kind="STUDENT",
        storage_key="fixtures/student-1.pdf",
        original_filename="student-1.pdf",
        sha256="d" * 64,
        mime_type="application/pdf",
        size_bytes=2048,
        page_count=2,
        status="PROCESSED",
        ordering_status="ORDERED",
        mapping_status="MAPPED",
    )
    usage = ProviderUsage(
        tenant_id=identity.tenant_a.id,
        job_id=job.id,
        provider="google",
        model="gemini-2.5-pro",
        purpose="MARKING",
        success=True,
        http_status=200,
    )
    decision = ReviewDecision(
        tenant_id=identity.tenant_a.id,
        job_id=job.id,
        question_id="1a",
        requested_reason="The model response was not usable.",
        mode="BALANCED",
    )
    db_session.add_all([document, usage, decision])
    db_session.flush()
    _move_to_review(
        db_session,
        job,
        ["Question 1a: the model response was not usable."],
    )

    detail = service(db_session).detail(actor.tenant_id, job.id)
    assert detail.id == job.id
    assert detail.submission is not None
    assert detail.submission.student_ref == "student-1"
    assert detail.assignment_name == "Fixture assignment"
    assert [item.original_filename for item in detail.documents] == ["student-1.pdf"]
    assert detail.provider_call is not None
    assert detail.provider_call.model == "gemini-2.5-pro"
    assert [item.question_id for item in detail.review_decisions] == ["1a"]
    assert detail.review_reasons == ["Question 1a: the model response was not usable."]
    assert [event.to_state for event in detail.events][-1] == "REVIEW_REQUIRED"

    with pytest.raises(AppError) as error:
        service(db_session).detail(identity.tenant_b.id, job.id)
    assert error.value.code is ErrorCode.NOT_FOUND


def test_review_required_job_can_be_cancelled(paper, identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job
    _move_to_review(db_session, job, ["A teacher must inspect question 1a."])

    cancelled = service(db_session).cancel(actor, job.id)
    assert cancelled.state == "CANCELLED"
    assert cancelled.cancel_requested is True

    event = JobRepository(db_session).events(actor.tenant_id, job.id)[-1]
    assert event.to_state == "CANCELLED"
    assert event.detail["previous_state"] == "REVIEW_REQUIRED"


def test_review_required_job_retry_is_refused_with_reason(paper, identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job
    _move_to_review(db_session, job, ["A teacher must inspect question 1a."])

    with pytest.raises(AppError) as error:
        service(db_session).retry(actor, job.id)
    assert error.value.code is ErrorCode.JOB_NOT_RETRYABLE
    assert "Teacher review is required first" in error.value.message
    assert db_session.get(CorrectionJob, job.id).state == "REVIEW_REQUIRED"


def test_retry_rejects_an_exhausted_budget(paper, identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job
    repository = JobRepository(db_session)
    repository.transition(job, JobState.VALIDATING)
    job.attempts = job.max_attempts
    job.retryable = False
    repository.transition(job, JobState.FAILED, detail={"code": "MAX_ATTEMPTS_EXHAUSTED"})
    db_session.commit()

    with pytest.raises(AppError) as error:
        service(db_session).retry(actor, job.id)
    assert error.value.code is ErrorCode.JOB_NOT_RETRYABLE
    assert "exhausted its attempt budget" in error.value.message


def test_cross_tenant_job_actions_are_not_found(paper, identity, db_session) -> None:
    job = service(db_session).create(principal_for(identity.user_a), make_payload(paper)).job
    other = principal_for(identity.user_b)
    job_service = service(db_session)

    for action in (job_service.cancel, job_service.retry):
        with pytest.raises(AppError) as error:
            action(other, job.id)
        assert error.value.code is ErrorCode.NOT_FOUND


def test_retry_preserves_previous_attempts_and_rejects_a_duplicate(
    paper, identity, db_session
) -> None:
    actor = principal_for(identity.user_a)
    job = service(db_session).create(actor, make_payload(paper)).job
    repository = JobRepository(db_session)
    repository.transition(job, JobState.VALIDATING)
    job.attempts = 2
    repository.transition(job, JobState.RETRY_SUSPENDED, detail={"code": "PIPELINE_UNAVAILABLE"})
    db_session.commit()

    retried = service(db_session).retry(actor, job.id)
    assert retried.state == "VALIDATING"
    assert retried.attempts == 0

    event = repository.events(actor.tenant_id, job.id)[-1]
    assert event.detail["previous_state"] == "RETRY_SUSPENDED"
    assert event.detail["previous_attempts"] == 2

    with pytest.raises(AppError) as error:
        service(db_session).retry(actor, job.id)
    assert error.value.code is ErrorCode.JOB_NOT_RETRYABLE
    assert db_session.scalar(
        select(func.count()).select_from(CorrectionJob).where(CorrectionJob.id == job.id)
    ) == 1
