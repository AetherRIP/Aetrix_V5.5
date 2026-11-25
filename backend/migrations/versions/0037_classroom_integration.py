"""0037: central Google Classroom connection and integration records

The Classroom connection becomes a platform singleton: one central Google account
performs every Classroom operation, and workspaces never authorise a personal
account.  ``classroom_connections`` therefore loses its per-tenant uniqueness,
gains the ``connection_key`` discriminator and the identity Google reports for
the central account, and its tenant column becomes nullable so history rows from
the earlier per-workspace design remain readable.

The earlier workspace grants are not convertible into a central grant: they were
issued to different Google accounts.  Their ciphertext is discarded and they are
marked ``RECONNECT_REQUIRED``, which is the honest state — an administrator
connects the central account once, and those rows stay as history.

Five tables record the integration: roster identity mappings, coursework
publication, submission ingestion, grade publication attempts and synchronization
runs.  Every one carries its workspace so tenant isolation is a query condition,
not a frontend filter.

Revision ID: 0037_classroom_integration
Revises: 0036_verification_completeness
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_classroom_integration"
down_revision = "0036_verification_completeness"
branch_labels = None
depends_on = None

_NEW_TABLES = (
    "classroom_roster_entries",
    "classroom_coursework_links",
    "classroom_submission_links",
    "classroom_grade_publications",
    "classroom_sync_runs",
)


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    # -- connection becomes the platform singleton -------------------------
    op.add_column(
        "classroom_connections", sa.Column("connection_key", sa.String(40))
    )
    op.add_column(
        "classroom_connections",
        sa.Column("connected_account_email", sa.String(320)),
    )
    op.add_column(
        "classroom_connections",
        sa.Column("connected_account_name", sa.String(200)),
    )
    op.add_column(
        "classroom_connections",
        sa.Column("last_refresh_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "classroom_connections",
        sa.Column(
            "requested_scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )
    op.alter_column(
        "classroom_connections", "tenant_id", existing_type=sa.Uuid(), nullable=True
    )
    op.execute(
        "ALTER TABLE public.classroom_connections "
        "DROP CONSTRAINT IF EXISTS uq_classroom_connections_tenant"
    )
    op.execute(
        "ALTER TABLE public.classroom_connections "
        "DROP CONSTRAINT IF EXISTS fk_classroom_connections_tenant_id_tenants"
    )
    op.create_foreign_key(
        "fk_classroom_connections_tenant_id_tenants",
        "classroom_connections",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_classroom_connections_connection_key",
        "classroom_connections",
        ["connection_key"],
    )
    # A workspace grant cannot serve as the central authorisation.  Discarding
    # the ciphertext is what makes RECONNECT_REQUIRED true rather than a label.
    op.execute(
        "UPDATE public.classroom_connections SET "
        "status = 'RECONNECT_REQUIRED', "
        "encrypted_access_token = NULL, "
        "encrypted_refresh_token = NULL, "
        "access_token_expires_at = NULL, "
        "scopes = '[]'::json, "
        "last_error_code = 'CENTRAL_ACCOUNT_REQUIRED', "
        "last_error_message = 'Google Classroom is now connected once by a platform "
        "administrator. This workspace grant was retired and never held the central "
        "authorisation.' "
        "WHERE connection_key IS NULL"
    )

    op.add_column(
        "classroom_classes", sa.Column("teacher_name", sa.String(300))
    )

    # -- roster identity mappings -----------------------------------------
    op.create_table(
        "classroom_roster_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", sa.String(200), nullable=False),
        sa.Column("google_user_id", sa.String(200), nullable=False),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(300)),
        sa.Column("email", sa.String(320)),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("match_source", sa.String(20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id", "course_id", "google_user_id", name="uq_roster_entry_google"
        ),
        sa.UniqueConstraint(
            "tenant_id", "course_id", "student_id", name="uq_roster_entry_student"
        ),
        sa.CheckConstraint("status IN ('ACTIVE','REMOVED')", name="status"),
        sa.CheckConstraint(
            "match_source IN ('EXTERNAL_ID','CREATED','MANUAL')", name="match_source"
        ),
    )
    op.create_index(
        "ix_roster_entry_course_status",
        "classroom_roster_entries",
        ["course_id", "status"],
    )
    op.create_index(
        "ix_roster_entry_student", "classroom_roster_entries", ["student_id"]
    )
    op.create_index(
        "ix_classroom_roster_entries_tenant_id",
        "classroom_roster_entries",
        ["tenant_id"],
    )

    # -- coursework publication -------------------------------------------
    op.create_table(
        "classroom_coursework_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "classroom_class_id",
            sa.Uuid(),
            sa.ForeignKey("classroom_classes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("course_id", sa.String(200), nullable=False),
        sa.Column("coursework_id", sa.String(200)),
        sa.Column("state", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("max_points", sa.Numeric(10, 2)),
        sa.Column(
            "publish_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by_subject", sa.String(200)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("last_error_message", sa.String(500)),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id", "assignment_id", name="uq_coursework_link_assignment"
        ),
        sa.UniqueConstraint(
            "tenant_id", "coursework_id", name="uq_coursework_link_coursework"
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','PUBLISHING','PUBLISHED','FAILED')", name="state"
        ),
    )
    op.create_index(
        "ix_coursework_link_course",
        "classroom_coursework_links",
        ["tenant_id", "course_id"],
    )
    op.create_index(
        "ix_coursework_link_class",
        "classroom_coursework_links",
        ["classroom_class_id"],
    )
    op.create_index(
        "ix_classroom_coursework_links_tenant_id",
        "classroom_coursework_links",
        ["tenant_id"],
    )

    # -- student submissions ----------------------------------------------
    op.create_table(
        "classroom_submission_links",
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
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("submissions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
        ),
        sa.Column("course_id", sa.String(200), nullable=False),
        sa.Column("coursework_id", sa.String(200), nullable=False),
        sa.Column("google_submission_id", sa.String(200), nullable=False),
        sa.Column("google_user_id", sa.String(200), nullable=False),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="DISCOVERED"),
        sa.Column("submission_state", sa.String(40)),
        sa.Column("late", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("ingest_error", sa.String(500)),
        sa.Column(
            "correction_job_id",
            sa.Uuid(),
            sa.ForeignKey("correction_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("approved_total", sa.Numeric(10, 2)),
        sa.Column("approved_max", sa.Numeric(10, 2)),
        sa.Column("approved_by_subject", sa.String(200)),
        sa.Column("approved_by_role", sa.String(20)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id", "google_submission_id", name="uq_submission_link_google"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "coursework_link_id",
            "google_user_id",
            name="uq_submission_link_student",
        ),
        sa.CheckConstraint(
            "state IN ('DISCOVERED','INGESTED','INGEST_FAILED','CORRECTING',"
            "'CORRECTED','WITHDRAWN')",
            name="state",
        ),
    )
    op.create_index(
        "ix_submission_link_coursework",
        "classroom_submission_links",
        ["coursework_link_id", "state"],
    )
    op.create_index(
        "ix_submission_link_submission",
        "classroom_submission_links",
        ["submission_id"],
    )
    op.create_index(
        "ix_classroom_submission_links_tenant_id",
        "classroom_submission_links",
        ["tenant_id"],
    )

    # -- grade publication attempts ---------------------------------------
    op.create_table(
        "classroom_grade_publications",
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
        sa.Column(
            "coursework_link_id",
            sa.Uuid(),
            sa.ForeignKey("classroom_coursework_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("draft_grade", sa.Numeric(10, 2)),
        sa.Column("assigned_grade", sa.Numeric(10, 2)),
        sa.Column("approved_by_subject", sa.String(200), nullable=False),
        sa.Column("approved_by_role", sa.String(20), nullable=False),
        sa.Column("authorized_by_subject", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column("external_grade_before", sa.Numeric(10, 2)),
        sa.Column("response_detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "state IN ('SUCCEEDED','FAILED','UNKNOWN','CONFLICT')", name="state"
        ),
    )
    op.create_index(
        "ix_grade_publication_link_attempt",
        "classroom_grade_publications",
        ["submission_link_id", "created_at"],
    )
    op.create_index(
        "ix_grade_publication_tenant_state",
        "classroom_grade_publications",
        ["tenant_id", "state"],
    )
    op.create_index(
        "ix_classroom_grade_publications_tenant_id",
        "classroom_grade_publications",
        ["tenant_id"],
    )

    # -- synchronization history -------------------------------------------
    op.create_table(
        "classroom_sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("course_id", sa.String(200)),
        sa.Column(
            "coursework_link_id",
            sa.Uuid(),
            sa.ForeignKey("classroom_coursework_links.id", ondelete="SET NULL"),
        ),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('COURSES','ROSTER','SUBMISSIONS')", name="kind"),
        sa.CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED')", name="status"
        ),
    )
    op.create_index(
        "ix_sync_run_tenant_kind",
        "classroom_sync_runs",
        ["tenant_id", "kind", "created_at"],
    )
    op.create_index("ix_sync_run_course", "classroom_sync_runs", ["course_id"])
    op.create_index(
        "ix_classroom_sync_runs_tenant_id", "classroom_sync_runs", ["tenant_id"]
    )

    # Student identities, submissions and grades must never be reachable through
    # the Data API: 0017 and 0019 revoke from ``anon``/``authenticated`` for the
    # same reason, and RLS covers a later default grant.
    for table in _NEW_TABLES:
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
        op.drop_table(table)

    op.drop_column("classroom_classes", "teacher_name")

    # The central connection cannot exist without its discriminator, and a
    # workspace-scoped schema has no place for it.  Removing it is the only
    # honest downgrade; the granted tokens are already unreadable history.
    op.execute(
        "DELETE FROM public.classroom_connections WHERE connection_key IS NOT NULL"
    )
    op.execute(
        "UPDATE public.classroom_connections SET tenant_id = "
        "(SELECT id FROM public.tenants ORDER BY created_at ASC LIMIT 1) "
        "WHERE tenant_id IS NULL"
    )
    # Restoring per-tenant uniqueness needs one row per workspace; a duplicate
    # key error would not say which workspace conflicts, so name it and stop.
    conflicts = op.get_bind().execute(
        sa.text(
            "SELECT tenant_id FROM public.classroom_connections "
            "GROUP BY tenant_id HAVING count(*) > 1 ORDER BY 1"
        )
    )
    duplicates = [str(tenant) for tenant in conflicts.scalars()]
    if duplicates:
        raise RuntimeError(
            "Cannot downgrade 0037: classroom_connections holds more than one row "
            f"for workspace(s) {', '.join(duplicates)}. Keep one row per workspace "
            "before downgrading."
        )
    op.drop_constraint(
        "uq_classroom_connections_connection_key",
        "classroom_connections",
        type_="unique",
    )
    op.drop_constraint(
        "fk_classroom_connections_tenant_id_tenants",
        "classroom_connections",
        type_="foreignkey",
    )
    op.alter_column(
        "classroom_connections", "tenant_id", existing_type=sa.Uuid(), nullable=False
    )
    op.create_foreign_key(
        "fk_classroom_connections_tenant_id_tenants",
        "classroom_connections",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_classroom_connections_tenant", "classroom_connections", ["tenant_id"]
    )
    op.drop_column("classroom_connections", "requested_scopes")
    op.drop_column("classroom_connections", "last_refresh_at")
    op.drop_column("classroom_connections", "connected_account_name")
    op.drop_column("classroom_connections", "connected_account_email")
    op.drop_column("classroom_connections", "connection_key")
