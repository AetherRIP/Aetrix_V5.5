"""0026: record scheme and transcription verdicts

The engine records two further kinds of independent evidence: the comparison of
the award with the approved scheme's own criteria (``SCHEME_MATHEMATICAL``, plus a
``SKIPPED`` status when the scheme states no comparable answer) and a blind second
reading of the answer (``TRANSCRIPTION``, with ``DIFFERS`` and ``ABSENT``
statuses).  The table is already keyed by (job, question, kind), so this migration
only widens the two check constraints; no column changes type and no award,
approval or existing verdict is touched.

Revision ID: 0026_verification_kinds
Revises: 0025_job_recovery_link
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_verification_kinds"
down_revision = "0025_job_recovery_link"
branch_labels = None
depends_on = None

_KINDS = (
    "('MATHEMATICAL','INTEGRITY','DOUBLE_CHECK','SCHEME_MATHEMATICAL','TRANSCRIPTION')"
)
_KINDS_BEFORE = "('MATHEMATICAL','INTEGRITY','DOUBLE_CHECK')"

_STATUSES = (
    "('EQUIVALENT','DIFFERENT','UNKNOWN','PASS','FAIL','REVIEW_REQUIRED',"
    "'AGREES','DISAGREES','UNVERIFIABLE','SKIPPED','DIFFERS','ABSENT')"
)
_STATUSES_BEFORE = (
    "('EQUIVALENT','DIFFERENT','UNKNOWN','PASS','FAIL','REVIEW_REQUIRED',"
    "'AGREES','DISAGREES','UNVERIFIABLE')"
)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_verification_results_kind"), "verification_results", type_="check"
    )
    op.create_check_constraint("kind", "verification_results", f"kind IN {_KINDS}")
    op.drop_constraint(
        op.f("ck_verification_results_status"), "verification_results", type_="check"
    )
    op.create_check_constraint("status", "verification_results", f"status IN {_STATUSES}")


def downgrade() -> None:
    # The narrower constraints cannot hold these verdicts.  They are derived
    # evidence for awards that stay exactly as they are, so removing them is the
    # only way back; no award, mark, approval or review decision is deleted.
    op.execute(
        sa.text(
            "DELETE FROM verification_results "
            "WHERE kind IN ('SCHEME_MATHEMATICAL','TRANSCRIPTION')"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM verification_results "
            "WHERE status IN ('SKIPPED','DIFFERS','ABSENT')"
        )
    )
    op.drop_constraint(
        op.f("ck_verification_results_kind"), "verification_results", type_="check"
    )
    op.create_check_constraint("kind", "verification_results", f"kind IN {_KINDS_BEFORE}")
    op.drop_constraint(
        op.f("ck_verification_results_status"), "verification_results", type_="check"
    )
    op.create_check_constraint(
        "status", "verification_results", f"status IN {_STATUSES_BEFORE}"
    )
