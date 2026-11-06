"""audit: remember who acted, even after they leave

An audit event referenced its actor by identifier only, so removing a member made
their past decisions anonymous. The label is the actor's name as it was at the
time of the change: copied, not joined, precisely so the history survives the
person's removal.

Existing rows are backfilled from the members that still exist; events whose actor
is already gone keep a null label and remain identified by their stored id.

Revision ID: 0004_audit_actor_label
Revises: 0003_identity_demo_tenants
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_audit_actor_label"
down_revision: str | None = "0003_identity_demo_tenants"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("actor_label", sa.String(320), nullable=True))
    op.execute(
        """
        UPDATE audit_events AS event
        SET actor_label = COALESCE(
            NULLIF(member.display_name, ''),
            member.email,
            member.subject
        )
        FROM users AS member
        WHERE event.actor_type = 'USER'
          AND event.actor_id = member.id::text
          AND event.actor_label IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("audit_events", "actor_label")
