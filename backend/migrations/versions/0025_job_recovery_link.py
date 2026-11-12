"""0025: link a recovery job to the refused run it re-marks

A refused run is evidence, not a result.  Re-marking it creates a second job
that points back at the refusal, so the original rows, guard decision and
engine attribution are never rewritten.  ``requested_engine_name`` records the
engine the new job was created for, so a worker running a different engine
refuses it instead of silently changing methodology.

Every column is nullable and every existing row keeps NULL: nothing is
backfilled and no historical result is touched.

Revision ID: 0025_job_recovery_link
Revises: 0024_double_check_verification
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_job_recovery_link"
down_revision = "0024_double_check_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "correction_jobs", sa.Column("recovery_of_job_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "correction_jobs",
        sa.Column("requested_engine_name", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "correction_jobs",
        sa.Column("requested_engine_version", sa.String(length=40), nullable=True),
    )
    op.create_foreign_key(
        "fk_correction_jobs_recovery_of",
        "correction_jobs",
        "correction_jobs",
        ["recovery_of_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_jobs_recovery_of", "correction_jobs", ["recovery_of_job_id"])


def downgrade() -> None:
    # The link is provenance, not a mark: dropping it loses no award, approval
    # or evidence row, and the recovery job itself remains a normal job.
    op.drop_index("ix_jobs_recovery_of", table_name="correction_jobs")
    op.drop_constraint(
        "fk_correction_jobs_recovery_of", "correction_jobs", type_="foreignkey"
    )
    op.drop_column("correction_jobs", "requested_engine_version")
    op.drop_column("correction_jobs", "requested_engine_name")
    op.drop_column("correction_jobs", "recovery_of_job_id")
