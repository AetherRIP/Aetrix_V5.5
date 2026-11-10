"""0009: remove the leftover Data API grant on verification_results.

Revision 0005 revokes table privileges from ``anon`` and ``authenticated`` for
every table that existed then, and 0006-0008 do the same for the tables they
create.  The live Supabase database nevertheless reported a surviving
``SELECT`` grant for ``authenticated`` on ``verification_results`` — a table
0005 names explicitly.  The grant is not exploitable while RLS is enabled with
no policies, but it violates the least-privilege posture and would become a
read path the moment a policy was added.

The revision is idempotent: ``REVOKE`` succeeds whether or not the grant is
present.  Its downgrade deliberately does **not** restore the grant; a security
lockdown is not reversed by rolling back a schema change.

Revision ID: 0009_verification_grants
Revises: 0008_platform_owner
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0009_verification_grants"
down_revision = "0008_platform_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'REVOKE ALL ON TABLE public."verification_results" FROM anon, authenticated'
    )


def downgrade() -> None:
    # Restoring a Data API grant would silently reopen a table the engine reads
    # only through its own database role.  The downgrade is intentionally a
    # no-op.
    pass
