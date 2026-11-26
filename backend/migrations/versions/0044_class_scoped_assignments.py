"""Give every new assignment an owning Classroom class.

Revision ID: 0044_class_scoped_assignments
Revises: 0043_classroom_class_assignments

An assignment created through the API names the course it belongs to.  The
allocation is the validated owner of that course, so the foreign key makes a
cross-workspace class reference impossible at the database layer.

Historical rows stay ``NULL``: they were created before the product associated
an assignment with a class, and this migration never guesses one.  Code reads
``NULL`` as "unassigned legacy assignment" and keeps it out of class-scoped
lists rather than attaching it to a class that nobody chose.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_class_scoped_assignments"
down_revision = "0043_classroom_class_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("classroom_allocation_id", sa.Uuid(), nullable=True),
    )
    op.add_column("assignments", sa.Column("course_id", sa.String(200), nullable=True))
    op.add_column("assignments", sa.Column("class_name", sa.String(300), nullable=True))
    op.create_foreign_key(
        op.f("fk_assignments_classroom_allocation_id_classroom_allocations"),
        "assignments",
        "classroom_allocations",
        ["classroom_allocation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_assignments_tenant_course",
        "assignments",
        ["tenant_id", "course_id"],
    )
    op.create_index(
        "ix_assignments_allocation",
        "assignments",
        ["classroom_allocation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assignments_allocation", table_name="assignments")
    op.drop_index("ix_assignments_tenant_course", table_name="assignments")
    op.drop_constraint(
        op.f("fk_assignments_classroom_allocation_id_classroom_allocations"),
        "assignments",
        type_="foreignkey",
    )
    op.drop_column("assignments", "class_name")
    op.drop_column("assignments", "course_id")
    op.drop_column("assignments", "classroom_allocation_id")
