"""0036: verification completeness and evidence authenticity

Completion and verification are different facts.  ``correction_jobs`` gains
``verification_status`` so a completed paper can honestly say whether every
required check ran and passed (``FULLY_VERIFIED``), whether some were never
bought (``PARTIALLY_VERIFIED``), whether a person is needed
(``REVIEW_REQUIRED``), whether a check contradicted the award
(``VERIFICATION_FAILED``), or whether no independent check applied at all.

``verification_results.kind`` is widened to accept ``EVIDENCE``: the
deterministic comparison of each awarded quotation against the blind
transcription.  Existing rows keep their kind and status; nothing is rewritten.

Revision ID: 0036_verification_completeness
Revises: 0035_provider_queue_wait
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_verification_completeness"
down_revision = "0035_provider_queue_wait"
branch_labels = None
depends_on = None

_KINDS_WITH_EVIDENCE = (
    "('MATHEMATICAL','INTEGRITY','DOUBLE_CHECK','SCHEME_MATHEMATICAL',"
    "'TRANSCRIPTION','EVIDENCE')"
)
_KINDS_PREVIOUS = (
    "('MATHEMATICAL','INTEGRITY','DOUBLE_CHECK','SCHEME_MATHEMATICAL','TRANSCRIPTION')"
)
_STATUSES = (
    "('FULLY_VERIFIED','PARTIALLY_VERIFIED','REVIEW_REQUIRED',"
    "'VERIFICATION_FAILED','VERIFICATION_NOT_REQUIRED')"
)


def upgrade() -> None:
    op.add_column(
        "correction_jobs", sa.Column("verification_status", sa.String(30), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_correction_jobs_verification_status"),
        "correction_jobs",
        f"verification_status IS NULL OR verification_status IN {_STATUSES}",
    )

    op.drop_constraint(
        op.f("ck_verification_results_kind"), "verification_results", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_verification_results_kind"),
        "verification_results",
        f"kind IN {_KINDS_WITH_EVIDENCE}",
    )


def downgrade() -> None:
    # An EVIDENCE verdict cannot be represented by the older constraint.  Refuse
    # rather than delete a verification record: the operator decides what
    # happens to evidence checks that were already taken.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM verification_results WHERE kind = 'EVIDENCE'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0036: evidence verification rows exist. '
                    'Archive them deliberately first.';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(
        op.f("ck_verification_results_kind"), "verification_results", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_verification_results_kind"),
        "verification_results",
        f"kind IN {_KINDS_PREVIOUS}",
    )
    op.drop_constraint(
        op.f("ck_correction_jobs_verification_status"), "correction_jobs", type_="check"
    )
    op.drop_column("correction_jobs", "verification_status")
