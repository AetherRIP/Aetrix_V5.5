"""Migration 0024, exercised against a database that already holds history.

The migration only widens two check constraints.  This test proves that on a real
PostgreSQL: a 0023 database with stored results and verification rows upgrades
cleanly, reports a single head, downgrades cleanly, and leaves the stored rows
byte-identical through the whole round trip.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import get_settings
from app.db.models import (
    CorrectionJob,
    QuestionResult,
    VerificationResult,
)
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
REV_0023 = "0023_engine_provenance"
REV_0024 = "0024_double_check_verification"


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", get_settings().database.dsn().replace("%", "%%")
    )
    return config


def _columns(connection, table: str) -> list[str]:
    return list(
        connection.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema = 'public' and table_name = :table "
                "order by ordinal_position"
            ),
            {"table": table},
        ).scalars()
    )


def _baseline_columns(engine) -> dict[str, list[str]]:
    """The columns that exist before the round trip starts."""

    with engine.connect() as connection:
        return {
            table: _columns(connection, table)
            for table in ("question_results", "verification_results")
        }


def _digest(connection, table: str, columns: list[str] | None = None) -> str:
    """A digest of the stored values, over the columns that existed before.

    Comparing ``t::text`` across the round trip would compare two *schemas*: a
    later revision that adds a nullable column changes the text of every row
    without changing a single stored value.  The columns present at the baseline
    are the ones whose values this test is about; a column added later is null by
    ``ALTER TABLE ... ADD COLUMN`` and carries no stored history to preserve.
    """

    names = columns if columns is not None else _columns(connection, table)
    rendered = "concat_ws('|', " + ", ".join(
        f'coalesce(t."{name}"::text, \'<null>\')' for name in names
    ) + ")"
    return connection.scalar(
        text(
            f"select md5(coalesce(string_agg({rendered}, '||' order by t.id), '')) "
            f"from {table} t"
        )
    )


def _snapshot(
    engine, columns: dict[str, list[str]] | None = None
) -> tuple[str, str, int, int, str]:
    baseline = columns or {}
    with engine.connect() as connection:
        return (
            _digest(connection, "question_results", baseline.get("question_results")),
            _digest(connection, "verification_results", baseline.get("verification_results")),
            connection.scalar(text("select count(*) from question_results")),
            connection.scalar(text("select count(*) from verification_results")),
            connection.scalar(text("select version_num from alembic_version")),
        )


def test_0024_round_trip_leaves_history_untouched(db_session, engine, paper, identity) -> None:
    config = _config()
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    # This test exercises the 0024 step of the round trip, not "0024 happens to
    # be the newest revision". A later revision on top of it must not make the
    # history assertion stale.
    assert len(heads) == 1
    reachable = {revision.revision for revision in script.walk_revisions()}
    assert REV_0024 in reachable
    head = heads[0]

    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        idempotency_key="migration-0024",
        request_hash="a" * 64,
        state="COMPLETED",
    )
    db_session.add(job)
    db_session.flush()
    db_session.add(
        QuestionResult(
            tenant_id=identity.tenant_a.id,
            job_id=job.id,
            question_id="1a",
            max_marks=2,
            awarded_marks=2,
            status="AWARDED",
            processing_state="MARKED",
            review_required=False,
            scheme_concerns=[{"code": "REVIEW", "message": "kept as written"}],
            raw_awarded_marks=2,
            normalised_awarded_marks=2,
            raw_response={"awarded_marks": 2},
            raw_response_truncated=False,
            engine_version="1.0.0",
            prompt_version="question_marking:v1",
        )
    )
    db_session.add(
        VerificationResult(
            tenant_id=identity.tenant_a.id,
            job_id=job.id,
            question_id="1a",
            kind="INTEGRITY",
            status="PASS",
            detail={"awarded_marks": 2, "max_marks": 2},
            created_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    db_session.close()

    try:
        command.downgrade(config, REV_0023)
        before = _snapshot(engine)
        baseline = _baseline_columns(engine)
        assert before[4] == REV_0023
        assert before[2] == 1 and before[3] == 1

        command.upgrade(config, "head")
        after_upgrade = _snapshot(engine, baseline)
        assert after_upgrade == (before[0], before[1], 1, 1, head)

        command.downgrade(config, REV_0023)
        after_downgrade = _snapshot(engine, baseline)
        assert after_downgrade == (before[0], before[1], 1, 1, REV_0023)

        command.upgrade(config, "head")
        assert _snapshot(engine, baseline)[0:2] == before[0:2]
    finally:
        command.upgrade(config, "head")


def test_the_head_widened_the_double_check_constraint(db_session, paper, identity) -> None:
    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        idempotency_key="migration-0024-kind",
        request_hash="b" * 64,
        state="COMPLETED",
    )
    db_session.add(job)
    db_session.commit()

    for kind, status in (("DOUBLE_CHECK", "AGREES"), ("DOUBLE_CHECK", "DISAGREES")):
        db_session.add(
            VerificationResult(
                tenant_id=identity.tenant_a.id,
                job_id=job.id,
                question_id=f"q-{status}",
                kind=kind,
                status=status,
                detail={},
            )
        )
    db_session.commit()

    assert (
        db_session.scalar(
            text(
                "select count(*) from verification_results "
                "where job_id = :id and kind = 'DOUBLE_CHECK'"
            ),
            {"id": job.id},
        )
        == 2
    )
