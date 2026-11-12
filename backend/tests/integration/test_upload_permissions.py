"""A reviewer can upload; a reviewer cannot manage exams.

The upload paths are the manual fallback when Google Classroom is unavailable,
so an assistant needs them. They deliberately do not carry exam authority: the
same account is refused when it tries to create an exam, create an assignment or
approve the scheme it just uploaded.
"""

from __future__ import annotations

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


def test_a_reviewer_registers_and_uploads_a_submission(
    client, paper, identity, auth_headers
) -> None:
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
