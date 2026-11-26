"""Manual marking-criteria authoring through the authenticated API.

The engine awards marks only from stored rows a person approved.  An uploaded
scheme whose extraction never ran has none, so a teacher must be able to type
them — within the approved blueprint's question maxima, before approval, and
never over an approved set.

Disposable loopback PostgreSQL only; no provider or Google call is made.
"""

from __future__ import annotations

import pytest
from app.db.models import MarkingCriterion, MarkScheme, MarkSchemeVersion
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


def _draft_version(db_session, identity, paper) -> MarkSchemeVersion:
    """An uploaded scheme version whose criteria nobody has written yet."""

    scheme = MarkScheme(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        title="Manual criteria scheme",
    )
    db_session.add(scheme)
    db_session.flush()
    version = MarkSchemeVersion(
        tenant_id=identity.tenant_a.id,
        mark_scheme_id=scheme.id,
        version=1,
        status="DRAFT",
        source="UPLOAD",
        content_hash="b" * 64,
    )
    db_session.add(version)
    db_session.commit()
    return version


def _criteria_url(version_id) -> str:
    return f"/api/v1/schemes/{version_id}/criteria"


def _create(client, headers, version_id, blueprint_id, **overrides):
    payload = {
        "blueprint_version_id": str(blueprint_id),
        "question_id": "1a",
        "code": "M1",
        "marks": 1,
        "ordinal": 0,
        "description": "M1 for forming the equation",
    }
    payload.update(overrides)
    return client.post(_criteria_url(version_id), headers=headers, json=payload)


def test_a_teacher_authors_criteria_within_the_question_maximum(
    client, auth_headers, identity, db_session, paper
) -> None:
    version = _draft_version(db_session, identity, paper)
    headers = auth_headers(identity.user_a)

    created = _create(client, headers, version.id, paper.blueprint.id)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["question_id"] == "1a"
    assert body["marks"] == 1

    listed = client.get(_criteria_url(version.id), headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [body["id"]]

    # 1a is worth 2 marks in the fixture blueprint.
    over = _create(client, headers, version.id, paper.blueprint.id, code="A1", marks=2)
    assert over.status_code == 422, over.text
    assert "1 mark(s) left" in over.text

    stored = db_session.scalar(
        select(func.count())
        .select_from(MarkingCriterion)
        .where(MarkingCriterion.scheme_version_id == version.id)
    )
    assert stored == 1, "a refused criterion must not be stored"


def test_unknown_questions_and_duplicate_identities_are_refused(
    client, auth_headers, identity, db_session, paper
) -> None:
    version = _draft_version(db_session, identity, paper)
    headers = auth_headers(identity.user_a)

    unknown = _create(
        client, headers, version.id, paper.blueprint.id, question_id="9z"
    )
    assert unknown.status_code == 422, unknown.text

    assert _create(client, headers, version.id, paper.blueprint.id).status_code == 201
    duplicate = _create(client, headers, version.id, paper.blueprint.id)
    assert duplicate.status_code == 409, duplicate.text


def test_criteria_can_be_corrected_and_removed_before_approval(
    client, auth_headers, identity, db_session, paper
) -> None:
    version = _draft_version(db_session, identity, paper)
    headers = auth_headers(identity.user_a)
    row = _create(client, headers, version.id, paper.blueprint.id).json()

    corrected = client.patch(
        f"{_criteria_url(version.id)}/{row['id']}",
        headers=headers,
        json={"marks": 2},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["marks"] == 2

    too_many = client.patch(
        f"{_criteria_url(version.id)}/{row['id']}",
        headers=headers,
        json={"marks": 3},
    )
    assert too_many.status_code == 422, too_many.text

    removed = client.delete(f"{_criteria_url(version.id)}/{row['id']}", headers=headers)
    assert removed.status_code == 204
    assert client.get(_criteria_url(version.id), headers=headers).json() == []


def test_the_wrong_role_and_another_tenant_cannot_author(
    client, auth_headers, identity, db_session, paper
) -> None:
    version = _draft_version(db_session, identity, paper)

    viewer = _create(
        client, auth_headers(identity.viewer), version.id, paper.blueprint.id
    )
    assert viewer.status_code == 403, viewer.text

    outsider = _create(
        client, auth_headers(identity.user_b), version.id, paper.blueprint.id
    )
    assert outsider.status_code == 404, outsider.text


def test_approved_criteria_are_immutable_and_a_revision_starts_unapproved(
    client, auth_headers, identity, db_session, paper
) -> None:
    headers = auth_headers(identity.user_a)

    refused = _create(
        client, headers, paper.scheme_version.id, paper.blueprint.id, marks=1
    )
    assert refused.status_code == 409, refused.text

    revised = client.post(
        f"/api/v1/schemes/{paper.scheme_version.id}/revisions", headers=headers
    )
    assert revised.status_code == 201, revised.text
    body = revised.json()
    assert body["id"] != str(paper.scheme_version.id)
    assert body["status"] == "DRAFT"

    copied = db_session.scalar(
        select(func.count())
        .select_from(MarkingCriterion)
        .where(MarkingCriterion.scheme_version_id == body["id"])
    )
    original = db_session.scalar(
        select(func.count())
        .select_from(MarkingCriterion)
        .where(MarkingCriterion.scheme_version_id == paper.scheme_version.id)
    )
    assert copied == original > 0

    version = db_session.get(MarkSchemeVersion, body["id"])
    assert version is not None
    assert version.criteria_approved_at is None
    assert version.criteria_rules_hash is None

    # The copy is writable; the approved original is untouched.
    first = db_session.scalar(
        select(MarkingCriterion).where(
            MarkingCriterion.scheme_version_id == version.id
        )
    )
    assert first is not None
    edited = client.patch(
        f"{_criteria_url(version.id)}/{first.id}",
        headers=headers,
        json={"description": "Reviewed wording"},
    )
    assert edited.status_code == 200, edited.text
    db_session.refresh(paper.scheme_version)
    assert paper.scheme_version.criteria_approved_at is not None
