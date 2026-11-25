"""0029: whole-paper marking provenance and the archived reply

Whole-paper marking asks the model once for every question of a paper.  That
creates two things the per-question path never needed: a complete reply worth
keeping as one document, and a way to say which request produced each question
row.  This revision adds both, plus the one state a paper must not lose.

Three changes:

* ``provider_responses`` archives the complete body of one provider reply, once
  per (job, body) pair, with its SHA-256.  A per-question row keeps its own full
  reply in ``question_results.raw_response``; a whole-paper body belongs to 39
  rows at once, so it is stored once and referenced.
* ``question_results`` gains the provenance of the request that produced it:
  ``response_source`` (which request shape), ``response_sequence`` (its position
  in a whole-paper reply) and ``provider_usage_id`` (the audited call, which also
  reaches the archived body).
* ``correction_jobs.marking_mode`` records the mode a paper was first marked in.
  A deployment changing its configuration must not switch a paper that is already
  part way through; a resumed job keeps the mode its rows were made in.

Revision ID: 0029_whole_paper_marking
Revises: 0028_merge_heads
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_whole_paper_marking"
down_revision = "0028_merge_heads"
branch_labels = None
depends_on = None

_SOURCES = "('PER_QUESTION','WHOLE_PAPER')"


def upgrade() -> None:
    # -- the mode a paper was marked in --------------------------------
    op.add_column(
        "correction_jobs", sa.Column("marking_mode", sa.String(length=20), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_correction_jobs_marking_mode"),
        "correction_jobs",
        f"marking_mode IS NULL OR marking_mode IN {_SOURCES}",
    )

    # -- which request produced a question row -------------------------
    op.add_column(
        "question_results",
        sa.Column("response_source", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "question_results", sa.Column("response_sequence", sa.Integer(), nullable=True)
    )
    op.add_column("question_results", sa.Column("provider_usage_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f("ck_question_results_response_source"),
        "question_results",
        f"response_source IS NULL OR response_source IN {_SOURCES}",
    )
    # SET NULL, not CASCADE: the ledger is append-only and a row outlives its
    # usage entry rather than disappearing with it.
    op.create_foreign_key(
        "fk_question_results_provider_usage_id_provider_usage",
        "question_results",
        "provider_usage",
        ["provider_usage_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_question_results_provider_usage_id", "question_results", ["provider_usage_id"]
    )

    # -- the archived reply --------------------------------------------
    op.create_table(
        "provider_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("provider_usage_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("response_source", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column(
            "body_truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("finish_reason", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_responses"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_provider_responses_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["correction_jobs.id"],
            name="fk_provider_responses_job_id_correction_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_usage_id"],
            ["provider_usage.id"],
            name="fk_provider_responses_provider_usage_id_provider_usage",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name="fk_provider_responses_prompt_version_id_prompt_versions",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("provider_usage_id", name="uq_provider_responses_usage"),
        sa.CheckConstraint(
            f"response_source IN {_SOURCES}",
            name=op.f("ck_provider_responses_response_source"),
        ),
    )
    op.create_index(
        "ix_provider_responses_tenant_id", "provider_responses", ["tenant_id"]
    )
    op.create_index(
        "ix_provider_responses_job", "provider_responses", ["job_id", "created_at"]
    )
    # A model's reply is evidence about an award, never a client-readable row:
    # the Data API roles must not see it even if the table is exposed.
    op.execute(
        'REVOKE ALL ON TABLE public."provider_responses" FROM anon, authenticated'
    )
    op.execute('ALTER TABLE public."provider_responses" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    # Dropping the archive destroys the only copy of a whole-paper reply that
    # belongs to more than one question row.  The marks, components, evidence
    # and verification verdicts all survive: they are decisions, not inputs.
    # A per-question row's own reply lives in ``question_results.raw_response``
    # and is unaffected, so only whole-paper provenance and the archived bodies
    # are lost, and they cannot be rebuilt from anything else in the database.
    op.execute('ALTER TABLE public."provider_responses" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_provider_responses_job", table_name="provider_responses")
    op.drop_index("ix_provider_responses_tenant_id", table_name="provider_responses")
    op.drop_table("provider_responses")

    op.drop_index("ix_question_results_provider_usage_id", table_name="question_results")
    op.drop_constraint(
        "fk_question_results_provider_usage_id_provider_usage",
        "question_results",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_question_results_response_source"),
        "question_results",
        type_="check",
    )
    op.drop_column("question_results", "provider_usage_id")
    op.drop_column("question_results", "response_sequence")
    op.drop_column("question_results", "response_source")

    op.drop_constraint(
        op.f("ck_correction_jobs_marking_mode"), "correction_jobs", type_="check"
    )
    op.drop_column("correction_jobs", "marking_mode")
