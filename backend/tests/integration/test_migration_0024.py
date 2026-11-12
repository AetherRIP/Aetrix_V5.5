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


def _digest(connection, table: str) -> str:
    return connection.scalar(
        text(f"select md5(coalesce(string_agg(t::text, '|' order by t.id), '')) from {table} t")
    )


def _snapshot(engine) -> tuple[str, str, int, int, str]:
    with engine.connect() as connection:
        return (
            _digest(connection, "question_results"),
            _digest(connection, "verification_results"),
            connection.scalar(text("select count(*) from question_results")),
            connection.scalar(text("select count(*) from verification_results")),
            connection.scalar(text("select version_num from alembic_version")),
        )


def test_0024_round_trip_leaves_history_untouched(db_session, engine, paper, identity) -> None:
    config = _config()
    assert ScriptDirectory.from_config(config).get_heads() == [REV_0024]

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
        assert before[4] == REV_0023
        assert before[2] == 1 and before[3] == 1

        command.upgrade(config, "head")
        after_upgrade = _snapshot(engine)
        assert after_upgrade == (before[0], before[1], 1, 1, REV_0024)

        command.downgrade(config, REV_0023)
        after_downgrade = _snapshot(engine)
        assert after_downgrade == (before[0], before[1], 1, 1, REV_0023)

        command.upgrade(config, "head")
        assert _snapshot(engine)[0:2] == before[0:2]
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
