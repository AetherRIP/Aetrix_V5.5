"""The Classroom integration against PostgreSQL.

These tests exercise the parts that only a real database can prove: the
singleton connection row, the upsert of discovered courses, tenant-scoped
queries, roster identity mapping and the approval gate in front of grade
publication.  Google is never called: the upstream functions are replaced with
deterministic results.

They require a disposable loopback PostgreSQL (``AETRIX_TEST_DATABASE_URL``);
the suite refuses a remote database by design.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from app.core.config import ClassroomSettings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import utcnow
from app.core.security import Principal, SecretBox
from app.db.models import (
    ClassroomAllocation,
    ClassroomClass,
    ClassroomClassAssignment,
    ClassroomConnection,
    ClassroomCourseworkLink,
    ClassroomGradePublication,
    ClassroomRosterEntry,
    ClassroomSubmissionLink,
    ClassroomSyncRun,
    CorrectionJob,
    QuestionResult,
    Student,
)
from app.schemas.classroom_class_assignments import ClassroomClassAssignmentCreate
from app.schemas.classroom_integration import (
    ApprovalRequest,
    GradePublishRequest,
)
from app.services.classroom_class_assignments import ClassroomClassAssignmentService
from app.services.classroom_google import (
    REQUIRED_SCOPES,
    ClassroomPerson,
    CourseListing,
    DiscoveredCourse,
    PersonListing,
    SubmissionListing,
    SubmissionRecord,
)
from app.services.classroom_grades import ClassroomGradeService
from app.services.classroom_oauth import PLATFORM_CONNECTION_KEY, ClassroomOAuthService
from app.services.classroom_roster import ClassroomRosterService
from app.services.classroom_submissions import ClassroomSubmissionService
from pydantic import SecretStr
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

COURSE_ID = "600100"


def _settings():
    return get_settings().model_copy(
        update={
            "classroom": ClassroomSettings(
                client_id="client-id.apps.googleusercontent.com",
                client_secret=SecretStr("client-secret"),
                redirect_uri="http://127.0.0.1:3000/auth/classroom",
                retry_backoff_seconds=0.0,
            )
        }
    )


def _principal(user, *, platform_role: str = "") -> Principal:
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        subject=user.subject,
        role=user.role,
        platform_role=platform_role,
    )


@pytest.fixture
def classroom_setup(db_session, identity, paper):
    """A verified course allocated to Alpha and a connected central account."""

    box = SecretBox(get_settings().security.encryption_key.get_secret_value())
    classroom = ClassroomClass(
        course_id=COURSE_ID,
        name="Year 10 Algebra",
        section="A",
        course_state="ACTIVE",
        verification="VERIFIED",
        source="google_classroom",
        owner_email="central@example.org",
        teacher_name="Central Account",
        synced_at=utcnow(),
        created_by_subject="operator",
    )
    db_session.add(classroom)
    db_session.flush()
    allocation = ClassroomAllocation(
        classroom_class_id=classroom.id,
        workspace_id=identity.tenant_a.id,
        course_id=COURSE_ID,
        class_name="Year 10 Algebra",
        workspace_name="Alpha",
        status="ACTIVE",
        origin="ALLOCATE",
        allocated_by_subject="operator",
        allocated_at=utcnow(),
    )
    # The allocation id is generated on flush, so the class assignment below
    # can only reference it once the row exists.
    db_session.add(allocation)
    db_session.flush()
    connection = ClassroomConnection(
        connection_key=PLATFORM_CONNECTION_KEY,
        tenant_id=None,
        status="CONNECTED",
        connected_by_subject="operator",
        connected_at=utcnow(),
        encrypted_access_token=box.encrypt("access-token-value"),
        encrypted_refresh_token=box.encrypt("refresh-token-value"),
        access_token_expires_at=utcnow() + timedelta(hours=1),
        scopes=list(REQUIRED_SCOPES),
        requested_scopes=list(REQUIRED_SCOPES),
        last_sync_counts={},
        connected_account_email="central@example.org",
        connected_account_name="Central Account",
    )
    assignment = ClassroomClassAssignment(
        allocation_id=allocation.id,
        workspace_id=identity.tenant_a.id,
        user_id=identity.reviewer.id,
        assigned_by_user_id=identity.user_a.id,
        assigned_at=utcnow(),
    )
    db_session.add_all([connection, assignment])
    db_session.commit()
    return SimpleSetup(
        classroom=classroom,
        allocation=allocation,
        connection=connection,
        assignment=paper.assignment,
        class_assignment=assignment,
    )


class SimpleSetup:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_the_connection_is_one_platform_row_and_never_returns_a_token(
    db_session, identity, classroom_setup
):
    settings = _settings()
    admin = _principal(identity.user_a, platform_role="ADMIN")

    read = ClassroomOAuthService(db_session, settings).connection(admin)

    assert read.status == "CONNECTED"
    assert read.missing_scopes == []
    assert read.connected_account_email == "central@example.org"
    serialised = read.model_dump_json()
    assert "access-token-value" not in serialised
    assert "refresh-token-value" not in serialised

    stored = db_session.scalar(
        select(ClassroomConnection).where(
            ClassroomConnection.connection_key == PLATFORM_CONNECTION_KEY
        )
    )
    assert stored is not None
    assert "access-token-value" not in (stored.encrypted_access_token or "")
    assert "refresh-token-value" not in (stored.encrypted_refresh_token or "")
    assert stored.tenant_id is None


def test_a_workspace_owner_cannot_read_the_central_connection(
    db_session, identity, classroom_setup
):
    settings = _settings()
    with pytest.raises(AppError) as caught:
        ClassroomOAuthService(db_session, settings).connection(
            _principal(identity.user_a)
        )
    assert caught.value.code is ErrorCode.FORBIDDEN


def test_access_token_is_the_decrypted_ciphertext(
    db_session, identity, classroom_setup
):
    settings = _settings()
    token = ClassroomOAuthService(db_session, settings).access_token()
    assert token == "access-token-value"


def test_course_discovery_upserts_instead_of_duplicating(
    db_session, identity, classroom_setup, monkeypatch
):
    settings = _settings()
    admin = _principal(identity.user_a, platform_role="ADMIN")

    def fake_list(settings_, access_token, *, max_courses=None, transport=None):
        return CourseListing(
            courses=[
                DiscoveredCourse(
                    course_id="700200",
                    name="Year 11 Geometry",
                    section="B",
                    course_state="ACTIVE",
                    time_zone="Europe/London",
                )
            ],
            truncated=False,
        )

    monkeypatch.setattr(
        "app.services.classroom_oauth.list_courses", fake_list
    )

    service = ClassroomOAuthService(db_session, settings)
    first = service.sync(admin)
    second = service.sync(admin)

    assert first.counts.created == 1
    assert second.counts.created == 0
    assert second.counts.updated == 1

    count = db_session.scalar(
        select(func.count())
        .select_from(ClassroomClass)
        .where(ClassroomClass.course_id == "700200")
    )
    assert count == 1
    runs = db_session.scalar(
        select(func.count())
        .select_from(ClassroomSyncRun)
        .where(ClassroomSyncRun.kind == "COURSES")
    )
    assert runs == 2


def test_only_the_allocated_workspace_sees_the_course(
    db_session, identity, classroom_setup
):
    settings = _settings()
    alpha = ClassroomRosterService(db_session, settings).courses(
        _principal(identity.user_a)
    )
    beta = ClassroomRosterService(db_session, settings).courses(
        _principal(identity.user_b)
    )

    assert [course.course_id for course in alpha] == [COURSE_ID]
    assert beta == []

    with pytest.raises(AppError) as caught:
        ClassroomRosterService(db_session, settings).roster(
            _principal(identity.user_b), COURSE_ID
        )
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_a_reviewer_sees_only_the_course_assigned_to_them(
    db_session, identity, classroom_setup
):
    settings = _settings()
    reviewer = _principal(identity.reviewer)

    # A synced student makes the roster assertion meaningful; it is reachable
    # only through the allocation the reviewer's assignment points at.
    student = Student(
        tenant_id=identity.tenant_a.id,
        student_ref="roster-1",
        display_name="Roster Student",
    )
    db_session.add(student)
    db_session.flush()
    db_session.add(
        ClassroomRosterEntry(
            tenant_id=identity.tenant_a.id,
            course_id=COURSE_ID,
            google_user_id="google-roster-1",
            student_id=student.id,
            full_name="Roster Student",
            status="ACTIVE",
            match_source="CREATED",
            last_seen_at=utcnow(),
        )
    )
    db_session.commit()

    assert [
        course.course_id
        for course in ClassroomRosterService(db_session, settings).courses(reviewer)
    ] == [COURSE_ID]
    roster = ClassroomRosterService(db_session, settings).roster(reviewer, COURSE_ID)
    assert [entry.student_ref for entry in roster] == ["roster-1"]

    db_session.delete(classroom_setup.class_assignment)
    db_session.commit()

    assert ClassroomRosterService(db_session, settings).courses(reviewer) == []
    with pytest.raises(AppError) as caught:
        ClassroomRosterService(db_session, settings).roster(reviewer, COURSE_ID)
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_an_owner_assigns_and_withdraws_a_class_and_duplicates_are_refused(
    db_session, identity, classroom_setup
):
    service = ClassroomClassAssignmentService(db_session)
    owner = _principal(identity.user_a)
    reviewer = _principal(identity.reviewer)

    db_session.delete(classroom_setup.class_assignment)
    db_session.commit()
    assert ClassroomRosterService(db_session, _settings()).courses(reviewer) == []

    row = service.create(
        owner,
        identity.tenant_a.id,
        COURSE_ID,
        ClassroomClassAssignmentCreate(user_id=identity.reviewer.id),
    )
    assert row.user_id == identity.reviewer.id
    assert [
        course.course_id
        for course in ClassroomRosterService(db_session, _settings()).courses(reviewer)
    ] == [COURSE_ID]

    with pytest.raises(AppError) as caught:
        service.create(
            owner,
            identity.tenant_a.id,
            COURSE_ID,
            ClassroomClassAssignmentCreate(user_id=identity.reviewer.id),
        )
    assert caught.value.code is ErrorCode.CONFLICT

    with pytest.raises(AppError) as caught:
        service.create(
            owner,
            identity.tenant_a.id,
            COURSE_ID,
            ClassroomClassAssignmentCreate(user_id=identity.user_a.id),
        )
    assert caught.value.code is ErrorCode.VALIDATION_ERROR

    with pytest.raises(AppError) as caught:
        service.create(
            owner,
            identity.tenant_a.id,
            COURSE_ID,
            ClassroomClassAssignmentCreate(user_id=identity.viewer.id),
        )
    assert caught.value.code is ErrorCode.VALIDATION_ERROR

    with pytest.raises(AppError) as caught:
        service.create(
            _principal(identity.user_b),
            identity.tenant_b.id,
            COURSE_ID,
            ClassroomClassAssignmentCreate(user_id=identity.reviewer.id),
        )
    # A course allocated to another workspace must look nonexistent rather than
    # reveal that it exists elsewhere (tenant isolation, not a permission hint).
    assert caught.value.code is ErrorCode.NOT_FOUND

    service.remove(owner, identity.tenant_a.id, COURSE_ID, row.id)
    assert ClassroomRosterService(db_session, _settings()).courses(reviewer) == []
    with pytest.raises(AppError) as caught:
        service.remove(owner, identity.tenant_a.id, COURSE_ID, row.id)
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_roster_sync_creates_students_once_and_marks_departures(
    db_session, identity, classroom_setup, monkeypatch
):
    settings = _settings()
    teacher = _principal(identity.user_a)
    state = {"people": ["101", "102"]}

    def fake_students(settings_, access_token, course_id, *, max_students=None, transport=None):
        return PersonListing(
            people=[
                ClassroomPerson(
                    user_id=user_id,
                    full_name="Ada Lovelace" if user_id == "101" else "Grace Hopper",
                    email=None,
                )
                for user_id in state["people"]
            ],
            truncated=False,
        )

    monkeypatch.setattr("app.services.classroom_roster.list_students", fake_students)
    service = ClassroomRosterService(db_session, settings)

    first = service.sync(teacher, COURSE_ID)
    assert first.counts["created"] == 2
    assert first.counts["removed"] == 0

    second = service.sync(teacher, COURSE_ID)
    assert second.counts["created"] == 0
    assert second.counts["updated"] == 2

    state["people"] = ["101"]
    third = service.sync(teacher, COURSE_ID)
    assert third.counts["removed"] == 1

    students = db_session.scalars(
        select(Student).where(Student.tenant_id == identity.tenant_a.id)
    ).all()
    assert len(students) == 2
    entries = db_session.scalars(
        select(ClassroomRosterEntry).where(
            ClassroomRosterEntry.tenant_id == identity.tenant_a.id
        )
    ).all()
    removed = [entry for entry in entries if entry.status == "REMOVED"]
    assert len(removed) == 1
    assert removed[0].google_user_id == "102"


def test_a_second_google_user_with_the_same_name_is_a_second_student(
    db_session, identity, classroom_setup, monkeypatch
):
    settings = _settings()
    teacher = _principal(identity.user_a)

    def fake_students(settings_, access_token, course_id, *, max_students=None, transport=None):
        return PersonListing(
            people=[
                ClassroomPerson(user_id="201", full_name="Alex Smith", email=None),
                ClassroomPerson(user_id="202", full_name="Alex Smith", email=None),
            ],
            truncated=False,
        )

    monkeypatch.setattr("app.services.classroom_roster.list_students", fake_students)
    result = ClassroomRosterService(db_session, settings).sync(teacher, COURSE_ID)

    assert result.counts["created"] == 2
    refs = {entry.student_ref for entry in result.entries}
    assert refs == {"201", "202"}


def _completed_job(db_session, paper, *, state: str = "COMPLETED"):
    job = CorrectionJob(
        tenant_id=paper.assignment.tenant_id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state=state,
        progress=1.0,
        idempotency_key=f"fixture-{state}",
        request_hash="c" * 64,
    )
    db_session.add(job)
    db_session.flush()
    for question_id, awarded, maximum in (("1a", 2, 2), ("1b", 3, 3)):
        db_session.add(
            QuestionResult(
                tenant_id=paper.assignment.tenant_id,
                job_id=job.id,
                question_id=question_id,
                max_marks=maximum,
                awarded_marks=awarded,
                status="AWARDED",
            )
        )
    db_session.commit()
    return job


def _submission_link(db_session, classroom_setup, job):
    coursework = ClassroomCourseworkLink(
        tenant_id=classroom_setup.assignment.tenant_id,
        assignment_id=classroom_setup.assignment.id,
        classroom_class_id=classroom_setup.classroom.id,
        course_id=COURSE_ID,
        coursework_id="work-1",
        state="PUBLISHED",
        title="Fixture coursework",
        publish_attempts=1,
        max_points=Decimal("10.00"),
    )
    db_session.add(coursework)
    db_session.flush()

    student = Student(
        tenant_id=classroom_setup.assignment.tenant_id,
        student_ref="101",
        display_name="Ada Lovelace",
    )
    db_session.add(student)
    db_session.flush()

    link = ClassroomSubmissionLink(
        tenant_id=classroom_setup.assignment.tenant_id,
        coursework_link_id=coursework.id,
        assignment_id=classroom_setup.assignment.id,
        submission_id=job.submission_id,
        course_id=COURSE_ID,
        coursework_id="work-1",
        google_submission_id="gs-1",
        google_user_id="101",
        student_id=student.id,
        state="CORRECTING",
        attachments=[],
        correction_job_id=job.id,
    )
    db_session.add(link)
    db_session.commit()
    return coursework, link


def test_the_approved_total_is_the_sum_of_decided_questions(
    db_session, identity, classroom_setup, paper
):
    settings = _settings()
    job = _completed_job(db_session, paper)
    _coursework, link = _submission_link(db_session, classroom_setup, job)
    service = ClassroomGradeService(db_session, settings)
    reviewer = _principal(identity.reviewer)

    review = service.review(reviewer, link.id)
    assert review.approvable is True
    assert review.total == Decimal("5.00")
    assert review.maximum == Decimal("5.00")

    approver = _principal(identity.user_a)
    approved = service.approve(
        approver, link.id, ApprovalRequest(confirm=True, note="checked")
    )
    assert approved.job_state == "COMPLETED"
    db_session.refresh(link)
    assert link.approved_total == Decimal("5.00")
    assert link.approved_by_subject == identity.user_a.subject

    with pytest.raises(AppError) as caught:
        service.approve(
            reviewer, link.id, ApprovalRequest(confirm=True, note="self-approval")
        )
    assert caught.value.code is ErrorCode.FORBIDDEN

    with pytest.raises(AppError) as caught:
        service.publish(
            reviewer,
            link.id,
            GradePublishRequest(confirm=True, reason="reviewer publication"),
        )
    assert caught.value.code is ErrorCode.FORBIDDEN


def test_an_incomplete_run_cannot_be_approved(
    db_session, identity, classroom_setup, paper
):
    settings = _settings()
    job = _completed_job(db_session, paper, state="REVIEW_REQUIRED")
    _coursework, link = _submission_link(db_session, classroom_setup, job)

    with pytest.raises(AppError) as caught:
        ClassroomGradeService(db_session, settings).approve(
            _principal(identity.user_a),
            link.id,
            ApprovalRequest(confirm=True),
        )
    assert caught.value.code is ErrorCode.CLASSROOM_GRADE_NOT_APPROVED


def test_an_uncertain_question_blocks_approval(
    db_session, identity, classroom_setup, paper
):
    settings = _settings()
    job = _completed_job(db_session, paper)
    db_session.add(
        QuestionResult(
            tenant_id=paper.assignment.tenant_id,
            job_id=job.id,
            question_id="2",
            max_marks=5,
            awarded_marks=0,
            status="REVIEW_REQUIRED",
            review_required=True,
        )
    )
    db_session.commit()
    _coursework, link = _submission_link(db_session, classroom_setup, job)

    review = ClassroomGradeService(db_session, settings).review(
        _principal(identity.reviewer), link.id
    )
    assert review.approvable is False
    assert review.uncertain[0]["question_id"] == "2"


def test_publishing_without_approval_is_refused(
    db_session, identity, classroom_setup, paper
):
    settings = _settings()
    job = _completed_job(db_session, paper)
    _coursework, link = _submission_link(db_session, classroom_setup, job)

    with pytest.raises(AppError) as caught:
        ClassroomGradeService(db_session, settings).publish(
            _principal(identity.user_a),
            link.id,
            GradePublishRequest(confirm=True, reason="publish now"),
        )
    assert caught.value.code is ErrorCode.CLASSROOM_GRADE_NOT_APPROVED


def test_publishing_writes_the_assigned_grade_and_is_idempotent(
    db_session, identity, classroom_setup, paper, monkeypatch
):
    settings = _settings()
    job = _completed_job(db_session, paper)
    _coursework, link = _submission_link(db_session, classroom_setup, job)
    service = ClassroomGradeService(db_session, settings)
    approver = _principal(identity.user_a)
    service.approve(approver, link.id, ApprovalRequest(confirm=True))

    writes: list[dict[str, object]] = []

    def fake_get(settings_, token, course_id, coursework_id, submission_id, *, transport=None):
        return SubmissionRecord(
            submission_id=submission_id,
            user_id="101",
            state="TURNED_IN",
            late=False,
            assigned_grade=None,
        )

    def fake_patch(
        settings_,
        token,
        course_id,
        coursework_id,
        submission_id,
        *,
        assigned_grade=None,
        draft_grade=None,
        transport=None,
    ):
        writes.append({"assigned": assigned_grade, "draft": draft_grade})
        return SubmissionRecord(
            submission_id=submission_id,
            user_id="101",
            state="RETURNED",
            late=False,
            assigned_grade=assigned_grade,
        )

    monkeypatch.setattr("app.services.classroom_grades.get_submission", fake_get)
    monkeypatch.setattr(
        "app.services.classroom_grades.patch_submission_grade", fake_patch
    )

    first = service.publish(
        approver, link.id, GradePublishRequest(confirm=True, reason="approved")
    )
    second = service.publish(
        approver, link.id, GradePublishRequest(confirm=True, reason="approved")
    )

    assert writes == [{"assigned": 5.0, "draft": None}]
    assert first.state == "SUCCEEDED"
    assert second.id == first.id
    count = db_session.scalar(
        select(func.count())
        .select_from(ClassroomGradePublication)
        .where(ClassroomGradePublication.submission_link_id == link.id)
    )
    assert count == 1


def test_a_foreign_assigned_grade_is_not_overwritten_without_permission(
    db_session, identity, classroom_setup, paper, monkeypatch
):
    settings = _settings()
    job = _completed_job(db_session, paper)
    _coursework, link = _submission_link(db_session, classroom_setup, job)
    service = ClassroomGradeService(db_session, settings)
    approver = _principal(identity.user_a)
    service.approve(approver, link.id, ApprovalRequest(confirm=True))

    monkeypatch.setattr(
        "app.services.classroom_grades.get_submission",
        lambda *args, **kwargs: SubmissionRecord(
            submission_id="gs-1",
            user_id="101",
            state="TURNED_IN",
            late=False,
            assigned_grade=9.0,
        ),
    )

    with pytest.raises(AppError) as caught:
        service.publish(
            approver, link.id, GradePublishRequest(confirm=True, reason="approved")
        )
    assert caught.value.code is ErrorCode.CLASSROOM_PUBLISH_CONFLICT

    written = db_session.scalar(
        select(ClassroomGradePublication.state).where(
            ClassroomGradePublication.submission_link_id == link.id
        )
    )
    assert written == "CONFLICT"


def test_a_withdrawn_submission_is_marked_not_deleted(
    db_session, identity, classroom_setup, monkeypatch
):
    settings = _settings()
    teacher = _principal(identity.user_a)

    monkeypatch.setattr(
        "app.services.classroom_roster.list_students",
        lambda *args, **kwargs: PersonListing(
            people=[
                ClassroomPerson(user_id="301", full_name="Ada", email=None)
            ],
            truncated=False,
        ),
    )
    ClassroomRosterService(db_session, settings).sync(teacher, COURSE_ID)

    coursework = ClassroomCourseworkLink(
        tenant_id=identity.tenant_a.id,
        assignment_id=classroom_setup.assignment.id,
        classroom_class_id=classroom_setup.classroom.id,
        course_id=COURSE_ID,
        coursework_id="work-9",
        state="PUBLISHED",
        title="Withdrawal test",
        publish_attempts=1,
    )
    db_session.add(coursework)
    db_session.commit()

    from app.schemas.classroom_integration import SubmissionSyncRequest

    monkeypatch.setattr(
        "app.services.classroom_submissions.list_submissions",
        lambda *args, **kwargs: SubmissionListing(
            submissions=[
                SubmissionRecord(
                    submission_id="gs-old",
                    user_id="301",
                    state="TURNED_IN",
                    late=False,
                    attachments=[],
                )
            ],
            truncated=False,
        ),
    )

    storage = _memory_storage()
    service = ClassroomSubmissionService(db_session, settings, storage)
    service.sync(teacher, SubmissionSyncRequest(coursework_link_id=coursework.id))
    link = db_session.scalar(
        select(ClassroomSubmissionLink).where(
            ClassroomSubmissionLink.tenant_id == identity.tenant_a.id
        )
    )
    assert link is not None
    assert link.state == "INGEST_FAILED"
    assert "no attachment" in (link.ingest_error or "").lower()


class _MemoryStorage:
    name = "memory"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str):
        from app.storage.base import StoredObject

        self.objects[key] = data
        return StoredObject(key=key, sha256="0" * 64, size_bytes=len(data))

    def read(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def _memory_storage() -> _MemoryStorage:
    return _MemoryStorage()
