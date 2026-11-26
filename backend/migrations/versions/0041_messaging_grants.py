"""Revoke browser-role grants on the messaging tables.

Revision ID: 0041_messaging_grants
Revises: 0040_messaging

The tables are only reachable through the authenticated engine API.  Supabase
can recreate default grants when a table is created, so this revision repeats
the revoke after 0040 and can be re-run safely on any environment.
"""

from __future__ import annotations

from alembic import op

revision = "0041_messaging_grants"
down_revision = "0040_messaging"
branch_labels = None
depends_on = None

_TABLES = (
    "conversations",
    "conversation_members",
    "messages",
    "message_notifications",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')


def downgrade() -> None:
    # Grants are intentionally not restored; the browser never had a supported
    # path to these tables.
    pass
