"""Google Classroom authorisation and course synchronisation.

The workspace is always the verified principal's tenant.  The OAuth state is
Fernet-encrypted and carries the workspace and subject that started the flow;
the authenticated callback refuses a state issued for anyone else.  That keeps
an authorisation URL from attaching an unrelated Classroom grant to a tenant.

Tokens never leave this module in a response.  Both are stored as ciphertext,
and a grant Google rejects has its ciphertext discarded so
``RECONNECT_REQUIRED`` cannot be mistaken for a usable connection.  A timeout
or a 5xx is recorded as a failed sync and leaves the authorisation intact.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal, SecretBox
from ..db.models import ClassroomClass, ClassroomConnection
from ..schemas.classroom_oauth import (
    ClassroomAuthorizationStart,
    ClassroomConnectionRead,
    ClassroomDisconnectRead,
    ClassroomSyncRead,
    SyncCountsRead,
    SyncedCourseRead,
)
from .classroom_google import (
    COURSES_SCOPE,
    ClassroomUpstreamError,
    DiscoveredCourse,
    UpstreamKind,
    authorization_url,
    exchange_code,
    list_courses,
    refresh_access_token,
    revoke_token,
)

MANAGER_ROLES = frozenset({"OWNER", "ADMIN", "PLATFORM_OWNER"})
_STATE_VERSION = 1
_UPSERT_CHUNK = 500
#: Refresh a little before Google's expiry so an in-flight read cannot expire.
_EXPIRY_SKEW = timedelta(seconds=60)


def ensure_classroom_manager(principal: Principal) -> None:
    if principal.role in MANAGER_ROLES or principal.is_platform_admin:
        return
    raise AppError(
        ErrorCode.FORBIDDEN,
        "Connecting Google Classroom requires a workspace owner or administrator.",
    )


def _invalid_state() -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        "The Google Classroom authorisation state is invalid or has expired. "
        "Start the connection again.",
    )


def _state_box(settings: Settings) -> SecretBox:
    if settings.security.encryption_key is None:
        raise AppError(
            ErrorCode.CLASSROOM_NOT_CONFIGURED,
            "Credential encryption is not configured, so a Classroom "
            "authorisation cannot be started.",
        )
    return SecretBox(settings.security.encryption_key.get_secret_value())


def issue_state(settings: Settings, principal: Principal) -> tuple[str, datetime]:
    """Bind a nonce, workspace and subject into an opaque state value."""

    expires_at = utcnow() + timedelta(seconds=settings.classroom.state_ttl_seconds)
    payload = json.dumps(
        {
            "v": _STATE_VERSION,
            "tenant_id": str(principal.tenant_id),
            "subject": principal.subject,
            "nonce": secrets.token_urlsafe(16),
            "expires_at": expires_at.isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return _state_box(settings).encrypt(payload), expires_at


def verify_state(settings: Settings, state: str, principal: Principal) -> None:
    """Refuse a state that is malformed, expired or issued for someone else."""

    try:
        raw = _state_box(settings).decrypt(state)
    except AppError as error:
        raise _invalid_state() from error
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise _invalid_state() from error
    if not isinstance(data, dict) or data.get("v") != _STATE_VERSION:
        raise _invalid_state()
    if data.get("tenant_id") != str(principal.tenant_id):
        raise _invalid_state()
    if data.get("subject") != principal.subject:
        raise _invalid_state()
    raw_expiry = data.get("expires_at")
    if not isinstance(raw_expiry, str):
        raise _invalid_state()
    try:
        expires_at = datetime.fromisoformat(raw_expiry)
    except ValueError as error:
        raise _invalid_state() from error
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= utcnow():
        raise _invalid_state()


def _safe_message(value: str) -> str:
    return " ".join(value.split())[:500]


class ClassroomOAuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.cloud = settings.classroom
        self.audit = AuditService(session)

    # -- helpers ---------------------------------------------------------
    def _require_configured(self) -> None:
        if not self.cloud.configured():
            raise AppError(
                ErrorCode.CLASSROOM_NOT_CONFIGURED,
                "Google Classroom OAuth is not configured. Set "
                "AETRIX_CLASSROOM__CLIENT_ID, AETRIX_CLASSROOM__CLIENT_SECRET and "
                "AETRIX_CLASSROOM__REDIRECT_URI.",
            )

    def _box(self) -> SecretBox:
        if self.settings.security.encryption_key is None:
            raise AppError(
                ErrorCode.CLASSROOM_NOT_CONFIGURED,
                "Credential encryption is not configured, so Classroom tokens "
                "cannot be stored.",
            )
        return SecretBox(self.settings.security.encryption_key.get_secret_value())

    def _row(self, tenant_id: UUID) -> ClassroomConnection | None:
        return self.session.scalar(
            select(ClassroomConnection).where(
                ClassroomConnection.tenant_id == tenant_id
            )
        )

    def _row_for_update(self, tenant_id: UUID) -> ClassroomConnection | None:
        return self.session.scalar(
            select(ClassroomConnection)
            .where(ClassroomConnection.tenant_id == tenant_id)
            .with_for_update()
        )

    def _read(self, row: ClassroomConnection | None) -> ClassroomConnectionRead:
        configured = self.cloud.configured()
        if row is None:
            return ClassroomConnectionRead(
                configured=configured,
                status="NOT_CONNECTED",
                redirect_uri=self.cloud.redirect_uri,
                required_scopes=[COURSES_SCOPE],
                granted_scopes=[],
                connected_at=None,
                connected_by_subject=None,
                last_synced_at=None,
                last_sync_status=None,
                last_sync_counts={},
                last_error_code=None,
                last_error_message=None,
            )
        return ClassroomConnectionRead(
            configured=configured,
            status=row.status,
            redirect_uri=self.cloud.redirect_uri,
            required_scopes=[COURSES_SCOPE],
            granted_scopes=list(row.scopes or []),
            connected_at=row.connected_at,
            connected_by_subject=row.connected_by_subject,
            last_synced_at=row.last_synced_at,
            last_sync_status=row.last_sync_status,
            last_sync_counts=dict(row.last_sync_counts or {}),
            last_error_code=row.last_error_code,
            last_error_message=row.last_error_message,
        )

    def _raise_upstream(self, error: ClassroomUpstreamError) -> NoReturn:
        if error.kind == UpstreamKind.RECONNECT_REQUIRED:
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "Google rejected the stored Classroom authorisation. Connect "
                "Classroom again.",
            )
        if error.kind == UpstreamKind.SCOPE_MISSING:
            raise AppError(
                ErrorCode.CLASSROOM_SCOPE_MISSING,
                "The Classroom authorisation is missing the course-read "
                "permission. Authorise again and accept it.",
            )
        if error.kind == UpstreamKind.CONFIGURATION:
            raise AppError(
                ErrorCode.CLASSROOM_NOT_CONFIGURED,
                "Google rejected the configured OAuth client. Check the client "
                "ID and secret.",
            )
        raise AppError(
            ErrorCode.CLASSROOM_UPSTREAM_ERROR,
            "Google Classroom could not be reached. The connection was kept; "
            "try again.",
        )

    def _mark_reconnect(
        self, row: ClassroomConnection, code: str, message: str
    ) -> None:
        row.status = "RECONNECT_REQUIRED"
        row.encrypted_access_token = None
        row.encrypted_refresh_token = None
        row.access_token_expires_at = None
        row.last_sync_status = "FAILED"
        row.last_error_code = code
        row.last_error_message = _safe_message(message)

    def _mark_failure(
        self, row: ClassroomConnection, code: str, message: str
    ) -> None:
        row.last_sync_status = "FAILED"
        row.last_error_code = code
        row.last_error_message = _safe_message(message)

    def _audit(
        self,
        principal: Principal,
        connection_id: UUID,
        action: str,
        detail: dict[str, object],
    ) -> None:
        self.audit.record(
            tenant_id=principal.tenant_id,
            action=action,
            entity_type="classroom_connection",
            entity_id=connection_id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail=detail,
        )

    # -- reads -----------------------------------------------------------
    def connection(self, principal: Principal) -> ClassroomConnectionRead:
        return self._read(self._row(principal.tenant_id))

    # -- authorisation ---------------------------------------------------
    def start(self, principal: Principal) -> ClassroomAuthorizationStart:
        ensure_classroom_manager(principal)
        self._require_configured()
        state, expires_at = issue_state(self.settings, principal)
        return ClassroomAuthorizationStart(
            authorization_url=authorization_url(self.cloud, state),
            expires_at=expires_at,
            redirect_uri=self.cloud.redirect_uri or "",
            scopes=[COURSES_SCOPE],
        )

    def complete(
        self, principal: Principal, *, code: str, state: str
    ) -> ClassroomConnectionRead:
        ensure_classroom_manager(principal)
        self._require_configured()
        verify_state(self.settings, state, principal)

        try:
            grant = exchange_code(self.cloud, code)
        except ClassroomUpstreamError as error:
            self._raise_upstream(error)

        if COURSES_SCOPE not in grant.scopes:
            # Google issued a token without the scope this integration needs.
            # Give it back rather than storing an authorisation that cannot read
            # a single course.
            revoke_token(self.cloud, grant.access_token)
            raise AppError(
                ErrorCode.CLASSROOM_SCOPE_MISSING,
                "Google did not grant the Classroom course-read permission. "
                "Authorise again and leave the Classroom checkbox selected.",
            )

        box = self._box()
        now = utcnow()
        row = self._row_for_update(principal.tenant_id)
        if row is None:
            row = ClassroomConnection(
                tenant_id=principal.tenant_id,
                status="CONNECTED",
                connected_by_subject=principal.subject,
                connected_at=now,
                last_sync_counts={},
            )
            self.session.add(row)
        row.encrypted_access_token = box.encrypt(grant.access_token)
        if grant.refresh_token:
            row.encrypted_refresh_token = box.encrypt(grant.refresh_token)
        row.access_token_expires_at = grant.expires_at
        row.scopes = list(grant.scopes)
        row.status = "CONNECTED"
        row.connected_at = now
        row.connected_by_subject = principal.subject
        row.last_error_code = None
        row.last_error_message = None
        self.session.flush()
        self._audit(
            principal,
            row.id,
            "classroom.connection_authorized",
            {
                "scopes": list(grant.scopes),
                "connected_by_subject": principal.subject,
                "result": "SUCCEEDED",
            },
        )
        self.session.commit()
        self.session.refresh(row)
        return self._read(row)

    # -- synchronisation -------------------------------------------------
    def _refresh(
        self,
        principal: Principal,
        row: ClassroomConnection,
        box: SecretBox,
    ) -> str:
        if not row.encrypted_refresh_token:
            self._mark_reconnect(
                row,
                "CLASSROOM_RECONNECT_REQUIRED",
                "The stored Classroom authorisation expired and Google issued "
                "no refresh token. Connect Classroom again.",
            )
            self._audit(
                principal,
                row.id,
                "classroom.sync.failed",
                {"result": "FAILED", "error_code": "CLASSROOM_RECONNECT_REQUIRED"},
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "The stored Classroom authorisation expired. Connect Classroom again.",
            )

        refresh_token = box.decrypt(row.encrypted_refresh_token)
        try:
            grant = refresh_access_token(self.cloud, refresh_token)
        except ClassroomUpstreamError as error:
            if error.kind in {
                UpstreamKind.RECONNECT_REQUIRED,
                UpstreamKind.SCOPE_MISSING,
            }:
                self._mark_reconnect(
                    row,
                    "CLASSROOM_RECONNECT_REQUIRED",
                    "Google rejected the stored Classroom refresh token.",
                )
                self._audit(
                    principal,
                    row.id,
                    "classroom.sync.failed",
                    {
                        "result": "FAILED",
                        "error_code": "CLASSROOM_RECONNECT_REQUIRED",
                    },
                )
                self.session.commit()
            else:
                self._mark_failure(
                    row,
                    "CLASSROOM_UPSTREAM_ERROR",
                    "Google could not refresh the Classroom authorisation.",
                )
                self._audit(
                    principal,
                    row.id,
                    "classroom.sync.failed",
                    {"result": "FAILED", "error_code": "CLASSROOM_UPSTREAM_ERROR"},
                )
                self.session.commit()
            self._raise_upstream(error)

        row.encrypted_access_token = box.encrypt(grant.access_token)
        if grant.refresh_token:
            row.encrypted_refresh_token = box.encrypt(grant.refresh_token)
        row.access_token_expires_at = grant.expires_at
        if grant.scopes:
            row.scopes = list(grant.scopes)
        return grant.access_token

    def _chunks(
        self, courses: list[DiscoveredCourse]
    ) -> list[list[DiscoveredCourse]]:
        return [
            courses[index : index + _UPSERT_CHUNK]
            for index in range(0, len(courses), _UPSERT_CHUNK)
        ]

    def _upsert(
        self,
        principal: Principal,
        courses: list[DiscoveredCourse],
        synced_at: datetime,
    ) -> dict[str, int]:
        seen: dict[str, DiscoveredCourse] = {}
        for course in courses:
            seen.setdefault(course.course_id, course)
        unique = list(seen.values())
        if not unique:
            return {"discovered": 0, "created": 0, "updated": 0}

        existing = set(
            self.session.scalars(
                select(ClassroomClass.course_id).where(
                    ClassroomClass.course_id.in_(
                        [course.course_id for course in unique]
                    )
                )
            )
        )
        for chunk in self._chunks(unique):
            statement = pg_insert(ClassroomClass).values(
                [
                    {
                        "course_id": course.course_id,
                        "name": course.name,
                        "section": course.section,
                        "course_state": course.course_state,
                        "verification": "VERIFIED",
                        "source": "google_classroom",
                        "synced_at": synced_at,
                        "created_by_subject": principal.subject,
                    }
                    for course in chunk
                ]
            )
            statement = statement.on_conflict_do_update(
                index_elements=[ClassroomClass.course_id],
                set_={
                    "name": statement.excluded.name,
                    "section": statement.excluded.section,
                    "course_state": statement.excluded.course_state,
                    "verification": statement.excluded.verification,
                    "source": statement.excluded.source,
                    "synced_at": statement.excluded.synced_at,
                    "updated_at": synced_at,
                },
            )
            self.session.execute(statement)

        created = sum(1 for course in unique if course.course_id not in existing)
        return {
            "discovered": len(unique),
            "created": created,
            "updated": len(unique) - created,
        }

    def sync(self, principal: Principal) -> ClassroomSyncRead:
        ensure_classroom_manager(principal)
        self._require_configured()

        row = self._row_for_update(principal.tenant_id)
        if row is None:
            raise AppError(
                ErrorCode.CLASSROOM_NOT_CONNECTED,
                "This workspace has not connected Google Classroom.",
            )
        if row.status != "CONNECTED":
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "Google Classroom must be connected again before courses can be read.",
            )
        if not row.encrypted_access_token:
            self._mark_reconnect(
                row,
                "CLASSROOM_RECONNECT_REQUIRED",
                "The stored Classroom access token is missing.",
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "The stored Classroom access token is missing. Connect Classroom again.",
            )

        box = self._box()
        try:
            access_token = box.decrypt(row.encrypted_access_token)
        except AppError:
            self._mark_reconnect(
                row,
                "CLASSROOM_RECONNECT_REQUIRED",
                "The stored Classroom access token could not be read.",
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "The stored Classroom authorisation could not be read with this "
                "key. Connect Classroom again.",
            ) from None

        expires_at = row.access_token_expires_at
        if expires_at is not None and expires_at <= utcnow() + _EXPIRY_SKEW:
            access_token = self._refresh(principal, row, box)

        try:
            listing = list_courses(
                self.cloud, access_token, max_courses=self.cloud.max_courses
            )
        except ClassroomUpstreamError as error:
            if error.kind in {
                UpstreamKind.RECONNECT_REQUIRED,
                UpstreamKind.SCOPE_MISSING,
            }:
                self._mark_reconnect(
                    row,
                    "CLASSROOM_RECONNECT_REQUIRED"
                    if error.kind == UpstreamKind.RECONNECT_REQUIRED
                    else "CLASSROOM_SCOPE_MISSING",
                    error.message,
                )
            else:
                self._mark_failure(
                    row,
                    "CLASSROOM_UPSTREAM_ERROR",
                    error.message,
                )
            self._audit(
                principal,
                row.id,
                "classroom.sync.failed",
                {
                    "result": "FAILED",
                    "error_code": row.last_error_code,
                    "truncated": False,
                },
            )
            self.session.commit()
            self._raise_upstream(error)

        now = utcnow()
        counts = self._upsert(principal, listing.courses, now)
        row.last_synced_at = now
        row.last_sync_status = "SUCCEEDED"
        row.last_sync_counts = counts
        row.last_error_code = None
        row.last_error_message = None
        self._audit(
            principal,
            row.id,
            "classroom.sync.succeeded",
            {
                "result": "SUCCEEDED",
                "counts": counts,
                "truncated": listing.truncated,
            },
        )
        self.session.commit()
        return ClassroomSyncRead(
            status="SUCCEEDED",
            synced_at=now,
            counts=SyncCountsRead(**counts),
            truncated=listing.truncated,
            courses=[
                SyncedCourseRead(
                    course_id=course.course_id,
                    name=course.name,
                    section=course.section,
                    course_state=course.course_state,
                )
                for course in listing.courses
            ],
        )

    # -- disconnection ---------------------------------------------------
    def disconnect(self, principal: Principal) -> ClassroomDisconnectRead:
        ensure_classroom_manager(principal)
        row = self._row_for_update(principal.tenant_id)
        if row is None:
            raise AppError(
                ErrorCode.CLASSROOM_NOT_CONNECTED,
                "This workspace has not connected Google Classroom.",
            )

        revoked = False
        box: SecretBox | None
        try:
            box = self._box()
        except AppError:
            box = None
        if box is not None:
            token: str | None = None
            if row.encrypted_refresh_token:
                try:
                    token = box.decrypt(row.encrypted_refresh_token)
                except AppError:
                    token = None
            if token is None and row.encrypted_access_token:
                try:
                    token = box.decrypt(row.encrypted_access_token)
                except AppError:
                    token = None
            if token is not None and self.cloud.configured():
                revoked = revoke_token(self.cloud, token)

        row.encrypted_access_token = None
        row.encrypted_refresh_token = None
        row.access_token_expires_at = None
        row.scopes = []
        row.status = "RECONNECT_REQUIRED"
        row.last_error_code = "DISCONNECTED"
        row.last_error_message = _safe_message(
            "The workspace disconnected Google Classroom. Authorise again to "
            "sync courses."
        )
        self._audit(
            principal,
            row.id,
            "classroom.connection_disconnected",
            {"result": "SUCCEEDED", "revoked_at_google": revoked},
        )
        self.session.commit()
        return ClassroomDisconnectRead(
            status="RECONNECT_REQUIRED", revoked=revoked
        )
