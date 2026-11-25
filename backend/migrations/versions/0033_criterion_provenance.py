"""0033: make an award's mark point provable, and provable only once

``criterion_results.criterion_id`` has existed since the criteria were imported,
but the marking path never wrote it: every row stored a code and NULL.  A code
is not an identity — the paper prints ``M1 M1 A1`` — so the stored award could
not be traced to the mark point it was given for, and the engine's own
component reconciliation had nothing to reconcile against.

This revision adds the same link where the quotation lives, and makes a
duplicate claim impossible at the storage layer:

``marking_evidence.criterion_id``
    the approved mark point a quotation was awarded against, so evidence and
    criterion travel together instead of being matched by code afterwards.

``uq_criterion_result_once_per_criterion``
    a partial unique index over ``(question_result_id, criterion_id)`` where
    ``criterion_id IS NOT NULL``.  One mark point can be paid once per question.
    Rows without a link (every historical row, and any award whose mark point
    the reply did not identify) are outside the index, so nothing existing can
    conflict and no criterion id is invented for a historical result.

Both changes are additive and nullable; nothing is backfilled.  The downgrade
drops the index and the column and leaves every stored mark, evidence row and
scheme untouched, so it is safe to reverse on a disposable database.

Revision ID: 0033_criterion_provenance
Revises: 0032_provider_attempt_routing
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_criterion_provenance"
down_revision = "0032_provider_attempt_routing"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_criterion_result_once_per_criterion"


def upgrade() -> None:
    op.add_column(
        "marking_evidence",
        sa.Column("criterion_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_marking_evidence_criterion_id",
        "marking_evidence",
        "marking_criteria",
        ["criterion_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        INDEX_NAME,
        "criterion_results",
        ["question_result_id", "criterion_id"],
        unique=True,
        postgresql_where=sa.text("criterion_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="criterion_results")
    op.drop_constraint(
        "fk_marking_evidence_criterion_id", "marking_evidence", type_="foreignkey"
    )
    op.drop_column("marking_evidence", "criterion_id")
