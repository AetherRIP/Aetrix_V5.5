"""Platform-level account administration through Supabase Auth.

Accounts are Supabase identities.  Aetrix keeps workspace membership rows, not a
second identity record, so this service reads identities from the Supabase Auth
administration API and joins Aetrix memberships by ``User.subject``.

Three rules govern the module:

* a missing administrative credential is a *reported state*
  (``ADMIN_NOT_CONFIGURED``), never a fabricated account list and never the
  workspace member list dressed up as every platform account;
* the service-role key stays inside this process — it is read from settings at
  the point of use and is never returned, logged or sent to a browser;
* every mutation is authorized here from the verified platform claim and
  recorded in ``platform_audit_events`` before the caller sees success.

Supabase Auth (GoTrue) exposes no service-role endpoint that revokes another
account's sessions, so that operation reports ``NOT_SUPPORTED`` rather than
pretending to have signed someone out.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import PlatformAdminSettings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.logging import get_logger, request_id_var
from ..core.security import Principal, platform_authority
from ..db.models import Invitation, PlatformAuditEvent, Tenant, User
from ..schemas.admin_accounts import (
    AccountActionRead,
    AccountAuditRead,
    AccountCapabilityRead,
    AccountDeletion,
    AccountInvitationRead,
    AccountMembershipRead,
    AccountOperationRead,
    AccountPage,
    AccountQuery,
    AccountRoleUpdate,
    AccountStatusUpdate,
    PlatformAccountDetail,
    PlatformAccountRead,
)

log = get_logger("aetrix.platform_accounts")

#: Roles stored in ``app_metadata.aetrix_role``.  ``owner`` is included so an
#: owner can be recognised and protected, but it is never assignable here.
ACCOUNT_ROLES: tuple[str, ...] = (
    "owner",
    "platform_operator",
    "supervisor",
    "assistant",
    "viewer",
)

#: What the owner may grant through this interface.
MANAGEABLE_ROLES: frozenset[str] = frozenset(
    {"platform_operator", "supervisor", "assistant", "viewer"}
)

#: What a platform administrator (not the owner) may grant.
ADMIN_MANAGEABLE_ROLES: frozenset[str] = frozenset({"supervisor", "assistant", "viewer"})

#: Supabase's ``ban_duration`` for an indefinite suspension: 100 years.  The
#: account cannot sign in again until an administrator reactivates it.
SUSPENDED_BAN_DURATION = "876000h"

_SOURCE = "supabase-auth"

ADMIN_NOT_CONFIGURED_MESSAGE = (
    "Platform-wide account management needs a Supabase service-role key, which is "
    "not configured on this engine. Set AETRIX_PLATFORM_ADMIN__SUPABASE_URL and "
    "AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY in the engine's secret environment. "
    "The browser never receives this key, and workspace features are unaffected."
)


# ---------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------


def account_role(app_metadata: Any) -> str:
    """The account's platform role from ``app_metadata``, or ``unassigned``.

    ``user_metadata`` is writable by the account itself and is deliberately not
    consulted.  Older Aetrix spellings are read but never written back.
    """

    metadata = app_metadata if isinstance(app_metadata, dict) else {}
    value = metadata.get("aetrix_role")
    if isinstance(value, str):
        normalised = {
            "PLATFORM_OWNER": "owner",
            "ADMIN": "platform_operator",
        }.get(value, value)
        if normalised in ACCOUNT_ROLES:
            return normalised
    return "unassigned"


def _parse_instant(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def account_status(user: dict[str, Any], now: datetime | None = None) -> str:
    """Derive account status from the identity provider's own fields.

    A suspension is a live ban; an account that has never confirmed its address
    is ``UNCONFIRMED``.  Nothing here is stored locally, so the status cannot
    drift from Supabase.
    """

    moment = now or utcnow()
    banned_until = _parse_instant(user.get("banned_until"))
    if banned_until is not None and banned_until > moment:
        return "SUSPENDED"
    confirmed = _parse_instant(user.get("email_confirmed_at")) or _parse_instant(
        user.get("confirmed_at")
    )
    if confirmed is None:
        return "UNCONFIRMED"
    return "ACTIVE"


def _display_name(user: dict[str, Any]) -> str | None:
    metadata = user.get("user_metadata")
    if isinstance(metadata, dict):
        for key in ("display_name", "full_name", "name"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
    return None


# ---------------------------------------------------------------------------
# Authorization policy
# ---------------------------------------------------------------------------


def ensure_platform_admin(principal: Principal) -> None:
    if platform_authority(principal) not in {"ADMIN", "PLATFORM_OWNER"}:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Platform account administration is restricted to platform owners "
            "and administrators.",
        )


def ensure_platform_owner(principal: Principal) -> None:
    if platform_authority(principal) != "PLATFORM_OWNER":
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Only the platform owner may perform that operation.",
        )


def ensure_role_change(
    *, actor: Principal, target_id: str, current_role: str, new_role: str
) -> None:
    authority = platform_authority(actor)
    ensure_platform_admin(actor)
    if current_role == "owner":
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Platform ownership is assigned by the identity-provider operator and "
            "cannot be changed through this interface.",
        )
    if target_id == actor.subject:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "An administrator cannot change their own platform role.",
        )
    if authority == "ADMIN":
        if current_role == "platform_operator":
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only the platform owner may change another administrator's role.",
            )
        if new_role not in ADMIN_MANAGEABLE_ROLES:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "A platform administrator may grant teacher, assistant or viewer "
                "roles only.",
                details={"grantable": sorted(ADMIN_MANAGEABLE_ROLES)},
            )
        return
    if new_role not in MANAGEABLE_ROLES:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "That platform role cannot be granted through this interface.",
            details={"grantable": sorted(MANAGEABLE_ROLES)},
        )


def ensure_status_change(*, actor: Principal, target_id: str, current_role: str) -> None:
    authority = platform_authority(actor)
    ensure_platform_admin(actor)
    if target_id == actor.subject:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "An administrator cannot suspend or reactivate their own account.",
        )
    if current_role == "owner":
        raise AppError(
            ErrorCode.FORBIDDEN,
            "The platform owner's account cannot be suspended here.",
        )
    if authority == "ADMIN" and current_role == "platform_operator":
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Only the platform owner may suspend another administrator.",
        )


def ensure_deletion(*, actor: Principal, target_id: str, current_role: str) -> None:
    ensure_platform_owner(actor)
    if target_id == actor.subject:
        raise AppError(
            ErrorCode.FORBIDDEN, "The platform owner cannot delete their own account."
        )
    if current_role == "owner":
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Platform ownership is assigned by the identity-provider operator; an "
            "owner account cannot be deleted through this interface.",
        )


# ---------------------------------------------------------------------------
# Supabase Auth admin client
# ---------------------------------------------------------------------------


class PlatformAdminClient:
    """Thin GoTrue ``/auth/v1/admin`` client carrying the service-role key.

    Failures are translated into the API's closed error vocabulary.  Upstream
    response bodies are never forwarded: they can echo the credential or another
    account's fields.
    """

    def __init__(
        self,
        url: str,
        service_key: str,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=url.rstrip("/") + "/auth/v1",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
                "Content-Type": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> PlatformAdminClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.request(method, path, json=json, params=params)
        except httpx.HTTPError as error:
            raise AppError(
                ErrorCode.ADMIN_UPSTREAM_ERROR,
                "Supabase Auth could not be reached from the engine, so no account "
                "data was read or changed.",
            ) from error
        if response.status_code == 404:
            raise AppError(
                ErrorCode.NOT_FOUND, "That account does not exist in Supabase Auth."
            )
        if response.status_code in {401, 403}:
            raise AppError(
                ErrorCode.ADMIN_UPSTREAM_ERROR,
                "Supabase Auth rejected the administrative credential. Check that "
                "AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY holds the project's "
                "service-role key.",
            )
        if response.status_code == 429:
            raise AppError(
                ErrorCode.ADMIN_UPSTREAM_ERROR,
                "Supabase Auth is rate limiting administrative requests; try again "
                "shortly.",
            )
        if response.status_code >= 400:
            raise AppError(
                ErrorCode.ADMIN_UPSTREAM_ERROR,
                "Supabase Auth refused the administrative request "
                f"(HTTP {response.status_code}).",
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise AppError(
                ErrorCode.ADMIN_UPSTREAM_ERROR,
                "Supabase Auth returned a response that could not be read.",
            ) from error

    def list_users(self, *, page: int, per_page: int) -> Any:
        return self._request(
            "GET", "/admin/users", params={"page": page, "per_page": per_page}
        )

    def get_user(self, user_id: str) -> Any:
        return self._request("GET", f"/admin/users/{user_id}")

    def update_user(self, user_id: str, payload: dict[str, Any]) -> Any:
        return self._request("PUT", f"/admin/users/{user_id}", json=payload)

    def delete_user(self, user_id: str) -> Any:
        return self._request("DELETE", f"/admin/users/{user_id}")

    def invite(self, email: str) -> Any:
        return self._request("POST", "/invite", json={"email": email})

    def recover(self, email: str) -> Any:
        return self._request("POST", "/recover", json={"email": email})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

ClientFactory = Callable[[], PlatformAdminClient]


def fetch_all_accounts(
    settings: PlatformAdminSettings,
    *,
    client_factory: ClientFactory | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Every Supabase account, bounded by the configured ceiling.

    Shared by account management and the platform overview census so both read
    the same identity source and apply the same ceiling.  Raises
    ``ADMIN_NOT_CONFIGURED`` when there is no service-role credential: callers
    must report that state, never substitute workspace rows.
    """

    if not settings.configured():
        raise AppError(ErrorCode.ADMIN_NOT_CONFIGURED, ADMIN_NOT_CONFIGURED_MESSAGE)
    if client_factory is not None:
        client = client_factory()
    else:
        assert settings.supabase_url is not None
        assert settings.service_role_key is not None
        client = PlatformAdminClient(
            settings.supabase_url,
            settings.service_role_key.get_secret_value(),
            timeout=settings.timeout_seconds,
        )

    users: list[dict[str, Any]] = []
    truncated = False
    with client:
        page = 1
        while True:
            batch = client.list_users(page=page, per_page=settings.page_size)
            if isinstance(batch, dict):
                batch = batch.get("users")
            if not isinstance(batch, list):
                raise AppError(
                    ErrorCode.ADMIN_UPSTREAM_ERROR,
                    "Supabase Auth returned an account list the engine could not "
                    "read.",
                )
            users.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < settings.page_size:
                break
            if len(users) >= settings.max_accounts:
                truncated = True
                break
            page += 1
            if page > 1000:  # pragma: no cover - defensive loop bound
                truncated = True
                break
    if len(users) > settings.max_accounts:
        users = users[: settings.max_accounts]
        truncated = True
    return users, truncated


class PlatformAccountService:
    def __init__(
        self,
        session: Session,
        settings: PlatformAdminSettings,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self._client_factory = client_factory

    # -- capability ------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self.settings.configured()

    def _client(self) -> PlatformAdminClient:
        if not self.configured:
            raise AppError(ErrorCode.ADMIN_NOT_CONFIGURED, ADMIN_NOT_CONFIGURED_MESSAGE)
        if self._client_factory is not None:
            return self._client_factory()
        assert self.settings.supabase_url is not None
        assert self.settings.service_role_key is not None
        return PlatformAdminClient(
            self.settings.supabase_url,
            self.settings.service_role_key.get_secret_value(),
            timeout=self.settings.timeout_seconds,
        )

    def capability(self) -> AccountCapabilityRead:
        configured = self.configured
        reason = (
            "Reading accounts and changing them happens through the Supabase Auth "
            "administration API with a server-side service-role key."
            if configured
            else "AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY and "
            "AETRIX_PLATFORM_ADMIN__SUPABASE_URL are not set on the engine, so "
            "platform-wide accounts cannot be read. Workspace features are "
            "unaffected."
        )
        return AccountCapabilityRead(
            configured=configured,
            reason=reason,
            operations=[
                AccountOperationRead(
                    name="list and inspect accounts",
                    supported=configured,
                    note="Supabase Auth users, including creation, confirmation, "
                    "last sign-in and ban state.",
                ),
                AccountOperationRead(
                    name="change platform role",
                    supported=configured,
                    note="Writes app_metadata.aetrix_role. Platform ownership is "
                    "never assignable here.",
                ),
                AccountOperationRead(
                    name="suspend and reactivate",
                    supported=configured,
                    note="Uses Supabase's ban_duration; suspension also invalidates "
                    "new sign-ins.",
                ),
                AccountOperationRead(
                    name="resend invitation",
                    supported=configured,
                    note="Supabase /invite, for accounts that never confirmed their "
                    "address.",
                ),
                AccountOperationRead(
                    name="send recovery email",
                    supported=configured,
                    note="Supabase /recover; the email is delivered by Supabase and no "
                    "link is returned to the engine.",
                ),
                AccountOperationRead(
                    name="revoke sessions",
                    supported=False,
                    note="Supabase Auth has no service-role endpoint to revoke "
                    "another account's sessions. Suspend the account instead; its "
                    "current access token expires on its own.",
                ),
                AccountOperationRead(
                    name="delete account",
                    supported=configured,
                    note="Owner only, confirmed by re-typing the account's email. "
                    "Aetrix membership rows are retained as history.",
                ),
            ],
        )

    # -- local context ---------------------------------------------------
    def _local_context(
        self, users: list[dict[str, Any]]
    ) -> tuple[
        dict[str, list[AccountMembershipRead]],
        dict[str, list[AccountInvitationRead]],
    ]:
        memberships: dict[str, list[AccountMembershipRead]] = defaultdict(list)
        invitations: dict[str, list[AccountInvitationRead]] = defaultdict(list)

        subjects = [str(user["id"]) for user in users if user.get("id")]
        if subjects:
            rows = self.session.execute(
                select(User, Tenant)
                .join(Tenant, User.tenant_id == Tenant.id)
                .where(User.subject.in_(subjects))
                .order_by(Tenant.name)
            ).all()
            for user_row, tenant in rows:
                memberships[user_row.subject].append(
                    AccountMembershipRead(
                        tenant_id=str(tenant.id),
                        workspace_name=tenant.name,
                        workspace_slug=tenant.slug,
                        role=user_row.role,
                        is_demo=tenant.is_demo,
                        user_row_id=str(user_row.id),
                        joined_at=user_row.created_at,
                    )
                )

        emails = sorted(
            {str(user["email"]).lower() for user in users if user.get("email")}
        )
        if emails:
            rows = self.session.execute(
                select(Invitation, Tenant)
                .join(Tenant, Invitation.tenant_id == Tenant.id)
                .where(func.lower(Invitation.email).in_(emails))
                .order_by(Invitation.created_at.desc())
            ).all()
            for invitation, tenant in rows:
                invitations[invitation.email.lower()].append(
                    AccountInvitationRead(
                        id=str(invitation.id),
                        email=invitation.email,
                        role=invitation.role,
                        status=invitation.status,
                        tenant_id=str(tenant.id),
                        workspace_name=tenant.name,
                        expires_at=invitation.expires_at,
                        created_at=invitation.created_at,
                    )
                )
        return memberships, invitations

    def _account(
        self,
        user: dict[str, Any],
        memberships: dict[str, list[AccountMembershipRead]],
        invitations: dict[str, list[AccountInvitationRead]],
    ) -> PlatformAccountRead:
        account_id = str(user.get("id") or "")
        email = user.get("email")
        email_key = str(email).lower() if email else ""
        mine = memberships.get(account_id, [])
        pending = [
            invite
            for invite in invitations.get(email_key, [])
            if invite.status == "PENDING"
        ]
        return PlatformAccountRead(
            id=account_id,
            email=email,
            display_name=_display_name(user),
            role=account_role(user.get("app_metadata")),
            status=account_status(user),
            created_at=_parse_instant(user.get("created_at")),
            updated_at=_parse_instant(user.get("updated_at")),
            last_sign_in_at=_parse_instant(user.get("last_sign_in_at")),
            email_confirmed_at=_parse_instant(user.get("email_confirmed_at")),
            banned_until=_parse_instant(user.get("banned_until")),
            memberships=mine,
            workspace_count=len(mine),
            has_workspace=bool(mine),
            pending_invitation_count=len(pending),
        )

    # -- reads -----------------------------------------------------------
    def _fetch_users(self) -> tuple[list[dict[str, Any]], bool]:
        return fetch_all_accounts(self.settings, client_factory=self._client_factory)

    @staticmethod
    def _matches(account: PlatformAccountRead, query: AccountQuery) -> bool:
        if query.q:
            needle = query.q.strip().lower()
            haystack = " ".join(
                part for part in (account.email, account.display_name, account.id) if part
            ).lower()
            if needle and needle not in haystack:
                return False
        if query.role and account.role != query.role:
            return False
        if query.status and account.status != query.status:
            return False
        if query.joined == "yes" and not account.has_workspace:
            return False
        return not (query.joined == "no" and account.has_workspace)

    def list_accounts(self, actor: Principal, query: AccountQuery) -> AccountPage:
        ensure_platform_admin(actor)
        users, truncated = self._fetch_users()
        memberships, invitations = self._local_context(users)
        accounts = [self._account(user, memberships, invitations) for user in users]
        filtered = [account for account in accounts if self._matches(account, query)]
        filtered.sort(
            key=lambda account: (
                account.created_at.timestamp() if account.created_at else 0.0
            ),
            reverse=True,
        )
        start = (query.page - 1) * query.page_size
        return AccountPage(
            items=filtered[start : start + query.page_size],
            total=len(filtered),
            page=query.page,
            page_size=query.page_size,
            source=_SOURCE,
            truncated=truncated,
        )

    def get_account(self, actor: Principal, account_id: str) -> PlatformAccountDetail:
        ensure_platform_admin(actor)
        with self._client() as client:
            user = client.get_user(account_id)
        if not isinstance(user, dict) or not user.get("id"):
            raise AppError(
                ErrorCode.ADMIN_UPSTREAM_ERROR,
                "Supabase Auth returned an account record the engine could not read.",
            )
        memberships, invitations = self._local_context([user])
        account = self._account(user, memberships, invitations)
        email_key = str(account.email).lower() if account.email else ""
        audit_rows = self.session.scalars(
            select(PlatformAuditEvent)
            .where(PlatformAuditEvent.target_subject == account_id)
            .order_by(PlatformAuditEvent.created_at.desc())
            .limit(25)
        ).all()
        # Reading another account's details is itself a sensitive action; record
        # it without turning ordinary self-inspection into audit noise.
        if actor.subject != account_id:
            self._record(
                actor,
                "account.inspected",
                account_id,
                account.email,
                {"via": "platform_account_management"},
            )
        return PlatformAccountDetail(
            **account.model_dump(),
            invitations=invitations.get(email_key, []),
            audit=[
                AccountAuditRead(
                    id=str(row.id),
                    action=row.action,
                    actor_subject=row.actor_subject,
                    actor_platform_role=row.actor_platform_role,
                    target_subject=row.target_subject,
                    target_email=row.target_email,
                    detail=dict(row.detail or {}),
                    created_at=row.created_at,
                )
                for row in audit_rows
            ],
        )

    # -- audit -----------------------------------------------------------
    def _record(
        self,
        actor: Principal,
        action: str,
        target_id: str,
        target_email: str | None,
        detail: dict[str, Any],
    ) -> None:
        self.session.add(
            PlatformAuditEvent(
                actor_user_id=actor.user_id,
                actor_subject=actor.subject,
                actor_platform_role=platform_authority(actor) or actor.role,
                action=action,
                target_subject=target_id,
                target_email=target_email,
                detail=detail,
                request_id=request_id_var.get(),
                created_at=utcnow(),
            )
        )
        self.session.commit()
        log.info(
            "platform account action recorded",
            extra={"extra_fields": {"action": action, "target": target_id}},
        )

    # -- mutations -------------------------------------------------------
    def update_role(
        self, actor: Principal, account_id: str, payload: AccountRoleUpdate
    ) -> PlatformAccountDetail:
        ensure_platform_admin(actor)
        with self._client() as client:
            target = client.get_user(account_id)
        if not isinstance(target, dict) or not target.get("id"):
            raise AppError(ErrorCode.NOT_FOUND, "That account does not exist.")
        current = account_role(target.get("app_metadata"))
        ensure_role_change(
            actor=actor,
            target_id=str(target["id"]),
            current_role=current,
            new_role=payload.role,
        )
        metadata = dict(target.get("app_metadata") or {})
        metadata["aetrix_role"] = payload.role
        with self._client() as client:
            client.update_user(account_id, {"app_metadata": metadata})
        self._record(
            actor,
            "account.role_changed",
            account_id,
            target.get("email"),
            {"previous_role": current, "role": payload.role, "reason": payload.reason},
        )
        return self.get_account(actor, account_id)

    def set_status(
        self, actor: Principal, account_id: str, payload: AccountStatusUpdate
    ) -> PlatformAccountDetail:
        ensure_platform_admin(actor)
        with self._client() as client:
            target = client.get_user(account_id)
        if not isinstance(target, dict) or not target.get("id"):
            raise AppError(ErrorCode.NOT_FOUND, "That account does not exist.")
        current = account_role(target.get("app_metadata"))
        ensure_status_change(
            actor=actor, target_id=str(target["id"]), current_role=current
        )
        suspended = payload.status == "SUSPENDED"
        with self._client() as client:
            client.update_user(
                account_id,
                {"ban_duration": SUSPENDED_BAN_DURATION if suspended else "none"},
            )
        self._record(
            actor,
            "account.suspended" if suspended else "account.reactivated",
            account_id,
            target.get("email"),
            {"role": current, "reason": payload.reason},
        )
        return self.get_account(actor, account_id)

    def resend_invitation(
        self, actor: Principal, account_id: str
    ) -> AccountActionRead:
        ensure_platform_admin(actor)
        with self._client() as client:
            target = client.get_user(account_id)
        email = target.get("email") if isinstance(target, dict) else None
        if not email:
            raise AppError(
                ErrorCode.CONFLICT, "That account has no email address to invite."
            )
        if account_status(target) != "UNCONFIRMED":
            raise AppError(
                ErrorCode.CONFLICT,
                "That account has already confirmed its address; send a recovery "
                "email instead.",
            )
        with self._client() as client:
            client.invite(str(email))
        role = account_role(target.get("app_metadata"))
        self._record(
            actor, "account.invitation_resent", account_id, email, {"role": role}
        )
        return AccountActionRead(
            status="INVITATION_SENT",
            message=f"Supabase accepted a fresh invitation for {email}.",
        )

    def request_recovery(
        self, actor: Principal, account_id: str
    ) -> AccountActionRead:
        ensure_platform_owner(actor)
        with self._client() as client:
            target = client.get_user(account_id)
        email = target.get("email") if isinstance(target, dict) else None
        if not email:
            raise AppError(
                ErrorCode.CONFLICT, "That account has no email address to recover."
            )
        with self._client() as client:
            client.recover(str(email))
        self._record(
            actor,
            "account.recovery_requested",
            account_id,
            email,
            {"role": account_role(target.get("app_metadata"))},
        )
        return AccountActionRead(
            status="RECOVERY_SENT",
            message=f"Supabase accepted a recovery email for {email}. The link is "
            "delivered by email and never returned to this interface.",
        )

    def revoke_sessions(self, actor: Principal, account_id: str) -> AccountActionRead:
        ensure_platform_admin(actor)
        raise AppError(
            ErrorCode.NOT_SUPPORTED,
            "Supabase Auth does not expose a service-role endpoint that revokes "
            "another account's sessions: only the account's own token can sign it "
            "out. Suspend the account to block new sign-ins; its current access "
            "token expires on its own.",
        )

    def delete_account(
        self, actor: Principal, account_id: str, payload: AccountDeletion
    ) -> AccountActionRead:
        ensure_platform_owner(actor)
        with self._client() as client:
            target = client.get_user(account_id)
        if not isinstance(target, dict) or not target.get("id"):
            raise AppError(ErrorCode.NOT_FOUND, "That account does not exist.")
        current = account_role(target.get("app_metadata"))
        ensure_deletion(
            actor=actor, target_id=str(target["id"]), current_role=current
        )
        email = target.get("email")
        if not isinstance(email, str) or payload.confirm_email.lower() != email.lower():
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The confirmation address does not match the account's email, so "
                "nothing was deleted.",
            )
        with self._client() as client:
            client.delete_user(account_id)
        self._record(
            actor,
            "account.deleted",
            account_id,
            email,
            {
                "role": current,
                "reason": payload.reason,
                "membership_rows_retained": True,
            },
        )
        return AccountActionRead(
            status="DELETED",
            message=f"Deleted the Supabase account {email}. Aetrix workspace "
            "membership rows are retained as history and no longer authenticate.",
        )
