"""0015: persist which model fills each correction role.

The environment stays the fallback, so an existing deployment keeps working
until an operator saves a selection.  A row exists only after discovery
confirmed the model was listed for a registered project.

Revision ID: 0015_model_selection
Revises: 0014_validation_health
Create Date: 2026-11-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0015_model_selection"
down_revision: str | None = "0014_validation_health"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "provider_model_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=True),
        sa.CheckConstraint(
            "role IN ('primary','review','lightweight')", name="role"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role", name="uq_provider_model_selection_role"),
    )


def downgrade() -> None:
    op.drop_table("provider_model_selections")
