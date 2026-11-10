"""Google Classroom course allocation against PostgreSQL.

These tests exercise the real partial unique index and the transactional
reassignment path.  A successful release/reassign is one commit: if anything
fails, the previous ACTIVE row must still be ACTIVE.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.db.models import (
    ClassroomAllocation,
    ClassroomClass,
    PlatformAuditEvent,
    Tenant,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

ADMIN_BASE = "/api/v1/admin/allocations"


def _headers(user, role: str = "owner") -> dict[str, str]:
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


def _owner_headers(identity) -> dict[str, str]:
    return _headers(identity.user_a, "owner")


def _register(
    client: TestClient, headers: dict[str, str], course_id: str = "600100"
) -> dict:
    response = client.post(
        f"{ADMIN_BASE}/classes",
        headers=headers,
        json={
            "course_id": course_id,
            "name": f"Class {course_id}",
            "section": "A",
            "attested": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _allocate(
    client: TestClient,
    headers: dict[str, str],
    class_id: str,
    workspace_id,
) -> dict:
    response = client.post(
        ADMIN_BASE,
        headers=headers,
        json={
            "classroom_class_id": class_id,
            "workspace_id": str(workspace_id),
            "reason": "timetable",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_record_allocate_and_list(client: TestClient, identity, db_session):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    assert recorded["verification"] == "UNVERIFIED"
    assert recorded["synced_at"] is None

    allocation = _allocate(client, headers, recorded["id"], identity.tenant_a.id)
    assert allocation["status"] == "ACTIVE"
    assert allocation["origin"] == "ALLOCATE"
    assert allocation["workspace_name"] == "Alpha"

    available = client.get(f"{ADMIN_BASE}/available-classes", headers=headers)
    assert available.status_code == 200
    assert available.json() == []

    history = client.get(ADMIN_BASE, headers=headers)
    assert history.status_code == 200
    assert history.json()["total"] == 1

    workspaces = client.get(f"{ADMIN_BASE}/workspaces", headers=headers)
    assert workspaces.status_code == 200
    alpha = next(row for row in workspaces.json() if row["id"] == str(identity.tenant_a.id))
    assert alpha["active_allocations"] == 1

    actions = set(
        db_session.scalars(
            select(PlatformAuditEvent.action).where(
                PlatformAuditEvent.action.like("classroom.%")
            )
        )
    )
    assert "classroom.class_recorded" in actions
    assert "classroom.allocation_created" in actions


def test_duplicate_active_allocation_is_refused(
    client: TestClient, identity, db_session
):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    _allocate(client, headers, recorded["id"], identity.tenant_a.id)

    duplicate = client.post(
        ADMIN_BASE,
        headers=headers,
        json={
            "classroom_class_id": recorded["id"],
            "workspace_id": str(identity.tenant_b.id),
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONFLICT"
    assert (
        db_session.scalar(
            select(func.count()).select_from(ClassroomAllocation).where(
                ClassroomAllocation.status == "ACTIVE"
            )
        )
        == 1
    )


def test_the_database_rejects_a_second_active_row(
    client: TestClient, identity, db_session
):
    """The API pre-check is not the guarantee; the partial unique index is."""

    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    _allocate(client, headers, recorded["id"], identity.tenant_a.id)
    klass = db_session.get(ClassroomClass, recorded["id"])
    assert klass is not None
    db_session.add(
        ClassroomAllocation(
            classroom_class_id=klass.id,
            workspace_id=identity.tenant_b.id,
            course_id=klass.course_id,
            class_name=klass.name,
            workspace_name=identity.tenant_b.name,
            status="ACTIVE",
            origin="ALLOCATE",
            allocated_by_subject="another-operator",
            allocated_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_release_makes_the_class_available_and_preserves_history(
    client: TestClient, identity, db_session
):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    first = _allocate(client, headers, recorded["id"], identity.tenant_a.id)

    released = client.post(
        f"{ADMIN_BASE}/{first['id']}/release",
        headers=headers,
        json={"reason": "teacher moved department"},
    )
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "RELEASED"
    assert released.json()["released_at"]

    available = client.get(f"{ADMIN_BASE}/available-classes", headers=headers)
    assert [row["id"] for row in available.json()] == [recorded["id"]]

    second = _allocate(client, headers, recorded["id"], identity.tenant_b.id)
    assert second["workspace_name"] == "Beta"

    history = client.get(f"{ADMIN_BASE}?status=ALL", headers=headers).json()
    assert history["total"] == 2
    assert {row["status"] for row in history["items"]} == {"ACTIVE", "RELEASED"}


def test_reassignment_releases_and_reallocates_in_one_operation(
    client: TestClient, identity, db_session
):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    first = _allocate(client, headers, recorded["id"], identity.tenant_a.id)

    moved = client.post(
        f"{ADMIN_BASE}/{first['id']}/reassign",
        headers=headers,
        json={"workspace_id": str(identity.tenant_b.id), "reason": "new teacher"},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["status"] == "ACTIVE"
    assert body["origin"] == "REASSIGN"
    assert body["workspace_name"] == "Beta"
    assert body["previous_allocation_id"] == first["id"]

    old = db_session.get(ClassroomAllocation, first["id"])
    assert old is not None
    assert old.status == "RELEASED"
    assert old.released_at is not None
    assert old.release_reason == "Reassigned: new teacher"

    audit = db_session.scalar(
        select(PlatformAuditEvent).where(
            PlatformAuditEvent.action == "classroom.allocation_reassigned"
        )
    )
    assert audit is not None
    assert audit.detail["previous_workspace_id"] == str(identity.tenant_a.id)


def test_reassignment_without_an_active_allocation_fails_safely(
    client: TestClient, identity
):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    first = _allocate(client, headers, recorded["id"], identity.tenant_a.id)
    released = client.post(
        f"{ADMIN_BASE}/{first['id']}/release", headers=headers, json={}
    )
    assert released.status_code == 200

    response = client.post(
        f"{ADMIN_BASE}/{first['id']}/reassign",
        headers=headers,
        json={"workspace_id": str(identity.tenant_b.id), "reason": "too late"},
    )
    assert response.status_code == 409
    history = client.get(f"{ADMIN_BASE}?status=ACTIVE", headers=headers).json()
    assert history["total"] == 0


def test_reassignment_to_the_same_workspace_is_refused(client: TestClient, identity):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    first = _allocate(client, headers, recorded["id"], identity.tenant_a.id)

    response = client.post(
        f"{ADMIN_BASE}/{first['id']}/reassign",
        headers=headers,
        json={
            "workspace_id": str(identity.tenant_a.id),
            "reason": "same workspace",
        },
    )
    assert response.status_code == 409


def test_suspended_and_demo_workspaces_cannot_receive_a_class(
    client: TestClient, identity, db_session
):
    demo = Tenant(name="Demo", slug="demo", is_demo=True)
    closed = Tenant(name="Closed", slug="closed", is_active=False)
    db_session.add_all([demo, closed])
    db_session.commit()
    headers = _owner_headers(identity)
    recorded = _register(client, headers)

    for workspace in (demo, closed):
        response = client.post(
            ADMIN_BASE,
            headers=headers,
            json={
                "classroom_class_id": recorded["id"],
                "workspace_id": str(workspace.id),
            },
        )
        assert response.status_code == 409, workspace.name


def test_registration_requires_attestation(client: TestClient, identity):
    response = client.post(
        f"{ADMIN_BASE}/classes",
        headers=_owner_headers(identity),
        json={"course_id": "600200", "name": "Unattested", "attested": False},
    )
    assert response.status_code == 422


def test_a_workspace_owner_cannot_administer_allocations(
    client: TestClient, identity
):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    workspace_owner = _headers(identity.user_a)
    teacher = _headers(identity.user_a, "supervisor")

    for user_headers in (workspace_owner, teacher):
        listing = client.get(ADMIN_BASE, headers=user_headers)
        assert listing.status_code == 403
        allocation = client.post(
            ADMIN_BASE,
            headers=user_headers,
            json={
                "classroom_class_id": recorded["id"],
                "workspace_id": str(identity.tenant_a.id),
            },
        )
        assert allocation.status_code == 403


def test_anonymous_requests_are_refused(client: TestClient):
    assert client.get(ADMIN_BASE).status_code == 401
    assert client.post(ADMIN_BASE, json={}).status_code == 401


def test_the_workspace_view_is_tenant_scoped(client: TestClient, identity):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)
    _allocate(client, headers, recorded["id"], identity.tenant_a.id)

    own = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/classroom-allocations",
        headers=_headers(identity.user_a),
    )
    assert own.status_code == 200
    assert own.json()[0]["course_id"] == recorded["course_id"]

    foreign = client.get(
        f"/api/v1/workspaces/{identity.tenant_b.id}/classroom-allocations",
        headers=_headers(identity.user_a),
    )
    assert foreign.status_code == 404


def test_concurrent_allocations_have_one_winner(
    client: TestClient, identity
):
    headers = _owner_headers(identity)
    recorded = _register(client, headers)

    def attempt(workspace_id) -> int:
        return client.post(
            ADMIN_BASE,
            headers=headers,
            json={
                "classroom_class_id": recorded["id"],
                "workspace_id": str(workspace_id),
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(
            pool.map(attempt, [identity.tenant_a.id, identity.tenant_b.id])
        )
    assert statuses == [201, 409]
