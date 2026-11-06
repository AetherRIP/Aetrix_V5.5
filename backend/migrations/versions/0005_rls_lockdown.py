"""Lock down the public schema for the Supabase Data API.

Revision ID: 0005_rls_lockdown
Revises: 0004_audit_actor_label

Context
-------
Every table in ``public`` was created by the engine's own migrations while the
project's default privileges still granted ``anon`` and ``authenticated`` full
DML on new tables.  The result was 29 tables with RLS disabled, no policies and
``anon=arwdDxtm`` on each of them, reachable through PostgREST.

Nothing in this repository uses the Data API.  The engine connects directly as
``postgres`` (``BYPASSRLS``) and the public frontend has no Supabase client, so
the Data API has no legitimate consumer today.  This migration therefore denies
the Data API by default instead of inventing permissive policies:

1. revoke table/sequence privileges from ``anon`` and ``authenticated``;
2. enable RLS on every table as defence in depth (no policies = deny);
3. revoke the default privileges that would re-grant access to future tables.

RLS is deliberately *not* forced: ``postgres`` owns these tables and must keep
bypassing RLS for the engine's direct connection.  ``service_role`` also keeps
``BYPASSRLS`` for trusted server-side use.

Tenant-scoped policies for a future browser client are documented, but not
created here: adding them before such a client exists would be speculative and
is exactly the permissive-policy shortcut this change is meant to avoid.

Rebase note
-----------
This revision was prepared as ``0003_rls_lockdown`` on top of
``0002_blueprint_guard_fix``, because that was the head recorded in the
repository.  The live database was already at ``0004_audit_actor_label``: the
Phase 2 revisions (``0003_identity_demo_tenants`` and ``0004_audit_actor_label``)
existed only on the unmerged ``aetrix/v5.5-consolidation`` branch.  Once they
were recovered into this branch the lock-down was renumbered to ``0005`` and
re-parented onto ``0004_audit_actor_label`` so the chain is linear and matches
the deployed state.  The SQL below is unchanged by the rebase: neither Phase 2
revision creates a table or grants a privilege, it only adds the
``tenants.is_demo`` and ``audit_events.actor_label`` columns on tables that are
already covered by ``ALL_TABLES``.
"""

from __future__ import annotations

from alembic import op

revision: str = "0005_rls_lockdown"
down_revision: str | None = "0004_audit_actor_label"
branch_labels: str | None = None
depends_on: str | None = None

#: Tables carrying a non-null ``tenant_id`` foreign key.
TENANT_SCOPED_TABLES = (
    "assignments",
    "audit_events",
    "blueprint_overrides",
    "cohort_analyses",
    "correction_jobs",
    "criterion_results",
    "document_pages",
    "documents",
    "exam_blueprint_versions",
    "exams",
    "job_events",
    "learning_feedback",
    "mark_scheme_versions",
    "mark_schemes",
    "marking_criteria",
    "marking_evidence",
    "page_question_mappings",
    "provider_credentials",
    "provider_quota_reservations",
    "provider_usage",
    "question_results",
    "review_decisions",
    "submissions",
    "users",
    "verification_results",
)

#: The tenant root.  Scoped by its own ``id``, not by a ``tenant_id`` column.
TENANT_ROOT_TABLES = ("tenants",)

#: Reference data and migration bookkeeping; still not Data-API readable.
SHARED_TABLES = (
    "alembic_version",
    "model_versions",
    "prompt_versions",
)

ALL_TABLES = TENANT_SCOPED_TABLES + TENANT_ROOT_TABLES + SHARED_TABLES

#: Default privileges are held by two grantors in Supabase.  ``postgres`` is
#: always reachable; ``supabase_admin`` may not be, so that part is guarded.
_REVOKE_DEFAULTS = """
DO $$
BEGIN
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
            'REVOKE ALL ON TABLES FROM anon, authenticated';
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
            'REVOKE ALL ON SEQUENCES FROM anon, authenticated';
    BEGIN
        EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public '
                'REVOKE ALL ON TABLES FROM anon, authenticated';
        EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public '
                'REVOKE ALL ON SEQUENCES FROM anon, authenticated';
    EXCEPTION
        -- ``undefined_object`` is raised when the grantor role does not exist at
        -- all (plain PostgreSQL and CI have no ``supabase_admin``);
        -- ``insufficient_privilege`` when it exists but this session may not
        -- alter its default privileges. Both mean "skip this grantor".
        WHEN insufficient_privilege OR undefined_object THEN
            RAISE NOTICE 'Could not alter default privileges for supabase_admin.';
    END;
END
$$;
"""

_GRANT_DEFAULTS = """
DO $$
BEGIN
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
            'GRANT ALL ON TABLES TO anon, authenticated';
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
            'GRANT ALL ON SEQUENCES TO anon, authenticated';
    BEGIN
        EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public '
                'GRANT ALL ON TABLES TO anon, authenticated';
        EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public '
                'GRANT ALL ON SEQUENCES TO anon, authenticated';
    EXCEPTION
        WHEN insufficient_privilege OR undefined_object THEN
            RAISE NOTICE 'Could not restore default privileges for supabase_admin.';
    END;
END
$$;
"""


def upgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated")

    # No policies are created: for anon/authenticated, "RLS on and no policy"
    # means every row is invisible and every write is refused.
    for table in ALL_TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')

    op.execute(_REVOKE_DEFAULTS)


def downgrade() -> None:
    """Restore the previous, exposed state.  Run only to roll back deliberately.

    This re-grants full DML on every public table to ``anon`` and
    ``authenticated`` and disables RLS, which re-opens the Data API.  It exists
    so the change is reversible, not because it is a safe steady state.
    """
    op.execute(_GRANT_DEFAULTS)

    for table in ALL_TABLES:
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')

    for table in ALL_TABLES:
        op.execute(f'GRANT ALL ON TABLE public."{table}" TO anon, authenticated')
    op.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated")
