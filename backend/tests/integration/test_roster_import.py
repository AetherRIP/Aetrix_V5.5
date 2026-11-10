"""Bulk student import: real CSV files, per-row outcomes, tenant scope."""

from __future__ import annotations

import csv
import io


def _csv(rows: list[list[str]], header: list[str] | None = None) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header or ["student_ref", "display_name", "class"])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _post(client, headers, workspace, data: bytes, *, name="roster.csv", content_type="text/csv"):
    return client.post(
        f"/api/v1/workspaces/{workspace}/students/import",
        headers=headers,
        files={"file": (name, data, content_type)},
    )


def test_import_creates_students_and_their_classes(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id
    payload = _csv(
        [
            ["S-001", "Ada Lovelace", "10A"],
            ["S-002", "Grace Hopper", "10A"],
            ["S-003", "", "10B"],
        ]
    )

    response = _post(client, headers, workspace, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_rows"] == 3
    assert body["created"] == 3
    assert body["skipped"] == 0
    assert body["failed"] == 0
    assert body["classes_created"] == 2
    assert body["issues"] == []
    assert body["created_refs"] == ["S-001", "S-002", "S-003"]

    classes = client.get(f"/api/v1/workspaces/{workspace}/classes", headers=headers).json()
    by_name = {row["name"]: row for row in classes}
    assert set(by_name) == {"10A", "10B"}
    assert by_name["10A"]["student_count"] == 2

    students = client.get(f"/api/v1/workspaces/{workspace}/students", headers=headers).json()
    assert [row["student_ref"] for row in students] == ["S-001", "S-002", "S-003"]
    assert students[2]["display_name"] is None
    assert students[2]["class_id"] == by_name["10B"]["id"]

    audit = client.get(
        f"/api/v1/workspaces/{workspace}/audit",
        headers=headers,
        params={"action": "student.imported"},
    )
    assert audit.status_code == 200, audit.text
    assert audit.json()[0]["detail"] == {
        "total_rows": 3,
        "created": 3,
        "skipped": 0,
        "failed": 0,
        "classes_created": 2,
    }

    # Importing the same file again creates nothing and says so row by row.
    again = _post(client, headers, workspace, payload)
    assert again.status_code == 200
    repeat = again.json()
    assert repeat["created"] == 0
    assert repeat["skipped"] == 3
    assert repeat["classes_created"] == 0
    assert all(issue["kind"] == "SKIPPED" for issue in repeat["issues"])
    assert len(
        client.get(f"/api/v1/workspaces/{workspace}/students", headers=headers).json()
    ) == 3


def test_import_reports_each_bad_row_with_its_line_number(
    client, identity, auth_headers
) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id
    existing = client.post(
        f"/api/v1/workspaces/{workspace}/students",
        headers=headers,
        json={"student_ref": "S-EXIST"},
    )
    assert existing.status_code == 201

    long_ref = "R" * 121
    payload = _csv(
        [
            ["S-EXIST", "Already here", "10A"],
            ["S-001", "Ada", "10A"],
            ["", "No reference", "10A"],
            ["S-001", "Duplicate", "10A"],
            [long_ref, "Too long", "10A"],
        ]
    )
    response = _post(client, headers, workspace, payload)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_rows"] == 5
    assert body["created"] == 1
    assert body["skipped"] == 2
    assert body["failed"] == 2
    assert body["classes_created"] == 1
    assert [(issue["row"], issue["kind"]) for issue in body["issues"]] == [
        (2, "SKIPPED"),
        (4, "ERROR"),
        (5, "SKIPPED"),
        (6, "ERROR"),
    ]
    assert "already exists" in body["issues"][0]["message"]
    assert body["issues"][1]["message"] == "student_ref is required."
    assert "Duplicate" in body["issues"][2]["message"]
    assert "120" in body["issues"][3]["message"]


def test_import_validates_the_file_before_writing_anything(
    client, identity, auth_headers
) -> None:
    headers = auth_headers(identity.user_a)
    workspace = identity.tenant_a.id

    missing_header = _post(
        client, headers, workspace, b"name,class\nAda,10A\n"
    )
    assert missing_header.status_code == 422
    assert missing_header.json()["error"]["details"]["required"] == ["student_ref"]

    empty = _post(client, headers, workspace, b"")
    assert empty.status_code == 422

    wrong_type = _post(
        client,
        headers,
        workspace,
        b"student_ref\nS-001\n",
        name="roster.png",
        content_type="image/png",
    )
    assert wrong_type.status_code == 415

    too_large = _post(
        client, headers, workspace, b"student_ref\n" + b"x" * 1_000_050
    )
    assert too_large.status_code == 413

    too_many = _post(
        client,
        headers,
        workspace,
        _csv([[f"S-{index:04d}", "", ""] for index in range(501)]),
    )
    assert too_many.status_code == 422
    assert too_many.json()["error"]["details"]["max_rows"] == 500

    students = client.get(f"/api/v1/workspaces/{workspace}/students", headers=headers).json()
    assert students == []
    assert client.get(f"/api/v1/workspaces/{workspace}/classes", headers=headers).json() == []


def test_import_is_teacher_only_and_workspace_scoped(
    client, identity, auth_headers
) -> None:
    owner = auth_headers(identity.user_a)
    outsider = auth_headers(identity.user_b)
    workspace = identity.tenant_a.id
    payload = _csv([["S-001", "Ada", "10A"]])

    assert _post(client, auth_headers(identity.viewer), workspace, payload).status_code == 403
    assert _post(client, outsider, workspace, payload).status_code == 404

    own = _post(client, outsider, identity.tenant_b.id, payload)
    assert own.status_code == 200
    assert own.json()["created"] == 1

    # The import landed in Beta, and Alpha still cannot see it.
    assert client.get(
        f"/api/v1/workspaces/{identity.tenant_b.id}/students", headers=outsider
    ).json()[0]["student_ref"] == "S-001"
    assert client.get(
        f"/api/v1/workspaces/{workspace}/students", headers=owner
    ).json() == []
