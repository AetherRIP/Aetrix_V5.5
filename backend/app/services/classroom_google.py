"""Google OAuth and Classroom course discovery.

This module talks to exactly three Google endpoints: the consent screen URL is
built here, the token endpoint exchanges and refreshes codes, and
``courses.list`` reads the courses a teacher owns.  No Google SDK is used:
``httpx`` is already a dependency and its transport can be injected so unit
tests never reach the network.

Failures are classified rather than flattened.  A revoked or rejected grant
must clear the workspace's stored tokens, while a timeout or a 500 must leave
the connection intact and be retried later.  The classifier also separates a
missing Classroom scope from a generic refusal so the interface can ask for
consent again instead of suggesting a transient outage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from ..core.config import ClassroomSettings

#: The only Google scope this integration requests.  It reads courses; it does
#: not read coursework, submissions or student names, and it writes nothing.
COURSES_SCOPE = "https://www.googleapis.com/auth/classroom.courses.readonly"

PAGE_SIZE = 100
MAX_PAGES = 100


class UpstreamKind:
    """How a Google failure affects the workspace's stored authorisation."""

    #: Google rejected the grant: the tokens must be discarded.
    RECONNECT_REQUIRED = "RECONNECT_REQUIRED"
    #: The grant exists but lacks the Classroom scope: consent again.
    SCOPE_MISSING = "SCOPE_MISSING"
    #: The configured OAuth client itself was refused.
    CONFIGURATION = "CONFIGURATION"
    #: Timeouts, 5xx, 429 and malformed responses: keep the connection.
    TRANSIENT = "TRANSIENT"


class ClassroomUpstreamError(Exception):
    def __init__(
        self, kind: str, message: str, *, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TokenGrant:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    #: Scopes Google reports as granted.  Empty when the response omitted them
    #: (a refresh response normally does), never filled with assumptions.
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredCourse:
    course_id: str
    name: str
    section: str | None
    course_state: str


@dataclass(frozen=True, slots=True)
class CourseListing:
    courses: list[DiscoveredCourse]
    #: True when the configured ceiling stopped the read before Google ran out.
    truncated: bool


def authorization_url(settings: ClassroomSettings, state: str) -> str:
    params = {
        "client_id": settings.client_id or "",
        "redirect_uri": settings.redirect_uri or "",
        "response_type": "code",
        "scope": COURSES_SCOPE,
        # Offline access is what makes a refresh token available; consent is
        # forced so a reconnect returns one even after a previous grant.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{settings.auth_url}?{urlencode(params)}"


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError as error:
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT,
            "Google returned a response that was not JSON.",
            status_code=response.status_code,
        ) from error
    if not isinstance(parsed, dict):
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT,
            "Google returned a malformed response.",
            status_code=response.status_code,
        )
    return parsed


def _describe(body: dict[str, Any]) -> tuple[str, str]:
    """The provider's error code and a short, token-free description."""

    raw = body.get("error")
    code = ""
    description = ""
    if isinstance(raw, dict):
        value = raw.get("error")
        if isinstance(value, str):
            code = value
        message = raw.get("message")
        if isinstance(message, str):
            description = message
        status = raw.get("status")
        if not code and isinstance(status, str):
            code = status
    elif isinstance(raw, str):
        code = raw
    detail = body.get("error_description")
    if not description and isinstance(detail, str):
        description = detail
    return code, " ".join(description.split())[:300]


def _token_error(response: httpx.Response) -> ClassroomUpstreamError:
    body = _body(response)
    code, description = _describe(body)
    message = description or "Google refused the token request."
    if code == "invalid_grant":
        return ClassroomUpstreamError(
            UpstreamKind.RECONNECT_REQUIRED, message, status_code=response.status_code
        )
    if code in {"invalid_client", "unauthorized_client"}:
        return ClassroomUpstreamError(
            UpstreamKind.CONFIGURATION, message, status_code=response.status_code
        )
    return ClassroomUpstreamError(
        UpstreamKind.TRANSIENT, message, status_code=response.status_code
    )


def _grant(response: httpx.Response) -> TokenGrant:
    if response.status_code >= 400:
        raise _token_error(response)
    body = _body(response)
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT,
            "Google returned no access token.",
            status_code=response.status_code,
        )
    raw_expiry = body.get("expires_in")
    seconds = 3600
    if isinstance(raw_expiry, int | float) and raw_expiry > 0:
        seconds = int(raw_expiry)
    raw_refresh = body.get("refresh_token")
    refresh_token = (
        raw_refresh if isinstance(raw_refresh, str) and raw_refresh else None
    )
    raw_scopes = body.get("scope")
    scopes = (
        tuple(part for part in raw_scopes.split() if part)
        if isinstance(raw_scopes, str)
        else ()
    )
    return TokenGrant(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        scopes=scopes,
    )


def _token_request(
    settings: ClassroomSettings,
    payload: dict[str, str],
    *,
    transport: httpx.BaseTransport | None,
) -> TokenGrant:
    with httpx.Client(
        timeout=settings.timeout_seconds, transport=transport
    ) as client:
        response = client.post(settings.token_url, data=payload)
    return _grant(response)


def exchange_code(
    settings: ClassroomSettings,
    code: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> TokenGrant:
    return _token_request(
        settings,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.client_id or "",
            "client_secret": (
                settings.client_secret.get_secret_value()
                if settings.client_secret is not None
                else ""
            ),
            "redirect_uri": settings.redirect_uri or "",
        },
        transport=transport,
    )


def refresh_access_token(
    settings: ClassroomSettings,
    refresh_token: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> TokenGrant:
    return _token_request(
        settings,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.client_id or "",
            "client_secret": (
                settings.client_secret.get_secret_value()
                if settings.client_secret is not None
                else ""
            ),
        },
        transport=transport,
    )


def revoke_token(
    settings: ClassroomSettings,
    token: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    """Best-effort revocation at Google; it never raises.

    The local ciphertext is discarded whether or not this succeeds, so the
    workspace can never keep using a token it disconnected.
    """

    try:
        with httpx.Client(
            timeout=settings.timeout_seconds, transport=transport
        ) as client:
            response = client.post(settings.revoke_url, data={"token": token})
        return response.status_code < 400
    except httpx.HTTPError:
        return False


def _courses_error(response: httpx.Response) -> ClassroomUpstreamError:
    body = _body(response)
    _, description = _describe(body)
    message = description or "Google Classroom refused the course read."
    if response.status_code == 401:
        return ClassroomUpstreamError(
            UpstreamKind.RECONNECT_REQUIRED, message, status_code=401
        )
    if response.status_code == 403 and "scope" in message.lower():
        return ClassroomUpstreamError(
            UpstreamKind.SCOPE_MISSING, message, status_code=403
        )
    return ClassroomUpstreamError(
        UpstreamKind.TRANSIENT, message, status_code=response.status_code
    )


def _course(raw: Any) -> DiscoveredCourse:
    if not isinstance(raw, dict):
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned a malformed course."
        )
    course_id = raw.get("id")
    name = raw.get("name")
    section = raw.get("section")
    state = raw.get("courseState")
    if not isinstance(course_id, str) or not course_id:
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned a course without an id."
        )
    return DiscoveredCourse(
        course_id=course_id,
        name=name if isinstance(name, str) and name.strip() else course_id,
        section=section if isinstance(section, str) and section.strip() else None,
        course_state=(
            state if state in {"ACTIVE", "ARCHIVED", "DELETED"} else "ACTIVE"
        ),
    )


def list_courses(
    settings: ClassroomSettings,
    access_token: str,
    *,
    max_courses: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> CourseListing:
    """Read the authenticated teacher's ACTIVE courses, following pages.

    The whole list is read up to the configured ceiling.  When the ceiling is
    reached the result says so instead of presenting a partial list as complete.
    """

    ceiling = max_courses if max_courses is not None else settings.max_courses
    collected: dict[str, DiscoveredCourse] = {}
    truncated = False
    page_token: str | None = None
    url = f"{settings.api_base_url.rstrip('/')}/courses"

    with httpx.Client(
        timeout=settings.timeout_seconds, transport=transport
    ) as client:
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {
                "teacherId": "me",
                "courseStates": "ACTIVE",
                "pageSize": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            if response.status_code >= 400:
                raise _courses_error(response)
            body = _body(response)
            raw_courses = body.get("courses", [])
            if not isinstance(raw_courses, list):
                raise ClassroomUpstreamError(
                    UpstreamKind.TRANSIENT,
                    "Google returned a malformed course list.",
                    status_code=response.status_code,
                )
            for raw in raw_courses:
                course = _course(raw)
                if course.course_id not in collected:
                    collected[course.course_id] = course
                if len(collected) >= ceiling:
                    truncated = True
                    break
            if truncated:
                break
            next_token = body.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token
        else:
            truncated = True

    return CourseListing(courses=list(collected.values()), truncated=truncated)
