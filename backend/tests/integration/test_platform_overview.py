"""Platform overview endpoint: real aggregate counts and honest unavailability.

The tests seed workspaces and classes directly so the expected counts are known:
only active, non-demo workspaces and their classes count.  The identity census
cannot be reached without a service-role key, so its metrics must report
themselves unavailable rather than zero; the workspace metrics stay available.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.core.config import PlatformAdminSettings, get_settings
from app.db.models import SchoolClass, Tenant
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _platform_headers(user, role: str) -> dict[str, str]:
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
    settings = get_settings().model_copy(
        update={"platform_admin": PlatformAdminSettings()}
    )
    client.app.dependency_overrides[get_settings] = lambda: settings


def _clear(client: TestClient) -> None:
    client.app.dependency_overrides.pop(get_settings, None)


def _seed(db_session, identity) -> None:
    demo = Tenant(name="Demo", slug="demo", is_demo=True)
    closed = Tenant(name="Closed", slug="closed", is_active=False)
    db_session.add_all([demo, closed])
    db_session.flush()
    db_session.add_all(
        [
            SchoolClass(tenant_id=identity.tenant_a.id, name="Alpha 1"),
            SchoolClass(tenant_id=identity.tenant_a.id, name="Alpha 2"),
            SchoolClass(tenant_id=identity.tenant_b.id, name="Beta 1"),
            SchoolClass(tenant_id=demo.id, name="Demo 1"),
            SchoolClass(tenant_id=closed.id, name="Closed 1"),
        ]
    )
    db_session.commit()


def test_owner_reads_workspaces_and_classes_but_not_identities(
    client: TestClient, identity, db_session
):
    _seed(db_session, identity)
    _unconfigured(client)
    try:
        response = client.get(
            "/api/v1/admin/overview",
            headers=_platform_headers(identity.user_a, "owner"),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        metrics = {metric["key"]: metric for metric in body["metrics"]}

        # Alpha and Beta are active; the demo and closed workspaces are not.
        assert metrics["teacher_workspaces"]["value"] == 2
        assert metrics["teacher_workspaces"]["state"] == "available"
        # Local workspace classes are not Classroom allocations.  No allocation
        # row exists in this fixture, so the measured value is zero.
        assert metrics["active_class_allocations"]["value"] == 0

        # No service-role key in this environment: unavailable, never zero.
        assert metrics["teachers"]["value"] is None
        assert metrics["teachers"]["state"] == "unavailable"
        assert metrics["assistant_accounts"]["value"] is None
        assert body["account_census"]["available"] is False
        assert body["account_census"]["reason"]

        # Counts only: no account, workspace or class identity is exposed.
        assert "Alpha" not in response.text
        assert "teacher-a" not in response.text
    finally:
        _clear(client)


def test_administrator_may_read_the_overview(
    client: TestClient, identity, db_session
):
    _seed(db_session, identity)
    _unconfigured(client)
    try:
        response = client.get(
            "/api/v1/admin/overview",
            headers=_platform_headers(identity.user_a, "platform_operator"),
        )
        assert response.status_code == 200
        metrics = {metric["key"]: metric for metric in response.json()["metrics"]}
        assert metrics["teacher_workspaces"]["value"] == 2
    finally:
        _clear(client)


def test_workspace_owner_and_teacher_are_refused(
    client: TestClient, identity
):
    _unconfigured(client)
    try:
        owner = client.get(
            "/api/v1/admin/overview", headers=_headers_for(identity.user_a)
        )
        assert owner.status_code == 403
        assert owner.json()["error"]["code"] == "FORBIDDEN"

        teacher = client.get(
            "/api/v1/admin/overview",
            headers=_platform_headers(identity.user_a, "supervisor"),
        )
        assert teacher.status_code == 403
    finally:
        _clear(client)


def _headers_for(user) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": user.subject,
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=1),
            "app_metadata": {"tenant_id": str(user.tenant_id)},
        },
        os.environ["AETRIX_AUTH__JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_anonymous_is_refused(client: TestClient):
    response = client.get("/api/v1/admin/overview")
    assert response.status_code == 401


def test_empty_platform_reports_real_zeros(client: TestClient, identity):
    _unconfigured(client)
    try:
        response = client.get(
            "/api/v1/admin/overview",
            headers=_platform_headers(identity.user_a, "owner"),
        )
        assert response.status_code == 200
        metrics = {metric["key"]: metric for metric in response.json()["metrics"]}
        assert metrics["teacher_workspaces"]["value"] == 0
        assert metrics["teacher_workspaces"]["state"] == "no_records"
        assert metrics["active_class_allocations"]["value"] == 0
        assert metrics["active_class_allocations"]["state"] == "no_records"
    finally:
        _clear(client)
