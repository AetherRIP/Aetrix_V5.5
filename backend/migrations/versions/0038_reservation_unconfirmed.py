"""Record a provider request whose quota consumption Google did not confirm.

A failed HTTP request is neither free nor automatically charged.  Before this
revision the only failure states were ``CONSUMED`` and ``RELEASED``, so a 503 —
which Google may or may not have metered — had to be written as one or the other,
and the call path wrote it as ``CONSUMED``: twenty overload responses exhausted a
free-tier day that had served no paper.

``UNCONFIRMED`` is the honest third state.  It is counted per minute (so a retry
storm still hits the rate gate) and excluded from the confirmed daily total.

Revision ID: 0038_reservation_unconfirmed
Revises: 0037_classroom_integration
"""

from __future__ import annotations

from alembic import op

revision = "0038_reservation_unconfirmed"
down_revision = "0037_classroom_integration"
branch_labels = None
depends_on = None

#: The constraint's real name, as it exists in the deployed database.
_CONSTRAINT = "ck_provider_quota_reservations_status"
_TABLE = "provider_quota_reservations"

#: The previous body, restored on downgrade.
_PREVIOUS = "status IN ('RESERVED','CONSUMED','RELEASED')"
_WITH_UNCONFIRMED = "status IN ('RESERVED','CONSUMED','RELEASED','UNCONFIRMED')"


def _replace(body: str) -> None:
    """Swap the check constraint for one with ``body``, keeping its name.

    The statements are raw DDL on purpose.  ``op.drop_constraint`` and
    ``op.create_check_constraint`` render the name through the metadata naming
    convention (``ck_%(table_name)s_%(constraint_name)s``), which would ask
    PostgreSQL to drop ``ck_provider_quota_reservations_ck_provider_quota_
    reserv_75d3`` — a name that does not exist — and would rename the
    constraint on creation.  The table's constraint was created with its plain
    name by the revision that introduced it, and ``models.py`` (which declares
    the name as ``status`` under the same convention) expects exactly that name.
    """

    op.execute(f'ALTER TABLE {_TABLE} DROP CONSTRAINT "{_CONSTRAINT}"')
    op.execute(
        f'ALTER TABLE {_TABLE} ADD CONSTRAINT "{_CONSTRAINT}" CHECK ({body})'
    )


def upgrade() -> None:
    _replace(_WITH_UNCONFIRMED)


def downgrade() -> None:
    # A row already in the new state cannot be represented by the old constraint.
    # Downgrading therefore reclassifies those rows as CONSUMED, which is the
    # pessimistic reading and preserves the audit trail rather than deleting it.
    op.execute(
        f"UPDATE {_TABLE} SET status = 'CONSUMED' WHERE status = 'UNCONFIRMED'"
    )
    _replace(_PREVIOUS)
