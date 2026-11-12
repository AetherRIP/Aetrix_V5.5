"""Regression cover for the integration suite's loopback-only database guard.

The integration suite migrates its database to head and truncates every table,
so ``tests/conftest.py`` refuses any DSN that is not on this machine. These
tests pin the accepted and refused shapes, prove a refusal names the offending
database without leaking its password, and prove the check happens before
Alembic is invoked rather than after the schema has already moved.
"""

from __future__ import annotations

import alembic.command
import pytest
from app.core.config import get_settings
from sqlalchemy.engine import make_url
from tests.conftest import _is_loopback_dsn, _refuse_non_loopback, migrated_database

PASSWORD = "hunter2-do-not-print"

REMOTE_POOLER = (
    "postgresql+psycopg://postgres.wswsibspyjrhlahxcefs:"
    f"{PASSWORD}@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require"
)

LOOPBACK_DSNS = [
    "postgresql+psycopg://postgres@localhost:5432/aetrix",
    "postgresql+psycopg://postgres@127.0.0.1:55432/aetrix_test",
    "postgresql+psycopg://postgres@127.0.0.53:5432/aetrix",
    "postgresql+psycopg://postgres@[::1]:5432/aetrix",
    "postgresql+psycopg://postgres@/aetrix?host=/var/run/postgresql",
]

REFUSED_DSNS = [
    REMOTE_POOLER,
    "postgresql+psycopg://postgres@db.example.com:5432/aetrix",
    "postgresql+psycopg://postgres@203.0.113.10:5432/aetrix",
]


@pytest.mark.parametrize("dsn", LOOPBACK_DSNS)
def test_a_database_on_this_machine_is_accepted(dsn: str) -> None:
    assert _is_loopback_dsn(dsn) is True
    _refuse_non_loopback(dsn)  # does not raise


@pytest.mark.parametrize("dsn", REFUSED_DSNS)
def test_a_remote_database_is_refused_and_named(dsn: str) -> None:
    assert _is_loopback_dsn(dsn) is False

    with pytest.raises(RuntimeError) as raised:
        _refuse_non_loopback(dsn)

    message = str(raised.value)
    assert "Refusing to run the integration suite" in message
    assert "AETRIX_TEST_DATABASE_URL" in message
    assert make_url(dsn).host in message, "the refusal must name the offending host"


def test_the_refusal_redacts_the_password() -> None:
    with pytest.raises(RuntimeError) as raised:
        _refuse_non_loopback(REMOTE_POOLER)

    message = str(raised.value)
    assert PASSWORD not in message
    assert "***" in message
    assert "pooler.supabase.com" in message


def test_the_migration_fixture_refuses_before_alembic_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-loopback URL must stop the run before ``alembic upgrade`` touches it."""
    upgrades: list[tuple[object, ...]] = []

    def _sentinel_upgrade(*args: object, **kwargs: object) -> None:
        upgrades.append(args)

    monkeypatch.setattr(alembic.command, "upgrade", _sentinel_upgrade)
    monkeypatch.setenv("AETRIX_DATABASE__URL", REMOTE_POOLER)
    get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="non-loopback"):
            migrated_database.__wrapped__()
    finally:
        get_settings.cache_clear()

    assert upgrades == [], "alembic upgrade ran against a non-loopback database"
