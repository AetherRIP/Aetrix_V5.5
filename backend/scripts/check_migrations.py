"""Prove the migration chain applies to an empty database and reverses again.

``pytest`` upgrades the integration database to head, so an upgrade that fails on
a database which has never seen it is already caught there.  Two things are not:

* a revision whose ``downgrade`` no longer reverses (nothing in the suite ever
  calls it), and
* a revision that only applies on top of an existing schema, because the suite's
  database has usually been migrated before.

This script empties ``public`` first, then walks the whole chain
``upgrade head`` -> ``downgrade base`` -> ``upgrade head``, so a new migration is
exercised exactly as a fresh deployment and a rollback would run it.

It drops the schema and therefore refuses any host that is not this machine.
Set ``AETRIX_TEST_DATABASE_URL`` (preferred) or ``AETRIX_DATABASE__URL`` to a
disposable loopback database::

    export AETRIX_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/aetrix_test
    cd backend && python scripts/check_migrations.py

Exit status is 0 only when every step ran and the database is back at head.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import create_engine, make_url, text  # noqa: E402

#: The two roles Supabase's Data API connects as.  Migrations revoke from them,
#: so they must exist before the first upgrade or the REVOKE has no target.
DATA_API_ROLES = ("anon", "authenticated", "service_role")


def _dsn() -> str:
    dsn = os.environ.get("AETRIX_TEST_DATABASE_URL") or os.environ.get(
        "AETRIX_DATABASE__URL", ""
    )
    if not dsn:
        raise SystemExit(
            "set AETRIX_TEST_DATABASE_URL to a disposable loopback database, e.g. "
            "postgresql+psycopg://postgres@127.0.0.1:5432/aetrix_test"
        )
    host = (make_url(dsn).host or "").strip().lower()
    if host not in {"", "localhost", "::1"} and not host.startswith("127."):
        raise SystemExit(
            f"refusing a non-loopback database ({host}): this script drops the public "
            "schema before migrating"
        )
    os.environ["AETRIX_DATABASE__URL"] = dsn
    return dsn


def _config(dsn: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", dsn.replace("%", "%%"))
    return config


def _ensure_data_api_roles(dsn: str) -> list[str]:
    """Create the Data API roles this database is missing, and report which."""

    created: list[str] = []
    engine = create_engine(dsn)
    try:
        with engine.begin() as connection:
            for role in DATA_API_ROLES:
                exists = connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": role}
                )
                if exists:
                    continue
                connection.execute(
                    text(
                        f"CREATE ROLE {role} NOLOGIN"
                        + (" BYPASSRLS" if role == "service_role" else "")
                    )
                )
                created.append(role)
    finally:
        engine.dispose()
    return created


def _reset(dsn: str) -> None:
    """Drop everything, so the upgrade starts where a new deployment starts."""

    engine = create_engine(dsn)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def _revision(dsn: str) -> str | None:
    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            if not connection.scalar(text("SELECT to_regclass('public.alembic_version')")):
                return None
            return connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()


def _public_tables(dsn: str) -> list[str]:
    """Application tables left in public; alembic's own bookkeeping is not one."""

    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            return sorted(
                connection.scalars(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                    )
                )
            )
    finally:
        engine.dispose()


def main() -> int:
    dsn = _dsn()
    config = _config(dsn)
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise SystemExit("the migration directory has no head revision")

    report: dict[str, object] = {
        "database": make_url(dsn).render_as_string(hide_password=True),
        "head": head,
    }
    steps: list[tuple[str, str]] = []

    def step(name: str, work) -> bool:
        try:
            work()
        except Exception as error:
            # The log keeps the traceback; the report keeps the one line an
            # operator needs to know which command to look at.
            traceback.print_exc()
            report["failed_step"] = name
            report["error"] = f"{type(error).__name__}: {error}"
            steps.append((name, "FAILED"))
            return False
        steps.append((name, "ok"))
        return True

    def create_roles() -> None:
        report["roles_created"] = _ensure_data_api_roles(dsn)

    def empty_schema() -> None:
        _reset(dsn)
        report["revision_at_start"] = _revision(dsn)

    def upgrade_head() -> None:
        command.upgrade(config, "head")
        report["revision_after_upgrade"] = _revision(dsn)

    def downgrade_base() -> None:
        command.downgrade(config, "base")
        report["revision_after_downgrade"] = _revision(dsn)
        report["tables_after_downgrade"] = _public_tables(dsn)

    def upgrade_head_again() -> None:
        command.upgrade(config, "head")
        report["revision_after_reupgrade"] = _revision(dsn)

    plan = [
        ("create the missing Data API roles", create_roles),
        ("empty the public schema", empty_schema),
        ("upgrade head", upgrade_head),
        ("downgrade base", downgrade_base),
        ("upgrade head again", upgrade_head_again),
    ]
    for name, work in plan:
        if not step(name, work):
            break

    # A claim is only made about a step that actually ran: a run that stopped at
    # the first connection failure must not also report the downgrade as wrong.
    settled = dict(steps)
    claims = {
        "started_empty": ("empty the public schema", report.get("revision_at_start") is None),
        "upgraded_to_head": (
            "upgrade head",
            report.get("revision_after_upgrade") == head,
        ),
        "downgraded_to_nothing": (
            "downgrade base",
            report.get("revision_after_downgrade") is None,
        ),
        "downgrade_left_no_tables": (
            "downgrade base",
            report.get("tables_after_downgrade") == [],
        ),
        "reupgraded_to_head": (
            "upgrade head again",
            report.get("revision_after_reupgrade") == head,
        ),
    }
    checks = {
        name: passed
        for name, (required_step, passed) in claims.items()
        if settled.get(required_step) == "ok"
    }
    report["steps"] = settled
    report["checks"] = checks
    report["failed"] = sorted(name for name, passed in checks.items() if not passed)
    ok = "failed_step" not in report and not report["failed"] and len(checks) == len(claims)
    report["result"] = "PASS" if ok else "FAIL"
    print(json.dumps(report, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
