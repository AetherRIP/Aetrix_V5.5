"""Project identity is evidence about Google's meter, never the Aetrix pool.

Gemini's free tier is metered per Google Cloud project and model.  Aetrix now
administers one pool per credential (``gemini-key-{id}``), but a pool is not proof
of a separate project: fifteen lent keys may bill one project.  These tests pin
the evidence vocabulary and the migration that stores it; the pool accounting
itself is covered by ``test_credential_pools.py``.

The migration tests read the revision text, because "additive only" is a property
of the statements: no ledger row may be recalculated to fit the new columns.
"""

from __future__ import annotations

import ast
import pathlib

from app.db import models as db_models
from app.services.project_identity import (
    DECLARED,
    PROJECT_IDENTITY_UNVERIFIED,
    VERIFIED,
    classify,
    is_established,
    pool_identity,
)

BACKEND = pathlib.Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "migrations" / "versions"
POOL_REVISION = VERSIONS / "0039_credential_pools.py"


# -- identity vocabulary ------------------------------------------------------


def test_a_synthetic_pool_label_is_not_an_identity() -> None:
    identity, reason = classify(
        project_id="user-downloads-pool", google_verified=False, declared_at=None
    )
    assert identity == PROJECT_IDENTITY_UNVERIFIED
    assert is_established(identity) is False
    assert "pooled label" in reason or "not a Google Cloud project id" in reason


def test_declaring_a_real_project_is_a_declared_identity_not_a_verified_one() -> None:
    identity, reason = classify(
        project_id="aetrix-marking-482113",
        google_verified=False,
        declared_at=object(),  # any recorded assertion instant
    )
    assert identity == DECLARED
    assert is_established(identity) is True
    assert "has not confirmed" in reason


def test_google_evidence_outranks_an_assertion() -> None:
    identity, _ = classify(
        project_id="aetrix-marking-482113",
        google_verified=True,
        declared_at=object(),
    )
    assert identity == VERIFIED
    assert is_established(identity) is True


def test_a_pool_label_cannot_be_declared_as_a_project() -> None:
    """Shape alone accepts ``user-downloads-pool``; the pool convention must not."""

    identity, reason = classify(
        project_id="user-downloads-pool",
        google_verified=False,
        declared_at=object(),
    )
    assert identity == PROJECT_IDENTITY_UNVERIFIED
    assert is_established(identity) is False
    assert "pooled label" in reason


def test_google_evidence_still_confirms_a_project_however_it_is_named() -> None:
    identity, _ = classify(
        project_id="aetrix-pool", google_verified=True, declared_at=None
    )
    assert identity == VERIFIED


def test_a_declared_id_that_cannot_be_a_project_stays_unverified() -> None:
    identity, _ = classify(
        project_id="unattributed", google_verified=False, declared_at=object()
    )
    assert identity == PROJECT_IDENTITY_UNVERIFIED
    assert is_established(identity) is False


def test_identity_is_ranked_with_google_first_for_a_group_display() -> None:
    assert pool_identity([PROJECT_IDENTITY_UNVERIFIED, DECLARED]) == DECLARED
    assert pool_identity([DECLARED, VERIFIED]) == VERIFIED
    assert pool_identity([]) == PROJECT_IDENTITY_UNVERIFIED


def test_an_unestablished_project_is_about_google_capacity_not_the_pool() -> None:
    """The vocabulary expresses doubt about Google, never a routing block."""

    identity, reason = classify(
        project_id="user-downloads-pool", google_verified=False, declared_at=None
    )
    assert is_established(identity) is False
    assert "Google-level capacity" in reason
    assert "not routed" not in reason


# -- the revision itself ------------------------------------------------------


def _identity_columns() -> set[str]:
    return {
        node.target.id
        for node in ast.walk(
            ast.parse(pathlib.Path(db_models.__file__).read_text(encoding="utf-8"))
        )
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _flat(value: str) -> str:
    return "".join(value.split())


def _revision_body() -> str:
    tree = ast.parse(POOL_REVISION.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_BODY":
            return str(node.value.value)
    raise AssertionError("the revision declares no constraint body")


def _revision_pool_body() -> str:
    tree = ast.parse(POOL_REVISION.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_POOL_BODY":
            return str(node.value.value)
    raise AssertionError("the revision declares no pool constraint body")


def test_the_identity_vocabulary_matches_the_database_constraint() -> None:
    expected = "project_identityIN('VERIFIED','DECLARED','PROJECT_IDENTITY_UNVERIFIED')"
    assert _flat(_revision_body()) == expected

    from sqlalchemy import CheckConstraint

    rendered = [
        _flat(str(constraint.sqltext))
        for constraint in db_models.ProviderCredential.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert expected in rendered


def test_a_pool_id_is_never_a_google_project_id_by_shape() -> None:
    expected = "pool_idLIKE'gemini-key-%'"
    assert _flat(_revision_pool_body()) == expected
    from sqlalchemy import CheckConstraint

    rendered = [
        _flat(str(constraint.sqltext))
        for constraint in db_models.ProviderCredential.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert expected in rendered


def test_the_revision_is_additive_and_never_rewrites_a_ledger_row() -> None:
    source = POOL_REVISION.read_text(encoding="utf-8")
    for column in (
        "project_identity",
        "project_identity_reason",
        "project_identity_declared_at",
        "project_identity_declared_by",
        "pool_id",
        "cooldown_kind",
        "consecutive_failures",
        "last_quota_exhausted_at",
        "last_quota_reason",
    ):
        assert column in source
    assert "ADD COLUMN" in source

    # Existing rows are stamped unverified and given the pool derived from their
    # own primary key — neither is a rewrite of recorded history.
    assert "PROJECT_IDENTITY_UNVERIFIED" in source
    assert "'gemini-key-' || id::text" in source
    # ... and no statement may recalculate, move or delete recorded history.  A
    # comment naming the ledger tables is fine; a statement touching them is not.
    for line in source.splitlines():
        if "provider_usage" in line or "provider_quota_reservations" in line:
            assert not any(
                keyword in line.upper()
                for keyword in ("UPDATE ", "DELETE ", "ALTER TABLE", "DROP ")
            ), line


def test_the_pool_columns_are_declared_on_the_credential() -> None:
    columns = _identity_columns()
    assert {
        "project_identity",
        "project_identity_reason",
        "project_identity_declared_at",
        "project_identity_declared_by",
        "pool_id",
        "cooldown_kind",
        "consecutive_failures",
        "last_quota_exhausted_at",
        "last_quota_reason",
    } <= columns
