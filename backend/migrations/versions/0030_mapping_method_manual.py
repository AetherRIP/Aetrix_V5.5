"""0030: a page mapping recorded by a person

Page-to-question mappings are produced by the mapper (``MODEL``) or by reading
printed question numbers (``TEXT_MATCH``).  Neither vocabulary can say "a person
corrected this", which is what a supervised pilot needs when the mapper attributes
a page to a parent question number (``16``) and leaves the scoreable leaf (``16b``)
without any page.  Adding ``MANUAL`` makes that correction representable without
rewriting the original row: the model's mapping stays, and the correction sits
beside it, naming what it was corrected from.

The check constraint this revision replaces carries a doubled name in the
catalogue (``ck_page_question_mappings_ck_page_question_mappings_method``),
because the table's first migration supplied an already-prefixed name to a naming
convention that prefixes again.  The drop names that exact constraint and uses
``IF EXISTS`` so the revision is still safe on a database where it was created
under the conventional name; the replacement is created under the conventional
name so the model's metadata and the catalogue agree from here on.

Nothing else changes: no mapping is rewritten, no confidence is edited, and every
existing row keeps its method.

Revision ID: 0030_mapping_method_manual
Revises: 0029_whole_paper_marking
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_mapping_method_manual"
down_revision = "0029_whole_paper_marking"
branch_labels = None
depends_on = None

_METHODS = "('TEXT_MATCH','MODEL','MANUAL')"
_METHODS_BEFORE = "('TEXT_MATCH','MODEL')"

#: The name the catalogue actually holds, and the conventional one the model uses.
_LEGACY_NAME = "ck_page_question_mappings_ck_page_question_mappings_method"
_CONVENTIONAL_NAME = "ck_page_question_mappings_method"


def upgrade() -> None:
    op.execute(
        sa.text(
            f'ALTER TABLE page_question_mappings DROP CONSTRAINT IF EXISTS "{_LEGACY_NAME}"'
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE page_question_mappings DROP CONSTRAINT IF EXISTS "{_CONVENTIONAL_NAME}"'
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE page_question_mappings ADD CONSTRAINT "{_CONVENTIONAL_NAME}" '
            f"CHECK (method IN {_METHODS})"
        )
    )


def downgrade() -> None:
    # The narrower constraint cannot hold a manual correction, so the correction
    # rows are removed on the way down.  They are mapping evidence, not marks:
    # every award, component, quote and verification verdict survives, and the
    # model's original mapping rows are untouched throughout.
    op.execute(sa.text("DELETE FROM page_question_mappings WHERE method = 'MANUAL'"))
    op.execute(
        sa.text(
            f'ALTER TABLE page_question_mappings DROP CONSTRAINT IF EXISTS "{_CONVENTIONAL_NAME}"'
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE page_question_mappings ADD CONSTRAINT "{_LEGACY_NAME}" '
            f"CHECK (method IN {_METHODS_BEFORE})"
        )
    )
