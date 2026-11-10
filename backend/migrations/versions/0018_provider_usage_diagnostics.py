"""0018: provider failure diagnostics and model-scoped quota reservations.

The ledger previously stored only an exception class.  Without the HTTP status,
Google's status enum, its message, token metadata and whether the request
reached Google, an operator could not tell a bad key from a 403 permission
failure, a network timeout or a parser defect.  Those fields are added as
nullable columns: historical rows cannot be rewritten because ``provider_usage``
is append-only, so the API labels their diagnostics as unavailable rather than
inventing them.

Quota reservations gain the model they were taken for.  Gemini meters per
project *and model*; without this column a flash call consumed the review
model's allowance.  Existing reservations are matched to the closest ledger row
for the same credential within a few seconds, and stay null when no unambiguous
match exists.

Credential health is narrowed to validity — HEALTHY, INVALID, DISABLED or
UNKNOWN.  Transport, quota and provider-server outcomes were never credential
validity and are now represented by the operational status derived from the
ledger and the project cooldown table.

Revision ID: 0018_provider_usage_diagnostics
Revises: 0017_classroom_allocations
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_provider_usage_diagnostics"
down_revision: str | None = "0017_classroom_allocations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HEALTH = "health IN ('HEALTHY','INVALID','DISABLED','UNKNOWN')"


def upgrade() -> None:
    op.add_column(
        "provider_quota_reservations",
        sa.Column("model", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_provider_reservation_project_model",
        "provider_quota_reservations",
        ["credential_id", "model", "created_at"],
        unique=False,
    )
    # Best-effort attribution for reservations written before the model was
    # stored.  A null remains null: guessing across models would corrupt the
    # very allowance this column exists to protect.
    op.execute(
        """
        UPDATE provider_quota_reservations AS r
        SET model = (
            SELECT u.model
            FROM provider_usage AS u
            WHERE u.credential_id = r.credential_id
              AND u.created_at BETWEEN r.created_at - interval '2 seconds'
                                   AND r.created_at + interval '15 seconds'
            ORDER BY abs(extract(epoch FROM (u.created_at - r.created_at)))
            LIMIT 1
        )
        WHERE r.model IS NULL
        """
    )

    op.add_column(
        "provider_usage",
        sa.Column("error_category", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("provider_code", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("provider_message", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("reached_provider", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("finish_reason", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_provider_usage_failure_created",
        "provider_usage",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("success = false"),
    )

    # Temporary operational values become UNKNOWN, or HEALTHY when a prior
    # successful call proves validity.  No key is promoted without evidence.
    op.drop_constraint("health", "provider_credentials", type_="check")
    op.execute(
        """
        UPDATE provider_credentials
        SET health = CASE
            WHEN health IN ('COOLDOWN', 'UNREACHABLE')
                 AND last_success_at IS NOT NULL THEN 'HEALTHY'
            WHEN health IN ('COOLDOWN', 'UNREACHABLE') THEN 'UNKNOWN'
            ELSE health
        END
        WHERE health IN ('COOLDOWN', 'UNREACHABLE')
        """
    )
    op.create_check_constraint("health", "provider_credentials", _HEALTH)


def downgrade() -> None:
    op.drop_constraint("health", "provider_credentials", type_="check")
    op.create_check_constraint(
        "health",
        "provider_credentials",
        "health IN ('HEALTHY','COOLDOWN','INVALID','DISABLED','UNKNOWN','UNREACHABLE')",
    )

    op.drop_index(
        "ix_provider_usage_failure_created", table_name="provider_usage"
    )
    op.drop_column("provider_usage", "finish_reason")
    op.drop_column("provider_usage", "reached_provider")
    op.drop_column("provider_usage", "provider_message")
    op.drop_column("provider_usage", "provider_code")
    op.drop_column("provider_usage", "error_category")

    op.drop_index(
        "ix_provider_reservation_project_model",
        table_name="provider_quota_reservations",
    )
    op.drop_column("provider_quota_reservations", "model")
