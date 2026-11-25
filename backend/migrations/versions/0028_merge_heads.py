"""0028: merge the two correction-engine branches

Two revisions were developed on top of ``0025_job_recovery_link`` at the same
time and both reached a database, in different places:

* ``0026_verification_kinds`` widens the verification kinds and statuses the
  current engine writes (``SCHEME_MATHEMATICAL``, ``TRANSCRIPTION``, plus the
  ``SKIPPED``/``DIFFERS``/``ABSENT`` statuses).  It is what the repository's
  engine depends on.
* ``0026_scheme_criteria_approval`` → ``0027_transcription_checks`` is the
  branch the live database is stamped at: reviewable scheme criteria and the
  ``transcription_checks`` table.

Neither branch supersedes the other, and rewriting either history would make a
revision that has already run look like something it was not.  This merge
revision is the documented Alembic answer: it changes no schema, declares both
heads as parents, and gives future revisions (the whole-paper marking work) a
single parent to build on.

Applying it to a database stamped at ``0027_transcription_checks`` runs
``0026_verification_kinds`` first — which is required, because the engine writes
verification kinds the live constraint currently rejects.

Revision ID: 0028_merge_heads
Revises: 0026_verification_kinds, 0027_transcription_checks
"""

from __future__ import annotations

revision = "0028_merge_heads"
down_revision = ("0026_verification_kinds", "0027_transcription_checks")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both branches are already applied by the time this revision runs."""


def downgrade() -> None:
    """A merge holds no schema of its own; downgrade passes through it."""
