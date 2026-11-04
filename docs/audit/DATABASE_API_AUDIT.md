# Database and API Audit

**Audit date:** 2026-11-03. The schema and the API surface were checked against each other, against the
permission matrix, against the screen inventory, and against D1's documented behaviour. Originals unchanged.

## Part A — Database

### DB-01 — HIGH — The identity schema does not match Better Auth's required schema
**Documents:** `DATABASE_DESIGN.md` §3, `ARCHITECTURE_DECISIONS.md` ADR-005.

**Problem.** The package defines `users(id, email, password_hash, mfa_secret, mfa_enabled, …)` and
`memberships(...)`. Better Auth does not work that way: it stores credentials in an **`account`** table
(provider `credential` holds the password hash), passkeys in a **`passkey`** table, 2FA secrets in a **`twoFactor`**
table, email verification/recovery in a **`verification`** table, and organization membership in **`member`**
keyed by `organizationId`, with `activeOrganizationId` on the session. None of these appear, and
`users.password_hash` / `mfa_secret` are columns Better Auth will not read.

**Evidence.** Better Auth schema and organization-plugin docs (2026): required tables `user`, `session`,
`account`, `verification`, plus plugin tables; email/password is an `account` row, not a column on `user`.

**Consequence.** P2 either (a) writes a hand-rolled auth implementation, discarding ADR-005's whole rationale, or
(b) reconciles two schemas under time pressure, most likely by duplicating identity rows — which then drift, and
the drift is a security bug (stale membership, orphaned session, a user who exists twice).

**Resolution.** Make Better Auth's tables the canonical identity model and map product concepts onto them
(`workspaces` ↔ `organization`, `memberships` ↔ `member`). Record the mapping table in
`DATABASE_DESIGN.md`; add `account`, `verification`, `passkey`, `twoFactor` to the catalogue. Keep `users` only
as a view or accept Better Auth's `user` naming and update the API layer.

**Owner approval:** Required — it changes the schema contract.

### DB-02 — HIGH — No table exists for workspace API keys, which the API and permission model both require
**Documents:** `API_DESIGN.md` §1, `USER_ROLES_AND_PERMISSIONS.md` §5 rule 6, `DATABASE_DESIGN.md` §3–§5.

**Problem.** The API accepts `Authorization: Bearer mc_…` with explicit scopes and states that such keys can
never manage members, credentials or delete. The permission document repeats the rule. There is **no
`api_keys` table** in any catalogue — no `id`, `workspace_id`, `key_hash`, `scopes`, `created_by`, `last_used_at`,
`revoked_at`.

**Consequence.** Either the feature is dropped late (breaking the "never a role-bearing key" control and pushing
customers to user sessions), or it is implemented ad hoc with the key stored in plaintext or without scope, which
is the privilege-escalation path the rule was written to prevent.

**Resolution.** Add `api_keys(id, workspace_id, label, key_hash UNIQUE, scopes_json, created_by, last_used_at,
expires_at, revoked_at)`, with only a hash stored, scopes validated against the permission vocabulary, and a test
that a key cannot call member/credential/delete routes.

**Owner approval:** Required.

### DB-03 — HIGH — Tenant consistency is a convention, not a constraint
**Documents:** `MULTI_TENANCY.md` §3 rule 5, `DATABASE_DESIGN.md` §5.

**Problem.** Child rows "assert equality on insert" in application code. SQLite has no cross-table CHECK, but it
does have `BEFORE INSERT`/`BEFORE UPDATE` triggers that can `RAISE(ABORT)`. None are specified, and the isolation
suite cannot catch the resulting row (see SEC-05).

**Resolution.** Add triggers on `submissions`, `results`, `question_results`, `assignment_questions`,
`mark_schemes`, `submission_files`, `overrides`, `comments`, `jobs`, `job_attempts`, `automation_operations`,
`enrollments`, `classroom_links` asserting the parent belongs to `NEW.workspace_id`. Add one test per table.

**Owner approval:** Not required.

### DB-04 — HIGH — Soft delete collides with every workspace-scoped unique constraint
**Documents:** `DATABASE_DESIGN.md` §1 §5, `ARCHITECTURE_DECISIONS.md` ADR-012.

**Problem.** `submissions` has `UNIQUE(ws, assignment_id, student_id)` and `deleted_at`; `memberships` has
`UNIQUE(ws, user_id)` and a `status`; `classes` sets `archived_at`. SQLite unique indexes include soft-deleted
rows. A student whose script was deleted cannot be re-uploaded; a removed member cannot be re-invited; a class
cannot be re-created with the same name if name is unique.

**Consequence.** Runtime 500s on a legitimate workflow (re-upload after a bad scan, re-invite after a staffing
change) that appear only in production, and are usually "fixed" by hard-deleting rows — defeating the entire
reason for soft delete.

**Resolution.** Convert to partial unique indexes: `UNIQUE(ws, assignment_id, student_id) WHERE deleted_at IS
NULL`, and the equivalent on `memberships` (`WHERE status != 'removed'`). SQLite supports this directly.

**Owner approval:** Not required.

### DB-05 — HIGH — Nothing at the database level prevents a mark above the maximum
**Documents:** `DATABASE_DESIGN.md` §1, `USER_JOURNEYS.md` J4, `ACCEPTANCE_CRITERIA.md` §2.

**Problem.** §1 says "enumerations are `TEXT` with a `CHECK` constraint, so a typo fails at write time", and the
product's central promise is that a mark can never exceed the question's maximum. But `question_results` has no
`CHECK (awarded >= 0 AND awarded <= max_marks)`, and `overrides` has none either. The guard is described as
client- and server-side (`J4`), i.e. application-only.

**Consequence.** The single invariant the product sells — no impossible mark — is enforced in the one place that
a future endpoint, migration, importer or manual fix can bypass. `ACCEPTANCE_CRITERIA.md` §2 asks for a test
proving persistence is impossible; with no constraint, that test can only prove the current handler checks it.

**Resolution.** Add `CHECK (awarded >= 0 AND awarded <= max_marks)` to `question_results`, and
`CHECK (to_marks >= 0)` plus a trigger validating against the question's max in `overrides`. Keep the API check
as well; this is defence in depth, not duplication.

**Owner approval:** Not required.

### DB-06 — MEDIUM — Two uniqueness constraints are global where they should be workspace-scoped
**Documents:** `DATABASE_DESIGN.md` §5.

`results(id, ws, submission_id fk UNIQUE, …)` and `submission_files(id, ws, submission_id fk, r2_key UNIQUE, …)`.
A global UNIQUE is harmless for UUID keys but signals the wrong tenancy model: it means two workspaces can never
hold the same logical key, and it forecloses ever re-importing a submission id from another tenant. Make them
`UNIQUE(ws, submission_id)` and `UNIQUE(ws, r2_key)` for consistency with every other table.

**Resolution.** Rewrite as composite constraints. **Owner approval:** Not required.

### DB-07 — MEDIUM — Metering can double-count, and the rollup has no idempotency rule
**Documents:** `DATABASE_DESIGN.md` §5, `OPERATIONS/COST_AND_SCALABILITY.md` §5, ADR-009.

`usage_events(id, ws, kind, quantity, unit, job_id, occurred_at)` is append-only with no uniqueness. Queues are
at-least-once and Workflow steps retry, so the same provider call can be metered twice — corrupting the only
dataset pricing will ever be derived from. `usage_daily` has `UNIQUE(ws, day, kind)` but no stated upsert
semantics (replace vs add), so an hourly re-roll can either double or erase.

**Resolution.** `UNIQUE(ws, job_id, attempt_no, kind)`, and define the rollup as
`INSERT … ON CONFLICT DO UPDATE SET quantity = excluded.quantity` computed from events, never incremented.
Add a reconciliation test: sum(events) = usage_daily for a fixture day.

**Owner approval:** Not required.

### DB-08 — MEDIUM — Question marks have no referential link to the blueprint
**Documents:** `DATABASE_DESIGN.md` §3 §5.

`question_results(question_no, awarded, max_marks, …)` is unique per `(ws, result_id, question_no)` but is not
linked to `assignment_questions`. A mark can be written for question 13 of a 12-question paper, and `max_marks`
on the result row can disagree with the blueprint's official value — which is exactly the drift the V5 blueprint
was built to prevent. `results.total_marks` is denormalised with no check that it equals the sum.

**Resolution.** Carry `assignment_question_id` as a FK and derive `max_marks` from it (or trigger-verify equality);
add a periodic `verify` job that asserts `total_marks = SUM(question_results.awarded)` and reports drift.

**Owner approval:** Not required.

### DB-09 — MEDIUM — Several screens and settings have no storage
**Documents:** `SCREEN_INVENTORY.md` §45–§47, `DATABASE_DESIGN.md`.

`workspaces` has `retention_days` and `plan`, but the Settings screen promises **branding**, **academic defaults**,
**correction defaults**, **notification preferences** and **quota** configuration; Usage shows storage and token
quotas per workspace. No `workspace_settings` table, no quota columns, no per-user notification preferences table
exists. `saved_views` exists with no API.

**Resolution.** Add `workspace_settings(ws, key, value_json)` or explicit columns for the tabs that are actually
built, plus `notification_preferences(user_id, ws, kind, channel)` and quota fields. Anything without storage
must be removed from the screen inventory.

**Owner approval:** Required (scope decision).

### DB-10 — MEDIUM — Missing indexes for the two most common reads
There is no index on `submissions(workspace_id, student_id)` (student profile, screen 40) and none on
`submission_files(submission_id)` (submission detail, screen 35). Both are per-student/per-submission lookups on
the hot path of the review canvas.

**Resolution.** Add both, leading with `workspace_id` where applicable.

**Owner approval:** Not required.

### DB-11 — MEDIUM — "Append-only audit" has no mechanism
`audit_log` is append-only by convention. SQLite supports `BEFORE UPDATE`/`BEFORE DELETE` triggers with
`RAISE(ABORT)`, which would make the claim true and cost nothing. `LG-4` says "no application path can update or
delete a row" — with one repository this is achievable, but a trigger is the only enforceable version.

**Resolution.** Add `BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'append-only'); END` and the DELETE
equivalent; keep one documented escape for the purge workflow (a separate table or a per-workspace drop).

**Owner approval:** Not required.

### DB-12 — LOW — The lease index exists but nothing uses it
`idx_jobs_ws_lease … WHERE status IN ('queued','running')` is created for a reaper that does not exist (ARC-02).
Either implement the reaper or drop the index so it does not imply a control that is absent.

### DB-13 — LOW — `d1 export` limitations are noted but not planned for
`BACKUP_AND_RECOVERY.md` correctly records that exports block the database and do not support FTS5. Since the
backup plan depends on daily full exports, add an explicit note that exports run against a **cloned bookmark**
where available, or accept the blocking window in the maintenance calendar.

---

## Part B — API

### API-01 — HIGH — The grade matrix has no endpoint
**Documents:** `SCREEN_INVENTORY.md` §36, `API_DESIGN.md` §7 §8.

Screen 36 (Results / grade matrix, pivot table, totals, distribution, outliers) is a P5/P7 deliverable with a CSV
export requirement (`ACCEPTANCE_CRITERIA.md` §8). The API exposes `GET /results/{id}` (single), `GET
/reports/class/{assignmentId}` (report record) and `GET /analytics/overview`, but **no results collection** for an
assignment or class.

**Consequence.** The screen will be built against an endpoint invented under pressure, most likely one that
returns all results for an assignment without pagination — a D1 50 MB result-cap error waiting for the largest
class.

**Resolution.** Add `GET /w/{slug}/assignments/{id}/results?cursor=&limit=` returning totals per student (no
per-question payload) and `GET /w/{slug}/assignments/{id}/results/summary` for aggregates. Paginate by default.

**Owner approval:** Not required.

### API-02 — HIGH — The workspace export endpoint is missing (see SEC-09)
`POST /w/{slug}/exports` and its status/download routes do not exist, though J8 and `MULTI_TENANCY.md` §7 describe
the behaviour. **Owner approval:** Required (it is the control that prevents a hand-rolled dump).

### API-03 — MEDIUM — Notifications have storage, a realtime event and a screen, but no endpoints
`SCREEN_INVENTORY.md` §25 (Inbox) and §45 (notification settings) need list, mark-read and preference endpoints.
`notifications(id, ws, user_id, payload_json, read_at)` exists; `API_DESIGN.md` has none.

**Resolution.** `GET /w/{slug}/notifications`, `POST /w/{slug}/notifications/{id}/read`,
`PATCH /me/notification-preferences`. Without them the inbox can only be built by querying D1 from the client —
which the architecture forbids.

### API-04 — MEDIUM — The publish tri-state is invisible to the UI
`automation_operations` is the core of the `NEEDS_VERIFICATION` story, and `POST /automation/{opId}/reconcile`
exists — but there is no `GET` for the operations of an assignment or submission, so screen 27's "blockers, next
action" and screen 37's "attach-to-Classroom" state cannot be rendered.

**Resolution.** `GET /w/{slug}/assignments/{id}/operations` and `GET /w/{slug}/submissions/{id}/operations`.

### API-05 — MEDIUM — One permission covers two distinct effects on publish
`POST /assignments/{id}/publish` requires `correction.approve` but performs report attachment (a `report.generate`
effect) *and* grade publication. A role granted approve-but-not-generate can trigger PDF generation, and there is
no way to publish grades without a report.

**Resolution.** Split into `publish` (grades/return) and `attach-report`, or require both permissions and state
it. The roles matrix currently implies `supervisor` can do both — make that explicit rather than implicit.

### API-06 — MEDIUM — Bulk correction has no documented bound
`POST /w/{slug}/corrections/bulk` can create an unbounded number of jobs in one request, each of which will call a
paid provider. Nothing caps the array, and the quota check is described per-job.

**Resolution.** Cap at ~100 per request, require `Idempotency-Key`, and check the workspace quota **once** for the
whole batch before enqueueing any of it (all-or-nothing), so a partial batch cannot blow the budget.

### API-07 — MEDIUM — `Idempotency-Key` is "required" on approvals, which contradicts the C2 decision
§1 requires an `Idempotency-Key` on POSTs that create jobs, uploads or publications; `TENANT_ISOLATION_TESTS.md`
C2 leaves the double-approval outcome undecided between `409` and idempotent `200`. Pick one and make the
requirement consistent: approval is an **If-Match** operation, not an idempotency-key operation.

### API-08 — MEDIUM — Error vocabulary has a semantic mismatch for quota
`quota_exceeded` maps to **402 Payment Required**. 402 means "payment needed", and there is no billing in the MVP;
a workspace over its AI quota has not been asked to pay. Use `429` with `code: quota_exceeded`, or `403`. Small,
but it will confuse client retry logic and any future billing integration.

### API-09 — LOW — `Vary`/caching assertions absent
See SEC-10. The API's caching rule is correct but untested.

### API-10 — LOW — Invitation acceptance can leak invite existence
`POST /auth/invitations/{token}/accept` is unauthenticated by design. If a signed-in user with a different email
is told "this invitation is for another address" while a random token yields "not found", tokens become an
enumeration oracle. Return one generic response for both cases.

---

## Part C — Cross-document mismatches

| # | Mismatch | Documents | Severity |
|---|---|---|---|
| 1 | Permission footnotes ² ⁴ ⁶ cannot be enforced by the API | roles §4 vs API §7–§8 | HIGH (SEC-04) |
| 2 | Export promised in journeys, absent from API | journeys J8 vs API §4 | HIGH |
| 3 | Grade matrix screen has no endpoint | screens §36 vs API | HIGH |
| 4 | `submissions.status` includes `published`; `results.status` does not | DB §4 | LOW — add or document |
| 5 | Jobs retention 90 days vs `usage_events` referencing `job_id` for 24 months | DB §5, privacy §4 | MEDIUM — define FK behaviour on job purge |
| 6 | `workspaces.status` exists; no status vocabulary listed | DB §3 vs §4 | LOW |
| 7 | `comments.visibility` is not in any status vocabulary | DB §5 | LOW |

## Part D — Verdict

| Area | Verdict |
|---|---|
| Tenancy model | Sound |
| Identity schema | **Must be reconciled with Better Auth before P2** |
| Constraints and triggers | **Insufficient — six additions required** |
| Mark integrity at the data layer | **Insufficient — DB-05** |
| API coverage vs screens | **Six gaps** (results, export, notifications, operations, bulk bound, preferences) |
| API conventions (pagination, versioning, errors) | Good |
| Idempotency and concurrency | Good design, two unresolved conflicts |
