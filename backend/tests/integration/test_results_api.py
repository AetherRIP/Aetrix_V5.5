"""Results reads, overrides, approval and page serving, all tenant-checked."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.security import Principal
from app.db.models import Document, DocumentPage, JobApproval, QuestionResult
from app.jobs.service import JobService
from app.schemas.api import CorrectionCreate
from app.storage.local import LocalStorage
from sqlalchemy import select

from tests.support import make_png


def _principal(user) -> Principal:
    return Principal(
        user_id=user.id, tenant_id=user.tenant_id, subject=user.subject, role=user.role
    )


def _completed_job(paper, identity, db_session, *, review_required: bool = False):
    job = JobService(db_session, get_settings()).create(
        _principal(identity.user_a),
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=f"results-{uuid.uuid4().hex[:12]}",
        ),
    ).job
    job.state = "COMPLETED"
    first = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id="1a",
        max_marks=2,
        awarded_marks=2,
        status="AWARDED",
        confidence=0.95,
        review_required=False,
    )
    second = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id="1b",
        max_marks=3,
        awarded_marks=1,
        status="AWARDED",
        confidence=0.9,
        review_required=review_required,
        scheme_concerns=[{"code": "REVIEW", "message": "confidence below floor"}]
        if review_required
        else [],
    )
    # The fixture blueprint's leaves are 1a, 1b and 2; every one needs a row for
    # the job to be approvable now that coverage is checked.
    third = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id="2",
        max_marks=5,
        awarded_marks=2,
        status="AWARDED",
        confidence=0.92,
        review_required=False,
    )
    db_session.add_all([first, second, third])
    db_session.commit()
    return job, first, second


def test_results_are_readable_and_totalled_from_the_job(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, first, _ = _completed_job(paper, identity, db_session)

    response = client.get(f"/api/v1/submissions/{paper.submission.id}/results", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == str(job.id)
    assert body["student_ref"] == "student-1"
    assert body["totals"] == {
        "awarded": 5,
        "total": 10,
        "questions": 3,
        "decided": 3,
        "undecided": 0,
        "scoreable": 3,
        "complete": True,
        "unanswered": 0,
        "review_required": 0,
        "approved": False,
        "state": "COMPLETED",
    }
    assert [row["question_id"] for row in body["questions"]] == ["1a", "1b", "2"]
    assert body["questions"][0]["id"] == str(first.id)
    assert body["record_version"] == job.record_version

    assert (
        client.get(
            f"/api/v1/corrections/{job.id}/results", headers=auth_headers(identity.user_b)
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/submissions/{paper.submission.id}/results",
            headers=auth_headers(identity.user_b),
        ).status_code
        == 404
    )


def test_submission_without_a_job_is_a_plain_404(
    client, identity, auth_headers, paper
) -> None:
    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results",
        headers=auth_headers(identity.user_a),
    )
    assert response.status_code == 404
    assert "has not been marked" in response.json()["error"]["message"]


def test_an_override_records_the_reason_actor_and_version(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, first, _ = _completed_job(paper, identity, db_session)

    response = client.post(
        f"/api/v1/results/{first.id}/override",
        headers=headers,
        json={
            "awarded_marks": 1,
            "reason": "Method mark only: the final line is arithmetic, not algebra.",
            "expected_record_version": job.record_version,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"]["awarded"] == 4
    assert body["questions"][0]["awarded_marks"] == 1
    assert body["record_version"] == job.record_version + 1
    assert body["reviews"][0]["question_id"] == "1a"
    assert body["reviews"][0]["first_award"] == 2
    assert body["reviews"][0]["second_award"] == 1
    assert body["questions"][0]["scheme_concerns"][-1]["code"] == "TEACHER_OVERRIDE"

    # A stale version is a conflict rather than a silent overwrite.
    stale = client.post(
        f"/api/v1/results/{first.id}/override",
        headers=headers,
        json={
            "awarded_marks": 2,
            "reason": "Retrying with an out-of-date version.",
            "expected_record_version": job.record_version,
        },
    )
    assert stale.status_code == 409

    too_high = client.post(
        f"/api/v1/results/{first.id}/override",
        headers=headers,
        json={"awarded_marks": 9, "reason": "Above the question maximum."},
    )
    assert too_high.status_code == 422

    short_reason = client.post(
        f"/api/v1/results/{first.id}/override",
        headers=headers,
        json={"awarded_marks": 1, "reason": "no"},
    )
    assert short_reason.status_code == 422

    cross_tenant = client.post(
        f"/api/v1/results/{first.id}/override",
        headers=auth_headers(identity.user_b),
        json={"awarded_marks": 1, "reason": "Someone else's result."},
    )
    assert cross_tenant.status_code == 404


def test_a_viewer_may_read_but_not_override(
    client, identity, auth_headers, paper, db_session
) -> None:
    _, first, _ = _completed_job(paper, identity, db_session)

    viewer_headers = auth_headers(identity.viewer)
    viewer_results = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results", headers=viewer_headers
    )
    assert viewer_results.status_code == 200
    refused = client.post(
        f"/api/v1/results/{first.id}/override",
        headers=viewer_headers,
        json={"awarded_marks": 2, "reason": "Viewers cannot change marks."},
    )
    assert refused.status_code == 403


def test_approval_is_refused_while_a_question_needs_review(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _, second = _completed_job(paper, identity, db_session, review_required=True)

    refused = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert refused.status_code == 409
    assert refused.json()["error"]["details"]["questions"] == ["1b"]

    resolved = client.post(
        f"/api/v1/results/{second.id}/override",
        headers=headers,
        json={"awarded_marks": 2, "reason": "Checked the working against the scheme."},
    )
    assert resolved.status_code == 200, resolved.text
    version = resolved.json()["record_version"]

    approved = client.post(
        f"/api/v1/corrections/{job.id}/approve",
        headers=headers,
        json={"note": "agreed at moderation", "expected_record_version": version},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["totals"]["approved"] is True
    assert body["approved_at"] is not None
    assert body["approved_by"] == str(identity.user_a.id)

    # Approval is idempotent, and an approved result cannot be overridden.
    again = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert again.status_code == 200
    locked = client.post(
        f"/api/v1/results/{second.id}/override",
        headers=headers,
        json={"awarded_marks": 1, "reason": "Changing an approved result."},
    )
    assert locked.status_code == 409


def test_a_reviewer_can_uphold_a_flagged_award_with_a_reason(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _, _ = _completed_job(paper, identity, db_session, review_required=True)

    upheld = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1b",
        headers=headers,
        json={"decision": "UPHOLD", "reason": "Re-read the script; the engine's reading is right."},
    )
    assert upheld.status_code == 200, upheld.text
    body = upheld.json()
    assert body["questions"][1]["review_required"] is False
    assert body["questions"][1]["awarded_marks"] == 1
    assert body["totals"]["review_required"] == 0
    assert body["reviews"][-1]["outcome"] == "UPHELD"
    assert body["reviews"][-1]["first_award"] == 1
    assert body["reviews"][-1]["second_award"] == 1

    approved = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert approved.status_code == 200, approved.text


def test_a_review_change_needs_a_mark_within_the_maximum(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _, _ = _completed_job(paper, identity, db_session, review_required=True)

    missing = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1b",
        headers=headers,
        json={"decision": "CHANGE", "reason": "The second line deserves the mark."},
    )
    assert missing.status_code == 422

    above = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1b",
        headers=headers,
        json={
            "decision": "CHANGE",
            "awarded_marks": 9,
            "reason": "More than the question is worth.",
        },
    )
    assert above.status_code == 422

    changed = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1b",
        headers=headers,
        json={
            "decision": "INDEPENDENT",
            "awarded_marks": 2,
            "reason": "Second pass awarded the method mark as well.",
        },
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["questions"][1]["awarded_marks"] == 2
    assert body["totals"]["review_required"] == 0
    assert body["reviews"][-1]["outcome"] == "SECOND_PASS"
    assert body["reviews"][-1]["first_award"] == 1
    assert body["reviews"][-1]["second_award"] == 2

    viewer = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1b",
        headers=auth_headers(identity.viewer),
        json={"decision": "UPHOLD", "reason": "Viewers do not review marks."},
    )
    assert viewer.status_code == 403

    cross_tenant = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1b",
        headers=auth_headers(identity.user_b),
        json={"decision": "UPHOLD", "reason": "Someone else's job."},
    )
    assert cross_tenant.status_code == 404

    unknown = client.post(
        f"/api/v1/corrections/{job.id}/reviews/9z",
        headers=headers,
        json={"decision": "UPHOLD", "reason": "A question this job does not have."},
    )
    assert unknown.status_code == 404


def test_approval_requires_the_approver_role(
    client, identity, auth_headers, paper, db_session
) -> None:
    job, _, _ = _completed_job(paper, identity, db_session)

    refused = client.post(
        f"/api/v1/corrections/{job.id}/approve",
        headers=auth_headers(identity.viewer),
        json={},
    )
    assert refused.status_code == 403
    assert (
        client.post(
            f"/api/v1/corrections/{job.id}/approve",
            headers=auth_headers(identity.user_b),
            json={},
        ).status_code
        == 404
    )


def test_page_images_are_served_only_to_the_owning_tenant(
    client, identity, auth_headers, paper, db_session, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "documents")
    stored = storage.put(f"{identity.tenant_a.id}/page-1.png", make_png(), "image/png")

    document = Document(
        tenant_id=identity.tenant_a.id,
        submission_id=paper.submission.id,
        kind="STUDENT",
        storage_key=stored.key,
        original_filename="answers.pdf",
        sha256="f" * 64,
        mime_type="application/pdf",
        size_bytes=1024,
        page_count=1,
        status="PROCESSED",
        ordering_status="ORDERED",
        mapping_status="UNMAPPED",
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            tenant_id=identity.tenant_a.id,
            document_id=document.id,
            page_index=1,
            storage_key=stored.key,
            width=1000,
            height=1400,
            quality_status="READABLE",
            checksum="f" * 64,
        )
    )
    db_session.commit()

    headers = auth_headers(identity.user_a)
    listing = client.get(f"/api/v1/submissions/{paper.submission.id}/pages", headers=headers)
    assert listing.status_code == 200
    assert listing.json() == [
        {
            "page_index": 1,
            "document_id": str(document.id),
            "quality_status": "READABLE",
            "width": 1000,
            "height": 1400,
        }
    ]

    image = client.get(f"/api/v1/submissions/{paper.submission.id}/pages/1", headers=headers)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"].startswith("private")
    assert image.content[:4] == b"\x89PNG"

    assert (
        client.get(
            f"/api/v1/submissions/{paper.submission.id}/pages/1",
            headers=auth_headers(identity.user_b),
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/submissions/{paper.submission.id}/pages/2", headers=headers
        ).status_code
        == 404
    )


def test_a_cancelled_job_cannot_be_approved_or_changed(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, first, _ = _completed_job(paper, identity, db_session)
    job.state = "CANCELLED"
    job.cancel_requested = True
    db_session.commit()

    assert (
        client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={}).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/results/{first.id}/override",
            headers=headers,
            json={"awarded_marks": 1, "reason": "A cancelled job stays cancelled."},
        ).status_code
        == 409
    )


def test_approved_marks_feed_the_gradebook(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _, _ = _completed_job(paper, identity, db_session)
    approved = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert approved.status_code == 200, approved.text

    gradebook = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/gradebook", headers=headers
    )
    assert gradebook.status_code == 200, gradebook.text
    body = gradebook.json()
    assert body["approved_jobs"] == 1
    assert body["students"][0]["student_ref"] == "student-1"
    assert body["students"][0]["approved_awarded"] == 5
    assert body["students"][0]["approved_possible"] == 10
    assert body["state"] == "OK"
    assert db_session.scalar(select(QuestionResult.id).limit(1)) is not None


def _refused_job(paper, identity, db_session, *, after=None):
    """A run the guard refused: its marks are kept as evidence, not presented."""

    job = JobService(db_session, get_settings()).create(
        _principal(identity.user_a),
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=f"refused-{uuid.uuid4().hex[:12]}",
        ),
    ).job
    job.state = "REVIEW_REQUIRED"
    job.result_source = "AUTOMATED_REFUSED"
    if after is not None:
        # Newer than the stored result, so presentation has something to skip.
        job.created_at = after.created_at + timedelta(seconds=1)
    row = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id="1a",
        max_marks=2,
        awarded_marks=0,
        status="REVIEW_REQUIRED",
        processing_state="NEEDS_REVIEW",
        review_required=True,
    )
    db_session.add(row)
    db_session.commit()
    return job, row


def test_a_refused_run_is_not_presented_and_the_stored_result_is(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    stored, _, _ = _completed_job(paper, identity, db_session)
    refused, _ = _refused_job(paper, identity, db_session, after=stored)

    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # The refused run is newer, and is deliberately not the presented job.
    assert body["job_id"] == str(stored.id)
    assert body["job_id"] != str(refused.id)
    assert body["refused_newer_job_id"] == str(refused.id)
    assert body["result_source"] is None
    assert body["totals"]["awarded"] == 5

    refused_response = client.get(
        f"/api/v1/corrections/{refused.id}/results", headers=headers
    )
    assert refused_response.status_code == 200, refused_response.text
    assert refused_response.json()["result_source"] == "AUTOMATED_REFUSED"
    assert refused_response.json()["totals"]["awarded"] == 0


def test_a_refused_run_cannot_be_approved(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    _completed_job(paper, identity, db_session)
    refused, _ = _refused_job(paper, identity, db_session)

    response = client.post(
        f"/api/v1/corrections/{refused.id}/approve", headers=headers, json={}
    )
    assert response.status_code == 409, response.text
    assert "refused by the result guard" in response.json()["error"]["message"]


def test_a_refused_run_cannot_be_overridden_or_reviewed(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    _completed_job(paper, identity, db_session)
    refused, row = _refused_job(paper, identity, db_session)

    override = client.post(
        f"/api/v1/results/{row.id}/override",
        headers=headers,
        json={"awarded_marks": 2, "reason": "Editing a run the engine refused."},
    )
    assert override.status_code == 409, override.text

    review = client.post(
        f"/api/v1/corrections/{refused.id}/reviews/1a",
        headers=headers,
        json={"decision": "UPHOLD", "reason": "Upholding a refused run."},
    )
    assert review.status_code == 409, review.text


def test_a_submission_with_only_refused_runs_is_not_ready(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    refused, _ = _refused_job(paper, identity, db_session)

    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results", headers=headers
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"
    assert response.json()["error"]["details"]["refused_job_id"] == str(refused.id)


def test_the_gradebook_cell_ignores_a_refused_run(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    stored, _, _ = _completed_job(paper, identity, db_session)
    _refused_job(paper, identity, db_session, after=stored)

    gradebook = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/gradebook", headers=headers
    )
    assert gradebook.status_code == 200, gradebook.text
    cells = gradebook.json()["students"][0]["cells"]
    cell = next(
        item for item in cells if item["assignment_id"] == str(paper.assignment.id)
    )
    assert cell["job_id"] == str(stored.id)
    assert cell["awarded"] == 5


def _job_with_rows(paper, identity, db_session, specs):
    """A completed job whose rows state exactly the decision each test needs."""

    job = JobService(db_session, get_settings()).create(
        _principal(identity.user_a),
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=f"states-{uuid.uuid4().hex[:12]}",
        ),
    ).job
    job.state = "COMPLETED"
    created = []
    for spec in specs:
        row = QuestionResult(
            tenant_id=job.tenant_id,
            job_id=job.id,
            question_id=spec["question_id"],
            max_marks=spec.get("max_marks", 2),
            awarded_marks=spec.get("awarded_marks", 0),
            status=spec["status"],
            processing_state=spec.get("processing_state"),
            confidence=spec.get("confidence", 0.9),
            review_required=spec.get("review_required", False),
            raw_awarded_marks=spec.get("raw_awarded_marks"),
            normalised_awarded_marks=spec.get("normalised_awarded_marks"),
            normalisation_anomaly=spec.get("normalisation_anomaly"),
        )
        db_session.add(row)
        created.append(row)
    db_session.commit()
    return job, created


_NEEDS_REVIEW = {
    "question_id": "1a",
    "status": "REVIEW_REQUIRED",
    "processing_state": "NEEDS_REVIEW",
    "awarded_marks": 0,
    "review_required": True,
}

_UNMARKED = {
    "question_id": "1a",
    "status": "UNMARKED",
    "processing_state": "UNMARKED",
    "awarded_marks": 0,
}

_CONFIRMED_ZERO = {
    "question_id": "1a",
    "status": "ZERO",
    "processing_state": "CONFIRMED_ZERO",
    "awarded_marks": 0,
    "confidence": 0.97,
}

_MARKED = {
    "question_id": "1a",
    "status": "AWARDED",
    "processing_state": "MARKED",
    "awarded_marks": 2,
}


def test_uphold_is_refused_on_a_needs_review_question(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_NEEDS_REVIEW)])

    response = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1a",
        headers=headers,
        json={"decision": "UPHOLD", "reason": "Keeping an award that was never produced."},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"
    assert response.json()["error"]["details"]["processing_state"] == "NEEDS_REVIEW"


def test_uphold_is_refused_on_an_unmarked_question(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_UNMARKED)])

    response = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1a",
        headers=headers,
        json={"decision": "UPHOLD", "reason": "Treating an unread question as a zero."},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"


def test_uphold_is_allowed_on_a_genuine_confirmed_zero(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_CONFIRMED_ZERO)])

    response = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1a",
        headers=headers,
        json={"decision": "UPHOLD", "reason": "Re-read the script; the blank is real."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["questions"][0]["awarded_marks"] == 0
    assert body["questions"][0]["status"] == "ZERO"
    assert body["questions"][0]["processing_state"] == "CONFIRMED_ZERO"
    assert body["questions"][0]["review_required"] is False


def test_uphold_is_allowed_on_a_marked_question(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    row = dict(_MARKED)
    row["review_required"] = True
    job, _ = _job_with_rows(paper, identity, db_session, [row])

    response = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1a",
        headers=headers,
        json={"decision": "UPHOLD", "reason": "The award is right after a second read."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["questions"][0]["awarded_marks"] == 2
    assert response.json()["questions"][0]["processing_state"] == "MARKED"


def test_approval_is_refused_while_a_question_is_undecided(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    # No review flag on the second row: only the processing state says it is open.
    undecided = dict(_NEEDS_REVIEW)
    undecided["question_id"] = "1b"
    undecided["review_required"] = False
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_MARKED), undecided])

    response = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"
    assert response.json()["error"]["details"]["questions"] == ["1b"]
    assert response.json()["error"]["details"]["states"]["1b"] == "NEEDS_REVIEW"


def test_approval_succeeds_when_every_question_is_decided(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    zero = dict(_CONFIRMED_ZERO)
    zero["question_id"] = "1b"
    zero["max_marks"] = 3
    last = dict(_CONFIRMED_ZERO)
    last["question_id"] = "2"
    last["max_marks"] = 5
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_MARKED), zero, last])

    response = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"]["approved"] is True
    assert body["totals"]["awarded"] == 2
    assert body["totals"]["total"] == 10


def test_review_actions_leave_status_and_state_consistent(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_MARKED)])

    changed = client.post(
        f"/api/v1/corrections/{job.id}/reviews/1a",
        headers=headers,
        json={"decision": "CHANGE", "awarded_marks": 0, "reason": "Nothing is earned here."},
    )
    assert changed.status_code == 200, changed.text
    question = changed.json()["questions"][0]
    assert question["status"] == "ZERO"
    assert question["processing_state"] == "CONFIRMED_ZERO"
    assert question["review_required"] is False
    assert question["normalised_awarded_marks"] == 0

    overridden = client.post(
        f"/api/v1/results/{question['id']}/override",
        headers=headers,
        json={"awarded_marks": 1, "reason": "The method mark is visible on page two."},
    )
    assert overridden.status_code == 200, overridden.text
    after = overridden.json()["questions"][0]
    assert after["status"] == "AWARDED"
    assert after["processing_state"] == "MARKED"
    assert after["awarded_marks"] == 1


def test_a_teacher_override_stays_authoritative(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    _job, rows = _job_with_rows(paper, identity, db_session, [dict(_MARKED)])

    first = client.post(
        f"/api/v1/results/{rows[0].id}/override",
        headers=headers,
        json={"awarded_marks": 1, "reason": "Only the first mark is earned."},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/results/{rows[0].id}/override",
        headers=headers,
        json={"awarded_marks": 2, "reason": "On reflection both marks are earned."},
    )
    assert second.status_code == 200, second.text
    question = second.json()["questions"][0]
    assert question["awarded_marks"] == 2
    assert question["processing_state"] == "MARKED"
    assert question["review_required"] is False
    assert second.json()["totals"]["awarded"] == 2


def test_results_expose_the_processing_state_and_the_raw_award(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    over_max = {
        "question_id": "1a",
        "status": "REVIEW_REQUIRED",
        "processing_state": "NEEDS_REVIEW",
        "awarded_marks": 0,
        "review_required": True,
        "raw_awarded_marks": 9,
        "normalised_awarded_marks": 0,
        "normalisation_anomaly": "OVER_MAX_AWARD",
    }
    _job_with_rows(paper, identity, db_session, [over_max])

    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results", headers=headers
    )
    assert response.status_code == 200, response.text
    question = response.json()["questions"][0]
    assert question["processing_state"] == "NEEDS_REVIEW"
    assert question["raw_awarded_marks"] == 9
    assert question["normalised_awarded_marks"] == 0
    assert question["normalisation_anomaly"] == "OVER_MAX_AWARD"
    # The stored award is the normalised one; the model's claim is evidence.
    assert question["awarded_marks"] == 0


def test_totals_cover_only_decided_questions(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    marked = dict(_MARKED)
    marked["max_marks"] = 2
    open_row = dict(_NEEDS_REVIEW)
    open_row["question_id"] = "1b"
    open_row["max_marks"] = 3
    unmarked = dict(_UNMARKED)
    unmarked["question_id"] = "1c"
    unmarked["max_marks"] = 4
    _job_with_rows(paper, identity, db_session, [marked, open_row, unmarked])

    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results", headers=headers
    )
    assert response.status_code == 200, response.text
    totals = response.json()["totals"]
    assert totals["awarded"] == 2
    assert totals["total"] == 2
    assert totals["questions"] == 3
    assert totals["scoreable"] == 3
    assert totals["decided"] == 1
    assert totals["undecided"] == 2
    assert totals["complete"] is False
    assert totals["unanswered"] == 1


def test_a_black_box_question_adds_no_marks_and_no_undecided_count(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    marked = dict(_MARKED)
    excluded = {
        "question_id": "2",
        "status": "EXCLUDED",
        "processing_state": None,
        "awarded_marks": 0,
        "max_marks": 5,
    }
    _job_with_rows(paper, identity, db_session, [marked, excluded])

    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results", headers=headers
    )
    assert response.status_code == 200, response.text
    totals = response.json()["totals"]
    assert totals["awarded"] == 2
    assert totals["total"] == 2
    assert totals["scoreable"] == 1
    assert totals["undecided"] == 0
    assert totals["complete"] is True


def test_the_gradebook_cell_counts_only_decided_questions(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    marked = dict(_MARKED)
    marked["max_marks"] = 2
    open_row = dict(_NEEDS_REVIEW)
    open_row["question_id"] = "1b"
    open_row["max_marks"] = 3
    open_row["review_required"] = False
    _job_with_rows(paper, identity, db_session, [marked, open_row])

    gradebook = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/gradebook", headers=headers
    )
    assert gradebook.status_code == 200, gradebook.text
    cell = next(
        item
        for item in gradebook.json()["students"][0]["cells"]
        if item["assignment_id"] == str(paper.assignment.id)
    )
    assert cell["awarded"] == 2
    assert cell["total"] == 2


def test_approval_reports_every_blueprint_leaf_without_a_result(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    # A decided row is not enough: the paper is missing 1b and 2 entirely.
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_MARKED)])

    response = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "RESULT_NOT_READY"
    assert error["details"]["questions"] == ["1b", "2"]
    assert error["details"]["missing"] == 2
    assert error["details"]["expected"] == 3

    # Nothing was manufactured to fill the gap.
    reported = client.get(
        f"/api/v1/submissions/{paper.submission.id}/results", headers=headers
    )
    assert reported.status_code == 200, reported.text
    assert [row["question_id"] for row in reported.json()["questions"]] == ["1a"]
    assert reported.json()["totals"]["scoreable"] == 1


def test_one_missing_leaf_blocks_approval_on_an_otherwise_complete_paper(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    second = dict(_MARKED)
    second["question_id"] = "1b"
    second["max_marks"] = 3
    job, _ = _job_with_rows(paper, identity, db_session, [dict(_MARKED), second])

    response = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["questions"] == ["2"]


def test_a_confirmed_zero_satisfies_coverage(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    zero_b = dict(_CONFIRMED_ZERO)
    zero_b["question_id"] = "1b"
    zero_b["max_marks"] = 3
    zero_last = dict(_CONFIRMED_ZERO)
    zero_last["question_id"] = "2"
    zero_last["max_marks"] = 5
    job, _ = _job_with_rows(
        paper, identity, db_session, [dict(_MARKED), zero_b, zero_last]
    )

    response = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["approved"] is True


def test_a_teacher_override_still_counts_as_coverage(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job, first, _ = _completed_job(paper, identity, db_session)

    overridden = client.post(
        f"/api/v1/results/{first.id}/override",
        headers=headers,
        json={"awarded_marks": 1, "reason": "Only the first mark is earned here."},
    )
    assert overridden.status_code == 200, overridden.text

    approved = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["totals"]["approved"] is True


def test_an_undecided_result_blocks_approval_even_when_coverage_is_complete(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    second = dict(_MARKED)
    second["question_id"] = "1b"
    second["max_marks"] = 3
    open_last = dict(_NEEDS_REVIEW)
    open_last["question_id"] = "2"
    open_last["max_marks"] = 5
    # Only the processing state says this is open: no review flag to fall back on.
    open_last["review_required"] = False
    job, _ = _job_with_rows(
        paper, identity, db_session, [dict(_MARKED), second, open_last]
    )

    response = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["questions"] == ["2"]
    assert response.json()["error"]["details"]["states"]["2"] == "NEEDS_REVIEW"


def test_a_historical_approval_is_not_rechecked_for_coverage(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    # The approval predates this check and covered only one question.
    job, rows = _job_with_rows(paper, identity, db_session, [dict(_MARKED)])
    db_session.add(
        JobApproval(
            tenant_id=job.tenant_id,
            job_id=job.id,
            approved_by=identity.user_a.id,
            approved_by_label="Fixture teacher",
            approved_at=datetime.now(UTC),
            approved_marks=rows[0].awarded_marks,
            total_marks=rows[0].max_marks,
            record_version=job.record_version,
        )
    )
    db_session.commit()

    response = client.post(f"/api/v1/corrections/{job.id}/approve", headers=headers, json={})
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["approved"] is True
