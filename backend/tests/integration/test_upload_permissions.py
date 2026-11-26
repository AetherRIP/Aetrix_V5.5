"""A reviewer can upload; a reviewer cannot manage exams.

The upload paths are the manual fallback when Google Classroom is unavailable,
so an assistant needs them. They deliberately do not carry exam authority: the
same account is refused when it tries to create an exam, create an assignment or
approve the scheme it just uploaded.
"""

from __future__ import annotations

from app.db.models import (
    ClassroomAllocation,
    ClassroomClass,
    ClassroomClassAssignment,
)

from tests.support import make_pdf


def _register(client, headers, assignment_id, student_ref: str):
    return client.post(
        "/api/v1/submissions",
        headers=headers,
        json={
            "assignment_id": str(assignment_id),
            "student_ref": student_ref,
            "content_hash": "c" * 64,
        },
    )


def _assign_reviewer_to_a_class(db_session, paper, identity) -> None:
    """Attach the fixture assignment to a class the reviewer holds.

    A reviewer's upload is class-scoped: it is allowed for a class they are
    assigned to, and refused for a legacy assignment that names no class.
    """

    classroom = ClassroomClass(
        course_id="uploader-course",
        name="Uploader class",
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
    paper.assignment.classroom_allocation_id = allocation.id
    paper.assignment.course_id = allocation.course_id
    paper.assignment.class_name = allocation.class_name
    db_session.commit()


def test_a_reviewer_registers_and_uploads_a_submission(
    client, paper, identity, auth_headers, db_session
) -> None:
    _assign_reviewer_to_a_class(db_session, paper, identity)
    headers = auth_headers(identity.reviewer)

    registered = _register(client, headers, paper.assignment.id, "reviewer-student")
    assert registered.status_code == 201, registered.text
    submission_id = registered.json()["id"]

    uploaded = client.post(
        f"/api/v1/submissions/{submission_id}/documents",
        headers=headers,
        files={
            "file": (
                "reviewer-student.pdf",
                make_pdf(["Question 1 Page 1 of 1"]),
                "application/pdf",
            )
        },
    )

    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["status"] == "PROCESSED"
    assert body["page_count"] == 1
    assert body["kind"] == "STUDENT"


def test_a_reviewer_uploads_a_mark_scheme_as_a_draft(client, paper, identity, auth_headers) -> None:
    response = client.post(
        f"/api/v1/exams/{paper.exam.id}/schemes",
        headers=auth_headers(identity.reviewer),
        data={"title": "Uploaded by an assistant"},
        files={
            "file": (
                "scheme.pdf",
                make_pdf(["Question 1: 2 marks"]),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"]["status"] == "DRAFT"
    assert body["scheme"]["exam_id"] == str(paper.exam.id)


def test_a_reviewer_cannot_manage_exams(client, paper, identity, auth_headers) -> None:
    headers = auth_headers(identity.reviewer)

    exam = client.post("/api/v1/exams", headers=headers, json={"title": "Reviewer exam"})
    assert exam.status_code == 403, exam.text
    assert exam.json()["error"]["code"] == "FORBIDDEN"

    assignment = client.post(
        "/api/v1/assignments",
        headers=headers,
        json={
            "exam_id": str(paper.exam.id),
            "blueprint_version_id": str(paper.blueprint.id),
            "scheme_version_id": str(paper.scheme_version.id),
            "name": "Reviewer assignment",
        },
    )
    assert assignment.status_code == 403, assignment.text

    approval = client.post(
        f"/api/v1/schemes/{paper.scheme_version.id}/approve",
        headers=headers,
        json={"reason": "assistant approval attempt"},
    )
    assert approval.status_code == 403, approval.text
    assert approval.json()["error"]["message"] == "This action requires a teacher or admin role."


def test_a_read_only_account_still_cannot_upload(client, paper, identity, auth_headers) -> None:
    response = _register(
        client, auth_headers(identity.viewer), paper.assignment.id, "viewer-student"
    )

    assert response.status_code == 403, response.text
    assert (
        response.json()["error"]["message"]
        == "This action requires a teacher, admin or reviewer role."
    )
