"""0021: keep the reset time Google returns with a quota definition.

Revision ID: 0021_google_quota_reset_time
Revises: 0020_google_cloud_quota
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_google_quota_reset_time"
down_revision: str | None = "0020_google_cloud_quota"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_cloud_quota_snapshots",
        sa.Column("reset_time", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("google_cloud_quota_snapshots", "reset_time")
