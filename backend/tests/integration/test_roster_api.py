"""Classes and the student roster, over the real API and a real database."""

from __future__ import annotations


def _create_class(client, headers, tenant_id, name: str, year_group: str | None = "Year 10"):
    response = client.post(
        f"/api/v1/workspaces/{tenant_id}/classes",
        headers=headers,
        json={"name": name, "year_group": year_group},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_classes_and_students_are_created_listed_and_counted(
    client, identity, auth_headers
) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id

    created = _create_class(client, headers, workspace, "10A")
    assert created["name"] == "10A"
    assert created["year_group"] == "Year 10"
    assert created["student_count"] == 0

    student = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-001", "display_name": "Ada Lovelace", "class_id": created["id"]},
    )
    assert student.status_code == 201, student.text
    body = student.json()
    assert body["student_ref"] == "S-001"
    assert body["display_name"] == "Ada Lovelace"
    assert body["class_id"] == created["id"]

    classes = client.get(f"/api/v1/workspaces/{workspace}/classes", headers=headers)
    assert classes.status_code == 200
    assert classes.json()[0]["student_count"] == 1

    students = client.get(f"/api/v1/workspaces/{workspace}/students", headers=headers)
    assert students.status_code == 200
    assert [row["student_ref"] for row in students.json()] == ["S-001"]

    filtered = client.get(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        params={"class_id": created["id"]},
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1

    empty_filter = client.get(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        params={"class_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert empty_filter.status_code == 404


def test_roster_rejects_duplicates_and_blank_names(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id
    _create_class(client, headers, workspace, "10A")

    duplicate = client.post(
        f"/api/v1/workspaces/{workspace}/classes",
        headers=headers,
        json={"name": "10A"},
    )
    assert duplicate.status_code == 409

    blank = client.post(
        f"/api/v1/workspaces/{workspace}/classes",
        headers=headers,
        json={"name": "   "},
    )
    assert blank.status_code == 422

    first = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-001"},
    )
    assert first.status_code == 201
    duplicate_student = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-001"},
    )
    assert duplicate_student.status_code == 409

    unknown_class = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-002", "class_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert unknown_class.status_code == 404


def test_roster_writes_require_a_teaching_role(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id
    created = _create_class(client, headers, workspace, "10A")
    student = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-001", "class_id": created["id"]},
    ).json()

    viewer = auth_headers(identity.viewer)
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace}/classes", headers=viewer, json={"name": "10B"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace}/students",
            headers=viewer,
            json={"student_ref": "S-002"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/classes/{created['id']}", headers=viewer, json={"name": "10C"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/students/{student['id']}", headers=viewer, json={"display_name": "X"}
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/classes/{created['id']}", headers=viewer).status_code == 403

    # Reading is a workspace capability, not a teaching one.
    assert client.get(f"/api/v1/workspaces/{workspace}/classes", headers=viewer).status_code == 200
    assert client.get(f"/api/v1/workspaces/{workspace}/students", headers=viewer).status_code == 200


def test_roster_is_invisible_to_another_workspace(client, identity, auth_headers) -> None:
    owner = auth_headers(identity.user_a)
    outsider = auth_headers(identity.user_b)
    workspace = identity.tenant_a.id
    created = _create_class(client, owner, workspace, "10A")
    student = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=owner,
        json={"student_ref": "S-001", "class_id": created["id"]},
    ).json()

    assert (
        client.get(f"/api/v1/workspaces/{workspace}/classes", headers=outsider).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace}/classes", headers=outsider, json={"name": "10B"}
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{workspace}/students", headers=outsider
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/classes/{created['id']}", headers=outsider, json={"name": "10B"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/students/{student['id']}",
            headers=outsider,
            json={"display_name": "Taken over"},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/classes/{created['id']}", headers=outsider).status_code == 404

    # A class id from another workspace cannot be attached to your own roster.
    cross = client.post(
        f"/api/v1/workspaces/{identity.tenant_b.id}/students",
        headers=outsider,
        json={"student_ref": "B-001", "class_id": created["id"]},
    )
    assert cross.status_code == 404


def test_deleting_a_class_keeps_its_students(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id
    created = _create_class(client, headers, workspace, "10A")
    student = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-001", "display_name": "Ada", "class_id": created["id"]},
    ).json()

    deleted = client.delete(f"/api/v1/classes/{created['id']}", headers=headers)
    assert deleted.status_code == 204

    assert client.get(f"/api/v1/workspaces/{workspace}/classes", headers=headers).json() == []
    survivors = client.get(f"/api/v1/workspaces/{workspace}/students", headers=headers).json()
    assert [row["student_ref"] for row in survivors] == ["S-001"]
    assert survivors[0]["class_id"] is None

    updated = client.patch(
        f"/api/v1/students/{student['id']}",
        headers=headers,
        json={"display_name": "Ada Lovelace"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Ada Lovelace"

    assert client.delete(f"/api/v1/students/{student['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/workspaces/{workspace}/students", headers=headers).json() == []


def test_roster_changes_are_audited(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id
    created = _create_class(client, headers, workspace, "10A")
    client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-001", "class_id": created["id"]},
    )

    audit = client.get(
        f"/api/v1/workspaces/{workspace}/audit",
        headers=headers,
        params={"entity_type": "class"},
    )
    assert audit.status_code == 200, audit.text
    assert [row["action"] for row in audit.json()] == ["class.created"]

    students = client.get(
        f"/api/v1/workspaces/{workspace}/audit",
        headers=headers,
        params={"entity_type": "student"},
    )
    assert [row["action"] for row in students.json()] == ["student.added"]
    assert students.json()[0]["detail"]["student_ref"] == "S-001"
