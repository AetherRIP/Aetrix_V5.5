"""Notifications and marking history read real stored rows, never samples."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models import Assignment, CorrectionJob, Exam, JobApproval, QuestionResult, Submission

BASE = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def _second_assignment(db_session, identity) -> Assignment:
    exam = Exam(tenant_id=identity.tenant_a.id, title="Second exam")
    db_session.add(exam)
    db_session.flush()
    assignment = Assignment(
        tenant_id=identity.tenant_a.id,
        exam_id=exam.id,
        name="Second sitting",
        completion_threshold=0.8,
        review_mode="BALANCED",
        created_by=identity.user_a.id,
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


def _job(
    db_session,
    paper,
    *,
    state: str,
    key: str,
    at: datetime,
    assignment=None,
    submission=None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> CorrectionJob:
    target_assignment = assignment or paper.assignment
    target_submission = submission or paper.submission
    job = CorrectionJob(
        tenant_id=target_assignment.tenant_id,
        assignment_id=target_assignment.id,
        submission_id=target_submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state=state,
        progress=0.4,
        attempts=1,
        idempotency_key=key,
        request_hash="f" * 64,
        error_code=error_code,
        error_message=error_message,
        created_at=at,
        updated_at=at,
    )
    db_session.add(job)
    db_session.flush()
    return job


def _result(db_session, job: CorrectionJob, question: str, max_marks: int, awarded: int):
    row = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id=question,
        max_marks=max_marks,
        awarded_marks=awarded,
        status="AWARDED",
        confidence=0.8,
        review_required=False,
        scheme_concerns=[],
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_notifications_are_derived_from_real_jobs_approvals_and_invitations(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id

    review_job = _job(
        db_session, paper, state="REVIEW_REQUIRED", key="notif-review", at=_at(1)
    )
    _result(db_session, review_job, "1a", max_marks=2, awarded=1)
    failed_job = _job(
        db_session,
        paper,
        state="FAILED",
        key="notif-failed",
        at=_at(2),
        error_code="PROVIDER_UNAVAILABLE",
    )
    approved_job = _job(
        db_session, paper, state="COMPLETED", key="notif-approved", at=_at(3)
    )
    _result(db_session, approved_job, "1a", max_marks=5, awarded=4)
    db_session.add(
        JobApproval(
            tenant_id=identity.tenant_a.id,
            job_id=approved_job.id,
            approved_by=identity.user_a.id,
            approved_by_label="Teacher A",
            approved_at=_at(4),
            approved_marks=4,
            total_marks=5,
        )
    )
    db_session.commit()

    invitation = client.post(
        f"/api/v1/workspaces/{workspace}/invitations",
        headers=headers,
        json={"email": "pending.assistant@example.test", "role": "REVIEWER"},
    )
    assert invitation.status_code == 201, invitation.text
    invitation_id = invitation.json()["id"]

    response = client.get(
        f"/api/v1/workspaces/{workspace}/notifications", headers=headers
    )
    assert response.status_code == 200, response.text
    items = response.json()
    kinds = {item["kind"] for item in items}
    assert kinds == {"REVIEW_REQUIRED", "JOB_FAILED", "RESULT_APPROVED", "INVITATION_PENDING"}
    assert len(items) == 4
    assert all(item["read"] is None for item in items)
    # Newest first; the invitation and approval share the wall clock, so assert
    # the ordering property rather than a timestamp from this machine.
    timestamps = [item["created_at"] for item in items]
    assert timestamps == sorted(timestamps, reverse=True)

    by_kind = {item["kind"]: item for item in items}
    assert by_kind["JOB_FAILED"]["job_id"] == str(failed_job.id)
    assert by_kind["JOB_FAILED"]["detail"] == "PROVIDER_UNAVAILABLE"
    assert by_kind["REVIEW_REQUIRED"]["submission_id"] == str(paper.submission.id)
    assert by_kind["RESULT_APPROVED"]["detail"].startswith("4 of 5 marks approved")
    assert by_kind["INVITATION_PENDING"]["invitation_id"] == invitation_id
    assert "pending.assistant@example.test" in by_kind["INVITATION_PENDING"]["detail"]
    for item in items:
        assert item["id"].split(":")[0] in {"job", "approval", "invitation"}

    # A reviewer sees the work, not the workspace's recruitment.
    viewer = client.get(
        f"/api/v1/workspaces/{workspace}/notifications",
        headers=auth_headers(identity.viewer),
    )
    assert viewer.status_code == 200
    viewer_kinds = {item["kind"] for item in viewer.json()}
    assert "INVITATION_PENDING" not in viewer_kinds
    assert viewer_kinds == {"REVIEW_REQUIRED", "JOB_FAILED", "RESULT_APPROVED"}

    empty = client.get(
        f"/api/v1/workspaces/{identity.tenant_b.id}/notifications",
        headers=auth_headers(identity.user_b),
    )
    assert empty.status_code == 200
    assert empty.json() == []

    foreign = client.get(
        f"/api/v1/workspaces/{workspace}/notifications",
        headers=auth_headers(identity.user_b),
    )
    assert foreign.status_code == 404


def test_marking_history_counts_marks_and_paginates(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id
    second = _second_assignment(db_session, identity)
    second_submission = Submission(
        tenant_id=identity.tenant_a.id,
        assignment_id=second.id,
        student_ref="student-2",
        status="REGISTERED",
        content_hash="a" * 64,
    )
    db_session.add(second_submission)
    db_session.flush()

    completed = _job(db_session, paper, state="COMPLETED", key="history-complete", at=_at(1))
    _result(db_session, completed, "1a", max_marks=2, awarded=2)
    _result(db_session, completed, "1b", max_marks=3, awarded=1)
    db_session.add(
        JobApproval(
            tenant_id=identity.tenant_a.id,
            job_id=completed.id,
            approved_by=identity.user_a.id,
            approved_by_label="Teacher A",
            approved_at=_at(2),
            approved_marks=3,
            total_marks=5,
        )
    )
    failed = _job(
        db_session,
        paper,
        state="FAILED",
        key="history-failed",
        at=_at(3),
        error_code="PROVIDER_UNAVAILABLE",
        error_message="The provider was unavailable.",
    )
    pending = _job(
        db_session,
        paper,
        state="CREATED",
        key="history-created",
        at=_at(4),
        assignment=second,
        submission=second_submission,
    )
    beta_exam = Exam(tenant_id=identity.tenant_b.id, title="Beta")
    db_session.add(beta_exam)
    db_session.flush()
    beta_assignment = Assignment(
        tenant_id=identity.tenant_b.id,
        exam_id=beta_exam.id,
        name="Beta assignment",
        completion_threshold=0.8,
        review_mode="BALANCED",
    )
    db_session.add(beta_assignment)
    db_session.flush()
    db_session.commit()

    response = client.get(
        f"/api/v1/workspaces/{workspace}/marking-history?limit=2", headers=headers
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert [row["job_id"] for row in page["items"]] == [str(pending.id), str(failed.id)]

    second_page = client.get(
        f"/api/v1/workspaces/{workspace}/marking-history?limit=2&offset=2", headers=headers
    ).json()
    assert [row["job_id"] for row in second_page["items"]] == [str(completed.id)]

    completed_row = second_page["items"][0]
    assert completed_row["assignment_name"] == "Fixture assignment"
    assert completed_row["student_ref"] == "student-1"
    assert completed_row["awarded"] == 3
    assert completed_row["total"] == 5
    assert completed_row["approved"] is True
    assert completed_row["approved_by_label"] == "Teacher A"
    assert completed_row["review_required"] == 0
    assert "beta" not in completed_row["assignment_name"].lower()

    newest = page["items"][0]
    assert newest["assignment_name"] == "Second sitting"
    assert newest["student_ref"] == "student-2"
    assert newest["awarded"] == 0
    assert newest["total"] == 0

    failed_only = client.get(
        f"/api/v1/workspaces/{workspace}/marking-history?state=FAILED", headers=headers
    )
    assert failed_only.status_code == 200
    assert failed_only.json()["total"] == 1
    assert failed_only.json()["items"][0]["error_code"] == "PROVIDER_UNAVAILABLE"

    viewer = client.get(
        f"/api/v1/workspaces/{workspace}/marking-history",
        headers=auth_headers(identity.viewer),
    )
    assert viewer.status_code == 200

    assert (
        client.get(
            f"/api/v1/workspaces/{workspace}/marking-history",
            headers=auth_headers(identity.user_b),
        ).status_code
        == 404
    )
