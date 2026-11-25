"""0031: record the marking rules an approval actually covered

``criteria_approved_at`` says a person reviewed the criteria.  It cannot say
*which* criteria: a mark point edited after review, a tolerance replaced, a
dependency added or an alternative re-targeted all leave the timestamp valid, and
the engine would mark against rules nobody approved.

This revision adds ``mark_scheme_versions.criteria_rules_hash``: a SHA-256 over
the approved rules (identity, marks, description, expected answer, dependencies,
alternative routes, award and withhold conditions) and the blueprint leaves they
were reviewed against.  The importer records it when it approves, and the marking
gate recomputes it from the stored rows before spending a provider request.

Nullable, and nothing is backfilled.  An existing approval cannot be shown to
cover the rows stored beside it unless the digest was recorded at the time, so
the gate fails closed and asks for a re-approval instead of inventing one.  No
criterion row, approval, award or historical result is modified here.

Revision ID: 0031_scheme_criteria_rules_hash
Revises: 0030_mapping_method_manual
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_scheme_criteria_rules_hash"
down_revision = "0030_mapping_method_manual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mark_scheme_versions",
        sa.Column("criteria_rules_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mark_scheme_versions", "criteria_rules_hash")
