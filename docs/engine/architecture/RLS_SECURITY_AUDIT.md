# RLS Security Audit — `rls_disabled_in_public`

**Project:** `wswsibspyjrhlahxcefs` (`aetrix-v5.5-dev`, `eu-west-2`, PostgreSQL 17.11)
**Audited:** 2026-11-06
**Scope:** all `public` relations, the Data API surface, and the `/auth/v1/token?grant_type=password` failures
**Status:** audit complete, remediation prepared, **not applied**

---

## 1. Summary

| Question | Answer |
|---|---|
| Tables with RLS disabled | **29 of 29** in `public` (report lists 28; see §3) |
| Policies in `public` | **0** |
| `anon` privileges | **full DML on every table** (`SELECT, INSERT, UPDATE, DELETE` + `TRUNCATE`) |
| `authenticated` privileges | **full DML on every table** |
| Data API reachable | **Yes** — PostgREST 14.18 connected as `authenticator`, `LISTEN "pgrst"` |
| Engine broken by enabling RLS | **No** — `postgres` and `service_role` both have `BYPASSRLS` |
| Evidence of exploitation | none found, but no API request logs exist to prove absence |
| Auth 500 caused by disabled RLS | **No** — ruled out by evidence, see §7 |

The finding is a **live, unauthenticated read/write path to every business table**, not a
style warning. It is also fully reversible to fix, because the engine never uses the Data
API.

---

## 2. Method

Read-only catalogue queries only (`pg_class`, `pg_policies`, `has_table_privilege`,
`pg_constraint`, `pg_indexes`, `pg_default_acl`, `pg_roles`, `pg_stat_activity`). No DDL,
no DML, no user records touched, no credentials read.

Application side: `backend/` (FastAPI + SQLAlchemy, connects directly with the `postgres`
role), `frontend/` (TanStack Start marketing surface; `package.json` contains no Supabase
client and `src/` issues no `fetch`).

---

## 3. Why the report says 28 and the database has 29

`public` contains 29 ordinary tables and **all 29** have `relrowsecurity = false`. The
Security Advisor's `rls_disabled_in_public` lint reports 28. The one-table difference is
`alembic_version`, the migration bookkeeping table: it has no application meaning and is
the only table whose exposure carries no data risk. Every table named in the report is
covered by this audit and by migration `0005_rls_lockdown`; `alembic_version` is locked
down too so the count cannot drift later.

---

## 4. Role and privilege model (observed)

| Role | Superuser | `BYPASSRLS` | Can login | Notes |
|---|---:|---:|---:|---|
| `postgres` | no | **yes** | yes | Table owner; the engine's connection role |
| `service_role` | no | **yes** | no | Trusted server-side key role |
| `supabase_admin` | yes | yes | yes | Platform administration |
| `authenticator` | no | no | yes | PostgREST login role; `SET ROLE` to `anon`/`authenticated` |
| `anon` | no | no | no | Unauthenticated Data API role |
| `authenticated` | no | no | no | Signed-in Data API role |
| `supabase_auth_admin` | no | no | yes | **Owns** the `auth` tables |

Table ACL on every audited table
(`users`, `tenants`, `provider_credentials`, `submissions`, `documents`, `correction_jobs`,
`audit_events`, `marking_evidence`, and the rest):

```
{postgres=arwdDxtm/postgres,
 anon=arwdDxtm/postgres,
 authenticated=arwdDxtm/postgres,
 service_role=arwdDxtm/postgres}
```

`arwdDxtm` includes `D` (TRUNCATE) and `t` (TRIGGER). Default privileges for **future**
tables are equally permissive and are held by two grantors, `postgres` and
`supabase_admin` — so every table ever created by a migration was exposed automatically.

---

## 5. Table audit

Sensitivity: **C** critical, **H** high, **M** medium, **L** low. Rows are exact where a
count was taken, otherwise the planner estimate.

### 5.1 Tenant-scoped tables (25, `tenant_id` FK → `tenants.id`)

| Table | Data | Sens. | Rows | Intended reader | Intended writer |
|---|---|---|---|---|---|
| `users` | subject (= auth uid), **email**, role, display name | **C** | 4 | Engine; tenant admins | Engine |
| `provider_credentials` | **encrypted API key**, fingerprint, health | **C** | 0 | Engine only | Engine only |
| `submissions` | student reference, status | **H** | 0 | Engine; tenant staff | Engine |
| `documents` | storage path, kind, exam/submission link | **H** | 0 | Engine; tenant staff | Engine |
| `document_pages` | rendered page assets, quality | **H** | 0 | Engine; tenant staff | Engine |
| `correction_jobs` | job state, idempotency key | **H** | 0 | Engine; tenant staff | Engine |
| `job_events` | append-only job state trail | **H** | 0 | Engine; tenant staff | Engine (insert only) |
| `audit_events` | actor, action, content hashes, request id | **H** | 46 | Engine; auditors | Engine (insert only) |
| `marking_evidence` | page/region quotes used to justify a mark | **H** | 0 | Engine; reviewers | Engine |
| `question_results` | per-question marks | **H** | 0 | Engine; tenant staff | Engine |
| `criterion_results` | per-criterion marks | **H** | 0 | Engine; reviewers | Engine |
| `verification_results` | SymPy/verifier outcomes | **H** | 0 | Engine; reviewers | Engine |
| `review_decisions` | human review outcomes | **H** | 0 | Engine; reviewers | Reviewers |
| `learning_feedback` | approved feedback text | **H** | 0 | Engine; tenant staff | Staff |
| `provider_usage` | token counts, cost, credential link | **H** | 0 | Engine; finance | Engine (insert only) |
| `provider_quota_reservations` | quota holds, expiry | M | 0 | Engine | Engine |
| `exams` | title, board, paper code | M | 0 | Engine; tenant staff | Staff |
| `exam_blueprint_versions` | canonical paper structure | M | 0 | Engine; tenant staff | Staff (immutable when approved) |
| `mark_schemes` | scheme title/exam link | M | 0 | Engine; tenant staff | Staff |
| `mark_scheme_versions` | scheme content, approval | M | 0 | Engine; tenant staff | Staff |
| `marking_criteria` | criterion definitions and marks | M | 0 | Engine; reviewers | Staff |
| `assignments` | exam/scheme bundle, thresholds | M | 0 | Engine; tenant staff | Staff |
| `page_question_mappings` | page → question mapping | M | 0 | Engine; staff | Engine/staff |
| `blueprint_overrides` | approved deviations, author | M | 0 | Engine; staff | Staff |
| `cohort_analyses` | aggregate cohort statistics | M | 0 | Engine; staff | Engine |

### 5.2 Tenant root (1)

| Table | Data | Sens. | Rows | Intended reader | Intended writer |
|---|---|---|---|---|---|
| `tenants` | workspace name, slug, active flag | **H** | 3 | Engine; platform admin | Engine/platform admin |

Tenant IDs are the isolation boundary; leaking the full tenant list enables targeted
enumeration of every other table.

### 5.3 Shared / reference (3)

| Table | Data | Sens. | Rows | Intended reader | Intended writer |
|---|---|---|---|---|---|
| `model_versions` | provider model ids, role | L | 0 | Engine; staff | Engine |
| `prompt_versions` | prompt ids, versions, hashes | L | 0 | Engine; staff | Engine |
| `alembic_version` | migration head | L | 1 | Operators | Alembic only |

### 5.4 Ownership relationships (observed)

- `users.tenant_id` → `tenants.id` (CASCADE).
- `users.subject` holds the Supabase auth uid. **3 of 4** app users' `subject` matches
  `auth.users.id` by text; 1 does not (a seeded/test identity).
- 25 tables carry `tenant_id` → `tenants.id` (CASCADE).
- Actor columns point at `users.id`: `created_by` (exams, assignments, blueprint
  versions), `author_id` (blueprint overrides), `approved_by` (blueprint versions,
  learning feedback).
- 82 FK/unique constraints and 81 indexes exist; every `tenant_id` is indexed, which keeps
  a future tenant predicate cheap.

---

## 6. RLS policy matrix

**Design decision.** The API has no legitimate consumer in this repository: the engine
uses a direct `postgres` connection that bypasses RLS, and the frontend has no Supabase
client. Therefore the correct policy for `anon` and `authenticated` today is **deny**, and
the correct fix is privilege revocation plus RLS as defence in depth — not a permissive
policy written to silence the advisor.

Legend: **D** = denied (no privilege and/or no policy), **B** = allowed by `BYPASSRLS`.

| Table | Engine (`postgres`) | `service_role` | `anon` | `authenticated` | Future Data API policy |
|---|---|---|---|---|---|
| `users` | B | B | D | D | own row only, or tenant staff |
| `tenants` | B | B | D | D | own tenant only |
| `provider_credentials` | B | B | D | D | **never** — server-side only |
| `provider_usage` | B | B | D | D | tenant staff, SELECT |
| `provider_quota_reservations` | B | B | D | D | **never** — server-side only |
| `submissions` | B | B | D | D | tenant-scoped, role-gated |
| `documents` | B | B | D | D | tenant-scoped, role-gated |
| `document_pages` | B | B | D | D | tenant-scoped, role-gated |
| `correction_jobs` | B | B | D | D | tenant-scoped, role-gated |
| `job_events` | B | B | D | D | tenant-scoped, SELECT |
| `audit_events` | B | B | D | D | tenant-scoped, SELECT (auditors) |
| `marking_evidence` | B | B | D | D | tenant-scoped, SELECT (reviewers) |
| `question_results` | B | B | D | D | tenant-scoped, SELECT |
| `criterion_results` | B | B | D | D | tenant-scoped, SELECT |
| `verification_results` | B | B | D | D | tenant-scoped, SELECT |
| `review_decisions` | B | B | D | D | tenant-scoped, reviewer write |
| `learning_feedback` | B | B | D | D | tenant-scoped, staff write |
| `exams` | B | B | D | D | tenant-scoped, staff |
| `exam_blueprint_versions` | B | B | D | D | tenant-scoped, staff |
| `mark_schemes` | B | B | D | D | tenant-scoped, staff |
| `mark_scheme_versions` | B | B | D | D | tenant-scoped, staff |
| `marking_criteria` | B | B | D | D | tenant-scoped, staff |
| `assignments` | B | B | D | D | tenant-scoped, staff |
| `page_question_mappings` | B | B | D | D | tenant-scoped, staff |
| `blueprint_overrides` | B | B | D | D | tenant-scoped, staff |
| `cohort_analyses` | B | B | D | D | tenant-scoped, staff |
| `model_versions` | B | B | D | D | authenticated SELECT |
| `prompt_versions` | B | B | D | D | **never** — server-side only |
| `alembic_version` | B | B | D | D | **never** — server-side only |

Required operations per table under the current (no-client) model: **no** SELECT, INSERT,
UPDATE or DELETE policy for `anon` or `authenticated`. Inserts and updates continue to
happen through the engine connection, where the existing database guards still apply
(append-only triggers on `audit_events`, `job_events`, `provider_usage`; approved-blueprint
immutability). Nothing in this change alters those triggers.

---

## 7. Security exposure assessment

**What an `anon` caller could do before the fix.** With the project URL and the public
`anon` key, PostgREST would execute as `anon`, which holds full DML, on tables with RLS
disabled:

- `GET /rest/v1/users?select=email,subject,role,tenant_id` — every account's email and
  Supabase subject id.
- `GET /rest/v1/tenants` — the complete workspace list.
- `GET /rest/v1/provider_credentials` — ciphertext, fingerprint, health, model access.
- `GET /rest/v1/submissions`, `documents`, `marking_evidence`, `question_results` — student
  references, storage paths, evidence quotes and marks as those tables fill.
- `DELETE /rest/v1/audit_events`, `DELETE /rest/v1/provider_usage` — the append-only
  triggers block `UPDATE` only; **`DELETE` was permitted**, so the audit trail could be
  destroyed.
- `PATCH`/`POST` on `users`/`tenants` — role escalation by rewriting `users.role`, since
  the engine trusts the stored role rather than the token.

**Severity qualifiers, stated precisely.**

- Provider API keys are **not** directly recoverable: `encrypted_secret` is a Fernet token
  and the key lives in `AETRIX_SECURITY__ENCRYPTION_KEY`, not in the database. What leaks
  is the credential inventory, fingerprints and account labels; combined with a leaked
  encryption key elsewhere the ciphertext would complete the chain.
- The data at risk today is small: 4 users, 3 tenants, 46 audit events, and every
  marking/submission table empty. This is a development project.
- **No evidence of exploitation** was found. It cannot be ruled out: the project has no
  API request logging (`audit_log_disable_postgres = true`, no log drain), so requests to
  PostgREST are not recorded anywhere this audit can read.

**Why it happened.** Tables are created by Alembic running as `postgres`, and the
project's default privileges grant `anon`/`authenticated` full DML on newly created
tables. RLS was never enabled afterwards, because the engine was designed around a direct
connection (`docs/engine/architecture/SECURITY.md` §4 states RLS is not the primary
control). That reasoning is sound for the engine but did not account for the Data API
being exposed by default.

---

## 8. Authentication 500 investigation (`/auth/v1/token?grant_type=password`)

**Conclusion: disabled RLS in `public` is not the cause, and neither is RLS on `auth`.**

| Check | Evidence | Verdict |
|---|---|---|
| Custom triggers on `auth.*` | none exist (only 4 non-internal triggers in the database, all `BEFORE UPDATE` guards in `public`) | ruled out |
| `auth` table RLS blocking GoTrue | `auth.users`, `sessions`, `refresh_tokens`, `identities`, `one_time_tokens` have RLS enabled **but are owned by `supabase_auth_admin`** and are not `FORCE`d, so the owner bypasses RLS | ruled out |
| Grants for GoTrue | `supabase_auth_admin` holds SELECT+INSERT on every `auth` table | healthy |
| Policies in `auth` | zero — consistent with owner-bypass design, not a fault | not the cause |
| Password grants succeeding | **55 sessions** and 55 refresh tokens across all 3 users between 02:09 and 02:55 UTC; 0 expired | endpoint works; failures are intermittent |
| Deadlocks / lock waits | `deadlocks = 0`; no blocked or long-running client queries at audit time | not a lock issue |
| Rollback ratio | 832 rollbacks / 74 299 commits (≈1.1%) over the instance lifetime | consistent with a few failed statements, not conclusive |
| Auth error text | `audit_log_disable_postgres = true`, `auth.audit_log_entries` empty, no log drain configured | **not recoverable from SQL** |

**Load pattern worth noting.** One user accumulated **37 sessions in 46 minutes** — roughly
one sign-in every 75 seconds — and another 11 in 7 minutes. That is an automated re-login
loop, not human behaviour, and it coincides with the reported 500s.

**Ranked hypotheses (unconfirmed).**

1. **Session/refresh churn race.** Concurrent password grants for the same user create
   `auth.sessions` + `auth.refresh_tokens` rows; rotation is enabled with a 10 s reuse
   interval. A burst can collide on `refresh_tokens_token_unique` or the session FK and
   surface as a GoTrue 500 rather than a 4xx.
2. **Transient connection/timeout failure under the burst.** `authenticator` runs with
   `statement_timeout = 8s`; `supabase_auth_admin` with a 60 s idle-in-transaction
   timeout. A pooler hiccup during a burst yields a database error surfaced as 500.
3. **Deployment/restart of the Auth container** during the test window (project was
   created the previous day).

Ruled out as causes: disabled RLS, missing grants, broken triggers, deadlocks, rate
limiting (which returns 429), and malformed client input (400).

**What is needed to close this out.** The definitive message is only in Auth logs:
Dashboard → *Logs → Auth* (or an enabled log drain), filtered to
`/token?grant_type=password` with status 500 — the response body carries GoTrue's
`error` / `error_description`, and the timestamp pattern will confirm or kill hypothesis 1.
Until that is read, no fix should be attempted: the endpoint is demonstrably working.

**Mitigation that is safe regardless.** Do not poll `/token?grant_type=password` in a loop;
reuse a session and refresh via `grant_type=refresh_token`, and add a single-flight token
refresh in the client once one exists. No production auth setting needs to change.

---

## 9. Proposed migration (`0005_rls_lockdown`)

Applied only after approval. It is transactional, idempotent and reversible.

1. `REVOKE ALL ON TABLE public.<t> FROM anon, authenticated` for all 29 tables.
2. `REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated`.
3. `ALTER TABLE public.<t> ENABLE ROW LEVEL SECURITY` for all 29 tables, **no policies**.
4. Revoke the default privileges held by `postgres` (and `supabase_admin` where
   permitted) so future tables are not auto-granted.

Deliberately **not** done:

- **No `FORCE ROW LEVEL SECURITY`.** `postgres` owns the tables and must keep bypassing
  RLS for the engine's direct connection. Forcing it would break every query.
- **No permissive policies.** There is no Data API client to serve.
- **No `service_role` changes.** It keeps `BYPASSRLS` for trusted server-side use.
- **No schema `USAGE` revoke.** Table-level denial already closes the path, and keeping
  `USAGE` avoids surprising platform tooling.

**Functional impact.** None expected. The API and worker connect as `postgres`
(`BYPASSRLS`); repositories already scope every query by `tenant_id` in code; no code path
uses PostgREST, the anon key or the service-role key.

**Performance impact.** RLS adds a predicate only for roles that do not bypass it, i.e.
roles that can no longer reach these tables at all. The engine's query plans are
unchanged.

> **Blocking precondition — resolved.** Staging first found that the project's
> `alembic_version` was `0004_audit_actor_label` while this repository's head was
> `0002_blueprint_guard_fix`, and that the live schema carried columns the models did not
> define (`audit_events.actor_label`, `tenants.is_demo`). The revision chain in this
> repository was simply behind the deployed one: `0003_identity_demo_tenants` and
> `0004_audit_actor_label` were authored on the unmerged
> `aetrix/v5.5-consolidation` branch. Both revisions have now been recovered into this
> branch verbatim, the two columns are back in `backend/app/db/models.py`, and the
> lock-down was renumbered from `0003` to **`0005_rls_lockdown`** and re-parented onto
> `0004_audit_actor_label`. The chain is now linear and matches the deployed database:
> `5828eae7d57d → 0001_append_only_guards → 2c331690c5f0 → 0002_blueprint_guard_fix`
> `→ 0003_identity_demo_tenants → 0004_audit_actor_label → 0005_rls_lockdown` (head).
> Neither recovered revision creates a table or changes a privilege, so the SQL in this
> migration is unchanged by the rebase and the two new columns land on tables already
> covered by `ALL_TABLES`. Still never stamp `alembic_version` by hand.

### Deployment plan

1. **Staging first.** Apply to a disposable/staging database, run
   `backend/tests/integration/rls_regression.sql`, then run the backend suite against it.
2. **Snapshot.** Take a Supabase backup/PITR checkpoint before production.
3. **Apply** `alembic upgrade head` in a maintenance window; it is a metadata-only change
   and takes seconds.
4. **Verify** — `anon`/`authenticated` denied (script §1–§5), engine `/ready` 200, one
   authenticated API request per role succeeds, worker claims/park a job.
5. **Watch** the next password grant and one registration for the 500 pattern from §8.
6. **Enable a log drain** so future auth and API errors are diagnosable.

### Rollback plan

- Preferred: `alembic downgrade -1` — restores grants, default privileges and disables
  RLS. It re-opens the exposure, so only use it if the lockdown breaks something.
- Immediate manual unblock (no data loss):
  `GRANT SELECT ON public.<t> TO authenticated;` and add the specific policy needed,
  rather than disabling RLS wholesale.
- If a table must be temporarily re-exposed for a legitimate client, add a **policy**, not
  a blanket grant, and record why.
- No downgrade touches user rows, marks or audit content.

---

## 10. Regression testing

`backend/tests/integration/rls_regression.sql` asserts, with `ON_ERROR_STOP`:

1. every `public` table has RLS enabled;
2. `anon` is denied SELECT on nine representative tables and denied INSERT;
3. `authenticated` is denied SELECT on `provider_credentials`, UPDATE and DELETE on
   `audit_events`, and cross-tenant reads;
4. the owner connection and `service_role` can still read (the "did we break the app"
   check);
5. no `anon`/`authenticated` table privileges remain.

**CI guard.** `backend/tests/integration/test_rls_guard.py` asserts these properties
globally rather than against the migration's table list: every table in `public` must have
RLS enabled, `anon` and `authenticated` must hold no table or sequence privilege, and the
schema's default privileges must not re-grant them on future objects. The `rls-guard` job
in `.github/workflows/ci.yml` provisions PostgreSQL 17, creates the Data API roles and
reproduces Supabase's default grants **before** `alembic upgrade head`, so the check fails
if a later migration adds a table without RLS, grants on one, or restores the defaults —
including when the lock-down itself is removed.

**Execution status.** Executed 2026-11-06 against a disposable PostgreSQL instance. No
hosted staging project exists — the organisation has a single Supabase project,
`aetrix-v5.5-dev` — so the migration was applied to a throwaway database rebuilt from the
SQLAlchemy metadata (28 model tables plus `alembic_version` = 29) with the `anon`,
`authenticated`, `service_role` and `supabase_admin` roles and Supabase's default grants
reproduced **before** applying the migration.

After the rebase described in §9 the run was repeated from the repository's `0002`-era
schema dump (still 29 tables including `alembic_version`), applying the recovered
`0003_identity_demo_tenants` → `0004_audit_actor_label` → `0005_rls_lockdown` chain in
order. The verified path is therefore exactly what `alembic upgrade head` performs on a
database at `0002`.

| Check | Result |
|---|---|
| Baseline exposure reproduced (RLS off; `anon` selects 29/29 and inserts on 29/29) | pass |
| Recovered chain applied in order: `0003_identity_demo_tenants` → `0004_audit_actor_label` → `0005_rls_lockdown` | pass |
| `0003` sets `tenants.is_demo = false` for existing rows; `0004` backfills `audit_events.actor_label` from `display_name` then `email`, leaving departed and non-`USER` actors null | pass |
| Regression script, all five sections | pass |
| Second upgrade (idempotency) | pass |
| `0005` downgrade restores grants and disables RLS; `0004`/`0003` downgrades drop their columns | pass |
| Re-upgrade, then regression again | pass |
| Post-state | 29/29 RLS on, 0 policies, `anon` SELECT 0/29 and INSERT 0/29, engine and `service_role` still read/write |
| Live Supabase project after the run | unchanged: 0 RLS, 0 policies, `anon` insert 29/29 |

Caveats: the test instance reports PostgreSQL 18.6 (the project runs 17.11) — RLS
semantics are identical but the version differs; the schema came from SQLAlchemy metadata
rather than the project's exact DDL; and this is a local disposable database, not
Supabase-hosted staging, so `supabase_admin`'s default-privilege branch and PostgREST
authorisation were exercised only at the SQL layer, not over HTTP.

---

## 11. Remaining risks and follow-ups

1. **`supabase_admin` default privileges.** If the migration's guarded block cannot alter
   them, a future table could be granted to `anon`/`authenticated` again. Verify with
   `SELECT * FROM pg_default_acl` after applying; fix in the dashboard if needed.
2. **GraphQL surface.** `graphql` and `graphql_public` also exist with permissive default
   grants from `supabase_admin`; `public` is not exposed there today, but the same default
   privilege review applies.
3. **Storage buckets** were out of scope for this audit; bucket policies need their own
   review before any document upload leaves the local filesystem adapter.
4. **No API/Auth request logging.** Historical exploitation cannot be ruled out and the
   §8 500s cannot be diagnosed until a log drain is enabled.
5. **Future browser client.** If one is added, it will need tenant-scoped policies — see
   Appendix A — plus the role mapping that already exists in `public.users`.
6. **`users.email` contains real-looking addresses on an undelegable domain.** Unrelated to
   RLS, but it is PII in a table that was publicly readable, so it is noted here.

---

## Appendix A — draft tenant policies (NOT applied)

Only for the day a browser-side client exists. Not part of migration `0003`.

```sql
create or replace function public.aetrix_current_tenant_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select u.tenant_id
    from public.users u
    where u.subject = (select auth.uid()::text)
    limit 1
$$;

revoke all on function public.aetrix_current_tenant_id() from public, anon;
grant execute on function public.aetrix_current_tenant_id() to authenticated;

-- Example: read-only, tenant-scoped, role-gated access to exam metadata.
create policy exams_tenant_read on public.exams
    for select to authenticated
    using (
        tenant_id = public.aetrix_current_tenant_id()
        and exists (
            select 1 from public.users u
            where u.subject = (select auth.uid()::text)
              and u.tenant_id = exams.tenant_id
        )
    );
```

`provider_credentials`, `prompt_versions` and `alembic_version` must never receive a
policy for `anon` or `authenticated`.
