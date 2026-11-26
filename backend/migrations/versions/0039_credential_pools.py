"""Per-credential pools, with Google project identity kept as evidence.

Aetrix manages roughly fifteen lent Gemini keys and has to enable, budget and
quarantine each of them separately.  This revision gives every credential the
pool it is accounted under — ``gemini-key-{credential_id}`` — and the per-pool
state the fleet screen needs: a consecutive-failure counter, a quarantine kind
and the last quota-exhaustion instant with Google's own reason.

It also records whether the credential's Google Cloud project is established.
That is a *different* fact: Google meters the free tier per project and model and
may put several API keys in one project, so a per-credential pool is never
evidence of a separate project allowance.  Every existing row is stamped
``PROJECT_IDENTITY_UNVERIFIED`` because nobody has asserted otherwise, which
keeps the fleet from presenting a shared Google allowance as independent.

The revision is additive: ``provider_usage`` and ``provider_quota_reservations``
are not touched, no historical usage is recalculated and no project id is
rewritten.  Legacy pooled labels (``user-downloads-pool``) stay exactly as
recorded; the new ``pool_id`` identifies the Aetrix pool, not a project.

Revision ID: 0039_credential_pools
Revises: 0038_reservation_unconfirmed
"""

from __future__ import annotations

from alembic import op

revision = "0039_credential_pools"
down_revision = "0038_reservation_unconfirmed"
branch_labels = None
depends_on = None

_TABLE = "provider_credentials"
_CONSTRAINT = "ck_provider_credentials_project_identity"
_INDEX = "ix_provider_credential_project_identity"
_BODY = "project_identity IN ('VERIFIED','DECLARED','PROJECT_IDENTITY_UNVERIFIED')"

_POOL_CONSTRAINT = "ck_provider_credentials_pool_id"
_POOL_UNIQUE = "uq_provider_credential_pool_id"
_POOL_BODY = "pool_id LIKE 'gemini-key-%'"
_COOLDOWN_CONSTRAINT = "ck_provider_credentials_cooldown_kind"
_COOLDOWN_BODY = "cooldown_kind IS NULL OR cooldown_kind IN ('QUOTA','AUTH')"
_COOLDOWN_INDEX = "ix_provider_credential_cooldown"

_REASON = (
    "No administrator has asserted which Google Cloud project this key bills, "
    "so Google-level capacity is unknown; the key is accounted as its own "
    "Aetrix pool."
)


def upgrade() -> None:
    # ── project identity: evidence, not the accounting unit ──────────────────
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN project_identity varchar(40) "
        "NOT NULL DEFAULT 'PROJECT_IDENTITY_UNVERIFIED'"
    )
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN project_identity_reason varchar(300)")
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN project_identity_declared_at timestamptz")
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN project_identity_declared_by varchar(200)")
    op.execute(
        f"UPDATE {_TABLE} SET project_identity_reason = '{_REASON}' "
        "WHERE project_identity_reason IS NULL"
    )
    op.execute(f'ALTER TABLE {_TABLE} ADD CONSTRAINT "{_CONSTRAINT}" CHECK ({_BODY})')
    op.execute(f"CREATE INDEX {_INDEX} ON {_TABLE} (project_identity)")

    # ── the Aetrix pool: one per credential, stable and unique ───────────────
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN pool_id varchar(64)")
    # Backfill from the primary key.  This is a derived identifier, not a
    # rewrite of recorded usage: nothing in the ledger is touched.
    op.execute(
        f"UPDATE {_TABLE} SET pool_id = 'gemini-key-' || id::text "
        "WHERE pool_id IS NULL"
    )
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN pool_id SET NOT NULL")
    op.execute(
        f'ALTER TABLE {_TABLE} ADD CONSTRAINT "{_POOL_UNIQUE}" UNIQUE (pool_id)'
    )
    op.execute(
        f'ALTER TABLE {_TABLE} ADD CONSTRAINT "{_POOL_CONSTRAINT}" CHECK ({_POOL_BODY})'
    )

    # ── per-pool operational state ───────────────────────────────────────────
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN cooldown_kind varchar(20)")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN consecutive_failures integer "
        "NOT NULL DEFAULT 0"
    )
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN last_quota_exhausted_at timestamptz")
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN last_quota_reason varchar(300)")
    op.execute(
        f'ALTER TABLE {_TABLE} '
        f'ADD CONSTRAINT "{_COOLDOWN_CONSTRAINT}" CHECK ({_COOLDOWN_BODY})'
    )
    op.execute(f"CREATE INDEX {_COOLDOWN_INDEX} ON {_TABLE} (cooldown_until)")


def downgrade() -> None:
    # Pool and identity evidence are not reconstructed on the way down: the
    # columns that hold them disappear, and no ledger row is altered to
    # compensate.  Historical reservations and usage keep their credential and
    # project references throughout.
    op.execute(f"DROP INDEX IF EXISTS {_COOLDOWN_INDEX}")
    op.execute(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "{_COOLDOWN_CONSTRAINT}"')
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS last_quota_reason")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS last_quota_exhausted_at")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS consecutive_failures")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS cooldown_kind")
    op.execute(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "{_POOL_CONSTRAINT}"')
    op.execute(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "{_POOL_UNIQUE}"')
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS pool_id")
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f'ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS "{_CONSTRAINT}"')
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS project_identity_declared_by")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS project_identity_declared_at")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS project_identity_reason")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS project_identity")
