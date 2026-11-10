"""0014: a distinct health state for a provider that could not be reached.

``UNKNOWN`` meant both "never tested" and "the probe failed for reasons that are
not the key's fault".  A timeout or a provider 5xx now records ``UNREACHABLE``,
so an operator can tell a new key from one that was simply not checkable, and a
transient failure is never mistaken for an authentication failure.

Revision ID: 0014_validation_health
Revises: 0013_service_heartbeat
Create Date: 2026-11-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_validation_health"
down_revision: str | None = "0013_service_heartbeat"
branch_labels: str | None = None
depends_on: str | None = None

_NEW = "health IN ('HEALTHY','COOLDOWN','INVALID','DISABLED','UNKNOWN','UNREACHABLE')"
_OLD = "health IN ('HEALTHY','COOLDOWN','INVALID','DISABLED','UNKNOWN')"


def upgrade() -> None:
    op.drop_constraint("health", "provider_credentials", type_="check")
    op.create_check_constraint("health", "provider_credentials", _NEW)


def downgrade() -> None:
    # The old vocabulary has no UNREACHABLE, so rows carrying it are folded back
    # into UNKNOWN before the narrower constraint is restored.
    op.execute("UPDATE provider_credentials SET health = 'UNKNOWN' WHERE health = 'UNREACHABLE'")
    op.drop_constraint("health", "provider_credentials", type_="check")
    op.create_check_constraint("health", "provider_credentials", _OLD)
