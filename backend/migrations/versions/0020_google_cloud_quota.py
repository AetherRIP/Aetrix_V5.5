"""0020: read-only Google Cloud quota and usage observations.

Three tables, all platform-scoped:

* ``google_cloud_projects`` preserves the operator-declared project id and
  records what Resource Manager returned about it.  A failed verification is a
  stored outcome, not a missing row.
* ``google_cloud_quota_snapshots`` holds the current observations from Cloud
  Quotas and Cloud Monitoring.  Rows are replaced per project on a successful
  sync, so a quota Google stops exposing does not linger as a limit.
* ``google_cloud_sync_runs`` records every attempt, including failures and
  partial runs, so the dashboard can show the last success and last failure
  separately.

Revision ID: 0020_google_cloud_quota
Revises: 0019_classroom_oauth
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_google_cloud_quota"
down_revision: str | None = "0019_classroom_oauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:
    return [
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
        "google_cloud_projects",
        sa.Column("project_id", sa.String(length=100), nullable=False),
        sa.Column("project_number", sa.String(length=32), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=40), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(length=30),
            nullable=False,
            server_default="UNVERIFIED",
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "quota_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("enabled_services", sa.JSON(), nullable=True),
        sa.Column("services_checked_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            "verification_status IN "
            "('VERIFIED','NOT_FOUND','PERMISSION_DENIED','ERROR',"
            "'UNVERIFIABLE','UNVERIFIED')",
            name="verification_status",
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "google_cloud_quota_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=100), nullable=False),
        sa.Column("quota_id", sa.String(length=200), nullable=False),
        sa.Column("metric", sa.String(length=300), nullable=False),
        sa.Column("service", sa.String(length=200), nullable=False),
        sa.Column("metric_display_name", sa.String(length=300), nullable=True),
        sa.Column("quota_display_name", sa.String(length=300), nullable=True),
        sa.Column("unit", sa.String(length=80), nullable=True),
        sa.Column("refresh_interval", sa.String(length=80), nullable=True),
        sa.Column("container_type", sa.String(length=40), nullable=True),
        sa.Column("is_precise", sa.Boolean(), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("dimensions_key", sa.String(length=32), nullable=False),
        sa.Column("limit_value", sa.Numeric(precision=30, scale=4), nullable=True),
        sa.Column(
            "limit_source",
            sa.String(length=30),
            nullable=False,
            server_default="UNAVAILABLE",
        ),
        sa.Column("usage_value", sa.Numeric(precision=30, scale=4), nullable=True),
        sa.Column("usage_metric", sa.String(length=300), nullable=True),
        sa.Column(
            "usage_source",
            sa.String(length=30),
            nullable=False,
            server_default="NOT_EXPOSED",
        ),
        sa.Column("usage_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exceeded_value", sa.Numeric(precision=30, scale=4), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "limit_source IN ('CLOUD_QUOTAS','CLOUD_MONITORING','UNAVAILABLE')",
            name="limit_source",
        ),
        sa.CheckConstraint(
            "usage_source IN ('CLOUD_MONITORING','NOT_EXPOSED')",
            name="usage_source",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["google_cloud_projects.project_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "quota_id",
            "dimensions_key",
            name="uq_google_quota_snapshot",
        ),
    )
    op.create_index(
        "ix_google_quota_snapshot_project",
        "google_cloud_quota_snapshots",
        ["project_id"],
    )

    op.create_table(
        "google_cloud_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=100), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "quota_infos", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "snapshots_written",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("api_calls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        *_stamps(),
        sa.CheckConstraint("trigger IN ('MANUAL','SCHEDULED')", name="trigger"),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED','PARTIAL','FAILED')", name="status"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["google_cloud_projects.project_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_google_quota_run_project",
        "google_cloud_sync_runs",
        ["project_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_google_quota_run_project", table_name="google_cloud_sync_runs")
    op.drop_table("google_cloud_sync_runs")
    op.drop_index(
        "ix_google_quota_snapshot_project", table_name="google_cloud_quota_snapshots"
    )
    op.drop_table("google_cloud_quota_snapshots")
    op.drop_table("google_cloud_projects")
