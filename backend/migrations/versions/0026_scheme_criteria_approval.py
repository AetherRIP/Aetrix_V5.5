"""0026: reviewable, approved mark-scheme criteria

The marking prompt can only be given the mark scheme if the scheme is stored as
rows, not only as a PDF.  This revision adds the review and approval trail that
lets an operator confirm those rows against the blueprint before marking uses
them, and records which blueprint version the criteria were approved against.

Every column is nullable and every existing row keeps NULL: nothing is
backfilled, no criterion is approved by this migration, and no historical mark
or scheme text is rewritten.

This file was lost from the working tree while its revision stayed applied in the
live database (which is stamped at ``0027_transcription_checks``, a child of this
revision).  It is restored from the surviving bytecode and the live catalogue so
the two branches share an ancestor again; the resulting schema is verified
column-for-column against the database it has to line up with.

Revision ID: 0026_scheme_criteria_approval
Revises: 0025_job_recovery_link
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_scheme_criteria_approval"
down_revision = "0025_job_recovery_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- the scheme version records what was approved, by whom, and against
    #    which blueprint.  SET NULL on deletion: losing the approver or the
    #    blueprint must not delete the scheme itself.
    op.add_column(
        "mark_scheme_versions",
        sa.Column("criteria_blueprint_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "mark_scheme_versions",
        sa.Column("criteria_blueprint_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "mark_scheme_versions",
        sa.Column("criteria_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mark_scheme_versions",
        sa.Column("criteria_approved_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "mark_scheme_versions",
        sa.Column("criteria_approval_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_scheme_versions_criteria_blueprint",
        "mark_scheme_versions",
        "exam_blueprint_versions",
        ["criteria_blueprint_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_scheme_versions_criteria_approver",
        "mark_scheme_versions",
        "users",
        ["criteria_approved_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # -- the criteria rows carry the printed question, the expected answer and
    #    the page they were read from, so a reviewer can check them without
    #    reopening the PDF.  CASCADE here: a criterion belongs to its blueprint.
    op.add_column(
        "marking_criteria",
        sa.Column("blueprint_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column("marking_criteria", sa.Column("question_text", sa.Text(), nullable=True))
    op.add_column("marking_criteria", sa.Column("expected_answer", sa.Text(), nullable=True))
    op.add_column("marking_criteria", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("marking_criteria", sa.Column("source_quote", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_marking_criteria_blueprint",
        "marking_criteria",
        "exam_blueprint_versions",
        ["blueprint_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_marking_criteria_blueprint", "marking_criteria", ["blueprint_version_id"]
    )


def downgrade() -> None:
    # The approval trail and the transcribed criterion text are the only things
    # dropped.  Awards, results, approvals of *results* and every scheme row that
    # predates this revision are untouched, but the approval trail and the
    # per-criterion source text cannot be reconstructed once dropped: a downgrade
    # is therefore a deliberate, irreversible loss of that review evidence.
    op.drop_index("ix_marking_criteria_blueprint", table_name="marking_criteria")
    op.drop_constraint(
        "fk_marking_criteria_blueprint", "marking_criteria", type_="foreignkey"
    )
    op.drop_column("marking_criteria", "source_quote")
    op.drop_column("marking_criteria", "source_page")
    op.drop_column("marking_criteria", "expected_answer")
    op.drop_column("marking_criteria", "question_text")
    op.drop_column("marking_criteria", "blueprint_version_id")

    op.drop_constraint(
        "fk_scheme_versions_criteria_approver", "mark_scheme_versions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_scheme_versions_criteria_blueprint", "mark_scheme_versions", type_="foreignkey"
    )
    op.drop_column("mark_scheme_versions", "criteria_approval_reason")
    op.drop_column("mark_scheme_versions", "criteria_approved_by")
    op.drop_column("mark_scheme_versions", "criteria_approved_at")
    op.drop_column("mark_scheme_versions", "criteria_blueprint_hash")
    op.drop_column("mark_scheme_versions", "criteria_blueprint_version_id")
