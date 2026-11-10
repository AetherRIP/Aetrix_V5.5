"""Unit checks for the Google Classroom OAuth client and state binding.

These tests never open a database or reach Google: the transport is mocked and
the settings are constructed explicitly, so they can run on a machine with no
PostgreSQL.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
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
from app.core.ids import utcnow
from app.core.security import Principal, SecretBox
from app.services.classroom_google import (
    COURSES_SCOPE,
    ClassroomUpstreamError,
    UpstreamKind,
    authorization_url,
    exchange_code,
    list_courses,
    refresh_access_token,
    revoke_token,
)
from app.services.classroom_oauth import (
    ensure_classroom_manager,
    issue_state,
    verify_state,
)
from cryptography.fernet import Fernet
from pydantic import SecretStr


def _settings(**classroom_overrides: object) -> Settings:
    return Settings(
        env=Environment.TEST,
        database=DatabaseSettings(
            url=SecretStr("postgresql+psycopg://user:pass@127.0.0.1:5432/aetrix_test")
        ),
        auth=AuthSettings(jwt_secret=SecretStr("unit-test-secret")),
        security=SecuritySettings(encryption_key=SecretStr(Fernet.generate_key().decode())),
        classroom=ClassroomSettings(
            client_id="client-id.apps.googleusercontent.com",
            client_secret=SecretStr("client-secret"),
            redirect_uri="http://127.0.0.1:3000/auth/classroom",
            **classroom_overrides,
        ),
    )


def _principal(*, tenant_id: uuid.UUID | None = None, subject: str = "teacher-a") -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        subject=subject,
        role="OWNER",
    )


def test_authorization_url_requests_offline_course_scope_only() -> None:
    settings = _settings()

    url = authorization_url(settings.classroom, "opaque-state")
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query))

    assert parsed.netloc == "accounts.google.com"
    assert params["scope"] == COURSES_SCOPE
    assert params["response_type"] == "code"
    assert params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    assert params["include_granted_scopes"] == "true"
    assert params["state"] == "opaque-state"
    assert params["redirect_uri"] == settings.classroom.redirect_uri
    assert "client-secret" not in url


def test_exchange_code_sends_the_secret_in_the_body() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        assert request.url == httpx.URL("https://oauth2.googleapis.com/token")
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
                "scope": f"{COURSES_SCOPE} openid",
            },
        )

    settings = _settings()
    grant = exchange_code(
        settings.classroom, "code-1", transport=httpx.MockTransport(handler)
    )

    assert "grant_type=authorization_code" in captured["body"]
    assert "code=code-1" in captured["body"]
    assert "client_secret=client-secret" in captured["body"]
    assert grant.access_token == "access-1"
    assert grant.refresh_token == "refresh-1"
    assert grant.scopes == (COURSES_SCOPE, "openid")


def test_invalid_grant_requires_a_new_authorisation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "Bad Request"},
        )

    with pytest.raises(ClassroomUpstreamError) as caught:
        exchange_code(_settings().classroom, "spent", transport=httpx.MockTransport(handler))

    assert caught.value.kind == UpstreamKind.RECONNECT_REQUIRED
    assert "Bad Request" in caught.value.message


def test_rejected_client_is_a_configuration_error_not_a_revoked_grant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    with pytest.raises(ClassroomUpstreamError) as caught:
        exchange_code(_settings().classroom, "code", transport=httpx.MockTransport(handler))

    assert caught.value.kind == UpstreamKind.CONFIGURATION


def test_refresh_does_not_invent_a_scope_or_refresh_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "grant_type=refresh_token" in body
        return httpx.Response(200, json={"access_token": "access-2", "expires_in": 1800})

    grant = refresh_access_token(
        _settings().classroom, "refresh-1", transport=httpx.MockTransport(handler)
    )

    assert grant.access_token == "access-2"
    assert grant.refresh_token is None
    assert grant.scopes == ()


def test_course_listing_paginates_and_asks_for_the_teachers_active_courses() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params.get("pageToken") is None:
            return httpx.Response(
                200,
                json={
                    "courses": [
                        {"id": "c-1", "name": "Year 10 Algebra", "courseState": "ACTIVE"}
                    ],
                    "nextPageToken": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={
                "courses": [
                    {
                        "id": "c-2",
                        "name": "Year 11 Geometry",
                        "section": "B",
                        "courseState": "ACTIVE",
                    }
                ]
            },
        )

    listing = list_courses(
        _settings().classroom, "access-1", transport=httpx.MockTransport(handler)
    )

    assert [course.course_id for course in listing.courses] == ["c-1", "c-2"]
    assert listing.courses[1].section == "B"
    assert listing.truncated is False
    assert len(calls) == 2
    first = calls[0]
    assert first.headers["authorization"] == "Bearer access-1"
    assert first.url.params.get("teacherId") == "me"
    assert first.url.params.get_list("courseStates") == ["ACTIVE"]
    assert first.url.params.get("pageSize") == "100"
    assert calls[1].url.params.get("pageToken") == "page-2"


def test_course_ceiling_reports_truncation_instead_of_a_complete_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "courses": [
                    {"id": "c-1", "name": "One"},
                    {"id": "c-2", "name": "Two"},
                ]
            },
        )

    listing = list_courses(
        _settings(max_courses=1).classroom,
        "access-1",
        transport=httpx.MockTransport(handler),
    )

    assert len(listing.courses) == 1
    assert listing.truncated is True


def test_revoked_access_token_is_classified_for_reconnection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "code": 401,
                    "message": "Request had invalid authentication credentials.",
                    "status": "UNAUTHENTICATED",
                }
            },
        )

    with pytest.raises(ClassroomUpstreamError) as caught:
        list_courses(_settings().classroom, "expired", transport=httpx.MockTransport(handler))

    assert caught.value.kind == UpstreamKind.RECONNECT_REQUIRED


def test_missing_scope_is_distinguished_from_a_transient_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "message": "Request had insufficient authentication scopes.",
                    "status": "PERMISSION_DENIED",
                }
            },
        )

    with pytest.raises(ClassroomUpstreamError) as caught:
        list_courses(_settings().classroom, "token", transport=httpx.MockTransport(handler))

    assert caught.value.kind == UpstreamKind.SCOPE_MISSING


def test_server_failure_keeps_the_connection_eligible_for_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "backend error"}})

    with pytest.raises(ClassroomUpstreamError) as caught:
        list_courses(_settings().classroom, "token", transport=httpx.MockTransport(handler))

    assert caught.value.kind == UpstreamKind.TRANSIENT


def test_revocation_failure_is_reported_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route", request=request)

    assert (
        revoke_token(
            _settings().classroom, "token", transport=httpx.MockTransport(handler)
        )
        is False
    )


def test_state_is_opaque_and_bound_to_the_workspace_and_subject() -> None:
    settings = _settings()
    principal = _principal()

    state, expires_at = issue_state(settings, principal)

    assert principal.subject not in state
    assert str(principal.tenant_id) not in state
    verify_state(settings, state, principal)

    other_subject = _principal(tenant_id=principal.tenant_id, subject="teacher-b")
    with pytest.raises(AppError) as wrong_subject:
        verify_state(settings, state, other_subject)
    assert wrong_subject.value.code is ErrorCode.VALIDATION_ERROR

    other_tenant = _principal(tenant_id=uuid.uuid4(), subject=principal.subject)
    with pytest.raises(AppError):
        verify_state(settings, state, other_tenant)

    # The state itself is what carries the deadline; no server-side session is
    # needed for the callback to reject a stale authorisation.
    assert expires_at > utcnow()


def test_expired_state_is_refused() -> None:
    settings = _settings()
    principal = _principal()
    box = SecretBox(settings.security.encryption_key.get_secret_value())
    expired = json.dumps(
        {
            "v": 1,
            "tenant_id": str(principal.tenant_id),
            "subject": principal.subject,
            "nonce": "n",
            "expires_at": (utcnow() - timedelta(seconds=30)).isoformat(),
        }
    )

    with pytest.raises(AppError) as caught:
        verify_state(settings, box.encrypt(expired), principal)

    assert caught.value.code is ErrorCode.VALIDATION_ERROR


def test_state_cannot_be_issued_without_an_encryption_key() -> None:
    settings = Settings(
        env=Environment.TEST,
        database=DatabaseSettings(
            url=SecretStr("postgresql+psycopg://user:pass@127.0.0.1:5432/aetrix_test")
        ),
        auth=AuthSettings(jwt_secret=SecretStr("unit-test-secret")),
        security=SecuritySettings(encryption_key=None),
    )

    with pytest.raises(AppError) as caught:
        issue_state(settings, _principal())

    assert caught.value.code is ErrorCode.CLASSROOM_NOT_CONFIGURED


def test_only_workspace_managers_may_change_the_connection() -> None:
    owner = _principal()
    ensure_classroom_manager(owner)

    teacher = Principal(
        user_id=uuid.uuid4(),
        tenant_id=owner.tenant_id,
        subject="teacher-c",
        role="TEACHER",
    )
    with pytest.raises(AppError) as caught:
        ensure_classroom_manager(teacher)
    assert caught.value.code is ErrorCode.FORBIDDEN

    platform = Principal(
        user_id=uuid.uuid4(),
        tenant_id=owner.tenant_id,
        subject="operator",
        role="ADMIN",
        platform_role="ADMIN",
    )
    ensure_classroom_manager(platform)
