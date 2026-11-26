"""Explicit user-to-Classroom-class assignments.

Revision ID: 0043_classroom_class_assignments
Revises: 0042_channel_archive

Workspace membership and class access are separate facts.  A TEACHER or
REVIEWER is assigned to one ACTIVE allocation at a time; OWNER, ADMIN and
PLATFORM_OWNER continue to manage every class in their workspace.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_classroom_class_assignments"
down_revision = "0042_channel_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classroom_class_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("allocation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"],
            ["classroom_allocations.id"],
            name=op.f(
                "fk_classroom_class_assignments_allocation_id_classroom_allocations"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["tenants.id"],
            name=op.f("fk_classroom_class_assignments_workspace_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_classroom_class_assignments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["users.id"],
            name=op.f("fk_classroom_class_assignments_assigned_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_classroom_class_assignments")
        ),
        sa.UniqueConstraint(
            "allocation_id",
            "user_id",
            name="uq_classroom_assignment_allocation_user",
        ),
    )
    op.create_index(
        "ix_classroom_assignment_workspace_user",
        "classroom_class_assignments",
        ["workspace_id", "user_id"],
    )
    op.create_index(
        "ix_classroom_assignment_allocation",
        "classroom_class_assignments",
        ["allocation_id"],
    )
    op.execute(
        'REVOKE ALL ON TABLE public."classroom_class_assignments" '
        "FROM anon, authenticated"
    )
    op.execute(
        'ALTER TABLE public."classroom_class_assignments" ENABLE ROW LEVEL SECURITY'
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classroom_assignment_allocation",
        table_name="classroom_class_assignments",
    )
    op.drop_index(
        "ix_classroom_assignment_workspace_user",
        table_name="classroom_class_assignments",
    )
    op.drop_table("classroom_class_assignments")