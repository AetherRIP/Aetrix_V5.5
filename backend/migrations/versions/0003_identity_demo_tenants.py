"""identity: mark a tenant as a read-only demo workspace

A demo workspace is a real tenant, so tenancy, audit and every existing query
apply unchanged.  Only the principal boundary behaves differently: mutating
requests are refused for principals whose tenant is a demo.

Revision ID: 0003_identity_demo_tenants
Revises: 0002_blueprint_guard_fix
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_identity_demo_tenants"
down_revision: str | None = "0002_blueprint_guard_fix"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "is_demo")
