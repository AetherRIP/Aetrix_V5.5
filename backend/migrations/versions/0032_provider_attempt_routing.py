"""0032: record which model in which chain answered, and what happened next

Before this revision one provider call could only be described by its model and
a ``retry_count``.  That is enough to see that something was retried and not
enough to see that Aetrix *switched models*: two rows with different models look
identical to two unrelated calls, and a fallback cannot be audited afterwards.

This revision adds the routing facts to the append-only usage ledger:

``model_role``           the correction role whose chain the attempt belongs to
``model_chain_position``  0-based position of that model in the role's chain
``attempt_index``         0-based attempt number within that model
``routing_decision``      SUCCESS / RETRY_SAME_MODEL / ROTATE_CREDENTIAL /
                          NEXT_MODEL / STOP
``cost_status``           KNOWN or COST_UNKNOWN, so a missing price is never
                          confused with a free call

Every column is nullable and nothing is backfilled: a historical row was
produced before chains existed, and inventing a chain position for it would be
fabricating provenance.  No existing usage row, credential, job or result is
modified.  The downgrade drops the columns and leaves the ledger otherwise
intact, so it is safe to reverse on a disposable database.

Revision ID: 0032_provider_attempt_routing
Revises: 0031_scheme_criteria_rules_hash
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_provider_attempt_routing"
down_revision = "0031_scheme_criteria_rules_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_usage",
        sa.Column("model_role", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("model_chain_position", sa.Integer(), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("attempt_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("routing_decision", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "provider_usage",
        sa.Column("cost_status", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("provider_usage", "cost_status")
    op.drop_column("provider_usage", "routing_decision")
    op.drop_column("provider_usage", "attempt_index")
    op.drop_column("provider_usage", "model_chain_position")
    op.drop_column("provider_usage", "model_role")
