"""Multi-contributor API key pool: contributor records and ownership chains.

Revision ID: 0007_contributors
Revises: 0006_provider_fleet

Context
-------
The fleet was built for one operator who provisioned every key.  It is now fed
by independent individuals who each lend one or more keys, sometimes from
projects other contributors already use.  Two facts must stay true:

1. Every contributed key is attributable to the person who lent it, and that
   person can take it back.  Attribution therefore lives on the credential, and
   the consent and revocation timestamps live on a contributor row — deleting
   the row would erase the record of consent, so withdrawal is a status, not a
   delete.
2. Quota stays a property of the *Google Cloud project*.  Since contributors and
   projects are many-to-many, ``provider_credentials.project_id`` remains the
   only input to quota counting; no contributor-level counter exists, because
   that is exactly how ten keys would look like ten pools again.

Changes
-------
* ``provider_contributors`` — identity, optional Aetrix account, status
  (ACTIVE / SUSPENDED / WITHDRAWN), consent record and the suspend/withdraw
  timestamps.
* ``provider_credentials.contributor_id`` — nullable: null means the platform
  owns the key, which is different from an unattributed contribution.
* ``provider_credentials.revoked_at`` / ``revoked_reason`` — a withdrawn key
  keeps its row and its ledger history but loses its ciphertext.
* ``provider_usage.contributor_id`` — denormalised so contribution statistics
  survive a key being retired.

RLS posture matches revision 0005/0006: enabled, no policies, and no grants to
``anon`` or ``authenticated``.  Keys are platform infrastructure and the browser
must never reach them directly.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007_contributors"
down_revision: str | None = "0006_provider_fleet"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "provider_contributors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("consent_version", sa.String(length=40), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_reference", sa.String(length=200), nullable=True),
        sa.Column("status_reason", sa.String(length=300), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_contributors")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_provider_contributors_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','WITHDRAWN')",
            name=op.f("ck_provider_contributors_status"),
        ),
        sa.UniqueConstraint("user_id", name="uq_provider_contributor_user"),
    )
    op.create_index(
        "ix_provider_contributor_status", "provider_contributors", ["status"]
    )

    op.add_column(
        "provider_credentials",
        sa.Column("contributor_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "provider_credentials",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "provider_credentials",
        sa.Column("revoked_reason", sa.String(length=300), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_provider_credentials_contributor_id_provider_contributors"),
        "provider_credentials",
        "provider_contributors",
        ["contributor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_provider_credential_contributor",
        "provider_credentials",
        ["contributor_id"],
    )

    op.add_column(
        "provider_usage",
        sa.Column("contributor_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_provider_usage_contributor_id_provider_contributors"),
        "provider_usage",
        "provider_contributors",
        ["contributor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_provider_usage_contributor_created",
        "provider_usage",
        ["contributor_id", "created_at"],
    )

    # Keys registered before this revision belong to the platform, not to a
    # contributor: leaving them null states that instead of inventing an owner.
    op.execute(
        """
        UPDATE provider_usage AS u
        SET contributor_id = c.contributor_id
        FROM provider_credentials AS c
        WHERE u.credential_id = c.id
          AND u.contributor_id IS NULL
          AND c.contributor_id IS NOT NULL
        """
    )

    op.execute('REVOKE ALL ON TABLE public."provider_contributors" FROM anon, authenticated')
    op.execute('ALTER TABLE public."provider_contributors" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_provider_usage_contributor_created", table_name="provider_usage")
    op.drop_constraint(
        op.f("fk_provider_usage_contributor_id_provider_contributors"),
        "provider_usage",
        type_="foreignkey",
    )
    op.drop_column("provider_usage", "contributor_id")

    op.drop_index("ix_provider_credential_contributor", table_name="provider_credentials")
    op.drop_constraint(
        op.f("fk_provider_credentials_contributor_id_provider_contributors"),
        "provider_credentials",
        type_="foreignkey",
    )
    op.drop_column("provider_credentials", "revoked_reason")
    op.drop_column("provider_credentials", "revoked_at")
    op.drop_column("provider_credentials", "contributor_id")

    op.drop_index("ix_provider_contributor_status", table_name="provider_contributors")
    op.drop_table("provider_contributors")
