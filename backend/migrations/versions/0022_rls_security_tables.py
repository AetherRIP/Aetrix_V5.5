"""0022: close the remaining platform tables to the Data API.

Five tables were added after ``0005_rls_lockdown`` and were never added to its
explicit list.  Nothing grants ``anon`` or ``authenticated`` access to them, but
RLS must still be enabled so a future default grant cannot expose platform
quota, provider selection or platform-audit rows.

Revision ID: 0022_rls_security_tables
Revises: 0021_google_quota_reset_time
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_rls_security_tables"
down_revision: str | None = "0021_google_quota_reset_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = (
    "google_cloud_projects",
    "google_cloud_quota_snapshots",
    "google_cloud_sync_runs",
    "platform_audit_events",
    "provider_model_selections",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
