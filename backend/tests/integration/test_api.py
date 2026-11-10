from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.ids import utcnow
from app.core.security import Principal
from app.db.models import MarkScheme, MarkSchemeVersion
from app.jobs.service import JobService
from app.schemas.api import CorrectionCreate


def _structure(marks: int = 10) -> dict:
    return {
        "paper_code": "API-01",
        "questions": [
            {"question_id": "1", "label": "Question 1", "max_marks": marks},
        ],
        "total_marks": marks,
        "notes": [],
    }


def _create_exam(client, headers, title: str = "API paper") -> dict:
    response = client.post("/api/v1/exams", headers=headers, json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def _approve_blueprint(client, headers, exam_id: str, marks: int = 10) -> dict:
    structure = _structure(marks)
    draft = client.put(
        f"/api/v1/exams/{exam_id}/blueprint",
        headers=headers,
        json={"structure": structure, "approve": False},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["status"] == "DRAFT"

    approved = client.put(
        f"/api/v1/exams/{exam_id}/blueprint",
        headers=headers,
        json={"structure": structure, "approve": True, "reason": "checked against paper"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    return approved.json()


def test_health_readiness_and_request_id(client) -> None:
    assert client.get("/health").status_code == 200
    readiness = client.get("/ready")
    assert readiness.status_code == 200
    assert readiness.json()["database"] == "ok"
    assert client.get("/version").status_code == 200
    assert client.get("/api/v1/openapi.json").status_code == 200

    identified = client.get("/health", headers={"X-Request-ID": "test-request-123"})
    assert identified.headers["X-Request-ID"] == "test-request-123"


def test_unauthenticated_requests_are_rejected(client) -> None:
    assert client.get("/api/v1/corrections").status_code == 401
    assert (
        client.get(
            "/api/v1/corrections", headers={"Authorization": "Bearer not-a-token"}
        ).status_code
        == 401
    )


def test_viewer_cannot_manage_exams(client, identity, auth_headers) -> None:
    response = client.post(
        "/api/v1/exams",
        headers=auth_headers(identity.viewer),
        json={"title": "Not allowed"},
    )
    assert response.status_code == 403


def test_blueprint_approval_is_draft_first(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    exam = _create_exam(client, headers)

    direct = client.put(
        f"/api/v1/exams/{exam['id']}/blueprint",
        headers=headers,
        json={"structure": _structure(), "approve": True, "reason": "no draft exists"},
    )
    assert direct.status_code == 409

    draft = client.put(
        f"/api/v1/exams/{exam['id']}/blueprint",
        headers=headers,
        json={"structure": _structure(), "approve": False},
    )
    assert draft.status_code == 200

    mismatch = client.put(
        f"/api/v1/exams/{exam['id']}/blueprint",
        headers=headers,
        json={"structure": _structure(11), "approve": True, "reason": "different"},
    )
    assert mismatch.status_code == 409

    missing_reason = client.put(
        f"/api/v1/exams/{exam['id']}/blueprint",
        headers=headers,
        json={"structure": _structure(), "approve": True},
    )
    assert missing_reason.status_code == 422


def test_correction_api_end_to_end(client, identity, auth_headers, db_session) -> None:
    headers = auth_headers(identity.user_a)
    exam = _create_exam(client, headers)
    blueprint = _approve_blueprint(client, headers, exam["id"])

    scheme = MarkScheme(
        tenant_id=identity.tenant_a.id,
        exam_id=uuid.UUID(exam["id"]),
        title="API scheme",
    )
    db_session.add(scheme)
    db_session.flush()
    scheme_version = MarkSchemeVersion(
        tenant_id=identity.tenant_a.id,
        mark_scheme_id=scheme.id,
        version=1,
        status="APPROVED",
        source="FIXTURE",
        content_hash="d" * 64,
        approved_at=utcnow(),
    )
    db_session.add(scheme_version)
    db_session.commit()

    assignment_response = client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "exam_id": exam["id"],
            "blueprint_version_id": blueprint["id"],
            "scheme_version_id": str(scheme_version.id),
            "name": "API assignment",
            "completion_threshold": 0.8,
            "review_mode": "BALANCED",
        },
    )
    assert assignment_response.status_code == 201, assignment_response.text
    assignment = assignment_response.json()

    submission_response = client.post(
        "/api/v1/submissions",
        headers=headers,
        json={
            "assignment_id": assignment["id"],
            "student_ref": "student-1",
            "content_hash": "b" * 64,
        },
    )
    assert submission_response.status_code == 201, submission_response.text
    submission = submission_response.json()

    payload = {
        "assignment_id": assignment["id"],
        "submission_id": submission["id"],
        "idempotency_key": "api-key-0001",
    }
    first = client.post("/api/v1/corrections", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    job = first.json()

    duplicate = client.post("/api/v1/corrections", headers=headers, json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == job["id"]

    detail = client.get(f"/api/v1/corrections/{job['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == "CREATED"
    assert len(body["events"]) >= 1
    assert body["events"][0]["to_state"] == "CREATED"

    other_headers = auth_headers(identity.user_b)
    assert client.get(f"/api/v1/corrections/{job['id']}", headers=other_headers).status_code == 404
    assert client.get("/api/v1/corrections", headers=other_headers).json() == []
    assert len(client.get("/api/v1/corrections", headers=headers).json()) == 1

    usage = client.get("/api/v1/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["requests"] == 0
    assert usage.json()["cost_usd"] == 0.0
    assert client.get("/api/v1/providers/health", headers=headers).json() == []

    cancelled = client.post(f"/api/v1/corrections/{job['id']}/cancel", headers=headers)
    assert cancelled.status_code == 202
    assert cancelled.json()["state"] == "CANCELLED"

    retry = client.post(f"/api/v1/corrections/{job['id']}/retry", headers=headers)
    assert retry.status_code == 409


def test_viewer_cannot_cancel_or_retry_a_job(
    client, identity, auth_headers, paper, db_session
) -> None:
    actor = Principal(
        user_id=identity.user_a.id,
        tenant_id=identity.tenant_a.id,
        subject=identity.user_a.subject,
        role=identity.user_a.role,
    )
    job = JobService(db_session, get_settings()).create(
        actor,
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key="viewer-role-0001",
        ),
    ).job

    viewer_headers = auth_headers(identity.viewer)
    assert (
        client.post(f"/api/v1/corrections/{job.id}/cancel", headers=viewer_headers).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/corrections/{job.id}/retry", headers=viewer_headers).status_code
        == 403
    )


def test_tenant_scoped_read_contracts(client, identity, auth_headers, paper) -> None:
    alpha_headers = auth_headers(identity.user_a)
    beta_headers = auth_headers(identity.user_b)

    alpha_workspaces = client.get("/api/v1/workspaces", headers=alpha_headers)
    assert alpha_workspaces.status_code == 200
    assert [row["id"] for row in alpha_workspaces.json()] == [str(identity.tenant_a.id)]
    assert alpha_workspaces.json()[0]["role"] == "OWNER"

    beta_workspaces = client.get("/api/v1/workspaces", headers=beta_headers)
    assert beta_workspaces.status_code == 200
    assert [row["id"] for row in beta_workspaces.json()] == [str(identity.tenant_b.id)]

    assert (
        client.get(
            f"/api/v1/workspaces/{identity.tenant_b.id}", headers=alpha_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{identity.tenant_b.id}/assignments",
            headers=alpha_headers,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{identity.tenant_b.id}/corrections",
            headers=alpha_headers,
        ).status_code
        == 404
    )

    assignments = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/assignments", headers=alpha_headers
    )
    assert assignments.status_code == 200
    assert [row["id"] for row in assignments.json()] == [str(paper.assignment.id)]

    assignment = client.get(
        f"/api/v1/assignments/{paper.assignment.id}", headers=alpha_headers
    )
    assert assignment.status_code == 200
    assert assignment.json()["name"] == "Fixture assignment"
    assert (
        client.get(
            f"/api/v1/assignments/{paper.assignment.id}", headers=beta_headers
        ).status_code
        == 404
    )

    submissions = client.get(
        f"/api/v1/assignments/{paper.assignment.id}/submissions", headers=alpha_headers
    )
    assert submissions.status_code == 200
    assert [row["id"] for row in submissions.json()] == [str(paper.submission.id)]

    submission = client.get(
        f"/api/v1/submissions/{paper.submission.id}", headers=alpha_headers
    )
    assert submission.status_code == 200
    assert submission.json()["student_ref"] == "student-1"
    assert (
        client.get(
            f"/api/v1/submissions/{paper.submission.id}", headers=beta_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/submissions/{paper.submission.id}/corrections", headers=beta_headers
        ).status_code
        == 404
    )
