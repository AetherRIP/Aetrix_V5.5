"""Unit checks for the Google Classroom integration surface.

No database and no network: the Google transport is a ``MockTransport`` and the
settings are constructed explicitly.  These tests cover the parts that decide
what Aetrix sends to Google, how it reads what comes back, and how it classifies
a failure, because a mistake there is either a wrong grade or a duplicate
coursework.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlparse

import httpx
import pytest
from app.core.config import (
    AuthSettings,
    ClassroomSettings,
    DatabaseSettings,
    Environment,
    SecuritySettings,
    Settings,
)
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal
from app.db.models import (
    ClassroomConnection,
    ClassroomCourseworkLink,
    ClassroomGradePublication,
    ClassroomRosterEntry,
    ClassroomSubmissionLink,
    ClassroomSyncRun,
)
from app.services.classroom_assignments import _due_parts
from app.services.classroom_google import (
    DRIVE_READONLY_SCOPE,
    REQUIRED_SCOPES,
    ClassroomUpstreamError,
    UpstreamKind,
    download_drive_file,
    exchange_code,
    get_account_identity,
    list_students,
    list_submissions,
    list_teachers,
    patch_submission_grade,
    return_submission,
)
from app.services.classroom_oauth import (
    issue_state,
    verify_state,
)
from cryptography.fernet import Fernet
from pydantic import SecretStr


def _classroom(**overrides: object) -> ClassroomSettings:
    return ClassroomSettings(
        client_id="client-id.apps.googleusercontent.com",
        client_secret=SecretStr("client-secret"),
        redirect_uri="http://127.0.0.1:3000/auth/classroom",
        retry_backoff_seconds=0.0,
        **overrides,
    )


def _settings() -> Settings:
    return Settings(
        env=Environment.TEST,
        database=DatabaseSettings(
            url=SecretStr("postgresql+psycopg://user:pass@127.0.0.1:5432/aetrix_test")
        ),
        auth=AuthSettings(jwt_secret=SecretStr("unit-test-secret")),
        security=SecuritySettings(
            encryption_key=SecretStr(Fernet.generate_key().decode())
        ),
        classroom=_classroom(),
    )


# -- roster -----------------------------------------------------------------


def test_students_are_read_across_pages_and_deduplicated() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params.get("pageToken") is None:
            return httpx.Response(
                200,
                json={
                    "students": [
                        {
                            "userId": "101",
                            "profile": {
                                "id": "101",
                                "name": {"fullName": "Ada Lovelace"},
                                "emailAddress": "ada@example.org",
                            },
                        }
                    ],
                    "nextPageToken": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={
                "students": [
                    {
                        "userId": "101",
                        "profile": {"id": "101", "name": {"fullName": "Ada Lovelace"}},
                    },
                    {
                        "userId": "102",
                        "profile": {
                            "id": "102",
                            "name": {"fullName": "Grace Hopper"},
                        },
                    },
                ]
            },
        )

    listing = list_students(
        _classroom(), "token", "course-1", transport=httpx.MockTransport(handler)
    )

    assert [person.user_id for person in listing.people] == ["101", "102"]
    assert listing.people[1].full_name == "Grace Hopper"
    assert listing.people[0].email == "ada@example.org"
    assert listing.truncated is False
    assert len(calls) == 2
    assert calls[0].url.path.endswith("/courses/course-1/students")
    assert calls[0].headers["authorization"] == "Bearer token"
    assert calls[1].url.params.get("pageToken") == "page-2"


def test_student_ceiling_reports_truncation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "students": [
                    {"userId": "1", "profile": {"id": "1"}},
                    {"userId": "2", "profile": {"id": "2"}},
                ]
            },
        )

    listing = list_students(
        _classroom(max_roster_students=1),
        "token",
        "course-1",
        transport=httpx.MockTransport(handler),
    )

    assert len(listing.people) == 1
    assert listing.truncated is True


def test_teachers_are_read_from_the_teachers_segment() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "teachers": [
                    {
                        "userId": "9",
                        "profile": {
                            "id": "9",
                            "name": {"fullName": "Central Account"},
                            "emailAddress": "central@example.org",
                        },
                    }
                ]
            },
        )

    listing = list_teachers(
        _classroom(), "token", "course-1", transport=httpx.MockTransport(handler)
    )

    assert listing.people[0].email == "central@example.org"
    assert seen[0].endswith("/courses/course-1/teachers")


# -- submissions ------------------------------------------------------------


def test_submissions_parse_attachments_and_paginate() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params.get("pageToken") is None:
            return httpx.Response(
                200,
                json={
                    "studentSubmissions": [
                        {
                            "id": "s-1",
                            "userId": "101",
                            "state": "TURNED_IN",
                            "late": True,
                            "draftGrade": 3.5,
                            "assignmentSubmission": {
                                "attachments": [
                                    {
                                        "driveFile": {
                                            "id": "file-1",
                                            "title": "answers.pdf",
                                            "alternateLink": "https://drive.google.com/file/d/file-1/view",
                                        }
                                    },
                                    {"youTubeVideo": {"id": "v1"}},
                                ]
                            },
                        }
                    ],
                    "nextPageToken": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={
                "studentSubmissions": [
                    {
                        "id": "s-2",
                        "userId": "102",
                        "state": "TURNED_IN",
                        "assignmentSubmission": {
                            "attachments": [
                                {"link": {"url": "https://example.org/x"}}
                            ]
                        },
                    }
                ]
            },
        )

    listing = list_submissions(
        _classroom(),
        "token",
        "course-1",
        "work-1",
        states=("TURNED_IN",),
        transport=httpx.MockTransport(handler),
    )

    assert [item.submission_id for item in listing.submissions] == ["s-1", "s-2"]
    first = listing.submissions[0]
    assert first.late is True
    assert first.draft_grade == 3.5
    assert first.assigned_grade is None
    assert first.attachments[0].kind == "DRIVE_FILE"
    assert first.attachments[0].drive_file_id == "file-1"
    assert first.attachments[0].title == "answers.pdf"
    # Google's DriveFile carries no mime type; the download's Content-Type decides.
    assert first.attachments[0].mime_type is None
    assert first.attachments[1].kind == "YOUTUBE_VIDEO"
    assert listing.submissions[1].attachments[0].kind == "LINK"
    assert listing.truncated is False
    assert calls[0].url.path.endswith("/courseWork/work-1/studentSubmissions")
    assert calls[0].url.params.get_list("states") == ["TURNED_IN"]


def test_submission_without_a_user_is_a_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"studentSubmissions": [{"id": "s-1"}]})

    with pytest.raises(ClassroomUpstreamError) as caught:
        list_submissions(
            _classroom(),
            "token",
            "course-1",
            "work-1",
            transport=httpx.MockTransport(handler),
        )

    assert caught.value.kind == UpstreamKind.TRANSIENT


# -- grades -----------------------------------------------------------------


def test_final_grade_patch_sends_only_the_assigned_grade_mask() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["mask"] = request.url.params.get("updateMask")
        captured["body"] = json.loads(request.content or b"{}")
        return httpx.Response(
            200,
            json={"id": "s-1", "userId": "101", "state": "RETURNED", "assignedGrade": 7.5},
        )

    record = patch_submission_grade(
        _classroom(),
        "token",
        "course-1",
        "work-1",
        "s-1",
        assigned_grade=7.5,
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "PATCH"
    assert str(captured["path"]).endswith(
        "/courses/course-1/courseWork/work-1/studentSubmissions/s-1"
    )
    assert captured["mask"] == "assignedGrade"
    assert captured["body"] == {"assignedGrade": 7.5}
    assert record.assigned_grade == 7.5


def test_draft_grade_patch_is_a_separate_field() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["mask"] = request.url.params.get("updateMask")
        captured["body"] = json.loads(request.content or b"{}")
        return httpx.Response(200, json={"id": "s-1", "userId": "101"})

    patch_submission_grade(
        _classroom(),
        "token",
        "course-1",
        "work-1",
        "s-1",
        draft_grade=4.0,
        transport=httpx.MockTransport(handler),
    )

    assert captured["mask"] == "draftGrade"
    assert captured["body"] == {"draftGrade": 4.0}


def test_patch_without_a_grade_is_refused_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be made")

    with pytest.raises(ClassroomUpstreamError) as caught:
        patch_submission_grade(
            _classroom(),
            "token",
            "course-1",
            "work-1",
            "s-1",
            transport=httpx.MockTransport(handler),
        )

    assert caught.value.kind == UpstreamKind.PERMANENT


def test_returning_work_uses_the_return_action() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(200, json={"id": "s-1", "userId": "101", "state": "RETURNED"})

    record = return_submission(
        _classroom(),
        "token",
        "course-1",
        "work-1",
        "s-1",
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "POST"
    assert captured["path"].endswith("/studentSubmissions/s-1:return")
    assert record.state == "RETURNED"


# -- failure classification and retry --------------------------------------


def test_a_permanent_refusal_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            403,
            json={"error": {"code": 403, "message": "The caller does not have permission"}},
        )

    with pytest.raises(ClassroomUpstreamError) as caught:
        list_students(
            _classroom(), "token", "course-1", transport=httpx.MockTransport(handler)
        )

    assert caught.value.kind == UpstreamKind.PERMANENT
    assert len(calls) == 1


def test_a_rate_limit_is_retried_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {}})
        return httpx.Response(
            200, json={"students": [{"userId": "1", "profile": {"id": "1"}}]}
        )

    listing = list_students(
        _classroom(), "token", "course-1", transport=httpx.MockTransport(handler)
    )

    assert len(calls) == 2
    assert listing.people[0].user_id == "1"


def test_exhausted_server_errors_are_transient_not_permanent() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": {"message": "backend error"}})

    with pytest.raises(ClassroomUpstreamError) as caught:
        list_teachers(
            _classroom(request_attempts=2),
            "token",
            "course-1",
            transport=httpx.MockTransport(handler),
        )

    assert caught.value.kind == UpstreamKind.TRANSIENT
    assert len(calls) == 2


# -- attachments ------------------------------------------------------------


def test_attachment_over_the_ceiling_is_refused_from_content_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "2048", "Content-Type": "application/pdf"},
            content=b"x" * 2048,
        )

    with pytest.raises(ClassroomUpstreamError) as caught:
        download_drive_file(
            _classroom(),
            "token",
            "file-1",
            max_bytes=1024,
            transport=httpx.MockTransport(handler),
        )

    assert caught.value.status_code == 413


def test_attachment_within_the_ceiling_is_returned_with_its_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("alt") == "media"
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf; charset=binary"},
            content=b"%PDF-1.4",
        )

    data, content_type = download_drive_file(
        _classroom(), "token", "file-1", transport=httpx.MockTransport(handler)
    )

    assert data == b"%PDF-1.4"
    assert content_type == "application/pdf"


def test_drive_scope_is_requested_for_attachments() -> None:
    assert DRIVE_READONLY_SCOPE in REQUIRED_SCOPES


# -- identity ---------------------------------------------------------------


def test_account_identity_is_read_from_userinfo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"email": "central@example.org", "name": "Central Account"}
        )

    email, name = get_account_identity(
        _classroom(), "token", transport=httpx.MockTransport(handler)
    )

    assert (email, name) == ("central@example.org", "Central Account")


def test_a_failed_identity_read_does_not_fail_authorisation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    assert get_account_identity(
        _classroom(), "token", transport=httpx.MockTransport(handler)
    ) == (None, None)


# -- due dates --------------------------------------------------------------


def test_due_date_is_expressed_in_the_course_time_zone() -> None:
    moment = datetime(2026, 5, 1, 22, 30, tzinfo=UTC)

    date, time = _due_parts(moment, "Asia/Tokyo")

    assert date == {"year": 2026, "month": 5, "day": 2}
    assert time == {"hours": 7, "minutes": 30}


def test_an_unknown_course_time_zone_falls_back_to_utc() -> None:
    moment = datetime(2026, 5, 1, 22, 30, tzinfo=UTC)

    date, time = _due_parts(moment, "Mars/Olympus_Mons")

    assert date == {"year": 2026, "month": 5, "day": 1}
    assert time == {"hours": 22, "minutes": 30}


# -- state binding ----------------------------------------------------------


def _principal(*, role: str = "OWNER", platform_role: str = "ADMIN") -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        subject="operator",
        role=role,
        platform_role=platform_role,
    )


def test_state_is_bound_to_the_platform_authority_that_issued_it() -> None:
    settings = _settings()
    principal = _principal()
    state, _expires_at = issue_state(settings, principal)
    verify_state(settings, state, principal)

    downgraded = Principal(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        subject=principal.subject,
        role="TEACHER",
        platform_role="",
    )
    with pytest.raises(AppError) as caught:
        verify_state(settings, state, downgraded)
    assert caught.value.code is ErrorCode.VALIDATION_ERROR


def test_authorization_url_is_never_built_from_a_request_host() -> None:
    settings = _settings()
    from app.services.classroom_google import authorization_url

    url = authorization_url(settings.classroom, "state")
    params = dict(parse_qsl(urlparse(url).query))
    assert params["redirect_uri"] == settings.classroom.redirect_uri


# -- schema shape -----------------------------------------------------------


def test_the_new_tables_carry_their_workspace_and_identity_constraints() -> None:
    assert ClassroomRosterEntry.__table__.c.tenant_id.nullable is False
    assert ClassroomSubmissionLink.__table__.c.tenant_id.nullable is False
    assert ClassroomGradePublication.__table__.c.tenant_id.nullable is False
    assert ClassroomCourseworkLink.__table__.c.tenant_id.nullable is False
    # Platform-wide course discovery has no workspace.
    assert ClassroomSyncRun.__table__.c.tenant_id.nullable is True
    # The central connection is not tenant-scoped.
    assert ClassroomConnection.__table__.c.tenant_id.nullable is True
    assert "connection_key" in ClassroomConnection.__table__.c

    unique_names = {
        constraint.name for constraint in ClassroomRosterEntry.__table__.constraints
    }
    assert "uq_roster_entry_google" in unique_names
    submission_uniques = {
        constraint.name for constraint in ClassroomSubmissionLink.__table__.constraints
    }
    assert "uq_submission_link_google" in submission_uniques


def test_no_classroom_contract_exposes_a_token() -> None:
    from app.schemas import classroom_integration, classroom_oauth

    for module in (classroom_integration, classroom_oauth):
        for name in dir(module):
            model = getattr(module, name)
            fields = getattr(model, "model_fields", None)
            if not isinstance(fields, dict):
                continue
            for field in fields:
                lowered = field.lower()
                assert "token" not in lowered, f"{name}.{field} looks like a credential"
                assert "secret" not in lowered, f"{name}.{field} looks like a secret"


def test_exchange_code_still_sends_the_secret_in_the_body() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "a", "expires_in": 60})

    exchange_code(
        _classroom(), "code-1", transport=httpx.MockTransport(handler)
    )

    assert "client_secret=client-secret" in captured["body"]
