"""0012: workspace classes and their student roster.

The roster is workspace-owned data, not a projection of Google Classroom (that
integration is still absent).  Both tables are tenant-scoped; a student keeps
their record when a class is deleted, and their class reference becomes null
rather than disappearing with it.

Revision ID: 0012_classes_students
Revises: 0011_job_approvals
Create Date: 2026-11-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012_classes_students"
down_revision: str | None = "0011_job_approvals"
branch_labels: str | None = None
depends_on: str | None = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
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
    ]


def upgrade() -> None:
    op.create_table(
        "classes",
        *_stamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("year_group", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classes")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_classes_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_classes_tenant_name"),
    )
    op.create_index(op.f("ix_classes_tenant_id"), "classes", ["tenant_id"])

    op.create_table(
        "students",
        *_stamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=True),
        sa.Column("student_ref", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_students")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_students_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_students_class_id_classes"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("tenant_id", "student_ref", name="uq_students_tenant_ref"),
    )
    op.create_index(op.f("ix_students_tenant_id"), "students", ["tenant_id"])
    op.create_index("ix_students_tenant_class", "students", ["tenant_id", "class_id"])

    for table in ("classes", "students"):
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_students_tenant_class", table_name="students")
    op.drop_index(op.f("ix_students_tenant_id"), table_name="students")
    op.drop_table("students")
    op.drop_index(op.f("ix_classes_tenant_id"), table_name="classes")
    op.drop_table("classes")
