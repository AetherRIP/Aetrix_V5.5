"""Archive state for workspace channels.

Revision ID: 0042_channel_archive
Revises: 0041_messaging_grants
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_channel_archive"
down_revision = "0041_messaging_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("archived_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_conversation_tenant_archived",
        "conversations",
        ["tenant_id", "archived_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_tenant_archived", table_name="conversations")
    op.drop_column("conversations", "archived_at")