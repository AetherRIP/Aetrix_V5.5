"""Unit tests for the workspace-role → platform-claim write.

No database and no network: the repository and audit service are replaced with
recorders, and the identity provider is a fake admin client.  These pin the
direction the platform directory reads: a change made on the Assistants screen
must leave ``app_metadata.aetrix_role`` in step, and the same audit event must
say what was written or why it was not.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import PlatformAdminSettings
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal
from app.schemas.identity import MemberRoleUpdate
from app.services.identity import IdentityService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeUsers:
    def __init__(self, target: Any) -> None:
        self.target = target

    def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Any:
        return self.target


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class FakeAdminClient:
    def __init__(
        self,
        user: dict[str, Any] | None = None,
        *,
        error: AppError | None = None,
    ) -> None:
        self.user = user or {}
        self.error = error
        self.gets = 0
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> FakeAdminClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_user(self, user_id: str) -> dict[str, Any]:
        self.gets += 1
        if self.error is not None:
            raise self.error
        return self.user

    def update_user(self, user_id: str, payload: dict[str, Any]) -> None:
        self.updates.append((user_id, payload))


def settings(*, configured: bool = True) -> PlatformAdminSettings:
    if not configured:
        return PlatformAdminSettings()
    return PlatformAdminSettings(
        supabase_url="https://project.supabase.co",
        service_role_key="service-role-key",
    )


def target(role: str = "TEACHER") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        subject="member-subject",
        role=role,
        email="member@example.com",
        display_name="Member",
    )


def actor(member: Any) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=member.tenant_id,
        subject="actor-subject",
        role="OWNER",
        platform_role="",
    )


def service(
    member: Any,
    client: FakeAdminClient | None,
    *,
    configured: bool = True,
) -> tuple[IdentityService, FakeSession, FakeAudit]:
    store = FakeSession()
    instance = IdentityService(
        store,  # type: ignore[arg-type]
        settings(configured=configured),
        client_factory=(lambda: client) if client is not None else None,
    )
    instance.users = FakeUsers(member)  # type: ignore[assignment]
    audit = FakeAudit()
    instance.audit = audit  # type: ignore[assignment]
    return instance, store, audit


def test_a_workspace_role_change_writes_the_matching_platform_claim() -> None:
    member = target("TEACHER")
    client = FakeAdminClient(
        {
            "id": "member-subject",
            "app_metadata": {"provider": "google", "aetrix_role": "supervisor"},
        }
    )
    instance, store, audit = service(member, client)

    changed = instance.update_member_role(
        actor(member), member.id, MemberRoleUpdate(role="REVIEWER", reason="cover")
    )

    assert changed.role == "REVIEWER"
    assert member.role == "REVIEWER"
    assert client.updates == [
        (
            "member-subject",
            {"app_metadata": {"provider": "google", "aetrix_role": "assistant"}},
        )
    ]
    assert store.commits == 1
    event = audit.events[0]
    assert event["action"] == "member.role_changed"
    assert event["detail"]["platform_claim"] == {
        "state": "written",
        "previous_role": "supervisor",
        "role": "assistant",
    }


def test_a_workspace_administrator_role_never_writes_platform_authority() -> None:
    member = target("TEACHER")
    client = FakeAdminClient({"app_metadata": {"aetrix_role": "supervisor"}})
    instance, _, audit = service(member, client)

    instance.update_member_role(
        actor(member), member.id, MemberRoleUpdate(role="ADMIN", reason="department duty")
    )

    assert member.role == "ADMIN"
    # The Admin role's platform spelling is platform_operator, which carries
    # platform authority; the claim is never written from this screen.
    assert client.gets == 0
    assert client.updates == []
    claim = audit.events[0]["detail"]["platform_claim"]
    assert claim["state"] == "skipped"
    assert "no platform-role spelling" in claim["reason"]


def test_granting_workspace_ownership_does_not_write_a_platform_claim() -> None:
    member = target("TEACHER")
    client = FakeAdminClient({"app_metadata": {"aetrix_role": "supervisor"}})
    instance, store, audit = service(member, client)

    instance.update_member_role(
        actor(member), member.id, MemberRoleUpdate(role="OWNER", reason="takes over")
    )

    # Writing "supervisor" here would let a later Teacher save demote the owner.
    assert member.role == "OWNER"
    assert client.gets == 0
    assert client.updates == []
    assert store.commits == 1
    claim = audit.events[0]["detail"]["platform_claim"]
    assert claim["state"] == "skipped"
    assert "Workspace ownership" in claim["reason"]


def test_a_platform_owner_claim_is_not_overwritten_from_a_workspace_screen() -> None:
    member = target("TEACHER")
    client = FakeAdminClient({"app_metadata": {"aetrix_role": "owner"}})
    instance, _, audit = service(member, client)

    instance.update_member_role(
        actor(member), member.id, MemberRoleUpdate(role="VIEWER", reason="cover")
    )

    assert member.role == "VIEWER"
    assert client.updates == []
    claim = audit.events[0]["detail"]["platform_claim"]
    assert claim["state"] == "skipped"
    assert claim["previous_role"] == "owner"
    assert "assigned in the identity provider" in claim["reason"]


def test_a_missing_credential_is_reported_and_the_workspace_change_stands() -> None:
    member = target("TEACHER")
    instance, store, audit = service(member, None, configured=False)

    instance.update_member_role(
        actor(member), member.id, MemberRoleUpdate(role="REVIEWER", reason="cover")
    )

    assert member.role == "REVIEWER"
    assert store.commits == 1
    claim = audit.events[0]["detail"]["platform_claim"]
    assert claim["state"] == "not_configured"
    assert "service-role key" in claim["reason"]


def test_a_missing_identity_provider_account_is_reported_not_raised() -> None:
    member = target("TEACHER")
    client = FakeAdminClient(error=AppError(ErrorCode.NOT_FOUND, "no such user"))
    instance, store, audit = service(member, client)

    instance.update_member_role(
        actor(member), member.id, MemberRoleUpdate(role="REVIEWER", reason="cover")
    )

    assert member.role == "REVIEWER"
    assert store.commits == 1
    assert client.updates == []
    claim = audit.events[0]["detail"]["platform_claim"]
    assert claim["state"] == "skipped"
    assert "No identity-provider account" in claim["reason"]


def test_an_upstream_failure_leaves_the_membership_row_unchanged() -> None:
    member = target("TEACHER")
    client = FakeAdminClient(
        error=AppError(ErrorCode.ADMIN_UPSTREAM_ERROR, "identity provider down")
    )
    instance, store, audit = service(member, client)

    with pytest.raises(AppError):
        instance.update_member_role(
            actor(member), member.id, MemberRoleUpdate(role="REVIEWER", reason="cover")
        )

    # The claim is written first, so a failed write leaves both stores as they
    # were instead of committing a one-sided change.
    assert member.role == "TEACHER"
    assert store.commits == 0
    assert audit.events == []
