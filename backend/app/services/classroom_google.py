"""Google OAuth and Classroom API access for the central account.

This module is the only place that talks to Google.  It builds the consent URL,
exchanges and refreshes codes, revokes grants, and calls the Classroom and Drive
endpoints the integration needs.  No Google SDK is used: ``httpx`` is already a
dependency and its transport can be injected, so unit tests never reach the
network.

Failures are classified rather than flattened.  A revoked or rejected grant must
clear the stored tokens, while a timeout or a 500 must leave the connection
intact and be retried later.  A permanent 400/403/404 is not retried at all, and
a missing Classroom scope is separated from a generic refusal so the interface
can ask for consent again instead of suggesting an outage.

Scopes are deliberately narrow and each one is load-bearing:

======================== =====================================================
``classroom.courses.readonly``          ``courses.list`` / ``courses.get``
``classroom.rosters.readonly``          ``courses.students.list``,
                                        ``courses.teachers.list``
``classroom.profile.emails``            ``emailAddress`` in a student or
                                        teacher profile
``classroom.coursework.students``       ``courses.courseWork.create``,
                                        ``courses.courseWork.studentSubmissions``
                                        read/patch, and the ``:return`` action
``drive.readonly``                      downloading a Drive attachment
``openid`` + ``userinfo.email``         ``userinfo``, so an administrator can
                                        see which account is connected
======================== =====================================================
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from ..core.config import ClassroomSettings

COURSES_SCOPE = "https://www.googleapis.com/auth/classroom.courses.readonly"
ROSTERS_SCOPE = "https://www.googleapis.com/auth/classroom.rosters.readonly"
PROFILE_EMAIL_SCOPE = "https://www.googleapis.com/auth/classroom.profile.emails"
COURSEWORK_SCOPE = "https://www.googleapis.com/auth/classroom.coursework.students"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
OPENID_SCOPE = "openid"
USERINFO_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"

#: Everything this integration asks for, in the order Google sees it.
REQUIRED_SCOPES: tuple[str, ...] = (
    COURSES_SCOPE,
    ROSTERS_SCOPE,
    PROFILE_EMAIL_SCOPE,
    COURSEWORK_SCOPE,
    DRIVE_READONLY_SCOPE,
    OPENID_SCOPE,
    USERINFO_EMAIL_SCOPE,
)

def missing_scopes(granted: tuple[str, ...] | list[str]) -> list[str]:
    """Required scopes absent from a grant.

    Google may return a superset after incremental authorisation; only
    the scopes this integration actually uses are checked.
    """

    held = set(granted)
    return [scope for scope in REQUIRED_SCOPES if scope not in held]


PAGE_SIZE = 100
MAX_PAGES = 100


class UpstreamKind:
    """How a Google failure affects the workspace's stored authorisation."""

    #: Google rejected the grant: the tokens must be discarded.
    RECONNECT_REQUIRED = "RECONNECT_REQUIRED"
    #: The grant exists but lacks a scope this operation needs: consent again.
    SCOPE_MISSING = "SCOPE_MISSING"
    #: The configured OAuth client itself was refused.
    CONFIGURATION = "CONFIGURATION"
    #: Timeouts, 5xx, 429 and malformed responses: keep the connection.
    TRANSIENT = "TRANSIENT"
    #: A 400/403/404 that retrying cannot fix.
    PERMANENT = "PERMANENT"


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
    #: The IANA zone the course uses.  Google requires a due date and time in
    #: this zone, so it is kept rather than guessed from the server's clock.
    time_zone: str | None = None
    room: str | None = None


@dataclass(frozen=True, slots=True)
class CourseListing:
    courses: list[DiscoveredCourse]
    #: True when the configured ceiling stopped the read before Google ran out.
    truncated: bool


@dataclass(frozen=True, slots=True)
class ClassroomPerson:
    user_id: str
    full_name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class PersonListing:
    people: list[ClassroomPerson]
    truncated: bool


@dataclass(frozen=True, slots=True)
class CourseworkRecord:
    coursework_id: str
    title: str
    state: str | None = None
    max_points: float | None = None
    due_date: dict[str, int] | None = None
    due_time: dict[str, int] | None = None


@dataclass(frozen=True, slots=True)
class Attachment:
    kind: str
    title: str | None = None
    drive_file_id: str | None = None
    alternate_link: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    submission_id: str
    user_id: str
    state: str | None
    late: bool
    attachments: list[Attachment] = field(default_factory=list)
    draft_grade: float | None = None
    assigned_grade: float | None = None
    update_time: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionListing:
    submissions: list[SubmissionRecord]
    truncated: bool


def authorization_url(settings: ClassroomSettings, state: str) -> str:
    params = {
        "client_id": settings.client_id or "",
        "redirect_uri": settings.redirect_uri or "",
        "response_type": "code",
        "scope": " ".join(REQUIRED_SCOPES),
        # Offline access is what makes a refresh token available; consent is
        # forced so a reconnect returns one even after a previous grant.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{settings.auth_url}?{urlencode(params)}"


# -- transport -------------------------------------------------------------


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


def _client(
    settings: ClassroomSettings, transport: httpx.BaseTransport | None
) -> httpx.Client:
    return httpx.Client(timeout=settings.timeout_seconds, transport=transport)


def _sleep(
    settings: ClassroomSettings,
    attempt: int,
    response: httpx.Response | None,
) -> None:
    delay = settings.retry_backoff_seconds * (2 ** attempt)
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw and raw.isdigit():
            # Google asks for a specific pause; obey it, bounded by the timeout.
            delay = min(float(raw), float(settings.timeout_seconds))
    if delay > 0:
        time.sleep(delay)


def _request(
    settings: ClassroomSettings,
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    """One request with bounded retries for a 429 or a 5xx.

    A 4xx other than 429 is returned immediately: retrying a permission or
    validation error cannot succeed and only burns quota.
    """

    attempts = settings.request_attempts
    last: httpx.Response | None = None
    for attempt in range(attempts):
        try:
            last = client.request(
                method, url, headers=headers, params=params, json=json
            )
        except httpx.TransportError as error:
            if attempt >= attempts - 1:
                raise ClassroomUpstreamError(
                    UpstreamKind.TRANSIENT,
                    "Google could not be reached. The connection was kept; try again.",
                ) from error
            _sleep(settings, attempt, None)
            continue
        retryable = last.status_code == 429 or last.status_code >= 500
        if retryable and attempt < attempts - 1:
            _sleep(settings, attempt, last)
            continue
        return last
    assert last is not None
    return last


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
    with _client(settings, transport) as client:
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
    platform can never keep using a token it disconnected.
    """

    try:
        with _client(settings, transport) as client:
            response = client.post(settings.revoke_url, data={"token": token})
        return response.status_code < 400
    except httpx.HTTPError:
        return False


# -- error classification --------------------------------------------------


def _api_error(response: httpx.Response, fallback: str) -> ClassroomUpstreamError:
    body = _body(response)
    code, description = _describe(body)
    message = description or fallback
    status = response.status_code
    if status == 401:
        return ClassroomUpstreamError(
            UpstreamKind.RECONNECT_REQUIRED, message, status_code=status
        )
    if status == 403:
        lowered = message.lower()
        insufficient = code in {
            "PERMISSION_DENIED",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
        }
        if "scope" in lowered or insufficient:
            return ClassroomUpstreamError(
                UpstreamKind.SCOPE_MISSING, message, status_code=status
            )
        return ClassroomUpstreamError(
            UpstreamKind.PERMANENT, message, status_code=status
        )
    if status in {400, 404, 409, 412}:
        return ClassroomUpstreamError(
            UpstreamKind.PERMANENT, message, status_code=status
        )
    return ClassroomUpstreamError(
        UpstreamKind.TRANSIENT, message, status_code=status
    )


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


# -- course discovery ------------------------------------------------------


def _course(raw: Any) -> DiscoveredCourse:
    if not isinstance(raw, dict):
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned a malformed course."
        )
    course_id = raw.get("id")
    name = raw.get("name")
    section = raw.get("section")
    state = raw.get("courseState")
    zone = raw.get("timeZone")
    room = raw.get("room")
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
        time_zone=zone if isinstance(zone, str) and zone.strip() else None,
        room=room if isinstance(room, str) and room.strip() else None,
    )


def list_courses(
    settings: ClassroomSettings,
    access_token: str,
    *,
    max_courses: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> CourseListing:
    """Read the central account's ACTIVE courses, following every page.

    The whole list is read up to the configured ceiling.  When the ceiling is
    reached the result says so instead of presenting a partial list as complete.
    """

    ceiling = max_courses if max_courses is not None else settings.max_courses
    collected: dict[str, DiscoveredCourse] = {}
    truncated = False
    page_token: str | None = None
    url = f"{settings.api_base_url.rstrip('/')}/courses"

    with _client(settings, transport) as client:
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {
                "teacherId": "me",
                "courseStates": "ACTIVE",
                "pageSize": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            response = _request(
                settings,
                client,
                "GET",
                url,
                headers=_headers(access_token),
                params=params,
            )
            if response.status_code >= 400:
                raise _api_error(response, "Google Classroom refused the course read.")
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


def get_course(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> DiscoveredCourse:
    url = f"{settings.api_base_url.rstrip('/')}/courses/{course_id}"
    with _client(settings, transport) as client:
        response = _request(
            settings, client, "GET", url, headers=_headers(access_token)
        )
    if response.status_code >= 400:
        raise _api_error(response, "Google Classroom refused the course read.")
    return _course(_body(response))


# -- roster ----------------------------------------------------------------


def _person(raw: Any) -> ClassroomPerson | None:
    if not isinstance(raw, dict):
        return None
    profile = raw.get("profile")
    if not isinstance(profile, dict):
        return None
    user_id = profile.get("id")
    if not isinstance(user_id, str) or not user_id:
        return None
    name = profile.get("name")
    full_name = None
    if isinstance(name, dict):
        value = name.get("fullName")
        if isinstance(value, str) and value.strip():
            full_name = value.strip()
    email = profile.get("emailAddress")
    return ClassroomPerson(
        user_id=user_id,
        full_name=full_name,
        email=email if isinstance(email, str) and email.strip() else None,
    )


def _list_people(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    segment: str,
    *,
    ceiling: int,
    transport: httpx.BaseTransport | None,
) -> PersonListing:
    collected: dict[str, ClassroomPerson] = {}
    truncated = False
    page_token: str | None = None
    url = f"{settings.api_base_url.rstrip('/')}/courses/{course_id}/{segment}"

    with _client(settings, transport) as client:
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"pageSize": PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            response = _request(
                settings,
                client,
                "GET",
                url,
                headers=_headers(access_token),
                params=params,
            )
            if response.status_code >= 400:
                raise _api_error(response, "Google Classroom refused the roster read.")
            body = _body(response)
            raw_people = body.get(segment, [])
            if not isinstance(raw_people, list):
                raise ClassroomUpstreamError(
                    UpstreamKind.TRANSIENT,
                    "Google returned a malformed roster.",
                    status_code=response.status_code,
                )
            for raw in raw_people:
                person = _person(raw)
                if person is None or person.user_id in collected:
                    continue
                collected[person.user_id] = person
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

    return PersonListing(people=list(collected.values()), truncated=truncated)


def list_students(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    *,
    max_students: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> PersonListing:
    ceiling = (
        max_students if max_students is not None else settings.max_roster_students
    )
    return _list_people(
        settings,
        access_token,
        course_id,
        "students",
        ceiling=ceiling,
        transport=transport,
    )


def list_teachers(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> PersonListing:
    return _list_people(
        settings,
        access_token,
        course_id,
        "teachers",
        ceiling=settings.max_roster_students,
        transport=transport,
    )


# -- account identity ------------------------------------------------------


def get_account_identity(
    settings: ClassroomSettings,
    access_token: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[str | None, str | None]:
    """The connected account's email and name, or ``(None, None)``.

    Identity is a convenience, never a requirement: a userinfo call that fails
    must not fail the authorization.  Nothing is inferred from the token.
    """

    try:
        with _client(settings, transport) as client:
            response = _request(
                settings,
                client,
                "GET",
                settings.userinfo_url,
                headers=_headers(access_token),
            )
    except ClassroomUpstreamError:
        return (None, None)
    if response.status_code >= 400:
        return (None, None)
    try:
        body = _body(response)
    except ClassroomUpstreamError:
        return (None, None)
    email = body.get("email")
    name = body.get("name")
    return (
        email if isinstance(email, str) and email.strip() else None,
        name if isinstance(name, str) and name.strip() else None,
    )


# -- coursework ------------------------------------------------------------


def _coursework(raw: Any) -> CourseworkRecord:
    if not isinstance(raw, dict):
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned a malformed coursework."
        )
    coursework_id = raw.get("id")
    if not isinstance(coursework_id, str) or not coursework_id:
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned coursework without an id."
        )
    points = raw.get("maxPoints")
    due_date = raw.get("dueDate")
    due_time = raw.get("dueTime")
    title = raw.get("title")
    state = raw.get("state")
    return CourseworkRecord(
        coursework_id=coursework_id,
        title=title if isinstance(title, str) else "",
        state=state if isinstance(state, str) else None,
        max_points=float(points) if isinstance(points, int | float) else None,
        due_date=due_date if isinstance(due_date, dict) else None,
        due_time=due_time if isinstance(due_time, dict) else None,
    )


def create_coursework(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    *,
    title: str,
    description: str | None = None,
    due_date: dict[str, int] | None = None,
    due_time: dict[str, int] | None = None,
    max_points: float | None = None,
    state: str = "PUBLISHED",
    transport: httpx.BaseTransport | None = None,
) -> CourseworkRecord:
    """Create one Classroom coursework.

    Google deduplicates nothing: retrying this call after an ambiguous failure
    can create a second coursework, so the caller must reconcile by listing
    before it retries.  ``state`` decides whether students can see it.
    """

    payload: dict[str, Any] = {
        "title": title,
        "workType": "ASSIGNMENT",
        "state": state,
    }
    if description:
        payload["description"] = description
    if due_date:
        payload["dueDate"] = due_date
    if due_time:
        payload["dueTime"] = due_time
    if max_points is not None:
        payload["maxPoints"] = max_points
    url = f"{settings.api_base_url.rstrip('/')}/courses/{course_id}/courseWork"
    with _client(settings, transport) as client:
        response = _request(
            settings,
            client,
            "POST",
            url,
            headers=_headers(access_token),
            json=payload,
        )
    if response.status_code >= 400:
        raise _api_error(response, "Google Classroom refused the coursework.")
    return _coursework(_body(response))


def list_coursework(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> list[CourseworkRecord]:
    """Every coursework on a course, following all pages.

    Used to reconcile a publication whose response was lost: the caller looks
    for the title it tried to create instead of creating it a second time.
    """

    collected: list[CourseworkRecord] = []
    seen: set[str] = set()
    page_token: str | None = None
    url = f"{settings.api_base_url.rstrip('/')}/courses/{course_id}/courseWork"
    with _client(settings, transport) as client:
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"pageSize": PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            response = _request(
                settings,
                client,
                "GET",
                url,
                headers=_headers(access_token),
                params=params,
            )
            if response.status_code >= 400:
                raise _api_error(
                    response, "Google Classroom refused the coursework read."
                )
            body = _body(response)
            raw_items = body.get("courseWork", [])
            if not isinstance(raw_items, list):
                raise ClassroomUpstreamError(
                    UpstreamKind.TRANSIENT,
                    "Google returned a malformed coursework list.",
                )
            for raw in raw_items:
                record = _coursework(raw)
                if record.coursework_id not in seen:
                    seen.add(record.coursework_id)
                    collected.append(record)
            next_token = body.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token
    return collected


def patch_coursework(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    coursework_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    due_date: dict[str, int] | None = None,
    due_time: dict[str, int] | None = None,
    max_points: float | None = None,
    transport: httpx.BaseTransport | None = None,
) -> CourseworkRecord:
    payload: dict[str, Any] = {}
    mask: list[str] = []
    if title is not None:
        payload["title"] = title
        mask.append("title")
    if description is not None:
        payload["description"] = description
        mask.append("description")
    if due_date is not None:
        payload["dueDate"] = due_date
        mask.append("dueDate")
    if due_time is not None:
        payload["dueTime"] = due_time
        mask.append("dueTime")
    if max_points is not None:
        payload["maxPoints"] = max_points
        mask.append("maxPoints")
    if not mask:
        raise ClassroomUpstreamError(
            UpstreamKind.PERMANENT, "No supported coursework field was supplied."
        )
    url = (
        f"{settings.api_base_url.rstrip('/')}/courses/{course_id}"
        f"/courseWork/{coursework_id}"
    )
    with _client(settings, transport) as client:
        response = _request(
            settings,
            client,
            "PATCH",
            url,
            headers=_headers(access_token),
            params={"updateMask": ",".join(mask)},
            json=payload,
        )
    if response.status_code >= 400:
        raise _api_error(response, "Google Classroom refused the coursework update.")
    return _coursework(_body(response))


# -- submissions -----------------------------------------------------------


def _attachment(raw: Any) -> Attachment | None:
    if not isinstance(raw, dict):
        return None
    # ``StudentSubmission.assignmentSubmission.attachments[].driveFile`` is
    # itself the DriveFile (id, title, alternateLink, thumbnailUrl); it is not
    # a wrapper around a second ``driveFile``.
    drive = raw.get("driveFile")
    if isinstance(drive, dict):
        file_id = drive.get("id")
        title = drive.get("title")
        mime = drive.get("mimeType")
        link = drive.get("alternateLink")
        if isinstance(file_id, str) and file_id:
            return Attachment(
                kind="DRIVE_FILE",
                title=title if isinstance(title, str) else None,
                drive_file_id=file_id,
                alternate_link=link if isinstance(link, str) else None,
                mime_type=mime if isinstance(mime, str) else None,
            )
    link_raw = raw.get("link")
    if isinstance(link_raw, dict):
        url = link_raw.get("url")
        title = link_raw.get("title")
        if isinstance(url, str) and url:
            return Attachment(
                kind="LINK",
                title=title if isinstance(title, str) else None,
                alternate_link=url,
            )
    if isinstance(raw.get("youTubeVideo"), dict):
        return Attachment(kind="YOUTUBE_VIDEO")
    if isinstance(raw.get("form"), dict):
        return Attachment(kind="FORM")
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _submission(raw: Any) -> SubmissionRecord:
    if not isinstance(raw, dict):
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned a malformed submission."
        )
    submission_id = raw.get("id")
    user_id = raw.get("userId")
    if not isinstance(submission_id, str) or not submission_id:
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned a submission without an id."
        )
    if not isinstance(user_id, str) or not user_id:
        raise ClassroomUpstreamError(
            UpstreamKind.TRANSIENT, "Google returned a submission without a user."
        )
    raw_attachments = raw.get("assignmentSubmission")
    attachments: list[Attachment] = []
    if isinstance(raw_attachments, dict):
        items = raw_attachments.get("attachments")
        if isinstance(items, list):
            for item in items:
                parsed = _attachment(item)
                if parsed is not None:
                    attachments.append(parsed)
    state = raw.get("state")
    update_time = raw.get("updateTime")
    return SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        state=state if isinstance(state, str) else None,
        late=bool(raw.get("late")),
        attachments=attachments,
        draft_grade=_number(raw.get("draftGrade")),
        assigned_grade=_number(raw.get("assignedGrade")),
        update_time=update_time if isinstance(update_time, str) else None,
    )


def list_submissions(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    coursework_id: str,
    *,
    max_submissions: int | None = None,
    states: tuple[str, ...] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> SubmissionListing:
    """Read student submissions for one coursework, following every page."""

    ceiling = (
        max_submissions if max_submissions is not None else settings.max_submissions
    )
    collected: dict[str, SubmissionRecord] = {}
    truncated = False
    page_token: str | None = None
    url = (
        f"{settings.api_base_url.rstrip('/')}/courses/{course_id}"
        f"/courseWork/{coursework_id}/studentSubmissions"
    )
    with _client(settings, transport) as client:
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"pageSize": PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            if states:
                params["states"] = list(states)
            response = _request(
                settings,
                client,
                "GET",
                url,
                headers=_headers(access_token),
                params=params,
            )
            if response.status_code >= 400:
                raise _api_error(
                    response, "Google Classroom refused the submission read."
                )
            body = _body(response)
            raw_items = body.get("studentSubmissions", [])
            if not isinstance(raw_items, list):
                raise ClassroomUpstreamError(
                    UpstreamKind.TRANSIENT,
                    "Google returned a malformed submission list.",
                )
            for raw in raw_items:
                record = _submission(raw)
                if record.submission_id not in collected:
                    collected[record.submission_id] = record
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
    return SubmissionListing(
        submissions=list(collected.values()), truncated=truncated
    )


def get_submission(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    coursework_id: str,
    submission_id: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> SubmissionRecord:
    url = (
        f"{settings.api_base_url.rstrip('/')}/courses/{course_id}"
        f"/courseWork/{coursework_id}/studentSubmissions/{submission_id}"
    )
    with _client(settings, transport) as client:
        response = _request(
            settings, client, "GET", url, headers=_headers(access_token)
        )
    if response.status_code >= 400:
        raise _api_error(response, "Google Classroom refused the submission read.")
    return _submission(_body(response))


def patch_submission_grade(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    coursework_id: str,
    submission_id: str,
    *,
    assigned_grade: float | None = None,
    draft_grade: float | None = None,
    transport: httpx.BaseTransport | None = None,
) -> SubmissionRecord:
    """Write one grade field and nothing else.

    ``draftGrade`` is a provisional mark Google shows to a teacher;
    ``assignedGrade`` is the returned grade a student sees.  They are separate
    fields with separate update masks, so publishing a final grade never
    silently leaves a provisional one behind, and writing a draft never
    releases a grade.
    """

    payload: dict[str, Any] = {}
    mask: list[str] = []
    if assigned_grade is not None:
        payload["assignedGrade"] = assigned_grade
        mask.append("assignedGrade")
    if draft_grade is not None:
        payload["draftGrade"] = draft_grade
        mask.append("draftGrade")
    if not mask:
        raise ClassroomUpstreamError(
            UpstreamKind.PERMANENT, "No grade was supplied."
        )
    url = (
        f"{settings.api_base_url.rstrip('/')}/courses/{course_id}"
        f"/courseWork/{coursework_id}/studentSubmissions/{submission_id}"
    )
    with _client(settings, transport) as client:
        response = _request(
            settings,
            client,
            "PATCH",
            url,
            headers=_headers(access_token),
            params={"updateMask": ",".join(mask)},
            json=payload,
        )
    if response.status_code >= 400:
        raise _api_error(response, "Google Classroom refused the grade update.")
    return _submission(_body(response))


def return_submission(
    settings: ClassroomSettings,
    access_token: str,
    course_id: str,
    coursework_id: str,
    submission_id: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> SubmissionRecord:
    """Return the work to the student so the assigned grade becomes visible."""

    url = (
        f"{settings.api_base_url.rstrip('/')}/courses/{course_id}"
        f"/courseWork/{coursework_id}/studentSubmissions/{submission_id}:return"
    )
    with _client(settings, transport) as client:
        response = _request(
            settings, client, "POST", url, headers=_headers(access_token), json={}
        )
    if response.status_code >= 400:
        raise _api_error(response, "Google Classroom refused to return the work.")
    return _submission(_body(response))


# -- attachments -----------------------------------------------------------


def download_drive_file(
    settings: ClassroomSettings,
    access_token: str,
    file_id: str,
    *,
    max_bytes: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[bytes, str]:
    """Download one Drive attachment, refusing anything above the byte ceiling.

    The ceiling is enforced from ``Content-Length`` before the body is read and
    again while streaming, so a missing or lying header cannot exhaust memory.
    """

    ceiling = max_bytes if max_bytes is not None else settings.max_attachment_bytes
    url = f"{settings.drive_base_url.rstrip('/')}/files/{file_id}"
    with _client(settings, transport) as client, client.stream(
        "GET",
        url,
        headers=_headers(access_token),
        params={"alt": "media"},
    ) as response:
        if response.status_code >= 400:
            # Read the error body without consuming the media stream.
            response.read()
            raise _api_error(response, "Google Drive refused the file read.")
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > ceiling:
            raise ClassroomUpstreamError(
                UpstreamKind.PERMANENT,
                f"The attachment is larger than the {ceiling} byte limit.",
                status_code=413,
            )
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > ceiling:
                raise ClassroomUpstreamError(
                    UpstreamKind.PERMANENT,
                    f"The attachment is larger than the {ceiling} byte limit.",
                    status_code=413,
                )
            chunks.append(chunk)
        content_type = (
            response.headers.get("Content-Type", "application/octet-stream")
            .split(";")[0]
            .strip()
        )
        return b"".join(chunks), content_type


def export_drive_file(
    settings: ClassroomSettings,
    access_token: str,
    file_id: str,
    *,
    mime_type: str = "application/pdf",
    max_bytes: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[bytes, str]:
    """Export a Google Workspace document through Drive's PDF export path.

    Only a Workspace type with a lossless page layout is exported; the caller
    decides which types qualify.  The byte ceiling is enforced exactly as it is
    for a direct download, so an export cannot exhaust memory.
    """

    ceiling = max_bytes if max_bytes is not None else settings.max_attachment_bytes
    url = f"{settings.drive_base_url.rstrip('/')}/files/{file_id}/export"
    with _client(settings, transport) as client, client.stream(
        "GET",
        url,
        headers=_headers(access_token),
        params={"mimeType": mime_type, "alt": "media"},
    ) as response:
        if response.status_code >= 400:
            response.read()
            raise _api_error(response, "Google Drive refused the document export.")
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > ceiling:
            raise ClassroomUpstreamError(
                UpstreamKind.PERMANENT,
                f"The exported document is larger than the {ceiling} byte limit.",
                status_code=413,
            )
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > ceiling:
                raise ClassroomUpstreamError(
                    UpstreamKind.PERMANENT,
                    f"The exported document is larger than the {ceiling} byte limit.",
                    status_code=413,
                )
            chunks.append(chunk)
        return b"".join(chunks), mime_type
