"""0024: record the independent double-check verdict

The V5 engine records its second, independent marking as a verification row.  A
verification row is already keyed by (job, question, kind), so this migration
only widens the two check constraints: one new kind and three new statuses.  No
existing row is touched and no column changes type.

Revision ID: 0024_double_check_verification
Revises: 0023_engine_provenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_double_check_verification"
down_revision = "0023_engine_provenance"
branch_labels = None
depends_on = None

_KINDS_WITH_DOUBLE_CHECK = "('MATHEMATICAL','INTEGRITY','DOUBLE_CHECK')"
_KINDS_WITHOUT = "('MATHEMATICAL','INTEGRITY')"

_STATUSES_WITH_DOUBLE_CHECK = (
    "('EQUIVALENT','DIFFERENT','UNKNOWN','PASS','FAIL','REVIEW_REQUIRED',"
    "'AGREES','DISAGREES','UNVERIFIABLE')"
)
_STATUSES_WITHOUT = "('EQUIVALENT','DIFFERENT','UNKNOWN','PASS','FAIL','REVIEW_REQUIRED')"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_verification_results_kind"), "verification_results", type_="check"
    )
    op.create_check_constraint(
        "kind", "verification_results", f"kind IN {_KINDS_WITH_DOUBLE_CHECK}"
    )
    op.drop_constraint(
        op.f("ck_verification_results_status"), "verification_results", type_="check"
    )
    op.create_check_constraint(
        "status", "verification_results", f"status IN {_STATUSES_WITH_DOUBLE_CHECK}"
    )


def downgrade() -> None:
    # Double-check verdicts cannot exist under the narrower constraint.  They are
    # derived evidence for a first award that stays exactly as it is, so removing
    # them is the only way back; no award, mark or approval is deleted.
    op.execute(sa.text("DELETE FROM verification_results WHERE kind = 'DOUBLE_CHECK'"))
    op.drop_constraint(
        op.f("ck_verification_results_kind"), "verification_results", type_="check"
    )
    op.create_check_constraint(
        "kind", "verification_results", f"kind IN {_KINDS_WITHOUT}"
    )
    op.drop_constraint(
        op.f("ck_verification_results_status"), "verification_results", type_="check"
    )
    op.create_check_constraint(
        "status", "verification_results", f"status IN {_STATUSES_WITHOUT}"
    )
