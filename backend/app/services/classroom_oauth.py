"""The platform's central Google Classroom authorisation.

There is one Google account, connected once by platform administration.  Every
Classroom read and write in Aetrix uses it, so no teacher authorises a personal
account and no workspace owns a credential.

The OAuth state is Fernet-encrypted and carries the nonce, workspace and subject
that started the flow; the authenticated callback refuses a state issued for
anyone else.  Only a platform administrator may start, complete, sync or
disconnect: a workspace owner's authority stops at their own tenant.

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
from ..core.logging import request_id_var
from ..core.security import Principal, SecretBox, platform_authority
from ..db.models import (
    ClassroomClass,
    ClassroomConnection,
    ClassroomSyncRun,
    PlatformAuditEvent,
)
from ..schemas.classroom_oauth import (
    ClassroomAuthorizationStart,
    ClassroomConnectionRead,
    ClassroomDisconnectRead,
    ClassroomSyncRead,
    SyncCountsRead,
    SyncedCourseRead,
)
from .classroom_google import (
    REQUIRED_SCOPES,
    ClassroomUpstreamError,
    DiscoveredCourse,
    UpstreamKind,
    authorization_url,
    exchange_code,
    get_account_identity,
    list_courses,
    missing_scopes,
    refresh_access_token,
    revoke_token,
)

#: The singleton discriminator.  A platform deployment has exactly one row.
PLATFORM_CONNECTION_KEY = "platform"
_STATE_VERSION = 1
_UPSERT_CHUNK = 500
#: Refresh a little before Google's expiry so an in-flight read cannot expire.
_EXPIRY_SKEW = timedelta(seconds=60)


def ensure_classroom_manager(principal: Principal) -> None:
    """Only platform administration controls the central connection."""

    if platform_authority(principal) in {"ADMIN", "PLATFORM_OWNER"}:
        return
    raise AppError(
        ErrorCode.FORBIDDEN,
        "The Google Classroom connection is managed by platform administration, "
        "not by a workspace.",
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
    """Bind a nonce, workspace, subject and platform role into an opaque state."""

    expires_at = utcnow() + timedelta(seconds=settings.classroom.state_ttl_seconds)
    payload = json.dumps(
        {
            "v": _STATE_VERSION,
            "tenant_id": str(principal.tenant_id),
            "subject": principal.subject,
            "platform_role": platform_authority(principal),
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
    if data.get("platform_role") != platform_authority(principal):
        # A grant started by a platform owner cannot be completed by an account
        # whose authority changed in between.
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


def _platform_audit(
    session: Session,
    principal: Principal,
    action: str,
    detail: dict[str, object],
    *,
    target: str = PLATFORM_CONNECTION_KEY,
) -> None:
    session.add(
        PlatformAuditEvent(
            actor_user_id=principal.user_id,
            actor_subject=principal.subject,
            actor_platform_role=platform_authority(principal) or principal.role,
            action=action,
            target_subject=target,
            target_email=None,
            detail=detail,
            request_id=request_id_var.get(),
            created_at=utcnow(),
        )
    )


class ClassroomOAuthService:
    def __init__(
        self, session: Session, settings: Settings, *, transport: object | None = None
    ) -> None:
        self.session = session
        self.settings = settings
        self.cloud = settings.classroom
        self.audit = AuditService(session)
        #: Injected in tests so no request reaches Google.
        self.transport = transport  # type: ignore[assignment]

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

    def _row(self) -> ClassroomConnection | None:
        return self.session.scalar(
            select(ClassroomConnection).where(
                ClassroomConnection.connection_key == PLATFORM_CONNECTION_KEY
            )
        )

    def _row_for_update(self) -> ClassroomConnection | None:
        return self.session.scalar(
            select(ClassroomConnection)
            .where(ClassroomConnection.connection_key == PLATFORM_CONNECTION_KEY)
            .with_for_update()
        )

    def _recent_runs(self, limit: int = 10) -> list[ClassroomSyncRun]:
        return list(
            self.session.scalars(
                select(ClassroomSyncRun)
                .where(
                    ClassroomSyncRun.kind == "COURSES",
                    ClassroomSyncRun.tenant_id.is_(None),
                )
                .order_by(ClassroomSyncRun.started_at.desc())
                .limit(limit)
            )
        )

    def _read(self, row: ClassroomConnection | None) -> ClassroomConnectionRead:
        configured = self.cloud.configured()
        runs = self._recent_runs()
        if row is None:
            return ClassroomConnectionRead(
                configured=configured,
                status="NOT_CONNECTED",
                redirect_uri=self.cloud.redirect_uri,
                required_scopes=list(REQUIRED_SCOPES),
                granted_scopes=[],
                missing_scopes=list(REQUIRED_SCOPES),
                connected_at=None,
                connected_by_subject=None,
                connected_account_email=None,
                connected_account_name=None,
                last_refresh_at=None,
                last_synced_at=None,
                last_sync_status=None,
                last_sync_counts={},
                last_error_code=None,
                last_error_message=None,
                recent_runs=[],
            )
        granted = list(row.scopes or [])
        return ClassroomConnectionRead(
            configured=configured,
            status=row.status,
            redirect_uri=self.cloud.redirect_uri,
            required_scopes=list(REQUIRED_SCOPES),
            granted_scopes=granted,
            missing_scopes=missing_scopes(granted),
            connected_at=row.connected_at,
            connected_by_subject=row.connected_by_subject,
            connected_account_email=row.connected_account_email,
            connected_account_name=row.connected_account_name,
            last_refresh_at=row.last_refresh_at,
            last_synced_at=row.last_synced_at,
            last_sync_status=row.last_sync_status,
            last_sync_counts=dict(row.last_sync_counts or {}),
            last_error_code=row.last_error_code,
            last_error_message=row.last_error_message,
            recent_runs=[
                {
                    "id": str(run.id),
                    "status": run.status,
                    "counts": dict(run.counts or {}),
                    "error_code": run.error_code,
                    "error_message": run.error_message,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                }
                for run in runs
            ],
        )

    def _raise_upstream(self, error: ClassroomUpstreamError) -> NoReturn:
        if error.kind == UpstreamKind.RECONNECT_REQUIRED:
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "Google rejected the stored Classroom authorisation. Connect "
                "the central Google account again.",
            )
        if error.kind == UpstreamKind.SCOPE_MISSING:
            raise AppError(
                ErrorCode.CLASSROOM_SCOPE_MISSING,
                "The Classroom authorisation is missing a permission this "
                "operation needs. Authorise again and accept every Classroom "
                "permission.",
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

    # -- reads -----------------------------------------------------------
    def connection(self, principal: Principal) -> ClassroomConnectionRead:
        ensure_classroom_manager(principal)
        return self._read(self._row())

    # -- authorisation ---------------------------------------------------
    def start(self, principal: Principal) -> ClassroomAuthorizationStart:
        ensure_classroom_manager(principal)
        self._require_configured()
        state, expires_at = issue_state(self.settings, principal)
        return ClassroomAuthorizationStart(
            authorization_url=authorization_url(self.cloud, state),
            expires_at=expires_at,
            redirect_uri=self.cloud.redirect_uri or "",
            scopes=list(REQUIRED_SCOPES),
        )

    def complete(
        self, principal: Principal, *, code: str, state: str
    ) -> ClassroomConnectionRead:
        ensure_classroom_manager(principal)
        self._require_configured()
        verify_state(self.settings, state, principal)

        try:
            grant = exchange_code(
                self.cloud, code, transport=self.transport  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            self._raise_upstream(error)

        absent = missing_scopes(grant.scopes)
        if absent:
            # Google issued a token without a scope this integration needs.
            # Give it back rather than storing an authorisation that cannot
            # perform a single Classroom write.
            revoke_token(
                self.cloud,
                grant.access_token,
                transport=self.transport,  # type: ignore[arg-type]
            )
            self._record_run(
                principal,
                kind="COURSES",
                status="FAILED",
                counts={"missing_scopes": len(absent)},
                error_code=str(ErrorCode.CLASSROOM_SCOPE_MISSING),
                error_message="Consent was granted without every required scope.",
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_SCOPE_MISSING,
                "Google did not grant every Classroom permission this integration "
                "needs. Authorise again and leave every Classroom checkbox "
                "selected.",
                details={"missing_scopes": absent},
            )

        email, name = get_account_identity(
            self.cloud,
            grant.access_token,
            transport=self.transport,  # type: ignore[arg-type]
        )

        box = self._box()
        now = utcnow()
        row = self._row_for_update()
        if row is None:
            row = ClassroomConnection(
                connection_key=PLATFORM_CONNECTION_KEY,
                tenant_id=None,
                status="CONNECTED",
                connected_by_subject=principal.subject,
                connected_at=now,
                last_sync_counts={},
                requested_scopes=list(REQUIRED_SCOPES),
            )
            self.session.add(row)
        row.encrypted_access_token = box.encrypt(grant.access_token)
        if grant.refresh_token:
            row.encrypted_refresh_token = box.encrypt(grant.refresh_token)
        row.access_token_expires_at = grant.expires_at
        row.scopes = list(grant.scopes)
        row.requested_scopes = list(REQUIRED_SCOPES)
        row.status = "CONNECTED"
        row.connected_at = now
        row.connected_by_subject = principal.subject
        row.connected_account_email = email or row.connected_account_email
        row.connected_account_name = name or row.connected_account_name
        row.last_refresh_at = now
        row.last_error_code = None
        row.last_error_message = None
        self.session.flush()
        _platform_audit(
            self.session,
            principal,
            "classroom.connection_authorized",
            {
                "scopes": list(grant.scopes),
                "connected_by_subject": principal.subject,
                "connected_account_email": email,
                "result": "SUCCEEDED",
            },
        )
        self.session.commit()
        self.session.refresh(row)
        return self._read(row)

    # -- credential access for the other Classroom services ---------------
    def access_token(self) -> str:
        """A usable bearer token, refreshing it when it is close to expiry.

        Raises ``CLASSROOM_NOT_CONNECTED`` or ``CLASSROOM_RECONNECT_REQUIRED``;
        never returns a token whose grant Google has rejected.
        """

        self._require_configured()
        row = self._row_for_update()
        if row is None:
            raise AppError(
                ErrorCode.CLASSROOM_NOT_CONNECTED,
                "The platform has not connected the central Google account.",
            )
        if row.status != "CONNECTED":
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "The central Google Classroom connection must be authorised "
                "again before Classroom can be used.",
            )
        if not row.encrypted_access_token:
            self._mark_reconnect(
                row,
                str(ErrorCode.CLASSROOM_RECONNECT_REQUIRED),
                "The stored Classroom access token is missing.",
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "The stored Classroom access token is missing. Connect the "
                "central Google account again.",
            )

        box = self._box()
        try:
            token = box.decrypt(row.encrypted_access_token)
        except AppError:
            self._mark_reconnect(
                row,
                str(ErrorCode.CLASSROOM_RECONNECT_REQUIRED),
                "The stored Classroom access token could not be read.",
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "The stored Classroom authorisation could not be read with this "
                "key. Connect the central Google account again.",
            ) from None

        expires_at = row.access_token_expires_at
        if expires_at is not None and expires_at <= utcnow() + _EXPIRY_SKEW:
            return self._refresh(row, box)
        return token

    def _refresh(
        self, row: ClassroomConnection, box: SecretBox
    ) -> str:
        if not row.encrypted_refresh_token:
            self._mark_reconnect(
                row,
                str(ErrorCode.CLASSROOM_RECONNECT_REQUIRED),
                "The stored Classroom authorisation expired and Google issued "
                "no refresh token. Connect the central account again.",
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                "The stored Classroom authorisation expired. Connect the central "
                "Google account again.",
            )

        refresh_token = box.decrypt(row.encrypted_refresh_token)
        try:
            grant = refresh_access_token(
                self.cloud,
                refresh_token,
                transport=self.transport,  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            if error.kind in {
                UpstreamKind.RECONNECT_REQUIRED,
                UpstreamKind.SCOPE_MISSING,
            }:
                self._mark_reconnect(
                    row,
                    str(ErrorCode.CLASSROOM_RECONNECT_REQUIRED),
                    "Google rejected the stored Classroom refresh token.",
                )
            else:
                self._mark_failure(
                    row,
                    str(ErrorCode.CLASSROOM_UPSTREAM_ERROR),
                    "Google could not refresh the Classroom authorisation.",
                )
            self.session.commit()
            self._raise_upstream(error)

        row.encrypted_access_token = box.encrypt(grant.access_token)
        if grant.refresh_token:
            row.encrypted_refresh_token = box.encrypt(grant.refresh_token)
        row.access_token_expires_at = grant.expires_at
        if grant.scopes:
            row.scopes = list(grant.scopes)
        row.last_refresh_at = utcnow()
        return grant.access_token

    # -- synchronisation history ------------------------------------------
    def _record_run(
        self,
        principal: Principal,
        *,
        kind: str,
        status: str,
        counts: dict[str, int],
        error_code: str | None = None,
        error_message: str | None = None,
        tenant_id: UUID | None = None,
        course_id: str | None = None,
        coursework_link_id: UUID | None = None,
    ) -> ClassroomSyncRun:
        now = utcnow()
        run = ClassroomSyncRun(
            tenant_id=tenant_id,
            kind=kind,
            status=status,
            course_id=course_id,
            coursework_link_id=coursework_link_id,
            actor_subject=principal.subject,
            counts=counts,
            error_code=error_code,
            error_message=error_message,
            started_at=now,
            finished_at=now if status != "RUNNING" else None,
        )
        self.session.add(run)
        return run

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
        *,
        teacher_name: str | None,
        teacher_email: str | None,
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
                        "owner_email": teacher_email,
                        "teacher_name": teacher_name,
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
                    "owner_email": statement.excluded.owner_email,
                    "teacher_name": statement.excluded.teacher_name,
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

        try:
            access_token = self.access_token()
        except AppError:
            row = self._row()
            if row is not None:
                _platform_audit(
                    self.session,
                    principal,
                    "classroom.sync.failed",
                    {
                        "result": "FAILED",
                        "error_code": row.last_error_code
                        or str(ErrorCode.CLASSROOM_NOT_CONNECTED),
                    },
                )
                self.session.commit()
            raise

        row = self._row_for_update()
        assert row is not None

        try:
            listing = list_courses(
                self.cloud,
                access_token,
                max_courses=self.cloud.max_courses,
                transport=self.transport,  # type: ignore[arg-type]
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
            self._record_run(
                principal,
                kind="COURSES",
                status="FAILED",
                counts={"discovered": 0},
                error_code=row.last_error_code,
                error_message=row.last_error_message,
            )
            _platform_audit(
                self.session,
                principal,
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
        counts = self._upsert(
            principal,
            listing.courses,
            now,
            teacher_name=row.connected_account_name,
            teacher_email=row.connected_account_email,
        )
        row.last_synced_at = now
        row.last_sync_status = "SUCCEEDED"
        row.last_sync_counts = counts
        row.last_error_code = None
        row.last_error_message = None
        self._record_run(
            principal,
            kind="COURSES",
            status="PARTIAL" if listing.truncated else "SUCCEEDED",
            counts=counts,
        )
        _platform_audit(
            self.session,
            principal,
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
        row = self._row_for_update()
        if row is None:
            raise AppError(
                ErrorCode.CLASSROOM_NOT_CONNECTED,
                "The platform has not connected the central Google account.",
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
                revoked = revoke_token(
                    self.cloud,
                    token,
                    transport=self.transport,  # type: ignore[arg-type]
                )

        row.encrypted_access_token = None
        row.encrypted_refresh_token = None
        row.access_token_expires_at = None
        row.scopes = []
        row.status = "RECONNECT_REQUIRED"
        row.last_error_code = "DISCONNECTED"
        row.last_error_message = _safe_message(
            "Platform administration disconnected the central Google account. "
            "Authorise again to use Classroom."
        )
        _platform_audit(
            self.session,
            principal,
            "classroom.connection_disconnected",
            {"result": "SUCCEEDED", "revoked_at_google": revoked},
        )
        self.session.commit()
        return ClassroomDisconnectRead(
            status="RECONNECT_REQUIRED", revoked=revoked
        )
