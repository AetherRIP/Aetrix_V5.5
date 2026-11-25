"""0035: record how long a provider call waited for a credential

Parallel correction makes contention visible: several questions ask for a lease
at the same time, and the pool serialises the read-and-reserve so quota is
counted once.  Without a number, "the paper was slow" cannot be separated from
"the provider was slow".

``provider_usage.queue_wait_ms`` stores the milliseconds spent acquiring the
lease and reservation for that attempt.  ``latency_ms`` already stores the
provider's own time.  Both are nullable: historical rows predate the column and
the ledger is append-only.

Revision ID: 0035_provider_queue_wait
Revises: 0034_parallel_marking
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_provider_queue_wait"
down_revision = "0034_parallel_marking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_usage", sa.Column("queue_wait_ms", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    # Queue time is accounting, not evidence: no mark or award depends on it.
    op.drop_column("provider_usage", "queue_wait_ms")
