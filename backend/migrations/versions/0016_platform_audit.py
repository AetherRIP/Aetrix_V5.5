"""0016: platform-level audit for account administration.

``audit_events`` is tenant-scoped, and suspending an account or changing a
platform role belongs to no single tenant.  This table records those actions
with the acting subject, the target subject and the decision, and the same
update guard the tenant ledgers carry keeps it append-only.

Revision ID: 0016_platform_audit
Revises: 0015_model_selection
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_platform_audit"
down_revision: str | None = "0015_model_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("actor_platform_role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target_subject", sa.String(200), nullable=False),
        sa.Column("target_email", sa.String(320), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_audit_events")),
    )
    op.create_index(
        "ix_platform_audit_target",
        "platform_audit_events",
        ["target_subject", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_platform_audit_created", "platform_audit_events", ["created_at"], unique=False
    )
    op.create_index(
        "ix_platform_audit_action",
        "platform_audit_events",
        ["action", "created_at"],
        unique=False,
    )
    # The guard function is created by migration 0001; reuse it so the platform
    # ledger is append-only for the same reason the tenant ledgers are.
    op.execute(
        "CREATE TRIGGER platform_audit_events_append_only "
        "BEFORE UPDATE ON platform_audit_events "
        "FOR EACH ROW EXECUTE FUNCTION aetrix_reject_update();"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS platform_audit_events_append_only ON platform_audit_events;"
    )
    op.drop_index("ix_platform_audit_action", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_created", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_target", table_name="platform_audit_events")
    op.drop_table("platform_audit_events")
