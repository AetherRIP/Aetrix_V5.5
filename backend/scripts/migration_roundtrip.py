"""Verify migration 0032 upgrade -> downgrade -> upgrade on a disposable database.

Refuses to run against anything but a loopback database, because it migrates and
drops columns.  It seeds one usage row first so the round trip proves that
existing ledger rows survive both directions, not merely that the DDL compiles.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, make_url, text  # noqa: E402

ADDED = (
    "model_role",
    "model_chain_position",
    "attempt_index",
    "routing_decision",
    "cost_status",
)


def _dsn() -> str:
    dsn = os.environ.get("AETRIX_TEST_DATABASE_URL") or os.environ.get(
        "AETRIX_DATABASE__URL", ""
    )
    if not dsn:
        raise SystemExit("set AETRIX_TEST_DATABASE_URL to a disposable loopback database")
    os.environ["AETRIX_DATABASE__URL"] = dsn
    host = (make_url(dsn).host or "").lower()
    if host not in {"", "localhost", "::1"} and not host.startswith("127."):
        raise SystemExit(f"refusing a non-loopback database ({host}); this test drops columns")
    return dsn


def _columns(dsn: str) -> set[str]:
    engine = create_engine(dsn)
    try:
        return {column["name"] for column in inspect(engine).get_columns("provider_usage")}
    finally:
        engine.dispose()


def _revision(dsn: str) -> str | None:
    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            return connection.execute(text("select version_num from alembic_version")).scalar()
    finally:
        engine.dispose()


def _seed_row(dsn: str) -> tuple[uuid.UUID, int]:
    """Insert one usage row through the ORM, so defaults and constraints apply."""

    from app.core.config import get_settings
    from app.db.models import ProviderUsage, Tenant
    from app.db.session import get_session_factory

    session_factory = get_session_factory(get_settings())
    with session_factory() as session:
        tenant = Tenant(name="migration-roundtrip", slug=f"rt-{uuid.uuid4().hex[:8]}")
        session.add(tenant)
        session.flush()
        usage = ProviderUsage(
            tenant_id=tenant.id,
            provider="roundtrip",
            model="roundtrip-model",
            purpose="marking",
            success=True,
        )
        session.add(usage)
        session.commit()
        return usage.id, 1


def _count(dsn: str) -> int:
    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            return int(connection.execute(text("select count(*) from provider_usage")).scalar())
    finally:
        engine.dispose()


def main() -> int:
    dsn = _dsn()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", dsn.replace("%", "%%"))

    report: dict[str, object] = {}

    command.upgrade(config, "head")
    report["upgraded_revision"] = _revision(dsn)
    report["columns_after_upgrade"] = sorted(_columns(dsn) & set(ADDED))

    usage_id, seeded = _seed_row(dsn)
    before = _count(dsn)
    report["rows_seeded"] = before

    command.downgrade(config, "0031_scheme_criteria_rules_hash")
    report["downgraded_revision"] = _revision(dsn)
    report["columns_after_downgrade"] = sorted(_columns(dsn) & set(ADDED))
    report["rows_after_downgrade"] = _count(dsn)

    command.upgrade(config, "head")
    report["reupgraded_revision"] = _revision(dsn)
    report["columns_after_reupgrade"] = sorted(_columns(dsn) & set(ADDED))
    report["rows_after_reupgrade"] = _count(dsn)

    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "select model_role, model_chain_position, attempt_index, "
                    "routing_decision, cost_status, provider, model, success "
                    "from provider_usage where id = :id"
                ),
                {"id": str(usage_id)},
            ).one()
    finally:
        engine.dispose()
    report["seeded_row_after_roundtrip"] = {
        "provider": row[5],
        "model": row[6],
        "success": row[7],
        "new_columns": list(row[:5]),
    }

    expected = sorted(ADDED)
    ok = (
        report["columns_after_upgrade"] == expected
        and report["columns_after_downgrade"] == []
        and report["columns_after_reupgrade"] == expected
        and report["rows_after_downgrade"] == before
        and report["rows_after_reupgrade"] == before
        and report["seeded_row_after_roundtrip"]["model"] == "roundtrip-model"
        and all(value is None for value in report["seeded_row_after_roundtrip"]["new_columns"])
    )
    report["result"] = "PASS" if ok else "FAIL"
    report["seeded_rows"] = seeded
    print(json.dumps(report, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
