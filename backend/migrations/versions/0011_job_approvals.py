"""0011: record a human approval separately from a finished marking run.

A correction job reaching ``COMPLETED`` means the engine finished.  It does not
mean a teacher accepted the marks, and the gradebook must not blur the two.  This
revision adds one approval row per job, naming the approver and the totals that
were approved, so a result can be reported as provisional or approved without
inferring it from a job state.

Revision ID: 0011_job_approvals
Revises: 0010_invitations
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011_job_approvals"
down_revision: str | None = "0010_invitations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "job_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by_label", sa.String(length=320), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_marks", sa.Integer(), nullable=False),
        sa.Column("total_marks", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_approvals")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_job_approvals_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["correction_jobs.id"],
            name=op.f("fk_job_approvals_job_id_correction_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_job_approvals_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("job_id", name="uq_job_approval_job"),
        sa.CheckConstraint(
            "approved_marks >= 0", name=op.f("ck_job_approvals_approved_marks_non_negative")
        ),
        sa.CheckConstraint(
            "total_marks >= 0", name=op.f("ck_job_approvals_total_marks_non_negative")
        ),
    )
    op.create_index(
        op.f("ix_job_approvals_tenant_id"), "job_approvals", ["tenant_id"]
    )

    op.execute('REVOKE ALL ON TABLE public."job_approvals" FROM anon, authenticated')
    op.execute('ALTER TABLE public."job_approvals" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index(op.f("ix_job_approvals_tenant_id"), table_name="job_approvals")
    op.drop_table("job_approvals")
