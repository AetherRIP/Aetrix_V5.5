from __future__ import annotations

import uuid

from app.core.ids import utcnow
from app.db.models import MarkScheme, MarkSchemeVersion


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
