"""0027: independent blind transcription evidence

A paper is read twice: once to mark it, and once by a reader that is given only
the page images and the question ids.  This table stores that second reading
next to the answer the marker recorded, so a difference is evidence a person can
weigh rather than a verdict that silently changes a mark.

Nothing here decides a mark.  The row records what the blind reader transcribed,
what the marker had recorded, whether the answer was legible, and which model and
prompt produced the reading.  One row per (job, question) is enough: a second
reading of the same answer is not a second opinion, it is a repeat.

This file was lost from the working tree while its revision stayed applied in the
live database (which is stamped at this revision).  It is restored from the
surviving bytecode and the live catalogue, and the table it creates is the table
the database already holds, including its constraints, index, RLS state and the
grants revoked from the anonymous roles.

Revision ID: 0027_transcription_checks
Revises: 0026_scheme_criteria_approval
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_transcription_checks"
down_revision = "0026_scheme_criteria_approval"
branch_labels = None
depends_on = None

_STATUSES = "('AGREES','DIFFERS','ABSENT','UNVERIFIABLE')"


def upgrade() -> None:
    op.create_table(
        "transcription_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("transcribed_answer", sa.Text(), nullable=True),
        sa.Column(
            "transcribed_question_id_seen", sa.String(length=40), nullable=True
        ),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("legible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("marker_answer", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("model_role", sa.String(length=20), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=True),
        sa.Column(
            "detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transcription_checks"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["correction_jobs.id"],
            name="fk_transcription_checks_job_id_correction_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_transcription_checks_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "job_id", "question_id", name="uq_transcription_job_question"
        ),
        # ``op.f`` marks the name as final so the metadata naming convention
        # does not prefix it a second time.
        sa.CheckConstraint(
            f"status IN {_STATUSES}", name=op.f("ck_transcription_checks_status")
        ),
    )
    op.create_index(
        "ix_transcription_checks_tenant_id", "transcription_checks", ["tenant_id"]
    )
    # A transcription verdict is reviewer evidence, never a client-readable row:
    # the Data API roles must not see it even if the table is exposed.
    op.execute(
        'REVOKE ALL ON TABLE public."transcription_checks" FROM anon, authenticated'
    )
    op.execute('ALTER TABLE public."transcription_checks" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    # Dropping the table destroys every recorded blind reading.  Those readings
    # are evidence about an award, not the award itself: the marks, results,
    # approvals and verification rows all survive.  There is no way to rebuild
    # the transcriptions from anything else in the database, so this downgrade is
    # an irreversible loss of that evidence and is documented as such.
    op.execute('ALTER TABLE public."transcription_checks" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_transcription_checks_tenant_id", table_name="transcription_checks")
    op.drop_table("transcription_checks")
