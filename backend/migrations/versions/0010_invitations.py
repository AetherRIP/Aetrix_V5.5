"""0010: invitation-only workspace membership.

Before this revision the engine could only be joined by a database seed or the
operator CLI: a person could sign in successfully through Supabase and still be
refused every tenant-scoped read, because no ``users`` row existed and no HTTP
path created one.  This revision makes membership an explicit, auditable grant.

Design notes
------------
* An invitation names the tenant and the workspace role.  Provisioning resolves
  the tenant from the invitation, never from the request body or from
  ``user_metadata``.
* ``email`` is stored lower-cased so the verified-email match is exact without
  relying on a database collation.
* ``token_hash`` is the SHA-256 of a one-time acceptance code; the plaintext is
  never persisted or logged.
* ``PLATFORM_OWNER`` is excluded from the role vocabulary.  Platform ownership
  is a platform capability assigned by the operator CLI, not a workspace grant.

RLS posture matches revisions 0005-0009: enabled with no policies and no grants
to ``anon`` or ``authenticated``.  The browser never reads this table directly.

Revision ID: 0010_invitations
Revises: 0009_verification_grants
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010_invitations"
down_revision: str | None = "0009_verification_grants"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=300), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_invitations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
            name=op.f("fk_invitations_accepted_by_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "role IN ('OWNER','ADMIN','TEACHER','REVIEWER','VIEWER')",
            name=op.f("ck_invitations_role"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','ACCEPTED','REVOKED')",
            name=op.f("ck_invitations_status"),
        ),
        sa.UniqueConstraint("token_hash", name="uq_invitation_token"),
    )
    op.create_index(
        "ix_invitation_email_status", "invitations", ["email", "status"]
    )
    op.create_index(
        "ix_invitation_tenant_status", "invitations", ["tenant_id", "status"]
    )
    op.create_index(
        op.f("ix_invitations_tenant_id"), "invitations", ["tenant_id"]
    )

    op.execute('REVOKE ALL ON TABLE public."invitations" FROM anon, authenticated')
    op.execute('ALTER TABLE public."invitations" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index(op.f("ix_invitations_tenant_id"), table_name="invitations")
    op.drop_index("ix_invitation_tenant_status", table_name="invitations")
    op.drop_index("ix_invitation_email_status", table_name="invitations")
    op.drop_table("invitations")
