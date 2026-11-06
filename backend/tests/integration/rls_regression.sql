-- RLS regression checks for the Aetrix public schema.
--
-- Run against a SCRATCH database (or staging) as a role that may SET ROLE,
-- never against production.  Every check states the expected outcome and
-- raises on a mismatch, so a silent permission change fails the run.
--
-- Usage:
--   psql "$AETRIX_TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f rls_regression.sql
--
-- On Supabase, the same assertions can be made over REST with each role's key;
-- this script asserts the database-level outcome that those keys depend on.
--
-- Expected result: "ALL RLS CHECKS PASSED".

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- 0. Preconditions: the lockdown migration must be applied.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    missing text;
BEGIN
    SELECT string_agg(c.relname, ', ')
    INTO missing
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND NOT c.relrowsecurity;

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'FAIL: RLS is not enabled on: %', missing;
    END IF;
    RAISE NOTICE 'PASS: RLS enabled on every public table';
END
$$;

-- ---------------------------------------------------------------------------
-- 1. Anonymous role must be denied read and write on every public table.
-- ---------------------------------------------------------------------------
BEGIN;
SET LOCAL ROLE anon;

DO $$
DECLARE
    target text;
BEGIN
    FOREACH target IN ARRAY ARRAY[
        'users', 'tenants', 'provider_credentials', 'submissions', 'documents',
        'correction_jobs', 'audit_events', 'marking_evidence', 'provider_usage'
    ]
    LOOP
        BEGIN
            EXECUTE format('SELECT count(*) FROM public.%I', target);
            RAISE EXCEPTION 'FAIL: anon SELECT succeeded on public.%', target;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'PASS: anon denied SELECT on public.%', target;
        END;
    END LOOP;
END
$$;

DO $$
BEGIN
    BEGIN
        INSERT INTO public.tenants (id, name, slug, is_active)
        VALUES ('00000000-0000-0000-0000-0000000000ff', 'rls-probe', 'rls-probe', true);
        RAISE EXCEPTION 'FAIL: anon INSERT succeeded on public.tenants';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'PASS: anon denied INSERT on public.tenants';
    END;
END
$$;
ROLLBACK;

-- ---------------------------------------------------------------------------
-- 2. Authenticated role must be denied too (no policies exist yet).
-- ---------------------------------------------------------------------------
BEGIN;
SET LOCAL ROLE authenticated;

DO $$
BEGIN
    BEGIN
        PERFORM count(*) FROM public.provider_credentials;
        RAISE EXCEPTION 'FAIL: authenticated SELECT succeeded on provider_credentials';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'PASS: authenticated denied SELECT on provider_credentials';
    END;

    BEGIN
        UPDATE public.audit_events SET tenant_id = tenant_id;
        RAISE EXCEPTION 'FAIL: authenticated UPDATE succeeded on audit_events';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'PASS: authenticated denied UPDATE on audit_events';
    END;

    BEGIN
        DELETE FROM public.audit_events;
        RAISE EXCEPTION 'FAIL: authenticated DELETE succeeded on audit_events';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'PASS: authenticated denied DELETE on audit_events';
    END;
END
$$;
ROLLBACK;

-- ---------------------------------------------------------------------------
-- 3. Cross-tenant read must be impossible for an authenticated caller.
--    With no policies this is denied outright; once tenant policies exist this
--    check should assert "0 rows" instead of "denied".
-- ---------------------------------------------------------------------------
BEGIN;
SET LOCAL ROLE authenticated;
DO $$
BEGIN
    BEGIN
        PERFORM count(*) FROM public.tenants
        WHERE id <> '00000000-0000-0000-0000-0000000000fe'::uuid;
        RAISE EXCEPTION 'FAIL: authenticated cross-tenant read succeeded';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'PASS: authenticated cross-tenant read denied';
    END;
END
$$;
ROLLBACK;

-- ---------------------------------------------------------------------------
-- 4. The engine connection (table owner) and service_role must still work.
--    This is the "did we break the application" check.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT count(*) INTO n FROM public.users;
    RAISE NOTICE 'PASS: owner connection can read public.users (% rows)', n;

    SELECT count(*) INTO n FROM public.tenants;
    SELECT count(*) INTO n FROM public.audit_events;
    SELECT count(*) INTO n FROM public.provider_credentials;
    RAISE NOTICE 'PASS: owner connection can read every audited table';
END
$$;

BEGIN;
SET LOCAL ROLE service_role;
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT count(*) INTO n FROM public.users;
    RAISE NOTICE 'PASS: service_role can read public.users (% rows)', n;
END
$$;
ROLLBACK;

-- ---------------------------------------------------------------------------
-- 5. No lingering grants: default privileges must not re-open the schema.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    offenders text;
BEGIN
    SELECT string_agg(DISTINCT c.relname, ', ')
    INTO offenders
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND (
          has_table_privilege('anon', c.oid, 'SELECT')
          OR has_table_privilege('anon', c.oid, 'INSERT')
          OR has_table_privilege('anon', c.oid, 'UPDATE')
          OR has_table_privilege('anon', c.oid, 'DELETE')
          OR has_table_privilege('authenticated', c.oid, 'SELECT')
          OR has_table_privilege('authenticated', c.oid, 'INSERT')
          OR has_table_privilege('authenticated', c.oid, 'UPDATE')
          OR has_table_privilege('authenticated', c.oid, 'DELETE')
      );

    IF offenders IS NOT NULL THEN
        RAISE EXCEPTION 'FAIL: anon/authenticated still hold DML on: %', offenders;
    END IF;
    RAISE NOTICE 'PASS: no anon/authenticated table privileges remain';
END
$$;

DO $$
BEGIN
    RAISE NOTICE 'ALL RLS CHECKS PASSED';
END
$$;
