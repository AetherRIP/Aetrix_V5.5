"""Rehearse and verify migration ``0039_credential_pools``.

Three jobs, one script, because they must agree about what 0039 is:

``--rehearse`` (loopback only)
    Start a disposable database at ``0038_reservation_unconfirmed``, seed
    representative credential and ledger rows, then walk
    ``upgrade 0039`` -> assertions -> ``downgrade 0038`` -> assertions ->
    ``upgrade 0039`` -> assertions.  Nothing here touches a real deployment.

``--capture PATH`` (read-only)
    Record what the database currently holds: its revision, the 22 pre-0039
    ``provider_credentials`` columns, row counts, and a content digest of
    ``provider_usage``, ``provider_quota_reservations`` and those 22 columns.
    Run it against production *before* migrating, so the same digests can be
    compared afterwards.

``--verify PATH`` (read-only)
    Check that the revision is 0039, that the nine columns, four constraints and
    two indexes exist, that every credential has a unique
    ``gemini-key-<uuid>`` pool, that the identity default and reason were
    backfilled, and that the captured digests still match.  It never writes.

Digests are order-independent: each row is canonicalised, its own digest is
taken, and the sorted row digests are hashed together.  A row that changed — or
one that appeared or vanished — changes the result, while a different physical
row order does not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, make_url, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

REVISION = "0039_credential_pools"
PREVIOUS = "0038_reservation_unconfirmed"

#: The nine columns 0039 adds, exactly as the revision creates them.
ADDED_COLUMNS = (
    "project_identity",
    "project_identity_reason",
    "project_identity_declared_at",
    "project_identity_declared_by",
    "pool_id",
    "cooldown_kind",
    "consecutive_failures",
    "last_quota_exhausted_at",
    "last_quota_reason",
)

#: The four CHECK/UNIQUE constraints it adds.
ADDED_CONSTRAINTS = (
    "ck_provider_credentials_project_identity",
    "uq_provider_credential_pool_id",
    "ck_provider_credentials_pool_id",
    "ck_provider_credentials_cooldown_kind",
)

#: The two indexes it adds.
ADDED_INDEXES = (
    "ix_provider_credential_project_identity",
    "ix_provider_credential_cooldown",
)

#: The 22 columns that existed at 0038.  The digest of these is the
#: pre-migration baseline that must survive 0039 unchanged.
LEGACY_COLUMNS = (
    "tenant_id",
    "account_label",
    "key_fingerprint",
    "encrypted_secret",
    "model_access",
    "budget",
    "health",
    "cooldown_until",
    "last_success_at",
    "last_error",
    "id",
    "created_at",
    "updated_at",
    "project_id",
    "auth_type",
    "tier",
    "last_failure_at",
    "last_failure_status",
    "last_validated_at",
    "contributor_id",
    "revoked_at",
    "revoked_reason",
)

HASHED_TABLES = ("provider_usage", "provider_quota_reservations")

DEFAULT_IDENTITY = "PROJECT_IDENTITY_UNVERIFIED"


# ── connection helpers ───────────────────────────────────────────────────────


def _dsn(explicit: str | None) -> str:
    dsn = explicit or os.environ.get("AETRIX_TEST_DATABASE_URL") or os.environ.get(
        "AETRIX_DATABASE__URL", ""
    )
    if not dsn:
        # Capture and verify are read-only and default to the database the
        # application is configured against (``backend/.env``), which is what a
        # pre/post-migration comparison has to look at.
        from app.core.config import get_settings

        dsn = get_settings().database.dsn()
    if not dsn:
        raise SystemExit(
            "set AETRIX_TEST_DATABASE_URL (preferred) or AETRIX_DATABASE__URL, or pass --dsn"
        )
    # ``migrations/env.py`` takes its URL from the typed settings, not from the
    # Alembic config option, so the target has to be written where it reads it.
    # Without this the migration would be applied to whatever ``backend/.env``
    # names — which is a real deployment — while the assertions inspected the
    # disposable database.  Setting the variable and clearing the cached
    # settings makes both halves of this script address one database.
    os.environ["AETRIX_DATABASE__URL"] = dsn
    os.environ.pop("AETRIX_TEST_DATABASE_URL", None)
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    resolved = get_settings_dsn()
    if resolved != dsn:
        raise SystemExit(
            "refusing to continue: the application settings resolve to a different "
            f"database than --dsn ({make_url(resolved).host} vs {make_url(dsn).host})"
        )
    return dsn


def get_settings_dsn() -> str:
    """The DSN the application (and therefore Alembic) will actually use."""

    from app.core.config import get_settings

    return get_settings().database.dsn()


def _is_loopback(dsn: str) -> bool:
    try:
        host = (make_url(dsn).host or "").strip().lower()
    except Exception:
        return False
    return host in {"", "localhost", "::1"} or host.startswith("127.")


def _config(dsn: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", dsn.replace("%", "%%"))
    return config


def _revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        found = connection.execute(
            text("select to_regclass('public.alembic_version')")
        ).scalar()
        if found is None:
            return None
        return connection.execute(text("select version_num from alembic_version")).scalar()


# ── canonical hashing ────────────────────────────────────────────────────────


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # ``float.hex`` is the exact value.  Two PostgreSQL builds may print the
        # same double differently (shortest-round-trip spelling changed between
        # minor versions), so a text form is not a safe digest input.
        return value.hex()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        # The same instant renders with whichever offset the session's timezone
        # reports.  Normalising to UTC makes a digest comparable between the
        # production session and a restored local copy.
        return (value.astimezone(UTC) if value.tzinfo is not None else value).isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_canonical(item) for item in value]
    return str(value)


def _float_expression(column: dict[str, Any]) -> str | None:
    """The exact-bytes expression for a floating-point column, or ``None``.

    A float read in text mode is decoded by the driver from whatever spelling
    the server used.  A session with reduced ``extra_float_digits`` prints 15
    significant digits, and parsing that back can land one ULP away from the
    stored value.  ``float8send`` returns the stored bytes, so a digest built
    from it compares the data rather than two servers' float formatting.
    """

    name = column["name"]
    rendered = str(column["type"]).lower()
    if "double precision" in rendered:
        return f"float8send({name})::text AS {name}"
    if rendered.startswith("real") or "float4" in rendered:
        return f"float4send({name})::text AS {name}"
    return None


def _table_digest(
    engine: Engine, table: str, columns: tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Row count and an order-independent content digest for one table."""

    inspector = inspect(engine)
    described = {column["name"]: column for column in inspector.get_columns(table)}
    present = set(described)
    selected = tuple(columns) if columns is not None else tuple(sorted(present))
    missing = [name for name in selected if name not in present]
    if missing:
        raise SystemExit(f"{table} is missing columns {missing}; wrong revision?")

    projected = [
        _float_expression(described[name]) or name for name in selected
    ]
    statement = f'SELECT {", ".join(projected)} FROM {table}'
    rows: list[str] = []
    with engine.connect() as connection:
        for row in connection.execute(text(statement)):
            payload = json.dumps(
                [_canonical(value) for value in row], sort_keys=True, default=str
            )
            rows.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    rows.sort()
    combined = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    return {"columns": list(selected), "rows": len(rows), "sha256": combined}


# ── schema assertions ────────────────────────────────────────────────────────


def assert_0038(engine: Engine) -> list[str]:
    """The pre-0039 shape: 22 columns, and none of 0039's nine."""

    problems: list[str] = []
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("provider_credentials")}
    stray = sorted(columns & set(ADDED_COLUMNS))
    if stray:
        problems.append(f"0038 still carries 0039 columns: {stray}")
    absent = [name for name in LEGACY_COLUMNS if name not in columns]
    if absent:
        problems.append(f"0038 is missing legacy columns: {absent}")
    checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("provider_credentials")
    }
    unique = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("provider_credentials")
    }
    leftover = sorted((checks | unique) & set(ADDED_CONSTRAINTS))
    if leftover:
        problems.append(f"0038 still carries 0039 constraints: {leftover}")
    indexes = {index["name"] for index in inspector.get_indexes("provider_credentials")}
    leftover_indexes = sorted(indexes & set(ADDED_INDEXES))
    if leftover_indexes:
        problems.append(f"0038 still carries 0039 indexes: {leftover_indexes}")
    return problems


def assert_0039(engine: Engine, *, expect_credentials: bool = True) -> list[str]:
    """Every invariant 0039 promises, checked against the live catalog and rows."""

    problems: list[str] = []
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("provider_credentials")}
    absent = [name for name in ADDED_COLUMNS if name not in columns]
    if absent:
        problems.append(f"missing 0039 columns: {absent}")
        # Later assertions depend on these columns existing.
        return problems

    legacy_absent = [name for name in LEGACY_COLUMNS if name not in columns]
    if legacy_absent:
        problems.append(f"0039 dropped legacy columns: {legacy_absent}")

    checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("provider_credentials")
    }
    unique = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("provider_credentials")
    }
    for name in (
        "ck_provider_credentials_project_identity",
        "ck_provider_credentials_pool_id",
        "ck_provider_credentials_cooldown_kind",
    ):
        if name not in checks:
            problems.append(f"missing check constraint {name}")
    if "uq_provider_credential_pool_id" not in unique:
        problems.append("missing unique constraint uq_provider_credential_pool_id")

    indexes = {index["name"] for index in inspector.get_indexes("provider_credentials")}
    for name in ADDED_INDEXES:
        if name not in indexes:
            problems.append(f"missing index {name}")

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "select id, pool_id, project_identity, project_identity_reason, "
                "consecutive_failures from provider_credentials"
            )
        ).all()

    if expect_credentials and not rows:
        problems.append("no provider credentials are present to verify")

    seen: set[str] = set()
    for identifier, pool_id, identity, reason, failures in rows:
        if pool_id != f"gemini-key-{identifier}":
            problems.append(f"credential {identifier} has pool_id {pool_id!r}")
        if pool_id in seen:
            problems.append(f"duplicate pool_id {pool_id!r}")
        seen.add(pool_id)
        if identity != DEFAULT_IDENTITY:
            problems.append(
                f"credential {identifier} has project_identity {identity!r}, "
                f"expected {DEFAULT_IDENTITY!r} on a fresh upgrade"
            )
        if not reason:
            problems.append(f"credential {identifier} has no project_identity_reason backfill")
        if failures is None or int(failures) != 0:
            problems.append(f"credential {identifier} has consecutive_failures {failures!r}")

    distinct = len({row[0] for row in rows})
    if len(seen) != distinct:
        problems.append("pool_id is not unique across credentials")
    return problems


# ── rehearsal ────────────────────────────────────────────────────────────────


def _seed(engine: Engine) -> dict[str, Any]:
    """Insert credentials and ledger rows that a real deployment would hold.

    Rows go in while the database is at 0038, so the upgrade has to cope with
    data that predates it — the case a blank database never exercises.
    """

    identifiers: list[str] = []
    with engine.begin() as connection:
        tenant_id = connection.execute(
            text(
                "insert into tenants (id, name, slug, is_active, created_at, updated_at) "
                "values (gen_random_uuid(), 'rehearsal', 'rehearsal', true, now(), now()) "
                "returning id"
            )
        ).scalar()
        for index in range(3):
            identifier = connection.execute(
                text(
                    "insert into provider_credentials "
                    "(id, tenant_id, account_label, key_fingerprint, encrypted_secret, "
                    " model_access, budget, health, project_id, created_at, updated_at) "
                    "values (gen_random_uuid(), :tenant, :label, :fingerprint, :secret, "
                    " '[]'::json, '{}'::json, 'HEALTHY', :project, now(), now()) returning id"
                ),
                {
                    "tenant": tenant_id,
                    "label": f"rehearsal-key-{index}",
                    # ``key_fingerprint`` is a 32-character digest in this schema.
                    "fingerprint": hashlib.sha256(str(index).encode()).hexdigest()[:32],
                    "secret": f"ciphertext-{index}",
                    "project": f"rehearsal-project-{index}",
                },
            ).scalar()
            identifiers.append(str(identifier))
        for index in range(2):
            connection.execute(
                text(
                    "insert into provider_usage "
                    "(id, tenant_id, provider, model, purpose, success, reported, "
                    " project_id, credential_id, created_at) "
                    "values (gen_random_uuid(), :tenant, 'gemini', 'gemini-3.6-flash', "
                    "'marking', true, true, :project, :credential, now())"
                ),
                {
                    "tenant": tenant_id,
                    "project": f"rehearsal-project-{index}",
                    "credential": identifiers[index % len(identifiers)],
                },
            )
            connection.execute(
                text(
                    "insert into provider_quota_reservations "
                    "(id, tenant_id, credential_id, purpose, status, expires_at, created_at) "
                    "values (gen_random_uuid(), :tenant, :credential, 'marking', 'CONSUMED', "
                    " now() + interval '1 hour', now())"
                ),
                {
                    "tenant": tenant_id,
                    "credential": identifiers[index % len(identifiers)],
                },
            )
    return {"tenant_id": str(tenant_id), "credential_ids": identifiers}


def rehearse(dsn: str) -> dict[str, Any]:
    if not _is_loopback(dsn):
        raise SystemExit(
            f"refusing to rehearse against a non-loopback database ({make_url(dsn).host}): "
            "this mode seeds rows and runs downgrades"
        )
    if get_settings_dsn() != dsn:
        raise SystemExit("refusing to rehearse: Alembic would target another database")
    engine = create_engine(dsn)
    report: dict[str, Any] = {"steps": {}, "checks": {}, "failed": []}
    config = _config(dsn)
    try:
        # Build 0038 first, so the upgrade starts from the real predecessor.
        command.upgrade(config, PREVIOUS)
        report["steps"]["upgrade to 0038"] = "ok"
        at_0038 = assert_0038(engine)
        report["checks"]["0038 shape"] = not at_0038
        report["failed"].extend(at_0038)

        seeded = _seed(engine)
        baseline = {
            table: _table_digest(engine, table) for table in HASHED_TABLES
        }
        baseline["provider_credentials"] = _table_digest(
            engine, "provider_credentials", LEGACY_COLUMNS
        )
        report["baseline"] = baseline

        command.upgrade(config, REVISION)
        report["steps"]["upgrade to 0039"] = "ok"
        report["revision_after_upgrade"] = _revision(engine)
        upgraded = assert_0039(engine)
        report["checks"]["0039 invariants"] = not upgraded
        report["failed"].extend(upgraded)

        after_upgrade = {
            table: _table_digest(engine, table) for table in HASHED_TABLES
        }
        after_upgrade["provider_credentials"] = _table_digest(
            engine, "provider_credentials", LEGACY_COLUMNS
        )
        drift = {
            name: {"before": baseline[name], "after": after_upgrade[name]}
            for name in baseline
            if baseline[name]["sha256"] != after_upgrade[name]["sha256"]
        }
        report["checks"]["legacy content preserved by upgrade"] = not drift
        if drift:
            report["failed"].append(f"upgrade altered recorded content: {sorted(drift)}")

        command.downgrade(config, PREVIOUS)
        report["steps"]["downgrade to 0038"] = "ok"
        report["revision_after_downgrade"] = _revision(engine)
        downgraded = assert_0038(engine)
        report["checks"]["0038 shape after downgrade"] = not downgraded
        report["failed"].extend(downgraded)
        after_downgrade = {
            table: _table_digest(engine, table) for table in HASHED_TABLES
        }
        after_downgrade["provider_credentials"] = _table_digest(
            engine, "provider_credentials", LEGACY_COLUMNS
        )
        drift = {
            name: {"before": baseline[name], "after": after_downgrade[name]}
            for name in baseline
            if baseline[name]["sha256"] != after_downgrade[name]["sha256"]
        }
        report["checks"]["legacy content preserved by downgrade"] = not drift
        if drift:
            report["failed"].append(f"downgrade altered recorded content: {sorted(drift)}")

        command.upgrade(config, REVISION)
        report["steps"]["re-upgrade to 0039"] = "ok"
        report["revision_after_reupgrade"] = _revision(engine)
        again = assert_0039(engine)
        report["checks"]["0039 invariants after re-upgrade"] = not again
        report["failed"].extend(again)
        report["seeded"] = seeded
    finally:
        engine.dispose()

    report["result"] = "PASS" if not report["failed"] and all(report["checks"].values()) else "FAIL"
    return report


# ── capture / verify ─────────────────────────────────────────────────────────


def capture(dsn: str, path: Path) -> dict[str, Any]:
    engine = create_engine(dsn)
    try:
        revision = _revision(engine)
        inspector = inspect(engine)
        columns = [column["name"] for column in inspector.get_columns("provider_credentials")]
        payload = {
            "revision": revision,
            "provider_credentials_columns": columns,
            "digests": {table: _table_digest(engine, table) for table in HASHED_TABLES},
        }
        payload["digests"]["provider_credentials"] = _table_digest(
            engine, "provider_credentials", LEGACY_COLUMNS
        )
    finally:
        engine.dispose()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def verify(dsn: str, path: Path) -> dict[str, Any]:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    engine = create_engine(dsn)
    report: dict[str, Any] = {"failed": [], "checks": {}, "compared": {}}
    try:
        revision = _revision(engine)
        report["revision"] = revision
        report["checks"]["revision is 0039"] = revision == REVISION
        if revision != REVISION:
            report["failed"].append(f"revision is {revision!r}, expected {REVISION!r}")

        problems = assert_0039(engine)
        report["checks"]["0039 invariants"] = not problems
        report["failed"].extend(problems)

        for table, expected in baseline["digests"].items():
            columns = tuple(expected["columns"])
            current = _table_digest(engine, table, columns)
            same = current["sha256"] == expected["sha256"]
            report["compared"][table] = {
                "expected_rows": expected["rows"],
                "current_rows": current["rows"],
                "match": same,
            }
            if not same:
                report["failed"].append(
                    f"{table} content differs from the pre-migration baseline "
                    f"(expected {expected['sha256'][:16]}, found {current['sha256'][:16]})"
                )
        report["checks"]["baseline digests match"] = all(
            item["match"] for item in report["compared"].values()
        )
    finally:
        engine.dispose()
    report["result"] = "PASS" if not report["failed"] else "FAIL"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN; defaults to the env")
    parser.add_argument(
        "--rehearse", action="store_true", help="loopback upgrade/downgrade rehearsal"
    )
    parser.add_argument(
        "--capture", type=Path, default=None, help="write a read-only baseline"
    )
    parser.add_argument(
        "--verify", type=Path, default=None, help="compare against a baseline"
    )
    arguments = parser.parse_args(argv)

    if not (arguments.rehearse or arguments.capture or arguments.verify):
        parser.error("choose --rehearse, --capture or --verify")

    dsn = _dsn(arguments.dsn)
    output: dict[str, Any] = {}
    try:
        if arguments.rehearse:
            output["rehearsal"] = rehearse(dsn)
        if arguments.capture:
            output["captured"] = capture(dsn, arguments.capture)
        if arguments.verify:
            output["verified"] = verify(dsn, arguments.verify)
    except Exception as error:  # report, never swallow
        output["error"] = f"{type(error).__name__}: {error}"
        output["traceback"] = traceback.format_exc()
        print(json.dumps(output, indent=2, default=str))
        return 1

    print(json.dumps(output, indent=2, default=str))
    if output.get("rehearsal", {}).get("result") == "FAIL":
        return 1
    if output.get("verified", {}).get("result") == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
