"""Integration coverage for the result guard and stale-write refusal.

These tests need a disposable PostgreSQL database (``AETRIX_TEST_DATABASE_URL``);
the suite refuses to truncate anything else.  They are the only place the
``FOR UPDATE`` reads, the approval/override lookups and the database check
constraint are exercised for real.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.core.config import get_settings
from app.correction.aetrix.pipeline import AetrixPipeline, validation_failed_for
from app.correction.guard import (
    ACTION_BLOCKED,
    ACTION_KEEP_EXISTING,
    RESULT_SOURCE_REFUSED,
    PriorResult,
    evaluate_overwrite,
)
from app.db.models import CorrectionJob, JobApproval, QuestionResult
from app.db.repositories import ResultRepository
from app.jobs.runner import JobRunner
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _job(db_session, paper, identity, *, key: str, state: str = "COMPLETED") -> CorrectionJob:
    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        idempotency_key=key,
        request_hash="c" * 64,
        state=state,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _result(
    db_session,
    identity,
    job,
    *,
    question_id: str = "1a",
    awarded: int = 2,
    max_marks: int = 2,
    concerns: list[dict] | None = None,
) -> QuestionResult:
    row = QuestionResult(
        tenant_id=identity.tenant_a.id,
        job_id=job.id,
        question_id=question_id,
        max_marks=max_marks,
        awarded_marks=awarded,
        status="AWARDED" if awarded else "ZERO",
        processing_state="MARKED" if awarded else "CONFIRMED_ZERO",
        review_required=False,
        scheme_concerns=concerns or [],
    )
    db_session.add(row)
    db_session.commit()
    return row


def _approve(db_session, job) -> None:
    db_session.add(
        JobApproval(
            tenant_id=job.tenant_id,
            job_id=job.id,
            approved_at=datetime.now(UTC),
            approved_marks=2,
            total_marks=2,
            record_version=0,
        )
    )
    db_session.commit()


def test_the_guard_refuses_a_run_that_failed_its_own_validation(
    db_session, paper, identity
) -> None:
    """The live caller must pass validation state, not judge totals alone."""

    prior = _job(db_session, paper, identity, key="validated")
    _result(db_session, identity, prior, question_id="1a", awarded=2, max_marks=2)
    current = _job(db_session, paper, identity, key="invalid", state="CORRECTING")
    row = _result(db_session, identity, current, question_id="1a", awarded=1, max_marks=2)
    # Totals look plausible, but the reply could not be parsed: the award is a
    # placeholder and the run must not overwrite the stored result.
    row.status = "REVIEW_REQUIRED"
    row.processing_state = "NEEDS_REVIEW"
    row.review_required = True
    row.normalisation_anomaly = "MODEL_RESPONSE_INVALID"
    db_session.commit()

    validation_failed = validation_failed_for([row], [])
    assert validation_failed is True

    action = AetrixPipeline()._apply_guard(
        session=db_session,
        current=current,
        rows=[row],
        validation_failed=validation_failed,
    )

    assert action == ACTION_KEEP_EXISTING
    db_session.refresh(current)
    assert current.result_source == RESULT_SOURCE_REFUSED


def test_the_prior_result_is_the_other_job_on_the_submission(
    db_session, paper, identity
) -> None:
    prior = _job(db_session, paper, identity, key="prior")
    _result(db_session, identity, prior, question_id="1a", awarded=2, max_marks=2)
    _result(db_session, identity, prior, question_id="1b", awarded=1, max_marks=3)
    current = _job(db_session, paper, identity, key="current", state="CORRECTING")

    totals = ResultRepository(db_session).prior_job_totals(
        identity.tenant_a.id, paper.submission.id, exclude_job_id=current.id
    )

    assert totals is not None
    job_id, earned, available, approved, override = totals
    assert job_id == prior.id
    assert (earned, available) == (3, 5)
    assert approved is False
    assert override is False


def test_no_other_job_means_nothing_to_protect(db_session, paper, identity) -> None:
    only = _job(db_session, paper, identity, key="only")

    assert (
        ResultRepository(db_session).prior_job_totals(
            identity.tenant_a.id, paper.submission.id, exclude_job_id=only.id
        )
        is None
    )


def test_an_approved_result_cannot_be_replaced(db_session, paper, identity) -> None:
    prior = _job(db_session, paper, identity, key="approved")
    _result(db_session, identity, prior, awarded=2, max_marks=2)
    _approve(db_session, prior)
    current = _job(db_session, paper, identity, key="newer", state="CORRECTING")

    totals = ResultRepository(db_session).prior_job_totals(
        identity.tenant_a.id, paper.submission.id, exclude_job_id=current.id
    )
    assert totals is not None and totals[3] is True

    decision = evaluate_overwrite(
        prior=PriorResult(
            job_id=totals[0],
            earned=totals[1],
            available=totals[2],
            approved=totals[3],
            teacher_override=totals[4],
        ),
        earned=2,
        available=2,
    )

    assert decision.action == ACTION_BLOCKED
    assert decision.may_present is False


def test_a_teacher_override_is_detected_and_respected(db_session, paper, identity) -> None:
    prior = _job(db_session, paper, identity, key="overridden")
    _result(
        db_session,
        identity,
        prior,
        awarded=1,
        max_marks=2,
        concerns=[{"code": "TEACHER_OVERRIDE", "message": "M1 awarded on review"}],
    )
    current = _job(db_session, paper, identity, key="later", state="CORRECTING")

    totals = ResultRepository(db_session).prior_job_totals(
        identity.tenant_a.id, paper.submission.id, exclude_job_id=current.id
    )
    assert totals is not None and totals[4] is True

    decision = evaluate_overwrite(
        prior=PriorResult(
            job_id=totals[0],
            earned=totals[1],
            available=totals[2],
            approved=totals[3],
            teacher_override=totals[4],
        ),
        earned=1,
        available=2,
    )

    assert decision.action == ACTION_KEEP_EXISTING


def test_another_workspace_sees_no_prior_result(db_session, paper, identity) -> None:
    prior = _job(db_session, paper, identity, key="tenant-a-job")
    _result(db_session, identity, prior)
    current = _job(db_session, paper, identity, key="tenant-a-current", state="CORRECTING")

    assert (
        ResultRepository(db_session).prior_job_totals(
            identity.tenant_b.id, paper.submission.id, exclude_job_id=current.id
        )
        is None
    )


def test_processing_state_rejects_an_unknown_value(db_session, paper, identity) -> None:
    job = _job(db_session, paper, identity, key="constraint")
    row = _result(db_session, identity, job)

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("update question_results set processing_state = 'MAYBE' where id = :id"),
            {"id": row.id},
        )
        db_session.commit()
    db_session.rollback()


def test_a_stale_worker_refuses_to_write(
    session_factory, db_session, paper, identity
) -> None:
    job = _job(db_session, paper, identity, key="stale", state="CORRECTING")
    job.record_version = 4
    job.lease_owner = "another-worker"
    db_session.commit()

    runner = JobRunner(
        session_factory=session_factory,
        pipeline=None,  # type: ignore[arg-type] - only the refusal path is used
        settings=get_settings(),
        worker_id="this-worker",
    )

    with session_factory() as session:
        loaded = session.get(CorrectionJob, job.id)
        assert runner._refuse_stale_write(session, loaded, 4) is True

    refused = db_session.scalar(
        text("select count(*) from audit_events where action = 'job.stale_write_refused'")
    )
    assert refused == 1


def test_a_current_worker_with_the_claimed_version_may_write(
    session_factory, db_session, paper, identity
) -> None:
    job = _job(db_session, paper, identity, key="current-lease", state="CORRECTING")
    job.record_version = 2
    job.lease_owner = "this-worker"
    db_session.commit()

    runner = JobRunner(
        session_factory=session_factory,
        pipeline=None,  # type: ignore[arg-type]
        settings=get_settings(),
        worker_id="this-worker",
    )

    with session_factory() as session:
        loaded = session.get(CorrectionJob, job.id)
        assert runner._refuse_stale_write(session, loaded, 2) is False


def test_a_version_change_after_the_claim_refuses_the_write(
    session_factory, db_session, paper, identity
) -> None:
    job = _job(db_session, paper, identity, key="moved-on", state="CORRECTING")
    job.record_version = 5
    job.lease_owner = "this-worker"
    db_session.commit()

    runner = JobRunner(
        session_factory=session_factory,
        pipeline=None,  # type: ignore[arg-type]
        settings=get_settings(),
        worker_id="this-worker",
    )

    with session_factory() as session:
        loaded = session.get(CorrectionJob, job.id)
        assert runner._refuse_stale_write(session, loaded, 3) is True


def test_a_job_without_an_override_or_approval_is_updatable(
    db_session, paper, identity
) -> None:
    prior = _job(db_session, paper, identity, key="plain")
    _result(db_session, identity, prior, awarded=2, max_marks=2)
    current = _job(db_session, paper, identity, key="plain-2", state="CORRECTING")

    totals = ResultRepository(db_session).prior_job_totals(
        identity.tenant_a.id, paper.submission.id, exclude_job_id=current.id
    )
    assert totals is not None

    decision = evaluate_overwrite(
        prior=PriorResult(
            job_id=totals[0],
            earned=totals[1],
            available=totals[2],
            approved=totals[3],
            teacher_override=totals[4],
        ),
        earned=2,
        available=2,
    )
    assert decision.may_present is True


def test_new_rows_accept_every_documented_state(db_session, paper, identity) -> None:
    job = _job(db_session, paper, identity, key="states")

    for index, (state, status) in enumerate(
        [
            ("MARKED", "AWARDED"),
            ("CONFIRMED_ZERO", "ZERO"),
            ("UNMARKED", "UNMARKED"),
            ("NEEDS_REVIEW", "REVIEW_REQUIRED"),
        ]
    ):
        db_session.add(
            QuestionResult(
                tenant_id=identity.tenant_a.id,
                job_id=job.id,
                question_id=f"q{index}",
                max_marks=2,
                awarded_marks=1 if state == "MARKED" else 0,
                status=status,
                processing_state=state,
                review_required=state == "NEEDS_REVIEW",
                scheme_concerns=[],
            )
        )
    db_session.commit()

    stored = db_session.scalar(
        text(
            "select count(*) from question_results "
            "where job_id = :id and processing_state is not null"
        ),
        {"id": job.id},
    )
    assert stored == 4
