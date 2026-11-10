"""0017: Google Classroom course inventory and workspace allocation.

A Classroom course has at most one ACTIVE allocation.  That is enforced here, in
the database, with a partial unique index on ``classroom_class_id`` where the
allocation is active; the API's pre-check is only there to return a useful 409
before touching the index.  Released rows are retained as history and are not
covered by the uniqueness rule, so a class can be allocated again after release.

The inventory is platform-level.  A course becomes known only when an operator
records one read from Google Classroom; no discovery/sync exists yet, so rows
default to ``UNVERIFIED`` and ``synced_at`` is null.

Revision ID: 0017_classroom_allocations
Revises: 0016_platform_audit
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_classroom_allocations"
down_revision: str | None = "0016_platform_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "classroom_classes",
        *_stamps(),
        sa.Column("course_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column(
            "course_state", sa.String(length=20), nullable=False, server_default="ACTIVE"
        ),
        sa.Column(
            "verification",
            sa.String(length=20),
            nullable=False,
            server_default="UNVERIFIED",
        ),
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default="operator_recorded",
        ),
        sa.Column("owner_email", sa.String(length=320), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_subject", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classroom_classes")),
        sa.UniqueConstraint("course_id", name="uq_classroom_classes_course"),
        sa.CheckConstraint(
            "course_state IN ('ACTIVE','ARCHIVED','DELETED')", name="course_state"
        ),
        sa.CheckConstraint(
            "verification IN ('UNVERIFIED','VERIFIED')", name="verification"
        ),
    )

    op.create_table(
        "classroom_allocations",
        *_stamps(),
        sa.Column("classroom_class_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.String(length=200), nullable=False),
        sa.Column("class_name", sa.String(length=300), nullable=False),
        sa.Column("workspace_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "origin", sa.String(length=20), nullable=False, server_default="ALLOCATE"
        ),
        sa.Column("allocated_by_subject", sa.String(length=200), nullable=False),
        sa.Column("allocated_by_label", sa.String(length=320), nullable=True),
        sa.Column(
            "allocated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("released_by_subject", sa.String(length=200), nullable=True),
        sa.Column("released_by_label", sa.String(length=320), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=500), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("previous_allocation_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classroom_allocations")),
        sa.ForeignKeyConstraint(
            ["classroom_class_id"],
            ["classroom_classes.id"],
            name=op.f("fk_classroom_allocations_classroom_class_id_classroom_classes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["tenants.id"],
            name=op.f("fk_classroom_allocations_workspace_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_allocation_id"],
            ["classroom_allocations.id"],
            name=op.f("fk_classroom_allocations_previous_allocation_id_classroom_allocations"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("status IN ('ACTIVE','RELEASED')", name="status"),
        sa.CheckConstraint("origin IN ('ALLOCATE','REASSIGN')", name="origin"),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND released_at IS NULL) OR "
            "(status = 'RELEASED' AND released_at IS NOT NULL)",
            name="released_state",
        ),
    )
    op.create_index(
        "uq_classroom_allocations_active_class",
        "classroom_allocations",
        ["classroom_class_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_classroom_allocations_workspace_status",
        "classroom_allocations",
        ["workspace_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_classroom_allocations_class_allocated",
        "classroom_allocations",
        ["classroom_class_id", "allocated_at"],
        unique=False,
    )

    for table in ("classroom_classes", "classroom_allocations"):
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index(
        "ix_classroom_allocations_class_allocated", table_name="classroom_allocations"
    )
    op.drop_index(
        "ix_classroom_allocations_workspace_status", table_name="classroom_allocations"
    )
    op.drop_index(
        "uq_classroom_allocations_active_class", table_name="classroom_allocations"
    )
    op.drop_table("classroom_allocations")
    op.drop_table("classroom_classes")
