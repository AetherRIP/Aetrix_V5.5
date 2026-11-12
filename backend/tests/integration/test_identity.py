"""Provisioning is invitation-only and tenant membership is never guessed."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.db.models import AuditEvent, Invitation, Tenant, User
from sqlalchemy import func, select

AUDIENCE = "authenticated"


def _token(
    subject: str,
    email: str | None,
    *,
    verified: bool = True,
    tenant_id: uuid.UUID | None = None,
) -> str:
    now = datetime.now(UTC)
    app_metadata: dict[str, object] = {"provider": "google"}
    if tenant_id is not None:
        app_metadata["tenant_id"] = str(tenant_id)
    claims: dict[str, object] = {
        "sub": subject,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=1),
        "app_metadata": app_metadata,
        "user_metadata": {"full_name": "Invited Teacher"},
    }
    if email is not None:
        claims["email"] = email
        claims["email_verified"] = verified
    return jwt.encode(claims, os.environ["AETRIX_AUTH__JWT_SECRET"], algorithm="HS256")


def _headers(subject: str, email: str | None, **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(subject, email, **kwargs)}"}


def _invite(client, owner_headers, tenant_id, email: str, role: str = "TEACHER"):
    response = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        headers=owner_headers,
        json={"email": email, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_verified_invitation_provisions_exactly_one_member(
    client, identity, auth_headers, db_session
) -> None:
    owner_headers = auth_headers(identity.user_a)
    invitation = _invite(client, owner_headers, identity.tenant_a.id, "new.teacher@example.test")
    assert invitation["acceptance_code"]
    assert invitation["status"] == "PENDING"

    invitee = _headers("invitee-1", "new.teacher@example.test")
    first = client.get("/api/v1/me", headers=invitee)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["tenant_id"] == str(identity.tenant_a.id)
    assert body["role"] == "TEACHER"
    assert body["ui_role"] == "supervisor"
    assert "approve" in body["capabilities"]
    assert body["workspace_slug"] == "alpha"

    second = client.get("/api/v1/me", headers=invitee)
    assert second.status_code == 200
    assert second.json()["user_id"] == body["user_id"]

    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count()).select_from(User).where(User.subject == "invitee-1")
        )
        == 1
    )
    stored = db_session.scalar(
        select(Invitation).where(Invitation.email == "new.teacher@example.test")
    )
    assert stored is not None
    assert stored.status == "ACCEPTED"
    assert stored.accepted_at is not None
    assert stored.accepted_by is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "member.provisioned")
        )
        == 1
    )


def test_an_uninvited_verified_account_is_refused_without_creating_a_row(
    client, identity, db_session
) -> None:
    before = db_session.scalar(select(func.count()).select_from(User))

    response = client.get("/api/v1/me", headers=_headers("stranger-1", "stranger@example.test"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PROVISIONING_REQUIRED"
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(User)) == before
    assert (
        db_session.scalar(
            select(func.count()).select_from(User).where(User.subject == "stranger-1")
        )
        == 0
    )


def test_open_access_admits_an_uninvited_account_into_one_shared_workspace(
    open_access_client, db_session
) -> None:
    headers = _headers("open-1", "open@example.test")

    first = open_access_client.get("/api/v1/me", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["role"] == "TEACHER"
    assert body["ui_role"] == "supervisor"
    assert body["workspace_slug"] == "pilot"
    assert "approve" in body["capabilities"]

    # A second request reuses the same membership; signing in again does not
    # create another account or another workspace.
    second = open_access_client.get("/api/v1/me", headers=headers)
    assert second.status_code == 200
    assert second.json()["user_id"] == body["user_id"]

    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count()).select_from(User).where(User.subject == "open-1")
        )
        == 1
    )
    assert db_session.scalar(select(func.count()).select_from(Tenant)) == 1
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "member.provisioned")
    )
    assert event is not None
    assert event.detail["method"] == "open_access"
    assert event.detail["role"] == "TEACHER"


def test_open_access_does_not_widen_tenancy(
    open_access_client, identity, paper
) -> None:
    headers = _headers("open-2", "open2@example.test")
    assert open_access_client.get("/api/v1/me", headers=headers).status_code == 200

    # An open-access account lives in the shared workspace only: another
    # workspace's records stay nonexistent rather than readable.
    for path in (
        f"/api/v1/workspaces/{identity.tenant_a.id}",
        f"/api/v1/workspaces/{identity.tenant_a.id}/assignments",
        f"/api/v1/assignments/{paper.assignment.id}",
    ):
        assert open_access_client.get(path, headers=headers).status_code == 404, path


def test_an_unverified_email_cannot_redeem_an_invitation(
    client, identity, auth_headers, db_session
) -> None:
    _invite(client, auth_headers(identity.user_a), identity.tenant_a.id, "unverified@example.test")

    response = client.get(
        "/api/v1/me",
        headers=_headers("unverified-1", "unverified@example.test", verified=False),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PROVISIONING_REQUIRED"
    assert response.json()["error"]["details"]["state"] == "EMAIL_UNVERIFIED"
    db_session.expire_all()
    pending = db_session.scalar(
        select(Invitation).where(Invitation.email == "unverified@example.test")
    )
    assert pending.status == "PENDING"


def test_provisioned_member_still_cannot_see_another_tenant(
    client, identity, auth_headers, paper
) -> None:
    _invite(
        client,
        auth_headers(identity.user_a),
        identity.tenant_a.id,
        "another.teacher@example.test",
    )
    invitee = _headers("invitee-2", "another.teacher@example.test")

    me = client.get("/api/v1/me", headers=invitee)
    assert me.status_code == 200

    for path in (
        f"/api/v1/workspaces/{identity.tenant_b.id}",
        f"/api/v1/workspaces/{identity.tenant_b.id}/assignments",
    ):
        assert client.get(path, headers=invitee).status_code == 404, path

    # The fixture assignment belongs to the invitee's own workspace, so the
    # same route must stay readable there: scoping is by tenant, not by route.
    assignment = client.get(f"/api/v1/assignments/{paper.assignment.id}", headers=invitee)
    assert assignment.status_code == 200
    submissions = client.get(
        f"/api/v1/assignments/{paper.assignment.id}/submissions", headers=invitee
    )
    assert submissions.status_code == 200
    assert [row["id"] for row in submissions.json()] == [str(paper.submission.id)]


def test_role_changes_are_audited_and_privileges_are_enforced(
    client, identity, auth_headers, db_session
) -> None:
    owner_headers = auth_headers(identity.user_a)

    promoted = client.patch(
        f"/api/v1/workspaces/{identity.tenant_a.id}/members/{identity.viewer.id}",
        headers=owner_headers,
        json={"role": "REVIEWER", "reason": "joined the marking rota"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "REVIEWER"

    db_session.expire_all()
    audited = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "member.role_changed")
    ).all()
    assert len(audited) == 1
    assert audited[0].detail["role"] == "REVIEWER"
    assert audited[0].detail["previous_role"] == "VIEWER"

    viewer_headers = auth_headers(identity.viewer)
    refused = client.post(
        f"/api/v1/workspaces/{identity.tenant_a.id}/invitations",
        headers=viewer_headers,
        json={"email": "not.allowed@example.test", "role": "VIEWER"},
    )
    assert refused.status_code == 403

    self_change = client.patch(
        f"/api/v1/workspaces/{identity.tenant_a.id}/members/{identity.user_a.id}",
        headers=owner_headers,
        json={"role": "VIEWER"},
    )
    assert self_change.status_code == 403

    cross_tenant = client.patch(
        f"/api/v1/workspaces/{identity.tenant_b.id}/members/{identity.user_b.id}",
        headers=owner_headers,
        json={"role": "VIEWER"},
    )
    assert cross_tenant.status_code == 404


@pytest.mark.parametrize(
    "role", ["OWNER", "ADMIN", "TEACHER", "REVIEWER", "VIEWER"]
)
def test_every_workspace_role_can_be_invited(client, identity, auth_headers, role) -> None:
    response = client.post(
        f"/api/v1/workspaces/{identity.tenant_a.id}/invitations",
        headers=auth_headers(identity.user_a),
        json={"email": f"{role.lower()}@example.test", "role": role},
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == role
