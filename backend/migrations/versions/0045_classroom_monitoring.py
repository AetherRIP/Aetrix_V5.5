"""Automatic Google Classroom submission monitoring.

Revision ID: 0045_classroom_monitoring
Revises: 0044_class_scoped_assignments

Five new tables, all additive.  No existing row is rewritten: monitoring keeps
its own configuration, its own submission versions, its own attachment records,
its own inspection cache and its own run history, and writes the shared
``classroom_submission_links`` row only as a summary for the existing review and
publication screens.

The downgrade drops only what this revision created, so an environment that has
not used monitoring returns to exactly the pre-monitoring schema.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_classroom_monitoring"
down_revision = "0044_class_scoped_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classroom_monitor_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "coursework_link_id",
            sa.Uuid(),
            sa.ForeignKey("classroom_coursework_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_queue", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column(
            "relevance_policy",
            sa.String(24),
            nullable=False,
            server_default="STRUCTURAL_ALLOW",
        ),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_status", sa.String(20), nullable=True),
        sa.Column("last_poll_error", sa.String(500), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backoff_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_counts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("monitoring_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enabled_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("enabled_by_subject", sa.String(200), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "coursework_link_id", name="uq_monitor_config_coursework"),
        sa.CheckConstraint(
            "relevance_policy IN ('STRUCTURAL_ALLOW','TEXT_REQUIRED')",
            name="relevance_policy",
        ),
    )
    op.create_index(
        "ix_monitor_config_due",
        "classroom_monitor_configs",
        ["enabled", "paused", "next_poll_at"],
    )
    op.create_index("ix_monitor_config_tenant", "classroom_monitor_configs", ["tenant_id"])

    op.create_table(
        "classroom_submission_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submission_link_id",
            sa.Uuid(),
            sa.ForeignKey("classroom_submission_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("google_update_time", sa.String(100), nullable=True),
        sa.Column("google_state", sa.String(40), nullable=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="DETECTED"),
        sa.Column(
            "correction_state",
            sa.String(20),
            nullable=False,
            server_default="NOT_QUEUED",
        ),
        sa.Column("eligibility", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("relevance", sa.String(24), nullable=False, server_default="UNASSESSED"),
        sa.Column("decision_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("inspection_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "aetrix_submission_id",
            sa.Uuid(),
            sa.ForeignKey("submissions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "correction_job_id",
            sa.Uuid(),
            sa.ForeignKey("correction_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_subject", sa.String(200), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(500), nullable=True),
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
        sa.UniqueConstraint(
            "tenant_id",
            "submission_link_id",
            "version",
            name="uq_submission_version_number",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "submission_link_id",
            "content_hash",
            name="uq_submission_version_content",
        ),
        sa.CheckConstraint(
            "state IN ('DETECTED','DOWNLOADING','INSPECTING','READY','IGNORED',"
            "'NEEDS_TEACHER','SUPERSEDED','FAILED')",
            name="submission_state",
        ),
        sa.CheckConstraint(
            "correction_state IN ('NOT_QUEUED','QUEUED','PROCESSING',"
            "'REVIEW_REQUIRED','COMPLETED','FAILED')",
            name="correction_state",
        ),
        sa.CheckConstraint(
            "eligibility IN ('PENDING','ELIGIBLE','NEEDS_TEACHER','BLOCKED')",
            name="eligibility",
        ),
        sa.CheckConstraint(
            "relevance IN ('UNASSESSED','LIKELY_RELEVANT','POSSIBLY_UNRELATED',"
            "'INSUFFICIENT_EVIDENCE','CANNOT_DETERMINE')",
            name="relevance",
        ),
    )
    op.create_index(
        "ix_submission_version_link",
        "classroom_submission_versions",
        ["submission_link_id", "version"],
    )
    op.create_index(
        "ix_submission_version_state",
        "classroom_submission_versions",
        ["tenant_id", "state"],
    )
    op.create_index(
        "ix_submission_version_job",
        "classroom_submission_versions",
        ["correction_job_id"],
    )

    op.create_table(
        "classroom_submission_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("classroom_submission_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("google_file_id", sa.String(300), nullable=True),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("declared_mime", sa.String(200), nullable=True),
        sa.Column("detected_mime", sa.String(120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.String(500), nullable=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("inspection", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.String(500), nullable=True),
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
        sa.UniqueConstraint("version_id", "position", name="uq_attachment_position"),
        sa.CheckConstraint(
            "kind IN ('DRIVE_FILE','LINK','YOUTUBE_VIDEO','FORM','UNKNOWN')",
            name="attachment_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','DOWNLOADED','CONVERTED','IGNORED',"
            "'UNSUPPORTED','FAILED','REJECTED')",
            name="attachment_status",
        ),
    )
    op.create_index(
        "ix_attachment_version",
        "classroom_submission_attachments",
        ["version_id", "position"],
    )

    op.create_table(
        "classroom_inspection_cache",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("readable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("findings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "content_sha256", name="uq_inspection_sha"),
    )

    op.create_table(
        "classroom_monitor_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "coursework_link_id",
            sa.Uuid(),
            sa.ForeignKey("classroom_coursework_links.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("counts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("trigger IN ('SCHEDULE','MANUAL')", name="trigger"),
        sa.CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED','SKIPPED')",
            name="status",
        ),
    )
    op.create_index(
        "ix_monitor_run_tenant",
        "classroom_monitor_runs",
        ["tenant_id", "started_at"],
    )
    op.create_index(
        "ix_monitor_run_coursework",
        "classroom_monitor_runs",
        ["coursework_link_id", "started_at"],
    )

    # Every new public table follows the existing least-privilege posture: RLS
    # on, no Data API grant.  ``tests/integration/test_rls_guard.py`` enforces
    # this globally, so a table added without it fails the build.
    for table in (
        "classroom_monitor_configs",
        "classroom_submission_versions",
        "classroom_submission_attachments",
        "classroom_inspection_cache",
        "classroom_monitor_runs",
    ):
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_monitor_run_coursework", table_name="classroom_monitor_runs")
    op.drop_index("ix_monitor_run_tenant", table_name="classroom_monitor_runs")
    op.drop_table("classroom_monitor_runs")
    op.drop_table("classroom_inspection_cache")
    op.drop_index("ix_attachment_version", table_name="classroom_submission_attachments")
    op.drop_table("classroom_submission_attachments")
    op.drop_index("ix_submission_version_job", table_name="classroom_submission_versions")
    op.drop_index("ix_submission_version_state", table_name="classroom_submission_versions")
    op.drop_index("ix_submission_version_link", table_name="classroom_submission_versions")
    op.drop_table("classroom_submission_versions")
    op.drop_index("ix_monitor_config_tenant", table_name="classroom_monitor_configs")
    op.drop_index("ix_monitor_config_due", table_name="classroom_monitor_configs")
    op.drop_table("classroom_monitor_configs")
