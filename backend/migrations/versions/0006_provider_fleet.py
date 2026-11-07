"""Provider fleet: Google Cloud project grouping and project-level quota.

Revision ID: 0006_provider_fleet
Revises: 0005_rls_lockdown

Context
-------
Gemini free-tier quota is granted per Google Cloud *project*, not per API key.
The engine previously counted rate limits per credential, so ten keys sharing
one project behaved like ten independent pools — ten times the real allowance,
and a burst of 429s as soon as the shared limit was reached.

This revision makes the project an explicit, operator-supplied attribute of a
credential and the unit quota is counted against:

1. ``provider_credentials.project_id`` — required, indexed, with a synthetic
   ``legacy-<fingerprint>`` value for keys that existed before this change;
   legacy keys keep their current behaviour (one pool each) until an operator
   assigns the real project, which is honest rather than guessed.
2. ``provider_credentials`` fleet columns: ``auth_type``, ``tier`` (FREE / PAID
   / UNKNOWN — never inferred), ``last_validated_at``, ``last_failure_at`` and
   ``last_failure_status``.
3. ``provider_usage.project_id`` — denormalised so project consumption is
   aggregated without a join and survives a key being removed — plus
   ``retry_count``.
4. ``provider_project_cooldowns`` — a shared pause for a project whose quota is
   exhausted, so every key under it stands down together.

The new table starts with the same deny-by-default posture as revision 0005:
RLS enabled, no policies, and no grants to ``anon`` or ``authenticated``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006_provider_fleet"
down_revision: str | None = "0005_rls_lockdown"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── provider_credentials ────────────────────────────────────────────────
    op.add_column(
        "provider_credentials",
        sa.Column("project_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "provider_credentials",
        sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="api_key"),
    )
    op.add_column(
        "provider_credentials",
        sa.Column("tier", sa.String(length=20), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column(
        "provider_credentials",
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "provider_credentials",
        sa.Column("last_failure_status", sa.Integer(), nullable=True),
    )
    op.add_column(
        "provider_credentials",
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Legacy keys cannot be attributed to a real project, so each becomes its own
    # pool.  Guessing that they share a project would under-use capacity;
    # guessing nothing would silently multiply it.
    op.execute(
        "UPDATE provider_credentials "
        "SET project_id = 'legacy-' || left(key_fingerprint, 16) "
        "WHERE project_id IS NULL"
    )
    op.alter_column("provider_credentials", "project_id", nullable=False)

    op.create_check_constraint(
        "tier",
        "provider_credentials",
        "tier IN ('FREE','PAID','UNKNOWN')",
    )
    op.create_check_constraint(
        "auth_type",
        "provider_credentials",
        "auth_type IN ('api_key','oauth')",
    )
    op.create_index(
        "ix_provider_credential_project",
        "provider_credentials",
        ["project_id"],
    )
    op.create_index(
        "ix_provider_credential_project_health",
        "provider_credentials",
        ["project_id", "health"],
    )

    # ── provider_usage ──────────────────────────────────────────────────────
    op.add_column(
        "provider_usage",
        sa.Column("project_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.execute(
        """
        UPDATE provider_usage AS u
        SET project_id = c.project_id
        FROM provider_credentials AS c
        WHERE u.credential_id = c.id AND u.project_id IS NULL
        """
    )
    op.execute("UPDATE provider_usage SET project_id = 'unattributed' WHERE project_id IS NULL")
    op.alter_column("provider_usage", "project_id", nullable=False)

    op.create_index(
        "ix_provider_usage_project_created",
        "provider_usage",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_provider_usage_model_created",
        "provider_usage",
        ["model", "created_at"],
    )

    # ── provider_project_cooldowns ──────────────────────────────────────────
    op.create_table(
        "provider_project_cooldowns",
        sa.Column("project_id", sa.String(length=100), primary_key=True),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.execute('REVOKE ALL ON TABLE public."provider_project_cooldowns" FROM anon, authenticated')
    op.execute('ALTER TABLE public."provider_project_cooldowns" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("provider_project_cooldowns")

    op.drop_index("ix_provider_usage_model_created", table_name="provider_usage")
    op.drop_index("ix_provider_usage_project_created", table_name="provider_usage")
    op.drop_column("provider_usage", "retry_count")
    op.drop_column("provider_usage", "project_id")

    op.drop_index("ix_provider_credential_project_health", table_name="provider_credentials")
    op.drop_index("ix_provider_credential_project", table_name="provider_credentials")
    op.drop_constraint("auth_type", "provider_credentials", type_="check")
    op.drop_constraint("tier", "provider_credentials", type_="check")
    op.drop_column("provider_credentials", "last_validated_at")
    op.drop_column("provider_credentials", "last_failure_status")
    op.drop_column("provider_credentials", "last_failure_at")
    op.drop_column("provider_credentials", "tier")
    op.drop_column("provider_credentials", "auth_type")
    op.drop_column("provider_credentials", "project_id")
