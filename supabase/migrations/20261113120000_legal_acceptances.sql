-- Legal acceptance records for the Aetrix pilot.
--
-- WHY THIS IS NOT AN ALEMBIC REVISION
-- The engine owns its own schema through Alembic, but its committed head is
-- 0025_job_recovery_link while the deployed database is already at
-- 0026_scheme_criteria_approval, a revision that exists only in uncommitted
-- engine work. A new revision added here would either have to name a revision
-- that is not in the repository, or create a second head in the engine's
-- migration chain and break `alembic upgrade head` and the engine test suite.
-- Both would entangle this legal feature with the unfinished correction engine.
--
-- This table is not engine data: nothing in `backend/` reads or writes it. It is
-- written only by the signed-in browser through the Supabase Data API, and its
-- access rules are enforced by the RLS policies below, not by the client.
--
-- Apply (idempotent) as the database owner:
--   psql "$AETRIX_DATABASE_URL" -f supabase/migrations/20261113120000_legal_acceptances.sql
--
-- It only creates a new table, a trigger and policies. It does not alter or
-- delete any existing row or table.

create table if not exists public.legal_acceptances (
  id uuid primary key default gen_random_uuid(),
  -- The identity provider's user id (auth.uid()), i.e. the account the
  -- acceptance belongs to. It is deliberately not the engine's workspace user
  -- id: acceptance follows a person across workspaces and devices.
  user_id uuid not null,
  document_type text not null,
  document_version text not null,
  accepted_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint legal_acceptances_document_type_format
    check (document_type ~ '^[a-z][a-z0-9_]{2,39}$'),
  constraint legal_acceptances_document_version_format
    check (document_version ~ '^[0-9]{1,3}\.[0-9]{1,3}(\.[0-9]{1,3})?$'),
  -- One record per person, document and version. A retried write, a second tab
  -- or a second device cannot create a duplicate.
  constraint uq_legal_acceptances_user_document_version
    unique (user_id, document_type, document_version)
);

comment on table public.legal_acceptances is
  'Explicit legal document acceptances. Append-only: rows are never updated.';
comment on column public.legal_acceptances.user_id is
  'Supabase auth user id (auth.uid()) that accepted the document.';
comment on column public.legal_acceptances.accepted_at is
  'Server-generated acceptance time; a client cannot supply it.';

-- The timestamp is the server's, not the caller's. Even if a column privilege
-- were widened later, the trigger overwrites whatever the insert supplied.
create or replace function public.legal_acceptances_stamp()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.accepted_at := now();
  new.created_at := now();
  return new;
end;
$$;

drop trigger if exists trg_legal_acceptances_stamp on public.legal_acceptances;
create trigger trg_legal_acceptances_stamp
  before insert on public.legal_acceptances
  for each row execute function public.legal_acceptances_stamp();

-- An acceptance is evidence of what a person agreed to and when. Rewriting it
-- would destroy that evidence, so an update is refused at the table.
create or replace function public.legal_acceptances_immutable()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  raise exception 'legal_acceptances rows are append-only'
    using errcode = 'restrict_violation';
end;
$$;

drop trigger if exists trg_legal_acceptances_immutable on public.legal_acceptances;
create trigger trg_legal_acceptances_immutable
  before update on public.legal_acceptances
  for each row execute function public.legal_acceptances_immutable();

-- Access control. 0005_rls_lockdown revoked every Data API grant, so this table
-- grants back only what the flow needs: read your own records, insert your own
-- records, and nothing else.
alter table public.legal_acceptances enable row level security;

revoke all on table public.legal_acceptances from anon, authenticated;
revoke all on table public.legal_acceptances from public;

grant select on table public.legal_acceptances to authenticated;
-- Column-level insert: a caller may name the document and version, but cannot
-- supply an id or a timestamp. Accepted time is therefore always the server's.
grant insert (user_id, document_type, document_version)
  on table public.legal_acceptances to authenticated;

drop policy if exists legal_acceptances_select_own on public.legal_acceptances;
create policy legal_acceptances_select_own
  on public.legal_acceptances
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists legal_acceptances_insert_own on public.legal_acceptances;
create policy legal_acceptances_insert_own
  on public.legal_acceptances
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

-- No update policy, no delete policy and no such grants: a signed-in user
-- cannot rewrite or erase their acceptance history to bypass the gate.
