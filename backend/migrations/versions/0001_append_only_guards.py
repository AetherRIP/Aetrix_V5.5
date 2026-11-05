"""append-only guards for audit and usage ledgers

Revision ID: 0001_append_only
Revises: 74aaa523074a
Create Date: 2026-11-05

The audit trail, job events and provider usage are evidence.  Application code
never updates them, and this trigger makes that a database rule rather than a
convention.  DELETE is intentionally still permitted so tenant removal and
retention jobs can work; the guard is against rewriting history.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_append_only"
down_revision: str | None = "5828eae7d57d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("audit_events", "job_events", "provider_usage")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION aetrix_reject_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'append-only relation %: updates are not permitted', TG_TABLE_NAME;
        END;
        $$;
        """
    )
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION aetrix_reject_update();"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.execute("DROP FUNCTION IF EXISTS aetrix_reject_update();")
