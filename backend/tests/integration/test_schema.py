from __future__ import annotations

import uuid

import pytest
from app.db.base import Base
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError


def test_every_model_table_exists(engine) -> None:
    names = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)
    assert expected <= names
    assert "alembic_version" in names


def test_foreign_keys_are_enforced_by_the_database(engine) -> None:
    with engine.connect() as connection:
        count = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE constraint_type = 'FOREIGN KEY' AND constraint_schema = 'public'"
            )
        ).scalar_one()
    assert count >= 50


def test_audit_events_cannot_be_rewritten(engine) -> None:
    tenant_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants (id, name, slug, is_active, created_at, updated_at) "
                "VALUES (:id, 'Audit tenant', 'audit-tenant', true, now(), now())"
            ),
            {"id": tenant_id},
        )
        connection.execute(
            text(
                "INSERT INTO audit_events "
                "(id, tenant_id, actor_type, action, entity_type, entity_id, detail, created_at) "
                "VALUES (:id, :tenant, 'SYSTEM', 'test.event', 'test', '1', '{}'::json, now())"
            ),
            {"id": uuid.uuid4(), "tenant": tenant_id},
        )

    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(text("UPDATE audit_events SET action = 'tampered'"))


def test_provider_usage_cannot_be_rewritten(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_usage "
                "(id, project_id, provider, model, purpose, reported, created_at) "
                "VALUES (:id, 'test-project', 'google', 'test-model', 'marking', true, now())"
            ),
            {"id": uuid.uuid4()},
        )

    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(text("UPDATE provider_usage SET model = 'tampered'"))
