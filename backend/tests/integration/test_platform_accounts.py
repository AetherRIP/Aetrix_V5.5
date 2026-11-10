"""Platform account endpoints: authorization and the missing-credential state.

The service-role key is absent from this repository by design, so these tests
assert the honest state: platform authority is enforced from the verified claim,
a workspace owner is refused, and a credentialed deployment is reported as
unconfigured rather than replaced with workspace members.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from app.core.config import PlatformAdminSettings, get_settings
from app.db.models import User
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _platform_headers(user: User, role: str) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": user.subject,
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=1),
            "app_metadata": {
                "tenant_id": str(user.tenant_id),
                "aetrix_role": role,
            },
        },
        os.environ["AETRIX_AUTH__JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _unconfigured(client: TestClient) -> None:
    """Pin the credential-absent state regardless of the developer's .env."""

    settings = get_settings().model_copy(
        update={"platform_admin": PlatformAdminSettings()}
    )
    client.app.dependency_overrides[get_settings] = lambda: settings


def _clear(client: TestClient) -> None:
    client.app.dependency_overrides.pop(get_settings, None)


def test_anonymous_requests_are_rejected(client: TestClient):
    response = client.get("/api/v1/admin/accounts")
    assert response.status_code == 401


def test_workspace_owner_has_no_platform_account_access(
    client: TestClient, identity, auth_headers
):
    # ``identity.user_a`` owns workspace Alpha.  That is a tenant relationship,
    # not platform authority, and it must not open the platform account list.
    response = client.get("/api/v1/admin/accounts", headers=auth_headers(identity.user_a))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_teacher_and_assistant_cannot_read_platform_accounts(
    client: TestClient, identity, db_session
):
    for subject, role in (("teacher-a", "TEACHER"), ("viewer-a", "VIEWER")):
        teacher = db_session.query(User).filter(User.subject == subject).one()
        response = client.get(
            "/api/v1/admin/accounts",
            headers=_platform_headers(teacher, "supervisor"),
        )
        # A workspace role in app_metadata confers no platform authority.
        assert response.status_code == 403, role


def test_owner_sees_an_unconfigured_capability_not_invented_access(
    client: TestClient, identity
):
    _unconfigured(client)
    try:
        response = client.get(
            "/api/v1/admin/accounts/capability",
            headers=_platform_headers(identity.user_a, "owner"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is False
        revoke = next(op for op in body["operations"] if op["name"] == "revoke sessions")
        assert revoke["supported"] is False
    finally:
        _clear(client)


def test_missing_credential_never_returns_workspace_members(
    client: TestClient, identity
):
    _unconfigured(client)
    try:
        response = client.get(
            "/api/v1/admin/accounts",
            headers=_platform_headers(identity.user_a, "owner"),
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ADMIN_NOT_CONFIGURED"
        text = response.text
        assert "items" not in text
        assert "teacher-a" not in text
    finally:
        _clear(client)


def test_administrator_cannot_delete_or_send_recovery(
    client: TestClient, identity
):
    _unconfigured(client)
    headers = _platform_headers(identity.user_a, "platform_operator")
    try:
        deleted = client.request(
            "DELETE",
            "/api/v1/admin/accounts/11111111-1111-1111-1111-111111111111",
            json={"confirm_email": "teacher-a@example.com", "reason": "duplicate"},
            headers=headers,
        )
        assert deleted.status_code == 403

        recovery = client.post(
            "/api/v1/admin/accounts/11111111-1111-1111-1111-111111111111/recovery",
            headers=headers,
        )
        assert recovery.status_code == 403

        # Listing is permitted to an administrator, and reports the missing key.
        listing = client.get("/api/v1/admin/accounts", headers=headers)
        assert listing.status_code == 503
        assert listing.json()["error"]["code"] == "ADMIN_NOT_CONFIGURED"
    finally:
        _clear(client)


def test_platform_role_comes_from_the_verified_claim_not_the_workspace_row(
    client: TestClient, identity
):
    """A workspace VIEWER carrying a platform-owner claim is the platform owner."""

    viewer = identity.viewer
    assert viewer.role == "VIEWER"
    assert UUID(str(viewer.tenant_id)) == identity.tenant_a.id
    _unconfigured(client)
    try:
        response = client.get(
            "/api/v1/admin/accounts/capability",
            headers=_platform_headers(viewer, "owner"),
        )
        assert response.status_code == 200
        assert response.json()["configured"] is False
    finally:
        _clear(client)
