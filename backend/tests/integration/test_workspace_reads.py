"""Workspace reads: dashboard, inbox, reports, gradebook and audit.

These endpoints are read-only, so the behaviour worth asserting is arithmetic,
ordering, empty-state shape and tenant scope.  Every figure below is computed
from rows the test inserts; nothing is compared against a hand-written estimate
of what the query "probably" does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models import (
    Assignment,
    AuditEvent,
    CorrectionJob,
    Exam,
    JobApproval,
    QuestionResult,
    Submission,
    User,
)

BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def _assignment(db_session, identity, *, name: str, created_at: datetime, tenant: str = "a"):
    tenant_id = identity.tenant_a.id if tenant == "a" else identity.tenant_b.id
    creator = identity.user_a.id if tenant == "a" else identity.user_b.id
    exam = Exam(tenant_id=tenant_id, title=f"{name} exam")
    db_session.add(exam)
    db_session.flush()
    assignment = Assignment(
        tenant_id=tenant_id,
        exam_id=exam.id,
        name=name,
        completion_threshold=0.8,
        review_mode="BALANCED",
        created_by=creator,
        created_at=created_at,
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


def _submission(db_session, assignment, *, student_ref: str) -> Submission:
    submission = Submission(
        tenant_id=assignment.tenant_id,
        assignment_id=assignment.id,
        student_ref=student_ref,
        status="REGISTERED",
        content_hash="d" * 64,
    )
    db_session.add(submission)
    db_session.flush()
    return submission


def _job(
    db_session,
    paper,
    assignment,
    submission,
    *,
    state: str,
    key: str,
    at: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
) -> CorrectionJob:
    job = CorrectionJob(
        tenant_id=assignment.tenant_id,
        assignment_id=assignment.id,
        submission_id=submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state=state,
        progress=0.0,
        attempts=0,
        idempotency_key=key,
        request_hash="e" * 64,
        error_code=error_code,
        error_message=error_message,
        created_at=at,
        updated_at=at,
    )
    db_session.add(job)
    db_session.flush()
    return job


def _result(
    db_session,
    job: CorrectionJob,
    question_id: str,
    *,
    max_marks: int,
    awarded: int,
    review_required: bool = False,
) -> QuestionResult:
    row = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id=question_id,
        max_marks=max_marks,
        awarded_marks=awarded,
        status="AWARDED",
        confidence=0.9,
        review_required=review_required,
        scheme_concerns=[],
    )
    db_session.add(row)
    db_session.flush()
    return row


def _approval(db_session, job: CorrectionJob, *, awarded: int, total: int, by) -> JobApproval:
    approval = JobApproval(
        tenant_id=job.tenant_id,
        job_id=job.id,
        approved_by=by.id,
        approved_by_label=by.display_name or by.email or str(by.id),
        approved_at=_at(0),
        approved_marks=awarded,
        total_marks=total,
    )
    db_session.add(approval)
    db_session.flush()
    return approval


def _audit(
    db_session,
    tenant_id,
    *,
    action: str,
    entity_type: str,
    at: datetime,
    entity_id: str = "entity-1",
    detail: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_type="SYSTEM",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
        created_at=at,
    )
    db_session.add(event)
    db_session.flush()
    return event


def test_empty_workspace_reads_are_empty_shapes_not_zeros(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id

    dashboard = client.get(f"/api/v1/workspaces/{workspace}/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json() == {
        "assignments": 0,
        "submissions": 0,
        "jobs_active": 0,
        "awaiting_review": 0,
        "failed_jobs": 0,
        "approved_results": 0,
        "recent_jobs": [],
    }

    assert client.get(f"/api/v1/workspaces/{workspace}/inbox", headers=headers).json() == []
    assert client.get(f"/api/v1/workspaces/{workspace}/reports", headers=headers).json() == []

    gradebook = client.get(f"/api/v1/workspaces/{workspace}/gradebook", headers=headers)
    assert gradebook.status_code == 200
    assert gradebook.json() == {
        "assignments": [],
        "students": [],
        "approved_jobs": 0,
        "provisional_jobs": 0,
        "mean_percent": None,
        "state": "INSUFFICIENT_DATA",
    }

    audit = client.get(f"/api/v1/workspaces/{workspace}/audit", headers=headers)
    assert audit.status_code == 200
    assert audit.json() == []


def test_dashboard_counts_real_rows_and_names_the_latest_eight_jobs(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    states = [
        "CREATED",
        "CREATED",
        "CREATED",
        "REVIEW_REQUIRED",
        "RETRY_SUSPENDED",
        "FAILED",
        "FAILED",
        "COMPLETED",
        "CANCELLED",
        "CANCELLED",
        "CREATED",
    ]
    jobs = [
        _job(
            db_session,
            paper,
            paper.assignment,
            paper.submission,
            state=state,
            key=f"dashboard-{index}",
            at=_at(index),
        )
        for index, state in enumerate(states, start=1)
    ]
    _approval(db_session, jobs[7], awarded=3, total=5, by=identity.user_a)

    # A second workspace with its own assignment and submission must never
    # contribute to the first workspace's counts.
    beta_assignment = _assignment(
        db_session, identity, name="Beta assignment", created_at=_at(30), tenant="b"
    )
    _submission(db_session, beta_assignment, student_ref="beta-student")
    db_session.commit()

    response = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/dashboard", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assignments"] == 1
    assert body["submissions"] == 1
    assert body["jobs_active"] == 6
    assert body["awaiting_review"] == 1
    assert body["failed_jobs"] == 2
    assert body["approved_results"] == 1

    recent = body["recent_jobs"]
    assert len(recent) == 8
    newest_first = sorted(jobs, key=lambda job: job.updated_at, reverse=True)[:8]
    assert [row["id"] for row in recent] == [str(job.id) for job in newest_first]
    assert all(row["student_ref"] == "student-1" for row in recent)
    assert recent[0]["state"] == "CREATED"
    # Compared as an instant, not as a string prefix: the API preserves the
    # server's UTC offset, so a literal "09:11" prefix only matches a UTC host.
    updated_at = datetime.fromisoformat(recent[0]["updated_at"])
    assert updated_at.tzinfo is not None
    assert updated_at == _at(11)

    beta = client.get(
        f"/api/v1/workspaces/{identity.tenant_b.id}/dashboard",
        headers=auth_headers(identity.user_b),
    )
    assert beta.status_code == 200
    assert beta.json()["assignments"] == 1
    assert beta.json()["submissions"] == 1
    assert beta.json()["jobs_active"] == 0
    assert beta.json()["recent_jobs"] == []


def test_inbox_lists_only_actionable_jobs_newest_first(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    review_job = _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="REVIEW_REQUIRED",
        key="inbox-review",
        at=_at(3),
    )
    _result(db_session, review_job, "1a", max_marks=2, awarded=2, review_required=True)
    _result(db_session, review_job, "1b", max_marks=3, awarded=1, review_required=True)
    _result(db_session, review_job, "2", max_marks=5, awarded=5)

    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="FAILED",
        key="inbox-failed",
        at=_at(5),
        error_message="The provider answered 503.",
    )
    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="RETRY_SUSPENDED",
        key="inbox-suspended",
        at=_at(4),
        error_code="PROVIDER_CAPACITY",
    )
    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="COMPLETED",
        key="inbox-completed",
        at=_at(6),
    )
    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="CREATED",
        key="inbox-created",
        at=_at(7),
    )
    db_session.commit()

    response = client.get(f"/api/v1/workspaces/{identity.tenant_a.id}/inbox", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["kind"] for item in items] == ["JOB_FAILED", "JOB_FAILED", "REVIEW_REQUIRED"]
    assert [item["detail"] for item in items] == [
        "The provider answered 503.",
        "PROVIDER_CAPACITY",
        "2 question(s) could not be marked with confidence.",
    ]
    assert items[2]["title"] == "student-1 needs review"
    assert all(item["read"] is None for item in items)

    viewer = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/inbox",
        headers=auth_headers(identity.viewer),
    )
    assert viewer.status_code == 200
    assert len(viewer.json()) == 3


def test_inbox_is_empty_when_no_job_needs_a_person(
    client, identity, auth_headers, paper, db_session
) -> None:
    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="COMPLETED",
        key="inbox-quiet",
        at=_at(1),
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/inbox",
        headers=auth_headers(identity.user_a),
    )
    assert response.status_code == 200
    assert response.json() == []


def test_reports_aggregate_per_assignment_without_leaking_another_tenant(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    paper.assignment.created_at = _at(0)

    approved_job = _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="COMPLETED",
        key="reports-approved",
        at=_at(1),
    )
    _result(db_session, approved_job, "1a", max_marks=2, awarded=2)
    _result(db_session, approved_job, "1b", max_marks=3, awarded=1)
    _approval(db_session, approved_job, awarded=3, total=5, by=identity.user_a)

    second = _assignment(db_session, identity, name="Second sitting", created_at=_at(10))
    second_submission = _submission(db_session, second, student_ref="student-2")
    unapproved = _job(
        db_session,
        paper,
        second,
        second_submission,
        state="COMPLETED",
        key="reports-unapproved",
        at=_at(11),
    )
    _result(db_session, unapproved, "1a", max_marks=4, awarded=1)

    beta_assignment = _assignment(
        db_session, identity, name="Beta assignment", created_at=_at(5), tenant="b"
    )
    _submission(db_session, beta_assignment, student_ref="beta-student")
    db_session.commit()

    response = client.get(f"/api/v1/workspaces/{identity.tenant_a.id}/reports", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["name"] for row in rows] == ["Second sitting", "Fixture assignment"]

    approved_row = rows[1]
    assert approved_row["assignment_id"] == str(paper.assignment.id)
    assert approved_row["submissions"] == 1
    assert approved_row["jobs_completed"] == 1
    assert approved_row["approved"] == 1
    assert approved_row["total_marks"] == 5
    assert approved_row["mean_percent"] == 60.0
    assert approved_row["state"] == "OK"

    unapproved_row = rows[0]
    assert unapproved_row["submissions"] == 1
    assert unapproved_row["jobs_completed"] == 1
    assert unapproved_row["approved"] == 0
    assert unapproved_row["total_marks"] == 0
    assert unapproved_row["mean_percent"] is None
    assert unapproved_row["state"] == "INSUFFICIENT_DATA"

    beta = client.get(
        f"/api/v1/workspaces/{identity.tenant_b.id}/reports",
        headers=auth_headers(identity.user_b),
    )
    assert beta.status_code == 200
    assert [row["name"] for row in beta.json()] == ["Beta assignment"]
    assert beta.json()[0]["mean_percent"] is None


def test_gradebook_arithmetic_counts_only_approved_marks(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    paper.assignment.created_at = _at(0)

    approved_job = _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="COMPLETED",
        key="gradebook-approved",
        at=_at(1),
    )
    _result(db_session, approved_job, "1a", max_marks=2, awarded=2)
    _result(db_session, approved_job, "1b", max_marks=3, awarded=1)
    _approval(db_session, approved_job, awarded=3, total=5, by=identity.user_a)

    second = _assignment(db_session, identity, name="Second sitting", created_at=_at(2))
    second_submission = _submission(db_session, second, student_ref="student-2")
    provisional_job = _job(
        db_session,
        paper,
        second,
        second_submission,
        state="COMPLETED",
        key="gradebook-provisional",
        at=_at(3),
    )
    _result(db_session, provisional_job, "1a", max_marks=4, awarded=2)
    db_session.commit()

    response = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/gradebook", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert [card["name"] for card in body["assignments"]] == [
        "Fixture assignment",
        "Second sitting",
    ]
    assert body["approved_jobs"] == 1
    assert body["provisional_jobs"] == 1
    assert body["mean_percent"] == 60.0
    assert body["state"] == "OK"

    students = {row["student_ref"]: row for row in body["students"]}
    assert students["student-1"]["approved_awarded"] == 3
    assert students["student-1"]["approved_possible"] == 5
    first_cell = students["student-1"]["cells"][0]
    assert first_cell["awarded"] == 3
    assert first_cell["total"] == 5
    assert first_cell["approved"] is True
    # A student with no submission for the second assignment has no submission
    # id at all; a placeholder identifier would be invented data.
    assert students["student-1"]["cells"][1]["submission_id"] is None
    assert students["student-1"]["cells"][1]["awarded"] is None

    assert students["student-2"]["approved_awarded"] == 0
    assert students["student-2"]["approved_possible"] == 0
    provisional_cell = students["student-2"]["cells"][1]
    assert provisional_cell["awarded"] == 2
    assert provisional_cell["approved"] is False
    assert provisional_cell["job_state"] == "COMPLETED"


def test_gradebook_does_not_call_failed_or_cancelled_jobs_provisional(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    paper.assignment.created_at = _at(0)

    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="FAILED",
        key="gradebook-failed",
        at=_at(1),
        error_code="PROVIDER_ERROR",
    )
    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="CANCELLED",
        key="gradebook-cancelled",
        at=_at(2),
    )
    _job(
        db_session,
        paper,
        paper.assignment,
        paper.submission,
        state="CREATED",
        key="gradebook-created",
        at=_at(3),
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/gradebook", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # None of these produced marks, so none of them may be reported as
    # "marked, not yet approved".
    assert body["provisional_jobs"] == 0
    assert body["approved_jobs"] == 0
    assert body["assignments"][0]["provisional_jobs"] == 0
    assert body["mean_percent"] is None
    assert body["state"] == "INSUFFICIENT_DATA"


def test_gradebook_filters_by_assignment_and_refuses_a_foreign_one(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    second = _assignment(db_session, identity, name="Second sitting", created_at=_at(2))
    _submission(db_session, second, student_ref="student-2")
    beta_assignment = _assignment(
        db_session, identity, name="Beta assignment", created_at=_at(3), tenant="b"
    )
    db_session.commit()

    filtered = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/gradebook",
        headers=headers,
        params={"assignment_id": str(second.id)},
    )
    assert filtered.status_code == 200, filtered.text
    body = filtered.json()
    assert [card["id"] for card in body["assignments"]] == [str(second.id)]
    assert [row["student_ref"] for row in body["students"]] == ["student-2"]

    foreign = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/gradebook",
        headers=headers,
        params={"assignment_id": str(beta_assignment.id)},
    )
    assert foreign.status_code == 404

    cross_tenant = client.get(
        f"/api/v1/workspaces/{identity.tenant_b.id}/gradebook", headers=headers
    )
    assert cross_tenant.status_code == 404


def test_workspace_audit_is_tenant_scoped_ordered_and_filterable(
    client, identity, auth_headers, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    first = _audit(
        db_session,
        identity.tenant_a.id,
        action="exam.created",
        entity_type="exam",
        at=_at(1),
        entity_id="exam-1",
    )
    second = _audit(
        db_session,
        identity.tenant_a.id,
        action="criterion.reviewed",
        entity_type="criterion",
        at=_at(2),
        entity_id="criterion-9",
    )
    third = _audit(
        db_session,
        identity.tenant_a.id,
        action="exam.created",
        entity_type="exam",
        at=_at(3),
        entity_id="exam-2",
    )
    fourth = _audit(
        db_session,
        identity.tenant_a.id,
        action="result.approved",
        entity_type="correction_job",
        at=_at(4),
        entity_id="job-7",
        detail={"approved_marks": 3},
    )
    beta = _audit(
        db_session,
        identity.tenant_b.id,
        action="beta.secret",
        entity_type="exam",
        at=_at(5),
        entity_id="beta-exam",
    )
    platform = _audit(
        db_session,
        None,
        action="workspace.provisioned",
        entity_type="tenant",
        at=_at(6),
        entity_id="tenant-x",
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/audit", headers=headers
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["id"] for row in rows] == [
        str(fourth.id),
        str(third.id),
        str(second.id),
        str(first.id),
    ]
    assert str(beta.id) not in {row["id"] for row in rows}
    assert str(platform.id) not in {row["id"] for row in rows}
    assert rows[0]["detail"] == {"approved_marks": 3}
    assert rows[0]["entity_id"] == "job-7"

    by_action = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/audit",
        headers=headers,
        params={"action": "exam.created"},
    )
    assert [row["entity_id"] for row in by_action.json()] == ["exam-2", "exam-1"]

    by_type = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/audit",
        headers=headers,
        params={"entity_type": "criterion"},
    )
    assert [row["id"] for row in by_type.json()] == [str(second.id)]

    page = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/audit",
        headers=headers,
        params={"limit": 2, "offset": 1},
    )
    assert [row["id"] for row in page.json()] == [str(third.id), str(second.id)]

    viewer = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/audit",
        headers=auth_headers(identity.viewer),
    )
    assert viewer.status_code == 200
    assert len(viewer.json()) == 4


def test_platform_audit_requires_the_platform_operator(
    client, identity, auth_headers, db_session
) -> None:
    platform_user = User(
        tenant_id=identity.tenant_a.id, subject="platform-1", role="PLATFORM_OWNER"
    )
    db_session.add(platform_user)
    _audit(
        db_session,
        identity.tenant_a.id,
        action="exam.created",
        entity_type="exam",
        at=_at(1),
    )
    _audit(
        db_session,
        identity.tenant_b.id,
        action="beta.secret",
        entity_type="exam",
        at=_at(2),
        entity_id="beta-exam",
    )
    _audit(
        db_session,
        None,
        action="workspace.provisioned",
        entity_type="tenant",
        at=_at(3),
        entity_id="tenant-x",
    )
    db_session.commit()

    allowed = client.get("/api/v1/admin/audit", headers=auth_headers(platform_user))
    assert allowed.status_code == 200, allowed.text
    actions = [row["action"] for row in allowed.json()]
    assert actions == ["workspace.provisioned", "beta.secret", "exam.created"]

    owner_refused = client.get("/api/v1/admin/audit", headers=auth_headers(identity.user_a))
    assert owner_refused.status_code == 403
    assert (
        client.get("/api/v1/admin/audit", headers=auth_headers(identity.viewer)).status_code
        == 403
    )


def test_every_workspace_read_refuses_a_foreign_workspace(
    client, identity, auth_headers
) -> None:
    foreign = identity.tenant_a.id
    outsider = auth_headers(identity.user_b)

    for path in (
        f"/api/v1/workspaces/{foreign}/dashboard",
        f"/api/v1/workspaces/{foreign}/inbox",
        f"/api/v1/workspaces/{foreign}/reports",
        f"/api/v1/workspaces/{foreign}/gradebook",
        f"/api/v1/workspaces/{foreign}/audit",
    ):
        response = client.get(path, headers=outsider)
        assert response.status_code == 404, path
        assert "error" in response.json(), path

    own = auth_headers(identity.user_a)
    for path in (
        f"/api/v1/workspaces/{foreign}/dashboard",
        f"/api/v1/workspaces/{foreign}/inbox",
        f"/api/v1/workspaces/{foreign}/reports",
        f"/api/v1/workspaces/{foreign}/gradebook",
        f"/api/v1/workspaces/{foreign}/audit",
    ):
        assert client.get(path, headers=own).status_code == 200, path
