"""Unit tests for platform account administration.

These are pure-logic tests: no database and no network.  They cover the role
policy that protects platform ownership, the interpretation of Supabase's own
fields, the credential-absent state, and the translation of upstream failures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.core.config import PlatformAdminSettings
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal
from app.schemas.admin_accounts import (
    AccountDeletion,
    AccountQuery,
    AccountRoleUpdate,
    AccountStatusUpdate,
)
from app.services.platform_accounts import (
    PlatformAccountService,
    PlatformAdminClient,
    account_role,
    account_status,
    ensure_deletion,
    ensure_role_change,
    ensure_status_change,
    fetch_all_accounts,
)


def _principal(platform_role: str, *, subject: str = "actor-subject", role: str = "TEACHER"):
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        subject=subject,
        role=role,
        platform_role=platform_role,
    )


def _settings() -> PlatformAdminSettings:
    return PlatformAdminSettings(
        supabase_url="https://project.supabase.co",
        service_role_key="service-role-key",
    )


def _user(
    account_id: str,
    email: str,
    role: str | None = None,
    *,
    name: str | None = None,
    confirmed: bool = True,
    banned_until: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = dict(extra_metadata or {})
    if role is not None:
        metadata["aetrix_role"] = role
    return {
        "id": account_id,
        "email": email,
        "app_metadata": metadata,
        "user_metadata": {"display_name": name} if name else {},
        "created_at": "2026-01-02T03:04:05+00:00",
        "updated_at": "2026-02-03T04:05:06+00:00",
        "last_sign_in_at": "2026-02-03T04:05:06+00:00",
        "email_confirmed_at": "2026-01-02T03:05:00+00:00" if confirmed else None,
        "banned_until": banned_until,
    }


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """The small slice of ``Session`` the service uses beyond the client."""

    def __init__(
        self,
        membership_rows: list[Any] | None = None,
        invitation_rows: list[Any] | None = None,
        audit_rows: list[Any] | None = None,
    ) -> None:
        self.membership_rows = membership_rows or []
        self.invitation_rows = invitation_rows or []
        self.audit_rows = audit_rows or []
        self.events: list[Any] = []
        self.commits = 0

    def execute(self, statement: Any) -> _Rows:
        if "FROM invitations" in str(statement):
            return _Rows(self.invitation_rows)
        return _Rows(self.membership_rows)

    def scalars(self, statement: Any) -> _Rows:
        return _Rows(self.audit_rows)

    def add(self, event: Any) -> None:
        self.events.append(event)

    def commit(self) -> None:
        self.commits += 1


class FakeClient:
    def __init__(self, users: list[dict[str, Any]]) -> None:
        self.users = users
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def list_users(self, *, page: int, per_page: int) -> dict[str, Any]:
        start = (page - 1) * per_page
        return {
            "aud": "authenticated",
            "users": self.users[start : start + per_page],
        }

    def get_user(self, user_id: str) -> dict[str, Any]:
        for user in self.users:
            if user["id"] == user_id:
                return user
        raise AppError(ErrorCode.NOT_FOUND, "That account does not exist in Supabase Auth.")

    def update_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.updates.append((user_id, payload))
        for user in self.users:
            if user["id"] == user_id:
                if "app_metadata" in payload:
                    user["app_metadata"] = payload["app_metadata"]
                if "ban_duration" in payload:
                    user["banned_until"] = (
                        (datetime.now(UTC) + timedelta(days=36500)).isoformat()
                        if payload["ban_duration"] != "none"
                        else None
                    )
        return {}

    def delete_user(self, user_id: str) -> None:
        self.updates.append((user_id, {"deleted": True}))

    def invite(self, email: str) -> None:
        self.updates.append(("invite", {"email": email}))

    def recover(self, email: str) -> None:
        self.updates.append(("recover", {"email": email}))


def _service(
    users: list[dict[str, Any]],
    *,
    session: FakeSession | None = None,
    configured: bool = True,
) -> tuple[PlatformAccountService, FakeClient, FakeSession]:
    client = FakeClient(users)
    store = session or FakeSession()
    settings = _settings() if configured else PlatformAdminSettings()
    service = PlatformAccountService(store, settings, client_factory=lambda: client)
    return service, client, store


# -- interpretation --------------------------------------------------------


def test_account_role_reads_only_app_metadata_and_normalises_legacy_values():
    assert account_role({"aetrix_role": "owner"}) == "owner"
    assert account_role({"aetrix_role": "PLATFORM_OWNER"}) == "owner"
    assert account_role({"aetrix_role": "ADMIN"}) == "platform_operator"
    assert account_role({"aetrix_role": "supervisor"}) == "supervisor"
    assert account_role({"aetrix_role": "made_up"}) == "unassigned"
    assert account_role({}) == "unassigned"
    # user_metadata is writable by the account itself; it must never confer a role.
    assert account_role(None) == "unassigned"


def test_account_status_derives_from_ban_and_confirmation():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    assert account_status(_user("u", "a@example.com", "viewer"), now) == "ACTIVE"
    assert account_status(_user("u", "a@example.com", confirmed=False), now) == "UNCONFIRMED"
    assert (
        account_status(
            _user("u", "a@example.com", banned_until="2027-01-01T00:00:00+00:00"), now
        )
        == "SUSPENDED"
    )
    # A ban that has expired does not keep an account suspended.
    assert (
        account_status(
            _user("u", "a@example.com", banned_until="2026-04-01T00:00:00+00:00"), now
        )
        == "ACTIVE"
    )


# -- authorization policy --------------------------------------------------


def test_owner_may_grant_every_manageable_role_but_never_ownership():
    owner = _principal("PLATFORM_OWNER")
    for role in ("platform_operator", "supervisor", "assistant", "viewer"):
        ensure_role_change(
            actor=owner, target_id="someone", current_role="viewer", new_role=role
        )
    with pytest.raises(AppError) as caught:
        ensure_role_change(
            actor=owner, target_id="someone", current_role="viewer", new_role="owner"
        )
    assert caught.value.code == ErrorCode.FORBIDDEN


def test_administrator_cannot_grant_administrator_or_change_an_administrator():
    admin = _principal("ADMIN")
    with pytest.raises(AppError) as caught:
        ensure_role_change(
            actor=admin,
            target_id="someone",
            current_role="viewer",
            new_role="platform_operator",
        )
    assert caught.value.code == ErrorCode.FORBIDDEN
    with pytest.raises(AppError):
        ensure_role_change(
            actor=admin,
            target_id="someone",
            current_role="platform_operator",
            new_role="viewer",
        )
    ensure_role_change(
        actor=admin, target_id="someone", current_role="viewer", new_role="supervisor"
    )


def test_nobody_changes_their_own_role_or_the_owners():
    owner = _principal("PLATFORM_OWNER", subject="owner-subject")
    with pytest.raises(AppError) as caught:
        ensure_role_change(
            actor=owner,
            target_id="owner-subject",
            current_role="platform_operator",
            new_role="supervisor",
        )
    assert caught.value.code == ErrorCode.FORBIDDEN
    with pytest.raises(AppError):
        ensure_role_change(
            actor=owner, target_id="other", current_role="owner", new_role="viewer"
        )
    with pytest.raises(AppError):
        ensure_role_change(
            actor=_principal("", role="TEACHER"),
            target_id="other",
            current_role="viewer",
            new_role="supervisor",
        )


def test_status_and_deletion_rules_protect_self_and_ownership():
    owner = _principal("PLATFORM_OWNER", subject="owner-subject")
    with pytest.raises(AppError):
        ensure_status_change(
            actor=owner, target_id="owner-subject", current_role="supervisor"
        )
    with pytest.raises(AppError):
        ensure_status_change(actor=owner, target_id="other", current_role="owner")
    with pytest.raises(AppError):
        ensure_status_change(
            actor=_principal("ADMIN"), target_id="other", current_role="platform_operator"
        )
    ensure_status_change(actor=owner, target_id="other", current_role="supervisor")

    with pytest.raises(AppError):
        ensure_deletion(actor=_principal("ADMIN"), target_id="other", current_role="viewer")
    with pytest.raises(AppError):
        ensure_deletion(actor=owner, target_id="owner-subject", current_role="viewer")
    with pytest.raises(AppError):
        ensure_deletion(actor=owner, target_id="other", current_role="owner")
    ensure_deletion(actor=owner, target_id="other", current_role="viewer")


# -- credential state ------------------------------------------------------


def test_missing_credential_is_a_reported_state_not_an_invented_list():
    service, client, _ = _service([], configured=False)
    with pytest.raises(AppError) as caught:
        service.list_accounts(_principal("PLATFORM_OWNER"), AccountQuery())
    assert caught.value.code == ErrorCode.ADMIN_NOT_CONFIGURED
    assert "SERVICE_ROLE_KEY" in caught.value.message
    assert client.updates == []

    capability = service.capability()
    assert capability.configured is False
    revoke = next(op for op in capability.operations if op.name == "revoke sessions")
    assert revoke.supported is False


def test_capability_reports_supported_operations_when_configured():
    service, _, _ = _service([])
    capability = service.capability()
    assert capability.configured is True
    assert all(op.supported for op in capability.operations if op.name != "revoke sessions")
    revoke = next(op for op in capability.operations if op.name == "revoke sessions")
    assert revoke.supported is False
    assert "service-role endpoint" in revoke.note


def test_account_list_reads_supabase_users_envelope():
    client = FakeClient(
        [
            _user("u-1", "ada@example.com", "platform_operator"),
            _user("u-2", "bo@example.com", "supervisor"),
        ]
    )

    users, truncated = fetch_all_accounts(_settings(), client_factory=lambda: client)

    assert [user["id"] for user in users] == ["u-1", "u-2"]
    assert truncated is False


# -- upstream translation --------------------------------------------------


def test_client_translates_upstream_failures_without_echoing_the_key():
    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"msg": "invalid JWT"})

    with PlatformAdminClient(
        "https://project.supabase.co",
        "super-secret-service-role",
        transport=httpx.MockTransport(rejected),
    ) as client, pytest.raises(AppError) as caught:
        client.list_users(page=1, per_page=50)
    assert caught.value.code == ErrorCode.ADMIN_UPSTREAM_ERROR
    assert "super-secret-service-role" not in caught.value.message

    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"msg": "User not found"})

    with PlatformAdminClient(
        "https://project.supabase.co",
        "key",
        transport=httpx.MockTransport(missing),
    ) as client, pytest.raises(AppError) as caught:
        client.get_user("gone")
    assert caught.value.code == ErrorCode.NOT_FOUND


def test_client_uses_the_admin_base_path_and_bearer_header():
    seen: dict[str, str] = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=[{"id": "u-1"}])

    with PlatformAdminClient(
        "https://project.supabase.co",
        "service-key",
        transport=httpx.MockTransport(ok),
    ) as client:
        client.list_users(page=2, per_page=10)
    assert seen["url"].startswith(
        "https://project.supabase.co/auth/v1/admin/users?page=2&per_page=10"
    )
    assert seen["authorization"] == "Bearer service-key"


# -- reads -----------------------------------------------------------------


def _membership(subject: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    tenant = SimpleNamespace(
        id=uuid.uuid4(), name="Alpha", slug="alpha", is_demo=False
    )
    user_row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        subject=subject,
        role="TEACHER",
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    return user_row, tenant


def test_owner_list_joins_memberships_and_never_invents_accounts():
    users = [
        _user("u-1", "ada@example.com", "platform_operator", name="Ada"),
        _user("u-2", "bo@example.com", None, confirmed=False),
    ]
    session = FakeSession(membership_rows=[_membership("u-1")])
    service, _, _ = _service(users, session=session)

    page = service.list_accounts(_principal("PLATFORM_OWNER"), AccountQuery())

    assert page.source == "supabase-auth"
    assert [item.id for item in page.items] == ["u-1", "u-2"]
    assert page.total == 2
    ada, bo = page.items
    assert (ada.email, ada.role, ada.status, ada.display_name) == (
        "ada@example.com",
        "platform_operator",
        "ACTIVE",
        "Ada",
    )
    assert ada.has_workspace is True
    assert ada.workspace_count == 1
    assert ada.memberships[0].workspace_slug == "alpha"
    assert bo.role == "unassigned"
    assert bo.status == "UNCONFIRMED"
    assert bo.has_workspace is False


def test_search_and_filters_run_over_the_platform_accounts():
    users = [
        _user("u-1", "ada@example.com", "platform_operator", name="Ada"),
        _user("u-2", "bo@example.com", None, confirmed=False),
    ]
    session = FakeSession(membership_rows=[_membership("u-1")])
    service, _, _ = _service(users, session=session)
    owner = _principal("PLATFORM_OWNER")

    def ids(query: AccountQuery) -> list[str]:
        return [item.id for item in service.list_accounts(owner, query).items]

    assert ids(AccountQuery(q="BO@")) == ["u-2"]
    assert ids(AccountQuery(q="ada")) == ["u-1"]
    assert ids(AccountQuery(q="u-2")) == ["u-2"]
    assert ids(AccountQuery(role="platform_operator")) == ["u-1"]
    assert ids(AccountQuery(role="unassigned")) == ["u-2"]
    assert ids(AccountQuery(status="UNCONFIRMED")) == ["u-2"]
    assert ids(AccountQuery(joined="yes")) == ["u-1"]
    assert ids(AccountQuery(joined="no")) == ["u-2"]
    page = service.list_accounts(owner, AccountQuery(page=2, page_size=1))
    assert page.total == 2
    assert [item.id for item in page.items] == ["u-2"]


def test_the_account_ceiling_is_reported_rather_than_hidden():
    users = [_user(f"u-{index}", f"user{index}@example.com", "viewer") for index in range(3)]
    service, _, _ = _service(
        users,
        session=FakeSession(),
    )
    service.settings = PlatformAdminSettings(
        supabase_url="https://project.supabase.co",
        service_role_key="key",
        max_accounts=2,
        page_size=2,
    )
    page = service.list_accounts(_principal("PLATFORM_OWNER"), AccountQuery())
    assert page.truncated is True
    assert page.total == 2


# -- mutations -------------------------------------------------------------


def test_role_change_preserves_other_app_metadata_and_is_audited():
    target = _user(
        "u-2", "bo@example.com", "supervisor", extra_metadata={"provider": "google"}
    )
    service, client, session = _service([target])

    result = service.update_role(
        _principal("PLATFORM_OWNER", subject="owner-subject"),
        "u-2",
        AccountRoleUpdate(role="assistant", reason="cover"),
    )

    assert client.updates == [
        ("u-2", {"app_metadata": {"provider": "google", "aetrix_role": "assistant"}})
    ]
    actions = [event.action for event in session.events]
    assert actions[0] == "account.role_changed"
    assert session.events[0].detail["previous_role"] == "supervisor"
    assert result.account.role == "assistant"
    # No membership row exists, and the response says so instead of reporting a
    # bare success that the account's shell role cannot follow.
    assert [effect.state for effect in result.memberships] == ["skipped"]
    assert "no workspace membership row" in result.memberships[0].reason
    # Reading the changed record is recorded too, because it is another account.
    assert "account.inspected" in actions


def test_role_change_updates_the_membership_role_the_shell_reads():
    """The platform role must reach ``users.role``; otherwise /me still says teacher."""

    target = _user("u-2", "bo@example.com", "supervisor")
    membership = _membership("u-2")
    member_row = membership[0]
    assert member_row.role == "TEACHER"
    service, client, session = _service([target], session=FakeSession([membership]))

    result = service.update_role(
        _principal("PLATFORM_OWNER", subject="owner-subject"),
        "u-2",
        AccountRoleUpdate(role="assistant", reason="cover"),
    )

    assert member_row.role == "REVIEWER"
    assert result.account.memberships[0].role == "REVIEWER"
    assert [effect.state for effect in result.memberships] == ["changed"]
    assert result.memberships[0].previous_role == "TEACHER"
    assert result.memberships[0].role == "REVIEWER"
    assert result.memberships[0].workspace_name == "Alpha"
    assert session.events[0].detail["membership_roles"] == [
        {
            "user_id": str(member_row.id),
            "previous_role": "TEACHER",
            "role": "REVIEWER",
        }
    ]
    assert client.updates == [
        ("u-2", {"app_metadata": {"aetrix_role": "assistant"}})
    ]


def test_a_role_change_reports_a_row_already_at_the_target_role():
    target = _user("u-2", "bo@example.com", "supervisor")
    membership = _membership("u-2")
    member_row, _ = membership
    assert member_row.role == "TEACHER"
    service, client, _ = _service([target], session=FakeSession([membership]))

    result = service.update_role(
        _principal("PLATFORM_OWNER", subject="owner-subject"),
        "u-2",
        AccountRoleUpdate(role="supervisor", reason="no change needed"),
    )

    assert member_row.role == "TEACHER"
    assert client.updates == [
        ("u-2", {"app_metadata": {"aetrix_role": "supervisor"}})
    ]
    assert [effect.state for effect in result.memberships] == ["skipped"]
    assert "already TEACHER" in result.memberships[0].reason


def test_a_platform_operator_change_leaves_every_membership_row_alone():
    target = _user("u-2", "bo@example.com", "supervisor")
    membership = _membership("u-2")
    member_row, _ = membership
    service, client, session = _service([target], session=FakeSession([membership]))

    result = service.update_role(
        _principal("PLATFORM_OWNER", subject="owner-subject"),
        "u-2",
        AccountRoleUpdate(role="platform_operator", reason="platform duty"),
    )

    assert member_row.role == "TEACHER"
    assert result.account.memberships[0].role == "TEACHER"
    assert [effect.state for effect in result.memberships] == ["skipped"]
    assert "platform-only" in result.memberships[0].reason
    assert client.updates == [
        ("u-2", {"app_metadata": {"aetrix_role": "platform_operator"}})
    ]
    assert session.events[0].detail["membership_roles"] == []


def test_a_platform_owner_membership_row_is_never_rewritten():
    target = _user("u-2", "bo@example.com", "supervisor")
    membership = _membership("u-2")
    member_row, _ = membership
    member_row.role = "PLATFORM_OWNER"
    service, client, session = _service([target], session=FakeSession([membership]))

    result = service.update_role(
        _principal("PLATFORM_OWNER", subject="owner-subject"),
        "u-2",
        AccountRoleUpdate(role="assistant", reason="cover"),
    )

    assert member_row.role == "PLATFORM_OWNER"
    assert result.account.memberships[0].role == "PLATFORM_OWNER"
    assert [effect.state for effect in result.memberships] == ["skipped"]
    assert "Platform ownership is not a workspace role" in result.memberships[0].reason
    assert client.updates == [
        ("u-2", {"app_metadata": {"aetrix_role": "assistant"}})
    ]
    assert session.events[0].detail["membership_roles"] == []


def test_a_role_change_for_an_account_with_no_membership_row_is_unaffected():
    target = _user("u-2", "bo@example.com", "supervisor")
    service, client, session = _service([target], session=FakeSession())

    result = service.update_role(
        _principal("PLATFORM_OWNER", subject="owner-subject"),
        "u-2",
        AccountRoleUpdate(role="assistant", reason="cover"),
    )

    assert result.account.memberships == []
    assert result.account.has_workspace is False
    assert [effect.state for effect in result.memberships] == ["skipped"]
    assert "no workspace membership row" in result.memberships[0].reason
    assert client.updates == [
        ("u-2", {"app_metadata": {"aetrix_role": "assistant"}})
    ]
    assert session.events[0].detail["membership_roles"] == []


def test_a_workspace_owner_survives_a_platform_role_round_trip():
    """The Assistants screen writes ``supervisor`` for an owner; a later
    "Teacher" save from Account management must not demote that row to TEACHER."""

    target = _user("u-2", "bo@example.com", "supervisor")
    membership = _membership("u-2")
    member_row, _ = membership
    member_row.role = "OWNER"
    service, client, session = _service([target], session=FakeSession([membership]))

    result = service.update_role(
        _principal("PLATFORM_OWNER", subject="owner-subject"),
        "u-2",
        AccountRoleUpdate(role="supervisor", reason="Teacher"),
    )

    # The claim moves; the ownership row does not.
    assert member_row.role == "OWNER"
    assert result.account.memberships[0].role == "OWNER"
    assert [effect.state for effect in result.memberships] == ["skipped"]
    assert "Workspace ownership is not changed" in result.memberships[0].reason
    assert client.updates == [
        ("u-2", {"app_metadata": {"aetrix_role": "supervisor"}})
    ]
    assert session.events[0].action == "account.role_changed"
    assert session.events[0].detail["membership_roles"] == []


def test_suspension_uses_a_ban_and_reactivation_lifts_it():
    service, client, session = _service([_user("u-2", "bo@example.com", "viewer")])
    owner = _principal("PLATFORM_OWNER", subject="owner-subject")

    suspended = service.set_status(
        owner, "u-2", AccountStatusUpdate(status="SUSPENDED", reason="policy")
    )
    assert client.updates[0] == ("u-2", {"ban_duration": "876000h"})
    assert suspended.status == "SUSPENDED"
    assert session.events[0].action == "account.suspended"

    active = service.set_status(
        owner, "u-2", AccountStatusUpdate(status="ACTIVE", reason="resolved")
    )
    assert client.updates[1] == ("u-2", {"ban_duration": "none"})
    assert active.status == "ACTIVE"
    actions = [event.action for event in session.events]
    assert actions.count("account.suspended") == 1
    assert actions.count("account.reactivated") == 1
    assert actions[-1] == "account.inspected"


def test_session_revocation_reports_not_supported():
    service, _, _ = _service([_user("u-2", "bo@example.com", "viewer")])
    with pytest.raises(AppError) as caught:
        service.revoke_sessions(
            _principal("PLATFORM_OWNER"), "u-2"
        )
    assert caught.value.code == ErrorCode.NOT_SUPPORTED
    assert "service-role endpoint" in caught.value.message


def test_deletion_needs_the_owners_confirmation_of_the_exact_address():
    service, client, session = _service([_user("u-2", "bo@example.com", "viewer")])
    owner = _principal("PLATFORM_OWNER", subject="owner-subject")

    with pytest.raises(AppError) as caught:
        service.delete_account(
            owner,
            "u-2",
            AccountDeletion(confirm_email="someone@example.com", reason="duplicate"),
        )
    assert caught.value.code == ErrorCode.VALIDATION_ERROR
    assert client.updates == []
    assert session.events == []

    result = service.delete_account(
        owner,
        "u-2",
        AccountDeletion(confirm_email="BO@example.com", reason="duplicate"),
    )
    assert client.updates == [("u-2", {"deleted": True})]
    assert result.status == "DELETED"
    assert session.events[0].action == "account.deleted"
    assert session.events[0].detail["membership_rows_retained"] is True


def test_recovery_is_owner_only_and_invitations_need_an_unconfirmed_account():
    service, client, session = _service(
        [
            _user("u-2", "bo@example.com", "viewer"),
            _user("u-3", "new@example.com", None, confirmed=False),
        ]
    )
    with pytest.raises(AppError):
        service.request_recovery(_principal("ADMIN"), "u-2")

    result = service.request_recovery(
        _principal("PLATFORM_OWNER", subject="owner-subject"), "u-2"
    )
    assert client.updates[-1] == ("recover", {"email": "bo@example.com"})
    assert result.status == "RECOVERY_SENT"
    assert session.events[-1].action == "account.recovery_requested"

    with pytest.raises(AppError) as caught:
        service.resend_invitation(_principal("ADMIN"), "u-2")
    assert caught.value.code == ErrorCode.CONFLICT

    service.resend_invitation(_principal("ADMIN"), "u-3")
    assert client.updates[-1] == ("invite", {"email": "new@example.com"})
