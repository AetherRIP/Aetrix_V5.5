"""Verify migration 0033 upgrade -> downgrade -> upgrade on a disposable database.

Refuses to run against anything but a loopback database, because it migrates,
drops a column and drops an index.

It proves four things the revision claims:

* the column, its foreign key and the partial unique index appear on upgrade;
* the index really refuses a second row for one mark point, while allowing any
  number of unlinked rows (which is what historical rows are);
* the downgrade removes exactly what it added and leaves stored marks alone;
* re-upgrading restores the structure without touching the rows it kept.

Rows are seeded with ``session_replication_role = replica`` so the script needs
no job, submission or scheme graph: it is a migration test, not a marking test.
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
from sqlalchemy.exc import IntegrityError  # noqa: E402

REVISION = "0033_criterion_provenance"
PREVIOUS = "0032_provider_attempt_routing"
INDEX = "uq_criterion_result_once_per_criterion"


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


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return config


def _revision(engine) -> str | None:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def _index_state(engine) -> dict[str, object]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'criterion_results' AND indexname = :name"
            ),
            {"name": INDEX},
        ).first()
    definition = row[0] if row else ""
    return {
        "present": bool(row),
        "unique": "UNIQUE INDEX" in definition.upper(),
        "partial": "criterion_id IS NOT NULL" in definition,
        "definition": definition,
    }


def _evidence_column(engine) -> dict[str, object]:
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("marking_evidence")}
    foreign_keys = [
        item
        for item in inspector.get_foreign_keys("marking_evidence")
        if "criterion_id" in (item.get("constrained_columns") or [])
    ]
    return {
        "present": "criterion_id" in columns,
        "nullable": columns.get("criterion_id", {}).get("nullable"),
        "foreign_key": [item.get("referred_table") for item in foreign_keys],
    }


def _insert(connection, *, question_result_id, criterion_id) -> None:
    connection.execute(
        text(
            "INSERT INTO criterion_results "
            "(id, tenant_id, question_result_id, criterion_id, code, awarded, evidence, created_at)"
            " VALUES (:id, :tenant, :question, :criterion, 'M1', true, '[]', now())"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant": str(uuid.uuid4()),
            "question": str(question_result_id),
            "criterion": str(criterion_id) if criterion_id else None,
        },
    )


def _seed(engine) -> dict[str, object]:
    """Seed the two row shapes the revision distinguishes."""

    shared_criterion = uuid.uuid4()
    duplicate_rejected = False
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        _insert(connection, question_result_id=uuid.uuid4(), criterion_id=None)
        _insert(connection, question_result_id=uuid.uuid4(), criterion_id=None)
        linked_question = uuid.uuid4()
        _insert(connection, question_result_id=linked_question, criterion_id=shared_criterion)
        # The refusal must not roll back the rows that are meant to survive, so
        # it happens inside its own savepoint.
        savepoint = connection.begin_nested()
        try:
            _insert(
                connection,
                question_result_id=linked_question,
                criterion_id=shared_criterion,
            )
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            duplicate_rejected = True
        transaction.commit()
    with engine.connect() as connection:
        total = connection.scalar(text("SELECT count(*) FROM criterion_results"))
    return {
        "rows": int(total or 0),
        "duplicate_rejected": duplicate_rejected,
        "shared_criterion": str(shared_criterion),
    }


def _row_state(engine, shared_criterion: str) -> dict[str, object]:
    with engine.connect() as connection:
        total = connection.scalar(text("SELECT count(*) FROM criterion_results"))
        linked = connection.scalar(
            text("SELECT count(*) FROM criterion_results WHERE criterion_id = :id"),
            {"id": shared_criterion},
        )
        nulls = connection.scalar(
            text("SELECT count(*) FROM criterion_results WHERE criterion_id IS NULL")
        )
        marks = connection.scalar(
            text("SELECT count(*) FROM criterion_results WHERE awarded IS TRUE AND code = 'M1'")
        )
    return {
        "rows": int(total or 0),
        "linked_to_the_mark_point": int(linked or 0),
        "unlinked": int(nulls or 0),
        "awarded_m1_rows": int(marks or 0),
    }


def main() -> int:
    dsn = _dsn()
    engine = create_engine(dsn)
    config = _config()
    report: dict[str, object] = {"database": make_url(dsn).render_as_string(hide_password=True)}
    try:
        command.upgrade(config, "head")
        report["upgraded_revision"] = _revision(engine)
        report["column_after_upgrade"] = _evidence_column(engine)
        report["index_after_upgrade"] = _index_state(engine)
        seeded = _seed(engine)
        report["seeded"] = seeded
        report["rows_after_upgrade"] = _row_state(engine, seeded["shared_criterion"])

        command.downgrade(config, PREVIOUS)
        report["downgraded_revision"] = _revision(engine)
        report["column_after_downgrade"] = _evidence_column(engine)
        report["index_after_downgrade"] = _index_state(engine)
        report["rows_after_downgrade"] = _row_state(engine, seeded["shared_criterion"])

        command.upgrade(config, "head")
        report["reupgraded_revision"] = _revision(engine)
        report["column_after_reupgrade"] = _evidence_column(engine)
        report["index_after_reupgrade"] = _index_state(engine)
        report["rows_after_reupgrade"] = _row_state(engine, seeded["shared_criterion"])
    finally:
        engine.dispose()

    checks = {
        "upgraded": report["upgraded_revision"] == REVISION,
        "column_added": report["column_after_upgrade"]["present"] is True,
        "foreign_key_added": report["column_after_upgrade"]["foreign_key"]
        == ["marking_criteria"],
        "index_added": report["index_after_upgrade"]["present"] is True,
        "index_unique": report["index_after_upgrade"]["unique"] is True,
        "index_partial": report["index_after_upgrade"]["partial"] is True,
        "duplicate_refused": report["seeded"]["duplicate_rejected"] is True,
        "unlinked_rows_allowed": report["rows_after_upgrade"]["unlinked"] == 2,
        "downgraded": report["downgraded_revision"] == PREVIOUS,
        "column_dropped": report["column_after_downgrade"]["present"] is False,
        "index_dropped": report["index_after_downgrade"]["present"] is False,
        "rows_survived_downgrade": report["rows_after_downgrade"]["rows"]
        == report["rows_after_upgrade"]["rows"],
        "awards_survived_downgrade": report["rows_after_downgrade"]["awarded_m1_rows"]
        == report["rows_after_upgrade"]["awarded_m1_rows"],
        "reupgraded": report["reupgraded_revision"] == REVISION,
        "column_restored": report["column_after_reupgrade"]["present"] is True,
        "index_restored": report["index_after_reupgrade"]["present"] is True,
        "rows_survived_reupgrade": report["rows_after_reupgrade"]["rows"]
        == report["rows_after_upgrade"]["rows"],
        "links_survived_reupgrade": report["rows_after_reupgrade"][
            "linked_to_the_mark_point"
        ]
        == 1,
    }
    report["checks"] = checks
    report["failed"] = sorted(name for name, passed in checks.items() if not passed)
    report["result"] = "PASS" if not report["failed"] else "FAIL"
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
