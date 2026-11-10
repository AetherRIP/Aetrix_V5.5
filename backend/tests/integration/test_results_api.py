"""Results reads, overrides, approval and page serving, all tenant-checked."""

from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.security import Principal
from app.db.models import Document, DocumentPage, QuestionResult
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
    db_session.add_all([first, second])
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
        "awarded": 3,
        "total": 5,
        "questions": 2,
        "unanswered": 0,
        "review_required": 0,
        "approved": False,
        "state": "COMPLETED",
    }
    assert [row["question_id"] for row in body["questions"]] == ["1a", "1b"]
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
    assert body["totals"]["awarded"] == 2
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
    assert body["students"][0]["approved_awarded"] == 3
    assert body["students"][0]["approved_possible"] == 5
    assert body["state"] == "OK"
    assert db_session.scalar(select(QuestionResult.id).limit(1)) is not None
