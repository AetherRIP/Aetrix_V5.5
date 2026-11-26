"""Question-level cohort intelligence.

Each expectation is computed by hand from the rows the test inserts.  The tests
deliberately include the cases that make a naive average lie: different maxima,
missing submissions, undecided rows, excluded rows, failed submissions and
provisional (unapproved) results.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models import (
    Assignment,
    ClassroomAllocation,
    ClassroomClass,
    ClassroomClassAssignment,
    CorrectionJob,
    Exam,
    JobApproval,
    QuestionResult,
    Submission,
    User,
)

BASE = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def _submission(db_session, assignment, ref: str, *, status: str = "REGISTERED") -> Submission:
    row = Submission(
        tenant_id=assignment.tenant_id,
        assignment_id=assignment.id,
        student_ref=ref,
        status=status,
        content_hash="c" * 64,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _job(
    db_session,
    paper,
    assignment,
    submission,
    *,
    state: str = "COMPLETED",
    key: str,
    at: datetime | None = None,
) -> CorrectionJob:
    job = CorrectionJob(
        tenant_id=assignment.tenant_id,
        assignment_id=assignment.id,
        submission_id=submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state=state,
        progress=1.0,
        attempts=1,
        idempotency_key=key,
        request_hash="f" * 64,
        created_at=at or _at(0),
        updated_at=at or _at(0),
    )
    db_session.add(job)
    db_session.flush()
    return job


def _result(
    db_session,
    job: CorrectionJob,
    question_id: str,
    *,
    maximum: int,
    awarded: int,
    status: str = "AWARDED",
    state: str | None = "MARKED",
) -> QuestionResult:
    row = QuestionResult(
        tenant_id=job.tenant_id,
        job_id=job.id,
        question_id=question_id,
        max_marks=maximum,
        awarded_marks=awarded,
        status=status,
        processing_state=state,
        review_required=False,
        scheme_concerns=[],
    )
    db_session.add(row)
    db_session.flush()
    return row


def _approve(db_session, job: CorrectionJob, user: User, *, awarded: int, total: int) -> None:
    db_session.add(
        JobApproval(
            tenant_id=job.tenant_id,
            job_id=job.id,
            approved_by=user.id,
            approved_by_label=user.display_name or user.email or str(user.id),
            approved_at=_at(0),
            approved_marks=awarded,
            total_marks=total,
        )
    )
    db_session.flush()


def _cohort(client, headers, workspace, assignment):
    return client.get(
        f"/api/v1/workspaces/{workspace}/cohort",
        params={"assignment_id": str(assignment.id)},
        headers=headers,
    )


def test_question_statistics_normalise_maxima_and_separate_approval(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    students = [
        paper.submission,
        _submission(db_session, paper.assignment, "student-2"),
        _submission(db_session, paper.assignment, "student-3"),
    ]
    scores = [
        (2, 4),  # 100%
        (1, 2),  # 50%
        (0, 1),  # 16.67%
    ]
    jobs = []
    for index, (student, (q1, q2)) in enumerate(zip(students, scores, strict=True)):
        job = _job(
            db_session,
            paper,
            paper.assignment,
            student,
            key=f"stats-{index}",
            at=_at(index),
        )
        _result(db_session, job, "1", maximum=2, awarded=q1)
        _result(db_session, job, "2", maximum=4, awarded=q2)
        jobs.append(job)
    # An undecided question must be counted as pending, not as a zero.
    _result(
        db_session,
        jobs[2],
        "3",
        maximum=2,
        awarded=0,
        status="UNMARKED",
        state="UNMARKED",
    )
    _approve(db_session, jobs[0], identity.user_a, awarded=6, total=6)
    db_session.commit()

    response = _cohort(client, headers, identity.tenant_a.id, paper.assignment)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["assignment"]["scope"] == "WORKSPACE"
    assert body["overview"]["included_students"] == 3
    assert body["overview"]["eligible_submissions"] == 3
    assert body["overview"]["approved_jobs"] == 1
    assert body["overview"]["provisional_jobs"] == 2
    assert body["overview"]["state"] == "OK"
    assert body["overview"]["mean_percent"] == 55.56
    assert body["overview"]["approved_mean_percent"] == 100.0

    by_id = {question["question_id"]: question for question in body["questions"]}
    q1 = by_id["1"]
    assert (q1["sample_size"], q1["approved_sample"], q1["provisional_sample"]) == (3, 1, 2)
    assert (q1["full_marks"], q1["zero_marks"], q1["partial_marks"]) == (1, 1, 1)
    assert q1["average_marks"] == 1.0
    assert q1["average_percent"] == 50.0
    assert q1["state"] == "OK"
    assert q1["attention"] is False

    q2 = by_id["2"]
    assert q2["average_percent"] == 58.33
    assert (q2["full_marks"], q2["zero_marks"], q2["partial_marks"]) == (1, 0, 2)

    q3 = by_id["3"]
    assert q3["sample_size"] == 0
    assert q3["pending_count"] == 1
    assert q3["state"] == "NO_RESULTS"


def test_missing_pending_and_failed_submissions_never_become_zero(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    completed = paper.submission
    job = _job(db_session, paper, paper.assignment, completed, key="present")
    _result(db_session, job, "1", maximum=2, awarded=1)

    _submission(db_session, paper.assignment, "never-uploaded")
    in_progress = _submission(db_session, paper.assignment, "still-marking")
    _job(db_session, paper, paper.assignment, in_progress, state="CREATED", key="running")

    failed = _submission(db_session, paper.assignment, "failed-upload", status="FAILED")
    failed_job = _job(db_session, paper, paper.assignment, failed, key="failed")
    _result(
        db_session,
        failed_job,
        "1",
        maximum=2,
        awarded=0,
        status="ZERO",
        state="CONFIRMED_ZERO",
    )
    db_session.commit()

    body = _cohort(client, headers, identity.tenant_a.id, paper.assignment).json()

    assert body["overview"]["eligible_submissions"] == 3
    assert body["overview"]["included_students"] == 1
    assert body["overview"]["pending_corrections"] == 2
    assert body["overview"]["mean_percent"] == 50.0
    assert body["completeness"]["excluded_submissions"] == 1
    assert body["completeness"]["submissions_total"] == 4

    q1 = body["questions"][0]
    assert q1["sample_size"] == 1
    assert q1["zero_marks"] == 0
    assert [student["student_ref"] for student in body["students"]] == ["student-1"]


def test_undecided_and_excluded_rows_stay_out_of_the_denominator(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job = _job(db_session, paper, paper.assignment, paper.submission, key="mixed")
    _result(db_session, job, "1", maximum=2, awarded=1)
    _result(
        db_session,
        job,
        "2",
        maximum=3,
        awarded=0,
        status="UNMARKED",
        state="UNMARKED",
    )
    _result(
        db_session,
        job,
        "3",
        maximum=2,
        awarded=0,
        status="EXCLUDED",
        state="UNMARKED",
    )
    db_session.commit()

    body = _cohort(client, headers, identity.tenant_a.id, paper.assignment).json()

    by_id = {question["question_id"]: question for question in body["questions"]}
    assert "3" not in by_id
    assert by_id["1"]["sample_size"] == 1
    assert by_id["1"]["state"] == "INSUFFICIENT_SAMPLE"
    assert by_id["2"]["sample_size"] == 0
    assert by_id["2"]["pending_count"] == 1
    assert body["completeness"]["excluded_rows"] == 1
    assert body["completeness"]["pending_rows"] == 1
    assert body["students"][0]["percentage"] == 50.0


def test_small_samples_are_flagged_and_support_needs_evidence(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    refs = [paper.submission]
    refs += [_submission(db_session, paper.assignment, f"low-{index}") for index in (1, 2)]
    for index, submission in enumerate(refs):
        job = _job(
            db_session,
            paper,
            paper.assignment,
            submission,
            key=f"low-{index}",
            at=_at(index),
        )
        for question in ("1", "2", "3"):
            _result(db_session, job, question, maximum=10, awarded=2)
    db_session.commit()

    body = _cohort(client, headers, identity.tenant_a.id, paper.assignment).json()

    assert body["overview"]["questions_requiring_attention"] == 3
    for question in body["questions"]:
        assert question["state"] == "OK"
        assert question["attention"] is True
    for student in body["students"]:
        assert student["support_flagged"] is True
        assert student["decided"] == 3
        assert "3 decided" in student["evidence"]


def test_topics_are_explicitly_unavailable_without_metadata(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    job = _job(db_session, paper, paper.assignment, paper.submission, key="topics")
    _result(db_session, job, "1", maximum=2, awarded=2)
    db_session.commit()

    body = _cohort(client, headers, identity.tenant_a.id, paper.assignment).json()
    assert body["topics"]["state"] == "unavailable"
    assert body["topics"]["items"] == []
    assert "no topic" in body["topics"]["reason"].lower()


def test_trends_compare_only_matching_questions(
    client, identity, auth_headers, paper, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    # The fixture assignment is created "now", so pin it before the later one for
    # a deterministic timeline.
    paper.assignment.created_at = _at(0)
    # Earlier assignment: 3 students at 2/10 on Q1.
    for index in range(3):
        submission = (
            paper.submission
            if index == 0
            else _submission(db_session, paper.assignment, f"old-{index}")
        )
        job = _job(
            db_session,
            paper,
            paper.assignment,
            submission,
            key=f"old-{index}",
            at=_at(index),
        )
        _result(db_session, job, "1", maximum=10, awarded=2)

    exam = Exam(tenant_id=identity.tenant_a.id, title="Later exam")
    db_session.add(exam)
    db_session.flush()
    later = Assignment(
        tenant_id=identity.tenant_a.id,
        exam_id=exam.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        name="Later assignment",
        completion_threshold=0.8,
        review_mode="BALANCED",
        created_by=identity.user_a.id,
        created_at=_at(60),
    )
    db_session.add(later)
    db_session.flush()
    for index in range(3):
        submission = _submission(db_session, later, f"new-{index}")
        job = _job(
            db_session,
            paper,
            later,
            submission,
            key=f"new-{index}",
            at=_at(61 + index),
        )
        _result(db_session, job, "1", maximum=10, awarded=5)
    db_session.commit()

    body = _cohort(client, headers, identity.tenant_a.id, later).json()

    assert body["trends"]["state"] == "OK"
    assert len(body["trends"]["points"]) == 2
    assert body["trends"]["points"][0]["mean_percent"] == 20.0
    assert body["trends"]["points"][1]["mean_percent"] == 50.0
    changes = body["trends"]["question_changes"]
    assert len(changes) == 1
    assert changes[0]["question_id"] == "1"
    assert changes[0]["max_marks"] == 10
    assert changes[0]["delta_percent"] == 30.0


def test_class_access_is_enforced_for_teachers_and_tenants(
    client, identity, auth_headers, paper, db_session
) -> None:
    classroom = ClassroomClass(
        course_id="course-900",
        name="10B Maths",
        created_by_subject=identity.user_a.subject,
    )
    db_session.add(classroom)
    db_session.flush()
    allocation = ClassroomAllocation(
        classroom_class_id=classroom.id,
        workspace_id=identity.tenant_a.id,
        course_id="course-900",
        class_name="10B Maths",
        workspace_name="Alpha",
        status="ACTIVE",
        origin="ALLOCATE",
        allocated_by_subject=identity.user_a.subject,
    )
    db_session.add(allocation)
    db_session.flush()
    paper.assignment.classroom_allocation_id = allocation.id
    paper.assignment.course_id = "course-900"
    paper.assignment.class_name = "10B Maths"

    teacher = User(tenant_id=identity.tenant_a.id, subject="assigned-teacher", role="TEACHER")
    db_session.add(teacher)
    db_session.commit()

    owner = _cohort(client, auth_headers(identity.user_a), identity.tenant_a.id, paper.assignment)
    assert owner.status_code == 200, owner.text
    assert owner.json()["assignment"]["scope"] == "CLASS"

    teacher_headers = auth_headers(teacher)
    refused = _cohort(client, teacher_headers, identity.tenant_a.id, paper.assignment)
    assert refused.status_code == 404

    db_session.add(
        ClassroomClassAssignment(
            allocation_id=allocation.id,
            workspace_id=identity.tenant_a.id,
            user_id=teacher.id,
        )
    )
    db_session.commit()
    allowed = _cohort(client, teacher_headers, identity.tenant_a.id, paper.assignment)
    assert allowed.status_code == 200, allowed.text

    viewer_headers = auth_headers(identity.viewer)
    assert (
        _cohort(client, viewer_headers, identity.tenant_a.id, paper.assignment).status_code
        == 404
    )

    other_tenant = _cohort(
        client, auth_headers(identity.user_b), identity.tenant_a.id, paper.assignment
    )
    assert other_tenant.status_code == 404


def test_empty_assignment_reports_insufficient_data(
    client, identity, auth_headers, paper, db_session
) -> None:
    exam = Exam(tenant_id=identity.tenant_a.id, title="Empty exam")
    db_session.add(exam)
    db_session.flush()
    empty = Assignment(
        tenant_id=identity.tenant_a.id,
        exam_id=exam.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        name="Empty assignment",
        course_id="empty-course",
        completion_threshold=0.8,
        review_mode="BALANCED",
        created_by=identity.user_a.id,
    )
    db_session.add(empty)
    db_session.commit()

    response = _cohort(client, auth_headers(identity.user_a), identity.tenant_a.id, empty)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overview"]["state"] == "INSUFFICIENT_DATA"
    assert body["overview"]["mean_percent"] is None
    assert body["questions"] == []
    assert body["students"] == []
    assert body["trends"]["state"] == "INSUFFICIENT_DATA"
