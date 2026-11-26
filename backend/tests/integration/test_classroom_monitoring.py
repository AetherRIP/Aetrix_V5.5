"""Automatic Classroom submission monitoring against PostgreSQL.

Google is never called: the listing and download functions are replaced with
deterministic results, and no marking provider is configured, so a queued job
stops before any paid request.  What these tests prove is the part that matters:
detection, idempotency, versioning, eligibility and permission boundaries.
"""

from __future__ import annotations

from datetime import timedelta

import pymupdf
import pytest
from app.classroom_monitoring import monitor as monitor_module
from app.classroom_monitoring import pipeline as pipeline_module
from app.classroom_monitoring.monitor import ClassroomMonitorService
from app.classroom_monitoring.schemas import MonitorIgnoreRequest, MonitorToggleRequest
from app.core.config import ClassroomSettings, Settings, StorageSettings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import utcnow
from app.core.security import Principal, SecretBox
from app.db.models import (
    ClassroomAllocation,
    ClassroomClass,
    ClassroomClassAssignment,
    ClassroomConnection,
    ClassroomCourseworkLink,
    ClassroomMonitorConfig,
    ClassroomMonitorRun,
    ClassroomRosterEntry,
    ClassroomSubmissionLink,
    ClassroomSubmissionVersion,
    CorrectionJob,
    Student,
)
from app.services.classroom_google import (
    REQUIRED_SCOPES,
    Attachment,
    ClassroomUpstreamError,
    SubmissionListing,
    SubmissionRecord,
    UpstreamKind,
)
from app.services.classroom_oauth import PLATFORM_CONNECTION_KEY
from app.storage import LocalStorage
from pydantic import SecretStr
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

COURSE_ID = "600100"
OTHER_COURSE_ID = "600200"


def _pdf(text: str = "Question 1 answer x = 4", pages: int = 1) -> bytes:
    document = pymupdf.open()
    for page_index in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 120), text, fontsize=14)
        for line in range(20):
            page.insert_text(
                (72, 170 + line * 24),
                f"Working {page_index + 1}.{line}: 3x + 2 = 14, so x = 4.",
                fontsize=12,
            )
    data = document.tobytes()
    document.close()
    return data


def _record(
    *,
    submission_id: str = "sub-1",
    user_id: str = "google-1",
    state: str = "TURNED_IN",
    update_time: str = "2026-11-26T09:00:00Z",
    attachments: list[Attachment] | None = None,
) -> SubmissionRecord:
    return SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        state=state,
        late=False,
        attachments=attachments
        if attachments is not None
        else [
            Attachment(
                kind="DRIVE_FILE",
                title="script.pdf",
                drive_file_id="file-1",
                mime_type="application/pdf",
            )
        ],
        update_time=update_time,
    )


def _settings(tmp_path) -> Settings:
    return get_settings().model_copy(
        update={
            "classroom": ClassroomSettings(
                client_id="client-id.apps.googleusercontent.com",
                client_secret=SecretStr("client-secret"),
                redirect_uri="http://127.0.0.1:3000/auth/classroom",
                retry_backoff_seconds=0.0,
                monitoring_enabled=True,
            ),
            "storage": StorageSettings(root=tmp_path / "documents"),
        }
    )


def _principal(user, *, role: str | None = None) -> Principal:
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        subject=user.subject,
        role=role or user.role,
    )


class FakeOAuth:
    transport = None

    def __init__(self, error: AppError | None = None) -> None:
        self.error = error

    def access_token(self) -> str:
        if self.error is not None:
            raise self.error
        return "access-token-value"


class FakeGoogle:
    def __init__(self, records: list[SubmissionRecord] | None = None) -> None:
        self.records = records or []
        self.list_calls = 0
        self.downloads: list[str] = []
        self.download_error: Exception | None = None
        self.files: dict[str, bytes] = {"file-1": _pdf(), "file-2": _pdf("Second attempt")}

    def list_submissions(self, *args, **kwargs) -> SubmissionListing:
        self.list_calls += 1
        return SubmissionListing(submissions=list(self.records), truncated=False)

    def download(self, settings, access_token, file_id, **kwargs):
        if self.download_error is not None:
            raise self.download_error
        self.downloads.append(file_id)
        return self.files[file_id], "application/pdf"

    def export(self, settings, access_token, file_id, **kwargs):
        self.downloads.append(file_id)
        return _pdf(), "application/pdf"


@pytest.fixture
def monitoring(db_session, identity, paper, tmp_path, monkeypatch):
    """A published coursework, a roster, a connected account and fakes."""

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
    other_classroom = ClassroomClass(
        course_id=OTHER_COURSE_ID,
        name="Year 11 Geometry",
        section="B",
        course_state="ACTIVE",
        verification="VERIFIED",
        source="google_classroom",
        synced_at=utcnow(),
        created_by_subject="operator",
    )
    db_session.add_all([classroom, other_classroom])
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
    other_allocation = ClassroomAllocation(
        classroom_class_id=other_classroom.id,
        workspace_id=identity.tenant_a.id,
        course_id=OTHER_COURSE_ID,
        class_name="Year 11 Geometry",
        workspace_name="Alpha",
        status="ACTIVE",
        origin="ALLOCATE",
        allocated_by_subject="operator",
        allocated_at=utcnow(),
    )
    db_session.add_all([allocation, other_allocation])
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
    student = Student(
        tenant_id=identity.tenant_a.id, student_ref="STU-1", display_name="Student One"
    )
    db_session.add(student)
    db_session.flush()
    entry = ClassroomRosterEntry(
        tenant_id=identity.tenant_a.id,
        course_id=COURSE_ID,
        google_user_id="google-1",
        student_id=student.id,
        full_name="Student One",
        status="ACTIVE",
        match_source="CREATED",
        last_seen_at=utcnow(),
    )
    link = ClassroomCourseworkLink(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        classroom_class_id=classroom.id,
        course_id=COURSE_ID,
        coursework_id="700100",
        state="PUBLISHED",
        title="Fixture assignment",
        published_at=utcnow(),
        published_by_subject="teacher-a",
    )
    db_session.add_all([connection, entry, link])
    db_session.commit()

    settings = _settings(tmp_path)
    storage = LocalStorage(tmp_path / "documents")
    google = FakeGoogle([_record()])
    monkeypatch.setattr(monitor_module, "list_submissions", google.list_submissions)
    monkeypatch.setattr(pipeline_module, "download_drive_file", google.download)
    monkeypatch.setattr(pipeline_module, "export_drive_file", google.export)

    def build(oauth: FakeOAuth | None = None) -> ClassroomMonitorService:
        return ClassroomMonitorService(
            db_session, settings, storage, oauth=oauth or FakeOAuth()
        )

    class Context:
        pass

    context = Context()
    context.classroom = classroom
    context.allocation = allocation
    context.other_allocation = other_allocation
    context.student = student
    context.entry = entry
    context.link = link
    context.assignment = paper.assignment
    context.settings = settings
    context.storage = storage
    context.google = google
    context.build = build
    context.session = db_session
    return context


def _versions(db_session, coursework_link_id) -> list[ClassroomSubmissionVersion]:
    return list(
        db_session.scalars(
            select(ClassroomSubmissionVersion)
            .join(
                ClassroomSubmissionLink,
                ClassroomSubmissionVersion.submission_link_id
                == ClassroomSubmissionLink.id,
            )
            .where(ClassroomSubmissionLink.coursework_link_id == coursework_link_id)
            .order_by(ClassroomSubmissionVersion.version.asc())
        )
    )


def _jobs(db_session) -> int:
    return db_session.scalar(select(func.count(CorrectionJob.id))) or 0


def test_a_turned_in_script_is_detected_inspected_and_queued(
    monitoring, identity
):
    service = monitoring.build()
    owner = _principal(identity.user_a)
    service.update(owner, monitoring.link.id, MonitorToggleRequest(enabled=True))

    result = service.manual_sync(owner, monitoring.link.id)

    assert result.status == "SUCCEEDED"
    assert result.counts["created"] == 1
    versions = _versions(monitoring.session, monitoring.link.id)
    assert len(versions) == 1
    version = versions[0]
    assert version.state == "READY", version.decision_reasons
    assert version.eligibility == "ELIGIBLE"
    assert version.correction_state == "QUEUED"
    assert version.document_id is not None
    assert version.correction_job_id is not None
    assert version.relevance == "LIKELY_RELEVANT"
    assert _jobs(monitoring.session) == 1
    link = monitoring.session.get(ClassroomSubmissionLink, version.submission_link_id)
    assert link.state == "CORRECTING"


def test_repeated_polls_do_not_download_or_queue_again(monitoring, identity):
    service = monitoring.build()
    owner = _principal(identity.user_a)
    service.update(owner, monitoring.link.id, MonitorToggleRequest(enabled=True))

    service.manual_sync(owner, monitoring.link.id)
    service.manual_sync(owner, monitoring.link.id)

    assert monitoring.google.downloads == ["file-1"]
    assert len(_versions(monitoring.session, monitoring.link.id)) == 1
    assert _jobs(monitoring.session) == 1


def test_a_draft_submission_never_enters_the_pipeline(monitoring, identity):
    monitoring.google.records = [_record(state="CREATED", attachments=[])]
    service = monitoring.build()

    result = service.manual_sync(_principal(identity.user_a), monitoring.link.id)

    assert result.counts["not_turned_in"] == 1
    assert _versions(monitoring.session, monitoring.link.id) == []
    assert monitoring.google.downloads == []


def test_an_external_link_is_recorded_and_not_fetched(monitoring, identity):
    monitoring.google.records = [
        _record(
            attachments=[
                Attachment(kind="LINK", title="https://example.org/answers")
            ]
        )
    ]
    service = monitoring.build()

    result = service.manual_sync(_principal(identity.user_a), monitoring.link.id)

    assert result.counts["ignored"] == 1
    version = _versions(monitoring.session, monitoring.link.id)[0]
    assert version.state == "IGNORED"
    assert version.eligibility == "BLOCKED"
    assert monitoring.google.downloads == []


def test_an_unsupported_attachment_requires_a_teacher(monitoring, identity):
    monitoring.google.records = [
        _record(
            attachments=[
                Attachment(
                    kind="DRIVE_FILE",
                    title="work.docx",
                    drive_file_id="file-1",
                    mime_type="application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document",
                )
            ]
        )
    ]
    service = monitoring.build()

    service.manual_sync(_principal(identity.user_a), monitoring.link.id)

    version = _versions(monitoring.session, monitoring.link.id)[0]
    assert version.state == "NEEDS_TEACHER"
    assert version.eligibility == "BLOCKED"
    assert _jobs(monitoring.session) == 0


def test_a_corrupt_pdf_is_blocked_before_correction(monitoring, identity):
    monitoring.google.files["file-1"] = b"%PDF-1.7 broken body"
    service = monitoring.build()

    service.manual_sync(_principal(identity.user_a), monitoring.link.id)

    version = _versions(monitoring.session, monitoring.link.id)[0]
    assert version.state == "NEEDS_TEACHER"
    assert version.eligibility == "BLOCKED"
    assert _jobs(monitoring.session) == 0


def test_a_missing_scheme_blocks_queueing(monitoring, identity):
    monitoring.assignment.scheme_version_id = None
    monitoring.session.commit()
    service = monitoring.build()

    service.manual_sync(_principal(identity.user_a), monitoring.link.id)

    version = _versions(monitoring.session, monitoring.link.id)[0]
    assert version.state == "NEEDS_TEACHER"
    assert version.correction_state == "NOT_QUEUED"
    assert _jobs(monitoring.session) == 0


def test_a_resubmission_is_a_new_version_without_destroying_history(
    monitoring, identity
):
    service = monitoring.build()
    owner = _principal(identity.user_a)
    service.update(owner, monitoring.link.id, MonitorToggleRequest(enabled=True))
    service.manual_sync(owner, monitoring.link.id)

    monitoring.google.records = [
        _record(
            update_time="2026-11-26T10:00:00Z",
            attachments=[
                Attachment(
                    kind="DRIVE_FILE",
                    title="second.pdf",
                    drive_file_id="file-2",
                    mime_type="application/pdf",
                )
            ],
        )
    ]
    service.manual_sync(owner, monitoring.link.id)

    versions = _versions(monitoring.session, monitoring.link.id)
    assert [version.version for version in versions] == [1, 2]
    assert versions[0].state == "SUPERSEDED"
    assert versions[0].superseded_at is not None
    assert versions[0].correction_job_id is not None
    assert versions[1].state == "READY"
    assert versions[1].correction_job_id != versions[0].correction_job_id
    assert _jobs(monitoring.session) == 2


def test_identical_work_from_two_students_is_flagged_not_merged(
    monitoring, identity, db_session
):
    second = Student(
        tenant_id=identity.tenant_a.id, student_ref="STU-2", display_name="Student Two"
    )
    db_session.add(second)
    db_session.flush()
    db_session.add(
        ClassroomRosterEntry(
            tenant_id=identity.tenant_a.id,
            course_id=COURSE_ID,
            google_user_id="google-2",
            student_id=second.id,
            status="ACTIVE",
            match_source="CREATED",
            last_seen_at=utcnow(),
        )
    )
    db_session.commit()
    monitoring.google.records = [
        _record(submission_id="sub-1", user_id="google-1"),
        _record(submission_id="sub-2", user_id="google-2"),
    ]
    service = monitoring.build()
    owner = _principal(identity.user_a)
    service.update(owner, monitoring.link.id, MonitorToggleRequest(enabled=True))

    service.manual_sync(owner, monitoring.link.id)

    versions = monitoring.session.scalars(
        select(ClassroomSubmissionVersion).order_by(
            ClassroomSubmissionVersion.version.asc()
        )
    ).all()
    assert len(versions) == 2
    codes = {
        reason.get("code")
        for version in versions
        for reason in (version.decision_reasons or [])
    }
    assert "POSSIBLE_SHARED_FILE" in codes
    assert _jobs(monitoring.session) == 2


def test_a_withdrawn_submission_supersedes_the_current_version(
    monitoring, identity
):
    service = monitoring.build()
    owner = _principal(identity.user_a)
    service.update(owner, monitoring.link.id, MonitorToggleRequest(enabled=True))
    service.manual_sync(owner, monitoring.link.id)

    monitoring.google.records = [_record(state="RECLAIMED_BY_STUDENT")]
    service.manual_sync(owner, monitoring.link.id)

    version = _versions(monitoring.session, monitoring.link.id)[0]
    assert version.state == "SUPERSEDED"
    link = monitoring.session.get(ClassroomSubmissionLink, version.submission_link_id)
    assert link.state == "WITHDRAWN"


def test_a_submission_missed_while_offline_is_recovered(monitoring, identity):
    service = monitoring.build()
    owner = _principal(identity.user_a)
    service.update(owner, monitoring.link.id, MonitorToggleRequest(enabled=True))
    monitoring.google.records = []
    service.manual_sync(owner, monitoring.link.id)
    assert _versions(monitoring.session, monitoring.link.id) == []

    monitoring.google.records = [_record()]
    service.manual_sync(owner, monitoring.link.id)

    versions = _versions(monitoring.session, monitoring.link.id)
    assert len(versions) == 1
    assert versions[0].state == "READY"


def test_a_rate_limit_backs_the_assignment_off(monitoring, identity):
    def limited(*args, **kwargs):
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google rate limited the request.", status_code=429
        )

    monitor_module.list_submissions = limited
    service = monitoring.build()

    with pytest.raises(AppError) as caught:
        service.manual_sync(_principal(identity.user_a), monitoring.link.id)
    assert caught.value.code is ErrorCode.CLASSROOM_UPSTREAM_ERROR

    config = monitoring.session.scalar(
        select(ClassroomMonitorConfig).where(
            ClassroomMonitorConfig.coursework_link_id == monitoring.link.id
        )
    )
    assert config is not None
    assert config.consecutive_failures == 1
    assert config.backoff_until is not None
    assert config.next_poll_at is not None
    assert config.next_poll_at > utcnow()
    runs = monitoring.session.scalars(select(ClassroomMonitorRun)).all()
    assert runs[-1].status == "FAILED"


def test_expired_credentials_stop_polling_without_marking_anything(
    monitoring, identity
):
    service = monitoring.build(
        oauth=FakeOAuth(AppError(ErrorCode.CLASSROOM_RECONNECT_REQUIRED, "expired"))
    )
    service.update(
        _principal(identity.user_a),
        monitoring.link.id,
        MonitorToggleRequest(enabled=True),
    )
    counts = service.cycle()

    assert counts["failed"] == 1
    config = monitoring.session.scalar(
        select(ClassroomMonitorConfig).where(
            ClassroomMonitorConfig.coursework_link_id == monitoring.link.id
        )
    )
    if config is not None:
        assert config.consecutive_failures == 1
    assert monitoring.google.downloads == []


def test_a_teacher_cannot_monitor_an_unallocated_class(monitoring, identity):
    service = monitoring.build()
    # A TEACHER has to be explicitly assigned to a class.
    from app.db.models import User

    teacher = User(
        tenant_id=identity.tenant_a.id, subject="teacher-assigned-elsewhere", role="TEACHER"
    )
    monitoring.session.add(teacher)
    monitoring.session.flush()
    monitoring.session.add(
        ClassroomClassAssignment(
            allocation_id=monitoring.other_allocation.id,
            workspace_id=identity.tenant_a.id,
            user_id=teacher.id,
            assigned_by_user_id=identity.user_a.id,
            assigned_at=utcnow(),
        )
    )
    monitoring.session.commit()

    with pytest.raises(AppError) as caught:
        service.read_state(_principal(teacher), monitoring.link.id)
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_an_assistant_on_the_class_can_read_but_not_configure(monitoring, identity):
    from app.db.models import User

    assistant = User(
        tenant_id=identity.tenant_a.id, subject="assistant-a", role="REVIEWER"
    )
    monitoring.session.add(assistant)
    monitoring.session.flush()
    monitoring.session.add(
        ClassroomClassAssignment(
            allocation_id=monitoring.allocation.id,
            workspace_id=identity.tenant_a.id,
            user_id=assistant.id,
            assigned_by_user_id=identity.user_a.id,
            assigned_at=utcnow(),
        )
    )
    monitoring.session.commit()
    service = monitoring.build()
    principal = _principal(assistant)

    state = service.read_state(principal, monitoring.link.id)
    assert state.coursework_link_id == monitoring.link.id
    with pytest.raises(AppError) as caught:
        service.update(principal, monitoring.link.id, MonitorToggleRequest(enabled=True))
    assert caught.value.code is ErrorCode.FORBIDDEN


def test_another_workspace_cannot_see_the_monitored_class(monitoring, identity):
    service = monitoring.build()
    outsider = _principal(identity.user_b)

    with pytest.raises(AppError) as caught:
        service.read_state(outsider, monitoring.link.id)
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_ignoring_a_submission_is_audited_and_keeps_the_record(
    monitoring, identity, db_session
):
    service = monitoring.build()
    owner = _principal(identity.user_a)
    # Automatic queueing is off, so the work is inspected but not yet marked;
    # that is the state in which a teacher may ignore it.
    service.update(
        owner,
        monitoring.link.id,
        MonitorToggleRequest(enabled=True, auto_queue=False),
    )
    service.manual_sync(owner, monitoring.link.id)
    version = _versions(db_session, monitoring.link.id)[0]
    assert version.state == "READY"
    assert version.correction_state == "NOT_QUEUED"

    read = service.ignore(
        owner, version.submission_link_id, MonitorIgnoreRequest(note="Not this task")
    )

    assert read.state == "IGNORED"
    assert read.resolution_note == "Not this task"
    assert _jobs(db_session) == 0


def test_monitoring_configuration_is_off_until_enabled(monitoring, identity):
    service = monitoring.build()
    owner = _principal(identity.user_a)

    state = service.read_state(owner, monitoring.link.id)
    assert state.enabled is False
    assert state.health == "DISABLED"

    state = service.update(owner, monitoring.link.id, MonitorToggleRequest(enabled=True))
    assert state.enabled is True
    assert state.health == "UNKNOWN"
    assert state.monitoring_since is not None
    assert state.interval_seconds >= 60


def test_a_second_workspace_never_sees_the_same_google_submission(
    monitoring, identity, db_session
):
    service = monitoring.build()
    service.manual_sync(_principal(identity.user_a), monitoring.link.id)
    link = db_session.scalar(select(ClassroomSubmissionLink))
    assert link is not None
    # The unique key is (tenant, google_submission_id); a foreign workspace's
    # read is scoped by its own tenant and finds nothing.
    outsider_rows = db_session.scalars(
        select(ClassroomSubmissionLink).where(
            ClassroomSubmissionLink.tenant_id == identity.tenant_b.id,
            ClassroomSubmissionLink.google_submission_id == link.google_submission_id,
        )
    ).all()
    assert outsider_rows == []


def test_the_monitoring_routes_are_workspace_scoped(
    client, auth_headers, monitoring, identity
):
    """The HTTP boundary, not just the service, enforces the tenant."""

    response = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/classroom/monitoring",
        headers=auth_headers(identity.user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert [row["coursework_link_id"] for row in body["states"]] == [
        str(monitoring.link.id)
    ]
    # The deployment default: the worker thread is off until an operator asks
    # for it, and the response says so instead of implying it is running.
    assert body["monitoring_enabled_on_server"] is False

    outsider = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/classroom/monitoring",
        headers=auth_headers(identity.user_b),
    )
    # A workspace the caller does not own is reported as absent, not forbidden.
    assert outsider.status_code == 404

    denied = client.patch(
        f"/api/v1/workspaces/{identity.tenant_a.id}/classroom/coursework/"
        f"{monitoring.link.id}/monitoring",
        json={"enabled": True},
        headers=auth_headers(identity.user_b),
    )
    assert denied.status_code == 404
