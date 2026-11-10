"""0019: Google Classroom OAuth connections.

One workspace owns at most one Classroom authorisation.  Both tokens are stored
only as Fernet ciphertext and are discarded the moment Google revokes or
rejects the grant, so ``RECONNECT_REQUIRED`` is a real state rather than a
label.  No row can hold a usable token while claiming to be disconnected.

Revision ID: 0019_classroom_oauth
Revises: 0018_provider_usage_diagnostics
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_classroom_oauth"
down_revision: str | None = "0018_provider_usage_diagnostics"
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
        "classroom_connections",
        *_stamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="RECONNECT_REQUIRED",
        ),
        sa.Column("connected_by_subject", sa.String(length=200), nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=30), nullable=True),
        sa.Column(
            "last_sync_counts", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classroom_connections")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_classroom_connections_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", name="uq_classroom_connections_tenant"),
        sa.CheckConstraint(
            "status IN ('CONNECTED','RECONNECT_REQUIRED')", name="status"
        ),
        sa.CheckConstraint(
            "last_sync_status IS NULL OR last_sync_status IN ('SUCCEEDED','FAILED')",
            name="last_sync_status",
        ),
    )
    op.create_index(
        "ix_classroom_connections_tenant_id",
        "classroom_connections",
        ["tenant_id"],
        unique=False,
    )

    op.execute(
        'REVOKE ALL ON TABLE public."classroom_connections" FROM anon, authenticated'
    )
    op.execute('ALTER TABLE public."classroom_connections" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index(
        "ix_classroom_connections_tenant_id", table_name="classroom_connections"
    )
    op.drop_table("classroom_connections")
