"""The student report route: tenant scoping, approval wording and detail levels."""

from __future__ import annotations

import uuid

import pymupdf
from app.core.config import get_settings
from app.core.security import Principal
from app.db.models import QuestionResult
from app.jobs.service import JobService
from app.schemas.api import CorrectionCreate

#: Every leaf in the fixture blueprint, so an approval can cover the paper.
_ROWS = (
    ("1a", 2, 2),
    ("1b", 3, 1),
    ("2", 5, 2),
)


def _principal(user) -> Principal:
    return Principal(
        user_id=user.id, tenant_id=user.tenant_id, subject=user.subject, role=user.role
    )


def _completed_job(paper, identity, db_session):
    job = JobService(db_session, get_settings()).create(
        _principal(identity.user_a),
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=f"report-{uuid.uuid4().hex[:12]}",
        ),
    ).job
    job.state = "COMPLETED"
    for question_id, max_marks, awarded in _ROWS:
        db_session.add(
            QuestionResult(
                tenant_id=job.tenant_id,
                job_id=job.id,
                question_id=question_id,
                max_marks=max_marks,
                awarded_marks=awarded,
                status="AWARDED",
                processing_state="MARKED",
                confidence=0.95,
                review_required=False,
                scheme_concerns=[],
            )
        )
    db_session.commit()
    return job


def _text(response) -> str:
    return "\n".join(
        page.get_text() for page in pymupdf.open(stream=response.content, filetype="pdf")
    ).upper()


def _report(client, headers, submission_id, detail: str | None = None):
    query = f"?detail={detail}" if detail else ""
    return client.get(f"/api/v1/submissions/{submission_id}/report{query}", headers=headers)


def test_the_report_is_a_pdf_for_the_owning_workspace(
    client, identity, auth_headers, paper, db_session
) -> None:
    job = _completed_job(paper, identity, db_session)

    response = _report(client, auth_headers(identity.user_a), paper.submission.id)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert ".pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")

    text = _text(response)
    assert "STUDENT CORRECTION REPORT" in text
    # ``_text`` upper-cases the extracted page text, so every literal is compared
    # in that form; the reference is still the stored one, not a rewritten value.
    assert "STUDENT-1" in text
    assert "FIXTURE ASSIGNMENT" in text
    assert str(job.id)[:8].upper() in text
    assert "5 / 10" in text
    assert "Q1A" in text and "Q1B" in text
    # Unapproved, so the document says so rather than presenting a final result.
    assert "NEEDS REVIEW" in text
    assert "NO TEACHER HAS APPROVED THIS RESULT" in text


def test_an_approved_result_is_labelled_approved(
    client, identity, auth_headers, paper, db_session
) -> None:
    job = _completed_job(paper, identity, db_session)
    headers = auth_headers(identity.user_a)
    approved = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert approved.status_code == 200, approved.text

    text = _text(_report(client, headers, paper.submission.id))
    assert "APPROVED BY TEACHER" in text
    assert "NO TEACHER HAS APPROVED THIS RESULT" not in text
    assert "50%" in text


def test_detail_levels_are_served_from_the_same_result(
    client, identity, auth_headers, paper, db_session
) -> None:
    _completed_job(paper, identity, db_session)
    headers = auth_headers(identity.user_a)

    summary = _text(_report(client, headers, paper.submission.id, "summary"))
    standard = _text(_report(client, headers, paper.submission.id, "standard"))
    detailed = _text(_report(client, headers, paper.submission.id, "detailed"))

    assert "QUESTION BREAKDOWN" not in summary
    assert "QUESTION BREAKDOWN" in standard
    assert "MARKING DETAIL" not in standard
    assert "MARKING DETAIL" in detailed
    # The approved scheme's mark points reach the detailed report.
    assert "M1 FOR FORMING THE EQUATION" in detailed


def test_a_report_is_never_served_across_workspaces(
    client, identity, auth_headers, paper, db_session
) -> None:
    _completed_job(paper, identity, db_session)

    response = _report(client, auth_headers(identity.user_b), paper.submission.id)
    assert response.status_code == 404


def test_a_submission_without_a_result_has_no_report(
    client, identity, auth_headers, paper
) -> None:
    response = _report(client, auth_headers(identity.user_a), paper.submission.id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"


def test_an_incomplete_result_prints_as_a_draft(
    client, identity, auth_headers, paper, db_session
) -> None:
    job = _completed_job(paper, identity, db_session)
    row = db_session.query(QuestionResult).filter_by(job_id=job.id, question_id="2").one()
    row.status = "REVIEW_REQUIRED"
    row.processing_state = "NEEDS_REVIEW"
    row.awarded_marks = 0
    row.review_required = True
    db_session.commit()

    text = _text(_report(client, auth_headers(identity.user_a), paper.submission.id))
    assert "INCOMPLETE CORRECTION" in text
    assert "MARKED ONLY" in text
    assert "DRAFT" in text
    assert "5 OF 10 MARKS WERE NEVER ASSESSED" in text


def test_a_refused_newer_run_is_named_on_a_stored_results_report(
    client, identity, auth_headers, paper, db_session
) -> None:
    from datetime import timedelta

    headers = auth_headers(identity.user_a)
    stored = _completed_job(paper, identity, db_session)

    refused = JobService(db_session, get_settings()).create(
        _principal(identity.user_a),
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=f"report-refused-{uuid.uuid4().hex[:12]}",
        ),
    ).job
    refused.state = "REVIEW_REQUIRED"
    refused.result_source = "AUTOMATED_REFUSED"
    refused.created_at = stored.created_at + timedelta(seconds=1)
    db_session.commit()

    text = _text(_report(client, headers, paper.submission.id))
    assert "REFUSED BY THE RESULT GUARD" in text
    assert "5 / 10" in text


def test_an_unknown_detail_level_is_refused(
    client, identity, auth_headers, paper, db_session
) -> None:
    _completed_job(paper, identity, db_session)
    headers = auth_headers(identity.user_a)

    assert _report(client, headers, paper.submission.id, "verbose").status_code == 422
