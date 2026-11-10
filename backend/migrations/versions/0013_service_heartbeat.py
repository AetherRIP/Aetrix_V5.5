"""0013: one heartbeat row per observable long-lived process.

The API cannot see the worker's process table, so "is the worker running?" was
unanswerable and the frontend guessed an answer.  The worker now renews a row
here and ``GET /status`` reports liveness from it.  A missing row means unknown,
never online.

The table holds no tenant data and no secret: a process name, the time it was
last seen, and benign detail such as its PID.

Revision ID: 0013_service_heartbeat
Revises: 0012_classes_students
Create Date: 2026-11-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013_service_heartbeat"
down_revision: str | None = "0012_classes_students"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "service_heartbeats",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_service_heartbeats")),
    )
    # Same lock as every other table: the browser-facing Supabase roles get no
    # grant.  Only the engine's own connection reads this table.
    op.execute('REVOKE ALL ON TABLE public."service_heartbeats" FROM anon, authenticated')
    op.execute('ALTER TABLE public."service_heartbeats" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("service_heartbeats")
