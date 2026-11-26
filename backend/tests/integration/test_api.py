from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.ids import utcnow
from app.core.security import Principal
from app.correction.scheme_criteria import criteria_rules_hash
from app.db.models import (
    Assignment,
    ClassroomAllocation,
    ClassroomClass,
    MarkingCriterion,
    MarkScheme,
    MarkSchemeVersion,
)
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
    # An assignment whose scheme carries no approved criteria cannot be marked,
    # and the API says so before anything is dispatched.  The fixture therefore
    # supplies a real, approved criterion set: one mark point carrying all ten
    # marks of the single-question blueprint, reviewed against that blueprint.
    structure = _structure()
    scheme_version = MarkSchemeVersion(
        tenant_id=identity.tenant_a.id,
        mark_scheme_id=scheme.id,
        version=1,
        status="APPROVED",
        source="FIXTURE",
        content_hash="d" * 64,
        approved_at=utcnow(),
        criteria_blueprint_version_id=uuid.UUID(blueprint["id"]),
        criteria_approved_at=utcnow(),
        criteria_approved_by=identity.user_a.id,
        criteria_approval_reason="fixture review against the approved blueprint",
    )
    db_session.add(scheme_version)
    db_session.flush()
    criterion = MarkingCriterion(
        tenant_id=identity.tenant_a.id,
        scheme_version_id=scheme_version.id,
        blueprint_version_id=uuid.UUID(blueprint["id"]),
        question_id="1",
        code="A1",
        ordinal=0,
        marks=10,
        description="A1 for the complete correct answer",
        dependencies=[],
        alternatives=[],
        source_ref={},
    )
    db_session.add(criterion)
    db_session.flush()
    scheme_version.criteria_rules_hash = criteria_rules_hash([criterion], structure)
    classroom = ClassroomClass(
        course_id="900988657199",
        name="Aetrix Testing",
        verification="VERIFIED",
        source="test",
        created_by_subject="test",
    )
    db_session.add(classroom)
    db_session.flush()
    allocation = ClassroomAllocation(
        classroom_class_id=classroom.id,
        workspace_id=identity.tenant_a.id,
        course_id=classroom.course_id,
        class_name=classroom.name,
        workspace_name=identity.tenant_a.name,
        allocated_by_subject="test",
    )
    db_session.add(allocation)
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
            "course_id": classroom.course_id,
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


def test_an_assignment_must_name_a_class_of_this_workspace(
    client, identity, auth_headers, paper, db_session
) -> None:
    """The playtest found assignments with no class at all.

    The route now requires one, and the service resolves it through this
    workspace's active allocation, so a bare or foreign course id is refused.
    """

    classroom = ClassroomClass(
        course_id="create-course",
        name="Creation class",
        verification="VERIFIED",
        source="FIXTURE",
        created_by_subject=identity.user_a.subject,
    )
    db_session.add(classroom)
    db_session.flush()
    allocation = ClassroomAllocation(
        classroom_class_id=classroom.id,
        workspace_id=identity.tenant_a.id,
        course_id=classroom.course_id,
        class_name=classroom.name,
        workspace_name=identity.tenant_a.name,
        allocated_by_subject=identity.user_a.subject,
    )
    db_session.add(allocation)
    db_session.commit()

    headers = auth_headers(identity.user_a)
    body = {
        "exam_id": str(paper.exam.id),
        "blueprint_version_id": str(paper.blueprint.id),
        "scheme_version_id": str(paper.scheme_version.id),
        "name": "Classless assignment",
    }

    missing = client.post("/api/v1/assignments", headers=headers, json=body)
    assert missing.status_code == 422, missing.text
    assert missing.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Select the class" in missing.json()["error"]["message"]

    foreign = client.post(
        "/api/v1/assignments",
        headers=headers,
        json={**body, "course_id": "not-allocated-here"},
    )
    assert foreign.status_code == 404, foreign.text

    accepted = client.post(
        "/api/v1/assignments",
        headers=headers,
        json={**body, "course_id": allocation.course_id},
    )
    assert accepted.status_code == 201, accepted.text
    saved = accepted.json()
    assert saved["course_id"] == allocation.course_id
    assert saved["class_name"] == classroom.name
    assert saved["classroom_allocation_id"] == str(allocation.id)


def test_a_reviewer_sees_only_the_assignments_of_their_classes(
    client, identity, auth_headers, paper, db_session
) -> None:
    """The playtest found an assistant reading every workspace correction job.

    A class-scoped assignment the reviewer holds is listed and readable.  A
    legacy assignment names no class, so nothing proves it belongs to the
    reviewer: it stays out of their list and its detail is reported missing.
    """

    from app.db.models import ClassroomAllocation, ClassroomClass, ClassroomClassAssignment

    classroom = ClassroomClass(
        course_id="reviewer-course",
        name="Reviewer class",
        verification="VERIFIED",
        source="FIXTURE",
        created_by_subject=identity.user_a.subject,
    )
    db_session.add(classroom)
    db_session.flush()
    allocation = ClassroomAllocation(
        classroom_class_id=classroom.id,
        workspace_id=identity.tenant_a.id,
        course_id=classroom.course_id,
        class_name=classroom.name,
        workspace_name=identity.tenant_a.name,
        allocated_by_subject=identity.user_a.subject,
    )
    db_session.add(allocation)
    db_session.flush()
    db_session.add(
        ClassroomClassAssignment(
            allocation_id=allocation.id,
            workspace_id=identity.tenant_a.id,
            user_id=identity.reviewer.id,
            assigned_by_user_id=identity.user_a.id,
        )
    )
    scoped = Assignment(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        name="Reviewer class assignment",
        completion_threshold=0.8,
        review_mode="BALANCED",
        created_by=identity.user_a.id,
        classroom_allocation_id=allocation.id,
        course_id=allocation.course_id,
        class_name=allocation.class_name,
    )
    legacy = Assignment(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        name="Legacy unassigned",
        completion_threshold=0.8,
        review_mode="BALANCED",
        created_by=identity.user_a.id,
    )
    db_session.add_all([scoped, legacy])
    db_session.commit()

    headers = auth_headers(identity.reviewer)
    listed = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/assignments", headers=headers
    )
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()}
    assert str(scoped.id) in ids
    assert str(legacy.id) not in ids

    assert (
        client.get(f"/api/v1/assignments/{scoped.id}", headers=headers).status_code == 200
    )
    hidden = client.get(f"/api/v1/assignments/{legacy.id}", headers=headers)
    assert hidden.status_code == 404, hidden.text

    owner = client.get(
        f"/api/v1/assignments/{legacy.id}", headers=auth_headers(identity.user_a)
    )
    assert owner.status_code == 200, owner.text
