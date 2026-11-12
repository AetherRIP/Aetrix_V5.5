"""0023: engine provenance, explicit processing state and retained evidence.

Additive and nullable: nothing is dropped, no historical mark is rewritten.  A
row written before this revision keeps its ``status``; the backfill states, in
new columns, what that status meant so the review screen does not have to
guess.

``raw_awarded_marks`` and ``normalised_awarded_marks`` are backfilled to the
stored award with ``normalisation_anomaly = 'LEGACY_BACKFILL'`` because the
original model value was not retained by the old engine.  Recording that gap
is honest; inventing a raw value would not be.

Revision ID: 0023_engine_provenance
Revises: 0022_rls_security_tables
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.correction.processing import backfill_state_case_sql

revision: str = "0023_engine_provenance"
down_revision: str | None = "0022_rls_security_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QUESTION_COLUMNS = (
    sa.Column("processing_state", sa.String(20), nullable=True),
    sa.Column("raw_awarded_marks", sa.Integer(), nullable=True),
    sa.Column("normalised_awarded_marks", sa.Integer(), nullable=True),
    sa.Column("normalisation_anomaly", sa.String(40), nullable=True),
    sa.Column("normalisation_detail", sa.JSON(), nullable=True),
    sa.Column("raw_response", sa.JSON(), nullable=True),
    sa.Column("raw_response_truncated", sa.Boolean(), nullable=False, server_default="false"),
    sa.Column("engine_version", sa.String(40), nullable=True),
    sa.Column("prompt_version", sa.String(80), nullable=True),
)

_JOB_COLUMNS = (
    sa.Column("engine_name", sa.String(40), nullable=True),
    sa.Column("engine_version", sa.String(40), nullable=True),
    sa.Column("primary_model", sa.String(120), nullable=True),
    sa.Column("secondary_model", sa.String(120), nullable=True),
    sa.Column("result_source", sa.String(40), nullable=True),
    sa.Column("submission_hash", sa.String(64), nullable=True),
    sa.Column("scheme_hash", sa.String(64), nullable=True),
    sa.Column("double_check_status", sa.String(40), nullable=True),
    sa.Column("disagreement_status", sa.String(40), nullable=True),
    sa.Column("recovery_rounds", sa.Integer(), nullable=False, server_default="0"),
)


def upgrade() -> None:
    for column in _QUESTION_COLUMNS:
        op.add_column("question_results", column)
    op.create_check_constraint(
        "processing_state",
        "question_results",
        "processing_state IS NULL OR processing_state IN "
        "('MARKED','CONFIRMED_ZERO','UNMARKED','NEEDS_REVIEW')",
    )

    for column in _JOB_COLUMNS:
        op.add_column("correction_jobs", column)

    op.create_table(
        "engine_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("engine_name", sa.String(40), nullable=False),
        sa.Column("engine_version", sa.String(40), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=True),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["correction_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_engine_runs_job", "engine_runs", ["job_id"])

    op.create_table(
        "grade_boundaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("qualification", sa.String(120), nullable=False),
        sa.Column("session", sa.String(80), nullable=False),
        sa.Column("specification", sa.String(80), nullable=False),
        sa.Column("grade", sa.String(8), nullable=False),
        sa.Column("min_percent", sa.Float(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="operator"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "min_percent >= 0 AND min_percent <= 100", name="min_percent_range"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "qualification", "session", "specification", "grade", name="uq_grade_boundary"
        ),
    )

    # -- backfill, stated plainly -------------------------------------------
    op.execute(
        """
        UPDATE question_results
        SET raw_awarded_marks = awarded_marks,
            normalised_awarded_marks = awarded_marks,
            normalisation_anomaly = 'LEGACY_BACKFILL'
        WHERE raw_awarded_marks IS NULL
        """
    )
    op.execute(
        f"""
        UPDATE question_results
        SET processing_state = {backfill_state_case_sql()}
        WHERE processing_state IS NULL
        """
    )

    # New platform tables follow the existing least-privilege posture: RLS on,
    # no Data API grant.
    for table in ("engine_runs", "grade_boundaries"):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')


def downgrade() -> None:
    op.drop_table("grade_boundaries")
    op.drop_index("ix_engine_runs_job", table_name="engine_runs")
    op.drop_table("engine_runs")
    for column in reversed(_JOB_COLUMNS):
        op.drop_column("correction_jobs", column.name)
    op.drop_constraint("processing_state", "question_results", type_="check")
    for column in reversed(_QUESTION_COLUMNS):
        op.drop_column("question_results", column.name)
