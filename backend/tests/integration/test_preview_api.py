"""The correction preview: a read-only composition of the stored sources."""

from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.security import Principal
from app.db.models import (
    CriterionResult,
    Document,
    DocumentPage,
    JobEvent,
    MarkingCriterion,
    PageQuestionMapping,
    ProviderResponse,
    QuestionResult,
    VerificationResult,
)
from app.jobs.service import JobService
from app.schemas.api import CorrectionCreate
from app.storage.local import LocalStorage
from sqlalchemy import func, select

from tests.support import make_png

ARCHIVE_SHA = "c" * 64


def _principal(user) -> Principal:
    return Principal(
        user_id=user.id, tenant_id=user.tenant_id, subject=user.subject, role=user.role
    )


def _preview_job(paper, identity, db_session, *, refused: bool = False):
    job = JobService(db_session, get_settings()).create(
        _principal(identity.user_a),
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=f"preview-{uuid.uuid4().hex[:12]}",
        ),
    ).job
    job.state = "REVIEW_REQUIRED"
    if refused:
        job.result_source = "AUTOMATED_REFUSED"

    first = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id="1a",
        max_marks=2,
        awarded_marks=2,
        status="AWARDED",
        processing_state="MARKED",
        confidence=0.95,
        student_answer="x = 7",
        response_source="WHOLE_PAPER",
        response_sequence=0,
        raw_awarded_marks=2,
        prompt_version="marking@v9",
        raw_response={
            "format": "WHOLE_PAPER_SLICE",
            "paper_sha256": ARCHIVE_SHA,
            "question_id": "1a",
            "item": {
                "question_id": "1a",
                "student_answer": "x = 7",
                "awarded_marks": 2,
                "components": [
                    {
                        "code": "M1",
                        "description": "M1 for forming the equation",
                        "marks": 1,
                        "awarded": True,
                        "reason": None,
                        "evidence": "2x + 4 = 18",
                    },
                    {
                        "code": "A1",
                        "description": "A1 for the correct value of x",
                        "marks": 1,
                        "awarded": True,
                        "reason": None,
                        "evidence": "x = 7",
                    },
                ],
                "confidence": 0.95,
                "review_reasons": [],
            },
        },
    )
    second = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id="1b",
        max_marks=3,
        awarded_marks=1,
        status="REVIEW_REQUIRED",
        processing_state="NEEDS_REVIEW",
        confidence=0.62,
        review_required=True,
        scheme_concerns=[
            {"code": "REVIEW", "message": "The components total 1 but the award is 2."}
        ],
    )
    third = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id="2",
        max_marks=5,
        awarded_marks=2,
        status="AWARDED",
        processing_state="MARKED",
        confidence=0.9,
    )
    db_session.add_all([first, second, third])
    db_session.flush()
    db_session.add_all(
        [
            CriterionResult(
                tenant_id=job.tenant_id,
                question_result_id=first.id,
                code="M1",
                awarded=True,
                evidence=[{"quote": "2x + 4 = 18"}],
            ),
            CriterionResult(
                tenant_id=job.tenant_id,
                question_result_id=first.id,
                code="A1",
                awarded=True,
                evidence=[{"quote": "x = 7"}],
            ),
        ]
    )
    db_session.add(
        ProviderResponse(
            tenant_id=job.tenant_id,
            job_id=job.id,
            response_source="WHOLE_PAPER",
            sequence=0,
            content_sha256=ARCHIVE_SHA,
            content_length=512,
            body={"questions": []},
            model="fixture-model",
            finish_reason="STOP",
        )
    )
    db_session.add(
        VerificationResult(
            tenant_id=job.tenant_id,
            job_id=job.id,
            question_id="1a",
            kind="MATHEMATICAL",
            status="EQUIVALENT",
            detail={"student_expression": "7", "expected_expression": "7"},
        )
    )
    if refused:
        db_session.add(
            JobEvent(
                tenant_id=job.tenant_id,
                job_id=job.id,
                # JobService.create already recorded event 1 (CREATED).
                event_seq=2,
                from_state="VALIDATING",
                to_state="REVIEW_REQUIRED",
                actor="worker:test",
                detail={
                    "guard": "BLOCKED",
                    "guard_reason": "The stored result is approved, so nothing was overwritten.",
                },
            )
        )
    db_session.commit()
    return job, first


def _student_page(paper, identity, db_session, tmp_path):
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
        ordering_status="UNVERIFIED",
        mapping_status="MAPPED",
    )
    db_session.add(document)
    db_session.flush()
    page = DocumentPage(
        tenant_id=identity.tenant_a.id,
        document_id=document.id,
        page_index=1,
        storage_key=stored.key,
        width=1000,
        height=1400,
        quality_status="READABLE",
        checksum="f" * 64,
    )
    db_session.add(page)
    db_session.flush()
    db_session.add(
        PageQuestionMapping(
            tenant_id=identity.tenant_a.id,
            document_id=document.id,
            page_id=page.id,
            blueprint_version_id=paper.blueprint.id,
            question_id="1a",
            confidence=0.95,
            method="MODEL",
            source_ref={},
        )
    )
    db_session.commit()
    return document, page


def test_preview_composes_script_scheme_and_archive(
    client, identity, auth_headers, paper, db_session, tmp_path
) -> None:
    job, first = _preview_job(paper, identity, db_session)
    document, _ = _student_page(paper, identity, db_session, tmp_path)
    criterion = db_session.scalar(
        select(MarkingCriterion).where(
            MarkingCriterion.scheme_version_id == paper.scheme_version.id,
            MarkingCriterion.question_id == "1a",
            MarkingCriterion.code == "M1",
        )
    )
    assert criterion is not None
    criterion.source_page = 3
    criterion.source_quote = "M1 for forming the equation"
    criterion.expected_answer = "x = 7"
    db_session.commit()

    headers = auth_headers(identity.user_a)
    before_rows = db_session.scalar(select(func.count()).select_from(QuestionResult))
    before_version = job.record_version
    before_award = first.awarded_marks

    response = client.get(f"/api/v1/submissions/{paper.submission.id}/preview", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["student_ref"] == "student-1"
    assert body["paper"]["paper_awarded"] == 5
    assert body["paper"]["paper_total"] == 10
    assert body["paper"]["questions_reviewed"] == 3
    assert body["paper"]["attention"] == 1
    assert body["paper"]["primary_model"] == job.primary_model

    question = next(item for item in body["questions"] if item["question_id"] == "1a")
    assert question["student_answer"] == "x = 7"
    assert question["location"] == {
        "page_index": 1,
        "confidence": 0.95,
        "method": "MODEL",
        "quality_status": "READABLE",
        "width": 1000,
        "height": 1400,
    }
    assert {criterion["code"] for criterion in question["scheme_criteria"]} == {"M1", "A1"}
    printed = next(item for item in question["scheme_criteria"] if item["code"] == "M1")
    assert printed["source_page"] == 3
    assert printed["source_quote"] == "M1 for forming the equation"
    assert printed["expected_answer"] == "x = 7"

    decisions = {item["code"]: item for item in question["criteria"]}
    assert decisions["M1"]["awarded"] is True
    assert decisions["M1"]["awarded_marks"] == 1
    assert decisions["M1"]["evidence"] == ["2x + 4 = 18"]
    assert decisions["A1"]["awarded"] is True
    assert question["component_total"] == 2
    assert question["component_consistent"] is True
    assert question["archive"]["content_sha256"] == ARCHIVE_SHA
    assert question["archive"]["model"] == "fixture-model"
    assert question["verifications"][0]["kind"] == "MATHEMATICAL"

    flagged = next(item for item in body["questions"] if item["question_id"] == "1b")
    assert flagged["review_required"] is True
    assert flagged["review_reasons"] == [
        "The components total 1 but the award is 2."
    ]
    assert flagged["component_total"] is None
    assert body["student_document"]["ordering_status"] == "UNVERIFIED"
    assert body["scheme_document"]["document_id"] is None
    assert any(warning["code"] == "PAGE_ORDERING" for warning in body["warnings"])

    # The read changed nothing.
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(QuestionResult)) == before_rows
    refreshed = db_session.get(QuestionResult, first.id)
    assert refreshed is not None
    assert refreshed.awarded_marks == before_award
    assert job.record_version == before_version
    assert document.id is not None


def test_a_refused_run_is_previewable_as_evidence(
    client, identity, auth_headers, paper, db_session
) -> None:
    """The guard's refusal is shown, not hidden by a fallback to nothing."""

    job, _ = _preview_job(paper, identity, db_session, refused=True)
    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/preview",
        headers=auth_headers(identity.user_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == str(job.id)
    assert body["paper"]["result_source"] == "AUTOMATED_REFUSED"
    assert body["paper"]["guard_decision"] == "BLOCKED"
    assert body["paper"]["guard_reason"] == (
        "The stored result is approved, so nothing was overwritten."
    )
    assert any(warning["code"] == "RUN_REFUSED" for warning in body["warnings"])
    assert len(body["questions"]) == 3


def test_a_submission_without_a_job_has_no_preview(
    client, identity, auth_headers, paper
) -> None:
    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/preview",
        headers=auth_headers(identity.user_a),
    )
    assert response.status_code == 404


def test_a_preview_is_tenant_scoped(client, identity, auth_headers, paper, db_session) -> None:
    _preview_job(paper, identity, db_session)
    response = client.get(
        f"/api/v1/submissions/{paper.submission.id}/preview",
        headers=auth_headers(identity.user_b),
    )
    assert response.status_code == 404


def test_document_pages_are_served_only_to_the_owning_tenant(
    client, identity, auth_headers, paper, db_session, tmp_path
) -> None:
    document, _ = _student_page(paper, identity, db_session, tmp_path)
    headers = auth_headers(identity.user_a)

    image = client.get(f"/api/v1/documents/{document.id}/pages/1", headers=headers)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"].startswith("private")
    assert image.content[:4] == b"\x89PNG"

    assert (
        client.get(
            f"/api/v1/documents/{document.id}/pages/1",
            headers=auth_headers(identity.user_b),
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/documents/{document.id}/pages/2", headers=headers).status_code
        == 404
    )
