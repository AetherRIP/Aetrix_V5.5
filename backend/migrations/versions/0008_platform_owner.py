"""0008: admit PLATFORM_OWNER to the engine's user-role vocabulary.

The engine's ``users.role`` is a workspace role today (OWNER/ADMIN/TEACHER/
REVIEWER/VIEWER). Platform ownership is not a workspace relationship — it is a
platform capability that keeps the workspace capabilities — so it needs its own
value. Reusing ``OWNER`` would have silently widened every workspace owner's
reach, which is the defect this revision exists to avoid.

The revision reads the live definition first and does nothing when the value is
already allowed, so it is safe on a database whose constraint was extended by
hand before this migration existed.

Revision ID: 0008_platform_owner
Revises: 0007_contributors
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_platform_owner"
down_revision = "0007_contributors"
branch_labels = None
depends_on = None

PLATFORM_ROLES = "'OWNER','ADMIN','TEACHER','REVIEWER','VIEWER','PLATFORM_OWNER'"
WORKSPACE_ROLES = "'OWNER','ADMIN','TEACHER','REVIEWER','VIEWER'"


def _current_definition() -> str | None:
    return op.get_bind().execute(
        sa.text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = to_regclass('public.users') AND conname = 'ck_users_role'"
        )
    ).scalar()


def upgrade() -> None:
    current = _current_definition()
    if current is not None and "PLATFORM_OWNER" in current:
        return
    if current is not None:
        op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint("role", "users", f"role IN ({PLATFORM_ROLES})")


def downgrade() -> None:
    # The narrower vocabulary cannot represent a platform owner, so the row is
    # demoted to a workspace owner first; the value would otherwise be invalid.
    op.execute("UPDATE public.users SET role = 'OWNER' WHERE role = 'PLATFORM_OWNER'")
    if _current_definition() is not None:
        op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint("role", "users", f"role IN ({WORKSPACE_ROLES})")
