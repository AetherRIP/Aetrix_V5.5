"""Platform configuration and retention records.

Revision ID: 0046_platform_settings
Revises: 0045_classroom_monitoring

One new singleton table (``platform_settings``), two nullable columns that record
what the retention sweep removed (``documents.storage_purged_at`` and
``document_pages.storage_purged_at``), and one nullable column that records which
registered template created a workspace (``tenants.workspace_template``).

All four changes are additive.  No existing row is rewritten, so no workspace is
retroactively changed by the new default and no already-ingested document is
claimed to have been purged.

The default row is explicit: ``standard`` template, 365-day script retention and
platform-owner-only audit access.  The last value preserves the behaviour the
engine had before this revision, when ``platform_audit`` was hard-wired to the
platform owner.

Downgrade drops only what this revision created; the table and its row return to
the pre-configuration schema without touching workspace or document data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_platform_settings"
down_revision = "0045_classroom_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("default_workspace_template", sa.String(40), nullable=False),
        sa.Column("uploaded_script_retention_days", sa.Integer(), nullable=False),
        sa.Column("audit_view_allowed_account_types", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_by_label", sa.String(320), nullable=True),
        sa.Column("updated_by_subject", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_platform_settings_singleton"),
        sa.CheckConstraint(
            "uploaded_script_retention_days BETWEEN 1 AND 3650",
            name="ck_platform_settings_retention_days_range",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_platform_settings_version_positive"
        ),
    )
    op.execute(
        """
        INSERT INTO platform_settings (
            id, default_workspace_template, uploaded_script_retention_days,
            audit_view_allowed_account_types, version
        ) VALUES (1, 'standard', 365, '["owner"]'::json, 1)
        """
    )

    op.add_column(
        "tenants", sa.Column("workspace_template", sa.String(40), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("storage_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_pages",
        sa.Column("storage_purged_at", sa.DateTime(timezone=True), nullable=True),
    )

    # The same least-privilege posture every other table follows: RLS on, no
    # Data API grant.  ``tests/integration/test_rls_guard.py`` enforces it.
    op.execute(
        'REVOKE ALL ON TABLE public."platform_settings" FROM anon, authenticated'
    )
    op.execute('ALTER TABLE public."platform_settings" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_column("document_pages", "storage_purged_at")
    op.drop_column("documents", "storage_purged_at")
    op.drop_column("tenants", "workspace_template")
    op.drop_table("platform_settings")
