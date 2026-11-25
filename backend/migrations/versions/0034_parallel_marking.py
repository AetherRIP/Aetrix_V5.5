"""0034: parallel correction as a recorded marking mode

Parallel correction sends the same per-question request as ``PER_QUESTION``; the
difference is that independent questions are corrected concurrently and every
row keeps the mode it was produced under.  Two check constraints currently name
only the two older modes, so a parallel row could not be stored at all:

* ``correction_jobs.marking_mode`` — the mode a paper was first marked in;
* ``question_results.response_source`` — the request shape that produced a row.

Both are widened to accept ``PARALLEL``.  No column, table, index or row is
added or changed: this revision only permits the value the engine now writes.
Historical rows keep their recorded mode and are never rewritten.

Revision ID: 0034_parallel_marking
Revises: 0033_criterion_provenance
"""

from __future__ import annotations

from alembic import op

revision = "0034_parallel_marking"
down_revision = "0033_criterion_provenance"
branch_labels = None
depends_on = None

_SOURCES = "('PER_QUESTION','WHOLE_PAPER','PARALLEL')"

#: The constraints as they existed before this revision.  A downgrade restores
#: them only when no parallel row exists; dropping the value from the constraint
#: while a row carries it would make the schema reject its own data.
_PREVIOUS_SOURCES = "('PER_QUESTION','WHOLE_PAPER')"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_correction_jobs_marking_mode"), "correction_jobs", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_correction_jobs_marking_mode"),
        "correction_jobs",
        f"marking_mode IS NULL OR marking_mode IN {_SOURCES}",
    )

    op.drop_constraint(
        op.f("ck_question_results_response_source"), "question_results", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_question_results_response_source"),
        "question_results",
        f"response_source IS NULL OR response_source IN {_SOURCES}",
    )


def downgrade() -> None:
    # A row produced in the parallel mode cannot be represented by the older
    # constraint.  Refuse rather than delete or relabel evidence: the operator
    # must decide what happens to a paper that was marked in that mode.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM question_results WHERE response_source = 'PARALLEL'
            ) OR EXISTS (
                SELECT 1 FROM correction_jobs WHERE marking_mode = 'PARALLEL'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0034: parallel marking rows exist. '
                    'Re-mark or archive them deliberately first.';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(
        op.f("ck_question_results_response_source"), "question_results", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_question_results_response_source"),
        "question_results",
        f"response_source IS NULL OR response_source IN {_PREVIOUS_SOURCES}",
    )
    op.drop_constraint(
        op.f("ck_correction_jobs_marking_mode"), "correction_jobs", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_correction_jobs_marking_mode"),
        "correction_jobs",
        f"marking_mode IS NULL OR marking_mode IN {_PREVIOUS_SOURCES}",
    )
