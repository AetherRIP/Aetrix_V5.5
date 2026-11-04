# Critical and High Remediation

**Date:** 2026-11-03 · **Scope:** the 1 CRITICAL and 26 HIGH findings, each resolved to the level where an
implementer needs no further decision. Medium and Low findings are dispositioned in
`REMEDIATION_MASTER_REGISTER.md` §2 and specified where they touch these.

Every entry follows the same shape: **problem → resolution → why this resolution → residual risk → proof.**
Where a resolution needs the owner, the decision id from `OWNER_APPROVAL_DECISIONS.md` is named; the spec is
still written, so approving the decision is a signature, not a design session.

---

## 1. ARC-01 / REL-01 — CRITICAL — the job pipeline can lose work silently

**Problem.** `BACKGROUND_PROCESSING.md` §2 reads:

```
insert jobs row (status=queued, idempotency_key)   [atomic]
enqueue { jobId, workspaceId }
```

The `[atomic]` annotation covers the D1 insert only. D1 and Queues share no transaction and D1 has no
interactive transactions, so there is no way to make both happen or neither. A Worker that dies, hits the CPU
wall, or throws on the enqueue leaves a `queued` row with **no message**. Nothing reclaims it: the documented
cron set covers Classroom reconciliation, stale uploads, purge, export, usage rollups and provider health — not
orphaned jobs. Queue depth reads healthy, because the queue is genuinely empty, and no error is ever raised.

**Resolution — transactional outbox.**

```sql
CREATE TABLE job_outbox (
  job_id           TEXT PRIMARY KEY REFERENCES jobs(id),
  workspace_id     TEXT NOT NULL REFERENCES organization(id),
  created_at       INTEGER NOT NULL,
  published_at     INTEGER,
  publish_attempts INTEGER NOT NULL DEFAULT 0,
  last_error       TEXT
);
CREATE INDEX idx_outbox_pending ON job_outbox(created_at) WHERE published_at IS NULL;
```

Creation becomes one batch (one transaction, one query against the 1,000-per-invocation budget):

```ts
await env.DB.batch([
  insertJobStmt,        // jobs row, status='queued'
  insertOutboxStmt,     // job_outbox row, published_at NULL
]);
```

A publisher cron runs every minute:

```sql
SELECT job_id, workspace_id FROM job_outbox
WHERE published_at IS NULL AND created_at < :now - 30000
ORDER BY created_at LIMIT 100;
```

For each row: `QUEUE.send({ jobId, workspaceId })`, then

```sql
UPDATE job_outbox SET published_at = :now
WHERE job_id = ? AND published_at IS NULL;
```

**Why an outbox rather than a retry loop or a second queue.** A retry loop around `send()` closes the
"enqueue threw" half but not the "Worker died between statements" half, which is the half that produces a silent
loss. A second queue does not create an atomic boundary; it moves it. The outbox is the only pattern that makes
the *database* the record of intent and treats publishing as repeatable work. It also gives monitoring something
observable (age of the oldest unpublished row), which the original design lacked entirely.

**At-least-once publishing is safe here**, and this matters because the publisher can crash between `send()` and
the `published_at` update: a duplicate message is harmless because the consumer claims with a guarded
`UPDATE … WHERE status='queued'` and because Workflow instance ids are unique per job (§2).

**Residual risk.** Up to 60 s of added latency between accepting a job and starting it (the publisher period).
Acceptable against a p90 promise measured in minutes, and the UI already shows `queued`. A stuck publisher is
detectable within two periods by `REL-02`'s alert.

**Proof.** `T-JOB-01`: kill the Worker between the batch and the enqueue (fault injection at the `send` call);
assert the job reaches `running` within 90 s. `T-JOB-02`: publish twice; assert one execution.

---

## 2. ARC-02 — HIGH — no reaper for a job stuck in `running`

**Problem.** Claiming is a conditional `UPDATE … SET status='running', lease_until=… WHERE id=? AND
status='queued'`. If the Workflow never starts or dies outside a retried step (platform incident, deploy
mid-flight, workflow-creation failure), the row stays `running` forever with an expired lease.
`idx_jobs_ws_lease` exists and nothing consumes it.

**Resolution — a lease reaper plus a structural guarantee.**

Every 2 minutes:

```sql
-- candidates
SELECT id, workspace_id, attempts, max_attempts FROM jobs
WHERE status IN ('running','parked')
  AND lease_until IS NOT NULL AND lease_until < :now
LIMIT 50;

-- requeue (attempts guarded)
UPDATE jobs SET status='queued', lease_until=NULL, attempts = attempts + 1, updated_at = :now
WHERE id = ? AND status IN ('running','parked') AND lease_until < :now;
```

If `attempts >= max_attempts`, set `failed` with `error_code='lease_expired'` instead, write a `job_attempts`
row, and notify the owner.

**The structural half is the part the audit did not state.** Workflow instances are created with
`instanceId = jobId`. Starting an instance that already exists does not create a second one, so re-queuing a job
whose Workflow is actually still alive cannot double-run the provider call. This is what makes a reaper safe to
add; without it, a reaper is a duplicate-charge generator.

**Residual risk.** A genuinely lost Workflow whose provider call had already been billed will be retried and
billed again. Bounded by `max_attempts` (default 3) and visible in `usage_events`, which is the honest
trade-off: paying twice occasionally beats a job that never completes.

**Proof.** `T-JOB-03`: kill a Workflow mid-run; assert a terminal state within two lease periods. `T-JOB-04`:
deliver the same message five times; assert `attempts = 1`.

---

## 3. ARC-03 — HIGH — the Durable Object is not justified by the workload it cites

**Problem.** `REALTIME_ARCHITECTURE.md` §2 chooses a hibernating Durable Object per workspace. The stated
benefit (idle sockets are cheap) is true, but the workload is 5–10 assistants per workspace on an
**asynchronous handoff** product whose only real-time need is job progress. Polling `/jobs/{id}` every 10 s from
10 concurrent users is roughly 86 k requests/day — inside the included 10 M/month, at effectively zero marginal
cost — and adds no stateful component, no ticket flow, no socket-auth surface, no replay cursors and no class
migration plan.

**Resolution.** `ADR-008` moves from **Accepted** to **DEFERRED**. P5 ships polling with a cadence ladder, ETag
revalidation and backoff. The full DO design is preserved, versioned, in `DURABLE_OBJECT_DEFERMENT_PLAN.md`,
with numeric promotion thresholds and a migration checklist.

**Why defer rather than delete.** The design is sound and will be needed if the product ever adds presence or
collaborative review. Deleting it would force a redesign later; building it now spends a stateful surface on a
need nobody has measured. Deferring preserves both options at the cost of a document.

**Residual risk.** A marker waiting on a 3-minute job sees updates at 2 s granularity rather than sub-second.
If pilot telemetry shows this is a complaint, the thresholds in the deferment plan trigger the DO build.

**Proof.** Deferment is proven by *absence*: P5 acceptance criteria no longer contain socket requirements, and
`T-UX-05` asserts progress is visible and resumes correctly after a tab is hidden and restored.

---

## 4. ARC-04 — HIGH — the PDF host is decided in the phase that depends on it

**Problem.** §7 of `SYSTEM_ARCHITECTURE.md` lists three options and recommends Workers Containers, whose GA
status the same document says must be re-verified — while `CLOUDFLARE_ARCHITECTURE.md` §1 excludes Containers
from the MVP service list. P1 is therefore asked to select an option that the cost and operational models
exclude, and `COST_AND_SCALABILITY.md` has no line for it.

**Resolution.** New **`ADR-017` — Report rendering host** (`REVISED_ARCHITECTURE_DECISIONS.md` §3.2), with:

| Option | Reproducibility | Data processor | Cost shape | Verdict |
|---|---|---|---|---|
| A. Workers Containers running ReportLab | Full (same code as V5) | None new | memory × wall-time per render; GA status must be confirmed | Viable, gate on GA |
| B. External render API | Full if deterministic | **New sub-processor** with student data | per document | Viable only with a DPA |
| C. Client-side print-to-PDF | None — depends on browser, fonts, version | None | zero | **Rejected for the authoritative report**; accepted for viewing |

Decision rule: P1 measures render time and cost per report; if Containers are GA and the measured cost is
within a stated envelope, option A; otherwise option B with a signed DPA. Option C remains the viewing path
either way. **The decision is required before P5** (not P7), because the report record, the R2 key layout and
`automation_operations.attach_report` all assume a server-generated artefact.

**Residual risk.** Option B sends scripts to a third processor. Mitigated by per-workspace credentials where
the customer contracts directly, and by listing the processor publicly.

**Proof.** `T-OPS-05`: render the same fixture report twice on the chosen host and compare bytes; a documented
variance list must be empty for the reproducible fields (totals, marks, names, lesson code).

---

## 5. SEC-01 — HIGH — the support-grant path is unspecified at the point that matters

**Problem.** `TenantContext` is minted only after a **membership** row resolves, and a platform operator has no
membership by design. No document says how a granted read obtains a context, whether the grant replaces the
membership check, how revocation is honoured mid-request, or how a granted 200 is distinguished from a leak.

**Resolution — a third context variant, not a flag.**

```ts
type TenantContext =
  | { kind: 'member';  workspaceId: string; userId: string; membershipId: string;
      role: Role; permissions: Set<Permission> }
  | { kind: 'apiKey';  workspaceId: string; keyId: string; scopes: Set<Permission> }
  | { kind: 'support'; workspaceId: string; operatorId: string; grantId: string;
      scope: Set<Permission>; expiresAt: number };   // read-only by construction
```

Rules, all testable:

1. The request carries `X-Support-Grant: <grantId>` **in addition to** the operator's session. There is no
   implicit support mode: without the header, an operator resolves to no workspace context at all.
2. `resolveTenant` re-reads the grant row on **every** request. No caching, because the whole value of the
   control is that revocation is immediate.
3. Validation: grant exists, `revoked_at IS NULL`, `expires_at > now`, `workspace_id` matches the path, and the
   authenticated user is in `platform_operators` with `status='active'`.
4. Authorization is checked **per permission key** against `grant.scope`, not per route. A grant scoped
   `correction.result.read` cannot fetch a file, because the file route requires `submission.read`.
5. Out-of-scope object access returns **404**, identical to any other cross-tenant miss, so the operator cannot
   use the grant to enumerate.
6. Every read writes an `audit_log` row inside the same `db.batch()` as the response's data read, with
   `actor_id = operatorId`, `action='support.read'`, `target_type`, `target_id`, `request_id`.
7. **Writes are impossible** under a support context: the repository's write methods accept
   `MemberContext | ApiKeyContext` only. This is a type-level control, not a policy check.
8. Grants are created **by the workspace owner**, require step-up re-authentication (`AU-7`), carry a typed
   reason of at least 20 characters, a scope drawn from a fixed read-only list, and `expires_at ≤ created_at +
   72 h` (enforced by `CHECK`).
9. A workspace-visible banner is driven by `GET /w/{slug}/support-grants/active`, and every granted read emits a
   notification to owners if more than 50 rows are read in one request.
10. Operators are themselves MFA-required and IP-restricted where feasible (`SA-6`).

**Why the id rather than a boolean.** A boolean on the session ("this operator is in support mode") applies to
*every* workspace the browser visits and survives navigation. A grant id binds one operator, one workspace, one
scope and one expiry to one header, and is re-validated per request. The `SEC-01` failure mode — a standing
cross-tenant read capability — is exactly what a session flag produces.

**Residual risk.** An operator can still read whatever the grant scopes, by design. The controls are consent,
scope, expiry, read-only and per-read audit; a malicious operator within scope is a personnel matter, not a
technical one.

**Proof.** `T-AUTH-09`: operator with a `correction.result.read` grant calls `GET /submissions/{id}/file` → 404;
grant revoked mid-session → next request 404; expired grant → 404; every successful read produces exactly one
audit row naming the operator. `T-AUTH-10`: a support context attempting `PATCH /results/{id}/questions/3`
cannot compile, and the route rejects a crafted request with 404.

---

## 6. SEC-02 — HIGH — MFA is mandatory by policy and unreachable by configuration

**Problem.** `AU-4` requires TOTP for `workspace_owner` and `platform_operator`. Better Auth's 2FA plugin gates
the password sign-in routes; passkey, social/OAuth, magic-link and email-OTP sign-ins are not gated by default,
and `AU-5` simultaneously encourages passkeys. A "Sign in with Google" button is therefore a complete bypass
for exactly the accounts the policy protects — while the checklist reads "MFA enforced". The 1.7.16 release
notes make this sharper: one fixed issue was "anonymous users linked on a sign-in awaiting 2FA", i.e. this is an
active area of the library, not a hypothetical.

**Resolution — enforce assurance in the application, not in the sign-in route.**

Sessions carry two additional fields (`session.additionalFields`):

- `amr` — the authentication methods used, e.g. `["pwd","totp"]` or `["passkey"]`.
- `mfaVerifiedAt` — epoch ms of the last successful second factor.

A middleware `requireAssurance(ctx, level)` runs on every authenticated route:

| Level | Required | Applied to |
|---|---|---|
| `standard` | a session | reads |
| `mfa` | `role` not in {owner, admin} **or** `mfaVerifiedAt` within 30 min | all workspace mutations, credentials, members, export, deletion |
| `stepup` | `freshAge` satisfied **and** TOTP re-prompted | password/MFA change, owner transfer, credential rotation, deletion, support grant |

Plus enrolment enforcement: a user whose role requires MFA and whose `user.twoFactorEnabled` is false is allowed
to sign in but every mutation returns `403 mfa_enrolment_required` until enrolment completes. The onboarding
checklist makes this step 7 for owners (`DOC-09`), so it is a guided path, not a wall.

**Why not just configure hooks per provider.** Hooks depend on each provider's callback shape and on library
behaviour that has changed twice in this release line. An assurance check reads only our own session fields, so
it is identical for password, passkey, Google and any future method — and it fails closed if a new method is
added and nobody writes a hook.

**Residual risk.** A stolen *session* that already passed MFA is not re-challenged for 30 minutes. Bounded by
the session lifetime decision (`C1`) and by step-up on destructive actions.

**Proof.** `T-AUTH-04…07`: one test per enabled method (password, passkey, Google, recovery code) asserting that
an owner without a second factor cannot perform a mutation; with a second factor, can. `T-AUTH-08` asserts the
30-minute assurance window and its expiry.

---

## 7. SEC-03 — HIGH — auth brute-force protection does not exist on Workers

**Problem.** Better Auth's rate limiter is on by default but **in-memory**, which its own docs call unsuitable
for serverless: Workers isolates are per-colo and short-lived, so the counter is effectively per-instance. The
compensating control in the package (an edge rule at `/auth/*` 10/min/IP) is also per-colo, and Cloudflare
permits one rate-limiting rule on Free, two on Pro. `AU-8` ("lockout after 10 consecutive failures per account
with exponential backoff") therefore describes a control that nothing stores or implements.

**Resolution — two layers, both real.**

1. **Library-level windows, in D1.** `rateLimit: { enabled: true, window: 10, max: 100, storage: "database" }`
   with the library's `rate_limit(id, key, count, lastRequest)` table. D1 is the single writer, so the counter
   is global rather than per-isolate. Default per-route rules retained (`/sign-in/*` 3/10 s, `/two-factor/*`
   3/10 s).
2. **Per-account lockout, in the application.** Two `user` additional fields — `failed_login_count`,
   `locked_until` — updated by a `after` hook on failed sign-in and reset on success:
   `delay = min(2^failures × 1 s, 15 min)`; at 10 consecutive failures the account locks for 15 minutes and the
   owner is emailed. This is the exponential backoff `AU-8` asks for, and it is account-scoped, which a per-IP
   rule cannot be.
3. **Edge rule retained** as a coarse shield: exactly one rule, `/auth/*`, 10/min/IP. The design no longer
   claims per-user platform limits (§`ARC-07`), so one rule is sufficient.
4. Per-user API limits move into the Worker (a D1 counter keyed by `(bucket, key, window)`), because Cloudflare's
   rule count is a plan constraint, not a design choice.

**Why D1 rather than the Workers Rate Limiting binding.** The binding's counters are per-colo, so a distributed
credential-stuffing attempt sees N× the advertised limit — the same defect as the in-memory limiter, one layer
out. D1 is the only component in this architecture with global state.

**Residual risk.** One D1 write per failed sign-in. At a few hundred failures/day this is nothing; under a
sustained attack it is a write amplifier, which is why the edge rule exists in front of it.

**Proof.** `T-AUTH-11`: 11 wrong passwords across three simulated colos → account locked, `locked_until` set,
backoff observed. `T-AUTH-12`: rate-limit counter survives an isolate restart (proving it is not in memory).

---

## 8. SEC-04 — HIGH — three permission restrictions cannot be expressed

**Problem.** The matrix promises `assistant` sees PII "only for students on their own assignments" (²),
`viewer` sees "aggregates only, no per-student PII" (⁴) and may export "only pre-aggregated exports" (⁶). The
policy model is one-dimensional (`permission → role`), and the endpoints are protected by coarse keys:
`GET /results/{id}` returns per-question marks to anyone with `correction.result.read`. Implemented literally, a
`viewer` reads a child's marks — a confidentiality failure with a written promise contradicting it.

**Resolution — two dimensions: a resource-aware check and an audience-derived shaper.**

```ts
can(ctx, 'correction.result.read', { workspaceId, ownerId, assigneeId, aggregateOnly })
```

Three scope mechanisms, declared once in `permissions.ts` and applied by the repository/shaper:

| Scope | Applies to | Rule |
|---|---|---|
| `assignee` | `student.pii.read`, `submission.read` for `assistant` | resource.assigneeId === ctx.membershipId, else 404 on detail routes and omission from lists |
| `aggregate` | `correction.result.read`, `report.export` for `viewer` | response shaper emits totals, band and counts; per-question rows and explanations are absent, not hidden |
| `owner-action` | `workspace.delete`, `workspace.transfer`, `support.grant` | owner only; unaffected by scope |

The shaper is the enforcement point, and it takes a `PiiLevel` derived from `(role, permission, scope)`:

- `full` — owner/admin/supervisor.
- `masked` — assistant (display name only, full name omitted; limits to assigned work).
- `aggregate` — viewer (no student identifiers at all; group sizes below 5 suppressed).

A single `shapeResult(row, level)` and `shapeStudent(row, level)` are the only functions that serialize these
entities, so "viewer gets per-question marks" is not a missing check in a handler — it is unrepresentable.

**Why not delete the footnotes and accept a weaker policy.** That was the audit's alternative and it is
legitimate, but it would remove the cover-staff persona from the product rather than fix a confidentiality
control the buyer can be shown. The cost of the resource-aware model is one extra parameter and two shaper
functions (`C3` records the alternative and the owner may still choose it).

**Residual risk.** Scope is evaluated in application code, so a new endpoint that bypasses the shaper can
regress it. Mitigated by (a) the shaper being the only serializer, (b) `T-PERM-05` asserting field presence per
role for every result-bearing route, (c) an isolation-suite row for `viewer`.

**Proof.** `T-PERM-01`: viewer calls every result route; assert no `questionResults`, no `explanation`, no
student name in any response. `T-PERM-02`: assistant requests a student not on their assignments → 404.
`T-PERM-03`: viewer export contains only aggregates. `T-PERM-04`: matrix cell-by-cell equality between the
generated matrix and `hasPermission` output.

---

## 9. SEC-05 / DB-03 — HIGH — tenant consistency is a convention, and the leak runs the wrong way to be caught

**Problem.** "Cross-tenant foreign keys are impossible by construction: child rows carry the parent's
`workspace_id`, and application code asserts equality on insert" (`MULTI_TENANCY.md` §3 rule 5). That is a code
convention. Nothing prevents `INSERT INTO submissions (workspace_id=A, assignment_id=<belongs to B>)`. The
isolation suite cannot catch it, because the row is written *with* `workspace_id=A`: every scoped read in A
finds it and B never looks. The corruption is silent until some future query joins without a predicate.

**Resolution — `BEFORE INSERT` and `BEFORE UPDATE OF` triggers on every child table.**

```sql
CREATE TRIGGER trg_submissions_tenant_ins
BEFORE INSERT ON submissions FOR EACH ROW
WHEN NOT EXISTS (
  SELECT 1 FROM assignments a
  WHERE a.id = NEW.assignment_id AND a.workspace_id = NEW.workspace_id)
BEGIN SELECT RAISE(ABORT, 'tenant_mismatch'); END;

CREATE TRIGGER trg_submissions_tenant_upd
BEFORE UPDATE OF assignment_id, student_id, workspace_id ON submissions FOR EACH ROW
WHEN NOT EXISTS (SELECT 1 FROM assignments a
                 WHERE a.id = NEW.assignment_id AND a.workspace_id = NEW.workspace_id)
   OR NOT EXISTS (SELECT 1 FROM students s
                  WHERE s.id = NEW.student_id AND s.workspace_id = NEW.workspace_id)
BEGIN SELECT RAISE(ABORT, 'tenant_mismatch'); END;
```

Applied to every table with a tenant FK: `classes`, `students`, `enrollments` (two parents),
`assignments`, `assignment_questions`, `mark_schemes`, `scheme_decisions`, `submissions` (two parents),
`submission_files`, `results`, `question_results`, `overrides`, `approvals`, `comments`, `jobs`, `job_attempts`,
`job_outbox`, `automation_operations`, `classroom_links`, `notifications`, `usage_events`, `audit_log`,
`api_keys`, `exports`, `review_drafts`, `sample_reviews`, `notification_preferences`, `support_grants`,
`idempotency_records`.

**Cost.** A trigger check is an indexed primary-key lookup on the parent — the cheapest possible read. Measured
against the alternative (a corrupt row discovered in an export six months later), this is free.

**Why the triggers and not a composite FK.** SQLite supports composite foreign keys, and
`FOREIGN KEY (workspace_id, assignment_id) REFERENCES assignments(workspace_id, id)` would work — but it
requires a unique index on `(workspace_id, id)` for every parent, doubles index size on the hot path, and gives a
useless error message. Triggers cost one primary-key probe and produce a named error (`tenant_mismatch`) that a
test can assert. Both are valid; the trigger is chosen for diagnosability and index economy.

**Residual risk.** A future table added without these triggers. Mitigated by `T-DB-01`, which enumerates every
table with a `workspace_id` column from `sqlite_master` and asserts it has at least one tenant trigger — a test
that fails when someone adds a table and forgets.

**Proof.** `T-DB-02`: for each child table, insert a row whose parent belongs to another workspace → `ABORT`
with `tenant_mismatch`. `T-DB-01`: schema enumeration test described above.

---

## 10. DB-01 — HIGH — the identity schema is a different system from the auth library

**Problem.** The package defines `users(id, email, password_hash, mfa_secret, …)`, `sessions(...)` and
`memberships(...)`. Better Auth stores credentials in `account` (`providerId='credential'`, hash in
`account.password`), TOTP secrets in `twoFactor`, WebAuthn credentials in `passkey`, verification tokens in
`verification`, and organization membership in `member` keyed by `organizationId`, with `activeOrganizationId` on
the session. None of those tables exist, and `users.password_hash`/`mfa_secret` are columns the library will
never read. Worse, Better Auth 1.7 performs **runtime schema validation by default, in production**: a
mismatched schema does not degrade, it rejects every request.

**Resolution — the library's schema is canonical; the product extends it through supported hooks.**

| Product concept | Canonical table | Extension mechanism |
|---|---|---|
| Workspace | `organization` | `additionalFields`: `plan`, `region`, `status`, `retentionDays`, `quotaAiCallsMonth`, `quotaStorageBytes`, `brandingJson`, `academicDefaultsJson`, `correctionDefaultsJson`, `deletedAt`, `purgeAfter`, `createdBy` |
| `users` | `user` | `additionalFields`: `failedLoginCount`, `lockedUntil`, `mfaRequired` |
| `sessions` | `session` | `additionalFields`: `amr`, `mfaVerifiedAt` |
| `memberships` | `member` | `additionalFields`: `status`, `invitedBy`, `joinedAt`, `removedAt` |
| `invitations` | `invitation` | library fields (`status`, `expiresAt`, `email`, `role`, `inviterId`) |
| `workspace_id` (everywhere) | `organization.id` | all tenant FKs reference `organization(id)` |

Consequences that must be stated, because they are not obvious:

- **Column names are camelCase** (`emailVerified`, `createdAt`, `userId`). SQLite identifiers are
  case-insensitive, so `createdat` and `createdAt` are the same column — but the code must use the library's
  exact spelling, and a lint rule enforces it, because a rename via `fields` is the supported escape hatch and
  silent case drift makes that harder to reason about.
- **Timestamps are integers.** Better Auth 1.7 requires date-typed timestamps; text timestamps break session
  `max_age` checks and produce a login loop. All timestamps in this schema are `INTEGER` epoch milliseconds,
  formatted to ISO-8601 at the API boundary. This supersedes `DATABASE_DESIGN.md` §1's TEXT timestamps.
- **We own the DDL.** The baseline is generated once from the auth config, committed to `migrations/`, and
  extended by hand. `auth migrate` is never run against production: it cannot reach D1 remotely, and an
  auto-migration that rewrites identity tables is not a deploy step anyone should have.
- **Version pinning is a security control.** `>= 1.7.16`; the 1.7.0–1.7.2 `account.issuer` churn is documented
  as a migration hazard, and the 1.7.16 release fixed a revoked-session/2FA interaction that this design depends
  on.

**Why not keep the product's own tables and mirror identity.** Two writers to one concept is the drift the audit
predicted: a stale membership row is a security bug, an orphaned session is a support ticket, and a user who
exists twice cannot be deleted cleanly. One table, extended, cannot drift.

**Residual risk.** A future library upgrade changes a column and our committed DDL lags. Mitigated by the
runtime validator (which fails loudly in staging), by an upgrade runbook step, and by pinning exact versions
rather than a caret range.

**Proof.** `T-DB-03`: boot the app against a freshly migrated database and assert (a) sign-up, sign-in, session
read, org create, invite and member role change all succeed, and (b) `sqlite_master` contains every table the
library's validator requires.

---

## 11. DB-02 — HIGH — no table exists for workspace API keys

**Problem.** The API accepts `Authorization: Bearer mc_…` with explicit scopes and states that such keys can
never manage members, credentials or delete. The permission document repeats the rule. No `api_keys` table
exists in any catalogue.

**Resolution.**

```sql
CREATE TABLE api_keys (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  label         TEXT NOT NULL,
  prefix        TEXT NOT NULL,          -- 'mc_live_ab12cd34', indexed, shown in the UI
  key_hash      TEXT NOT NULL,          -- SHA-256 hex of the secret half
  scopes_json   TEXT NOT NULL,          -- array of permission keys, validated at write
  created_by    TEXT NOT NULL REFERENCES user(id),
  created_at    INTEGER NOT NULL,
  last_used_at  INTEGER,
  expires_at    INTEGER,
  revoked_at    INTEGER
);
CREATE UNIQUE INDEX ux_api_keys_prefix ON api_keys(prefix);
```

Rules:

- Format `mc_{live|test}_{8-char prefix}_{32-byte secret}`. Only the hash is stored; the secret is shown once.
- **SHA-256, not scrypt.** The secret is 256 bits of CSPRNG output, so there is no dictionary to slow down, and
  the verification happens on every request — a slow KDF here would be a self-inflicted CPU bill. Compare in
  constant time.
- Scopes are drawn from the same permission vocabulary, intersected with an **allow-list** of API-eligible keys.
  A hard deny-list (`workspace.member.*`, `credential.*`, `workspace.delete`, `workspace.transfer`,
  `support.grant`, `workspace.quota.write`, `apiKey.*`) is applied after the intersection, so a future permission
  added to the vocabulary is ineligible by default.
- `last_used_at` is updated at most once per minute per key, to avoid a D1 write per request.
- Keys are per-environment (`live`/`test`), independently revocable, and expire by default after 12 months.
- An API-key context can never create another key (`apiKey.create` is owner-and-session-only).

**Proof.** `T-PERM-07`: a key scoped `submission:read` calling `POST /members`, `DELETE /credentials/{id}`,
`DELETE /workspaces/{slug}` and `POST /api-keys` → 403 each; a key from workspace A against workspace B → 404.

---

## 12. DB-04 — HIGH — soft delete collides with every workspace-scoped unique constraint

**Problem.** `submissions` has `UNIQUE(ws, assignment_id, student_id)` and `deleted_at`; `memberships` has
`UNIQUE(ws, user_id)` and a `status`; `classes` sets `archived_at`. SQLite unique indexes include soft-deleted
rows, so a student whose script was deleted cannot be re-uploaded, a removed member cannot be re-invited, and the
"fix" in production is always a hard delete — destroying the reason soft delete existed.

**Resolution — partial unique indexes.**

```sql
CREATE UNIQUE INDEX ux_submissions_active
  ON submissions(workspace_id, assignment_id, student_id) WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX ux_member_active
  ON member(organizationId, userId) WHERE status <> 'removed';

CREATE UNIQUE INDEX ux_students_external
  ON students(workspace_id, external_ref)
  WHERE external_ref IS NOT NULL AND deleted_at IS NULL;

CREATE UNIQUE INDEX ux_invitations_pending
  ON invitation(organizationId, email) WHERE status = 'pending';
```

Note on `member`: the library may already create a unique index on `(organizationId, userId)`. That index is
**dropped in favour of the partial one** as an explicit, reviewed migration step, with `T-DB-05` asserting the
re-invite path works. If a future library version re-creates it, the migration test fails rather than production.

**Proof.** `T-DB-05`: delete a submission, re-upload for the same student/assignment → 201; remove a member,
re-invite → 201; anonymise a student, add a new one with the same external ref → 201.

---

## 13. DB-05 — HIGH — nothing prevents a mark above the maximum

**Problem.** §1 of the database document says enumerations are `CHECK`-constrained "so a typo fails at write
time", and the product's central promise is that a mark can never exceed the question maximum. But
`question_results` has no `CHECK (awarded <= max_marks)` and `overrides` has none either; the guard is
application-side only — the one place a future endpoint, importer or manual fix bypasses.

**Resolution — constraint plus trigger plus derived totals.**

```sql
-- question_results
awarded     REAL,                     -- NULL means "not yet determined" (needs_review)
max_marks   REAL NOT NULL,
CHECK (awarded IS NULL OR (awarded >= 0 AND awarded <= max_marks)),
CHECK (needs_review = 0 OR awarded IS NULL)   -- a review row carries no number, not a zero

-- overrides: validate against the blueprint, not the row
CREATE TRIGGER trg_overrides_max_ins BEFORE INSERT ON overrides FOR EACH ROW
WHEN NOT EXISTS (
  SELECT 1 FROM results r
  JOIN submissions s ON s.id = r.submission_id
  JOIN assignment_questions aq ON aq.assignment_id = s.assignment_id
                              AND aq.question_no = NEW.question_no
  WHERE r.id = NEW.result_id AND r.workspace_id = NEW.workspace_id)
   OR NEW.to_marks > (
  SELECT aq.max_marks FROM results r
  JOIN submissions s ON s.id = r.submission_id
  JOIN assignment_questions aq ON aq.assignment_id = s.assignment_id
                              AND aq.question_no = NEW.question_no
  WHERE r.id = NEW.result_id AND r.workspace_id = NEW.workspace_id)
BEGIN SELECT RAISE(ABORT, 'mark_exceeds_max'); END;
```

`awarded IS NULL` for `needs_review` is deliberate: it makes "missing question → never a silent 0" a **schema
invariant** rather than a workflow convention, and it prevents the class of bug where a review row is
accidentally summed into a total.

Totals are then derived, not trusted:

```sql
CREATE TRIGGER trg_qr_totals_ai AFTER INSERT ON question_results FOR EACH ROW
BEGIN
  UPDATE results SET
    total_marks      = (SELECT COALESCE(SUM(awarded),0) FROM question_results
                        WHERE result_id = NEW.result_id),
    marked_questions = (SELECT COUNT(*) FROM question_results
                        WHERE result_id = NEW.result_id AND awarded IS NOT NULL),
    total_questions  = (SELECT COUNT(*) FROM assignment_questions
                        WHERE assignment_id = (SELECT s.assignment_id FROM submissions s
                                               WHERE s.id = (SELECT submission_id FROM results
                                                             WHERE id = NEW.result_id))),
    is_complete      = ((SELECT COUNT(*) FROM question_results WHERE result_id = NEW.result_id
                          AND awarded IS NULL) = 0)
  WHERE id = NEW.result_id;
END;
```

(Equivalent `AFTER UPDATE` and `AFTER DELETE` triggers.) Handlers never write `total_marks`; a weekly integrity
job asserts `total_marks = SUM(awarded)` and reports drift, which is the check that would catch a manual fix.

**Proof.** `T-DB-06`: direct SQL insert of `awarded = max_marks + 0.5` → `CHECK` failure; override above max →
`mark_exceeds_max`; override for a question not in the blueprint → `mark_exceeds_max` (the `NOT EXISTS` branch).
`T-DB-07`: insert 12 question results → `total_marks` equals their sum with no handler involvement; a
`needs_review` row leaves `is_complete = 0` and contributes nothing to the total.

---

## 14. DB-09 — MEDIUM→HIGH in effect — the screens that exist have nowhere to store their settings

**Problem.** `workspaces` has `retention_days` and `plan`, but Settings promises branding, academic defaults,
correction defaults, notification preferences and quota configuration; the Usage screen shows per-workspace
storage and token quotas; `saved_views` exists with no API. Nothing stores these, so either the screens ship
with dead controls or each tab invents a table.

**Resolution.** Four typed `additionalFields` JSON columns on `organization` (`brandingJson`,
`academicDefaultsJson`, `correctionDefaultsJson`), five scalar columns (`plan`, `region`, `status`,
`retentionDays`, `deletedAt`/`purgeAfter`), two quota columns (`quotaAiCallsMonth`, `quotaStorageBytes`), and a
`notification_preferences` table keyed `(userId, workspaceId, kind)` with a channel enum.

JSON is chosen over a key-value `workspace_settings(table, key, value)` because these are read as a whole object
by one screen, are never queried by field, and a KV table makes validation and migration of a settings *shape*
impossible to reason about. Typed columns are chosen for anything that is queried, constrained or billed.

**Proof.** `T-API-09`: every Settings tab writes and reads back; `T-DB-12` asserts the JSON columns validate
against their zod schema on write and reject unknown keys.

---

## 15. API-01 — HIGH — the grade matrix has no endpoint

**Problem.** Screen 36 is a P7 deliverable with a CSV export requirement, but the API exposes only
`GET /results/{id}`, `GET /reports/class/{assignmentId}` (a report record) and `GET /analytics/overview`. There
is no collection of results for an assignment or class. The screen will be built against an invented endpoint —
most likely one that returns all results unpaginated, which is a 50 MB result-cap error waiting for the largest
class.

**Resolution.**

```
GET /w/{slug}/assignments/{id}/results?cursor=&limit=50&status=&assignee=
    → { data: [{ submissionId, studentId, displayName, totalMarks, maxMarks,
                 status, isComplete, markedQuestions, totalQuestions }], nextCursor }
GET /w/{slug}/assignments/{id}/results/summary
    → { count, mean, median, distribution[bands], outliers[], suppressedGroups }
GET /w/{slug}/classes/{id}/results?assignmentId=
```

Rules: totals only (no per-question payload — that stays on `GET /results/{id}`); cursor pagination, default 50,
max 200; aggregates suppressed below a group of 5; `viewer` receives the summary but a per-student list with
names replaced by indices (§`SEC-04`); CSV comes from the export pipeline, never from this route.

**Proof.** `T-API-01`: 400-student assignment paginates fully with stable cursors; response size stays under
1 MB per page; viewer response contains no names; summary is numerically identical to the CSV export.

---

## 16. API-02 / SEC-09 — HIGH — workspace export is promised and does not exist

**Problem.** J8 promises an owner-triggered export producing a signed bundle, `MULTI_TENANCY.md` §7 describes
the Workflow, `DP-3` requires it — and there is no endpoint. `THREAT_MODEL.md` T17 correctly bans
`d1 export --table`, precisely because the obvious shortcut is table-wide. A rushed implementation is the single
most likely source of the first real cross-tenant leak.

**Resolution.**

```
POST /w/{slug}/exports   { kind: 'workspace'|'assignment'|'class', targetId? }  → 202 { exportId }
GET  /w/{slug}/exports?cursor=                       → list with state
GET  /w/{slug}/exports/{id}                          → state, manifest, row counts, expiry
GET  /w/{slug}/exports/{id}/download                 → 302 to a 5-minute signed URL
DELETE /w/{slug}/exports/{id}                        → revoke early
```

Implemented **only** as a Workflow, one step per table, each step streaming `WHERE workspace_id = ?` into R2
under `ws/{workspaceId}/exports/{exportId}/…`, then a zip manifest with per-file SHA-256 and per-table row
counts. The manifest is stored on the `exports` row and in `audit_log`.

Structural protections: the route requires `workspace.export` (owner/admin only); the Workflow takes
`(workspaceId, exportId)` as params and each step re-asserts the workspace from the row, never from the message;
`T-ISO-09` counts rows per workspace inside the produced archive and asserts zero foreign rows; the R2 key is
derived, never accepted; the download URL is single-use, 5 minutes, and audited.

**Proof.** `T-ISO-09` (as above) plus `T-API-02`: an export cannot be created for a workspace the caller is not
an owner/admin of; a download link expires; a partial failure leaves `state='failed'` with no downloadable
artefact.

---

## 17. DOC-01 — HIGH — three documents disagree on whether V5 data is migrated

**Problem.** `ADR-015` (Accepted) describes an importer that "reads V5 SQLite exports and writes through the
public API path". `OPEN_QUESTIONS.md` Q5 defaults to "**No automatic migration**" and `DATABASE_DESIGN.md` §8
says "**No V5 data is migrated automatically** — an importer is a separate decision." An accepted ADR outranks
an open question's default, so a reader implementing P1 could reasonably start building an importer.

**Resolution.** `ADR-015` becomes **DEFERRED**, and one normative sentence replaces three positions:

> V5 remains the source of truth until P1 parity passes. **No V5 data is migrated automatically.** If Q5 is
> answered "yes", the importer's *shape* is API-mediated — it will exercise the public API, and `CH1L1`
> lesson identities are preserved as external references — but no importer is built until that decision is made.

This keeps the useful part of ADR-015 (the identity-preservation rule and the API-mediated shape) while removing
the implication that work is committed. `C15` records the decision with its options.

**Proof.** Documentation-level: the three documents now state one position, and `UPDATED_TRACEABILITY_MATRIX.md`
marks the requirement as "deferred by decision", not "gap".

---

## 18. DOC-02 / DOC-03 / DOC-04 — HIGH — the documentation contradicts itself at the API seam

**Problem.** Three of these are the same class: a journey or a screen describes behaviour the API does not
support. DOC-02 (permission footnotes) is resolved by `SEC-04`; DOC-03 (export) by `API-02`; DOC-04 (grade
matrix) by `API-01`.

**Resolution.** Beyond the individual endpoints, the remediation adds a **generated** endpoint→screen→permission
matrix (`UPDATED_TRACEABILITY_MATRIX.md` §2) and makes it a CI artefact: every route declares its screen and its
permission in a route manifest, and a test fails if a screen in the inventory references a route that does not
exist, or a route declares a permission absent from the vocabulary. This is the structural fix — the three
contradictions existed because nothing checked the seam.

**Proof.** `T-API-10`: route manifest ↔ screen inventory ↔ permission vocabulary cross-check passes; adding a
screen reference to a non-existent route fails the build.

---

## 19. UX-01 — HIGH — an interrupted review loses the most valuable keystroke in the product

**Problem.** `RESPONSIVE_DESIGN.md` says drafts "persist locally until saved", while the write model is
version-guarded on the server. A local draft applied later can overwrite a change made in between, or fail and
lose the text; there is no server-side draft, no autosave cadence and no rule for what a local draft means after
a version bump. The recovery path can therefore cause the lost update J5 exists to prevent.

**Resolution — server-side drafts, local storage as cache only.**

```sql
CREATE TABLE review_drafts (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  result_id    TEXT NOT NULL REFERENCES results(id),
  actor_id     TEXT NOT NULL REFERENCES user(id),
  body_json    TEXT NOT NULL,
  base_version INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_review_drafts ON review_drafts(workspace_id, result_id, actor_id);
```

Behaviour:

1. Autosave debounced at 2 s after the last keystroke, and on `visibilitychange → hidden`, and on blur.
2. A draft **never** bumps the result version; only an explicit save does.
3. Save sends `If-Match: base_version`. On `409`, the server returns the current marks and the draft is kept; the
   UI shows a diff and offers "keep mine", "take theirs", or "merge per question". Nothing is auto-applied.
4. On reopen, an existing draft is restored with a banner: "Unsaved changes from 14:02 — resume or discard".
5. Drafts are deleted on successful save, on approval of that result, and by the retention sweep at 30 days.
6. `localStorage` holds a copy keyed by `(resultId, baseVersion)` for the network-loss case, and is **discarded**
   if its `baseVersion` is behind the server's — it is a cache, never a source of truth.

**Why server-side.** Local-only cannot survive a device change, a browser profile reset, or a second reviewer on
the same result, and it cannot distinguish "my draft" from "a stale copy of someone else's edit". The server
version is the only thing that can be diffed against the current row.

**Proof.** `T-UX-01`: kill the tab mid-override, reopen → text restored, `results.version` unchanged; a concurrent
save then a draft save → 409 with a diff, no data loss; the same flow across devices restores the draft.

---

## 20. UX-02 — HIGH — simultaneous approval is undecided inside a blocking suite

**Problem.** `TENANT_ISOLATION_TESTS.md` C2 says "`409` (already approved) or `200` idempotent — decided
behaviour, documented, and tested" and does not decide it. A blocking test cannot contain an undecided assertion,
and the product promise is that a human decides every mark that matters — so the second approver must not be told
they approved something they did not.

**Resolution.**

| Case | Response |
|---|---|
| Same actor re-submits the same approval | `202` idempotent, `{ approvedAt, approvedBy }`, no second row |
| Different actor approves an already-approved result | `409 already_approved` with `{ approvedBy, approvedAt }` |
| Approval of a result with `needs_review` rows | `409 incomplete_result` listing the review rows |
| Approval with a stale `If-Match` | `409 version_mismatch` with current marks |

The screen shows "Approved by J. Patel, 2 minutes ago" on the 409 path, which is the state that makes the
distinction useful rather than merely correct.

**Proof.** `T-API-03` covers all four rows; C2 is rewritten in `ACC-R` as decided behaviour.

---

## 21. REL-03 — HIGH — the file backup plan is not implementable

**Problem.** `BACKUP_AND_RECOVERY.md` states R2 objects are "versioned by key prefix" and recoverable from a
"replication bucket" with continuous on-write replication. R2 has **neither** object versioning nor native
cross-bucket replication (re-verified this phase against the S3 compatibility matrix and the durability page).
There is no undo for an overwritten or deleted object, and the document promises one.

**Resolution.** A real pipeline, built on primitives that exist, specified in full in
`R2_BACKUP_AND_RECOVERY_DESIGN.md`. Summary:

- Backup bucket `mc-files-backup-{env}`, separate credentials, **bucket lock** on the `v1/` prefix (blocks
  delete and overwrite for the retention period).
- Every `object-create` event on the primary bucket → `backup-events` Queue → consumer performs a **server-side
  `CopyObject`** into `v1/{yyyy}/{mm}/{dd}/{originalKey}` and writes a `backup_objects` manifest row.
- **No Worker byte-piping**: copy is Class A, no egress, no CPU, and works for 200 MB files.
- `object-delete` events are recorded, **not** propagated: deletion in the primary bucket marks
  `source_deleted_at` and leaves the backup intact, so a mistaken prefix purge is recoverable for the retention
  window.
- Nightly reconciliation: `ListObjectsV2` on the primary bucket compared against `backup_objects` for the last
  30 days, covering objects whose event was never delivered.
- Integrity: `submission_files.sha256` is written at upload; the manifest stores it; verification samples objects
  and compares `head()` size plus the stored digest (R2's multipart ETag is not a whole-object MD5, and CRC64NVME
  `FULL_OBJECT` is the only whole-object checksum R2 will give for multipart — both facts are recorded so nobody
  builds a check on ETag equality).

**Residual risk.** Storage roughly doubles for scripts (costed: +$8/mo at 100 workspaces in the year-1 average).
A same-account copy does not survive account loss; that is stated plainly and the mitigation (periodic off-
provider export, egress free) is recorded as a post-MVP option rather than pretended.

**Proof.** `T-BKP-01`: delete an object in the primary bucket → restore from backup → digest matches.
`T-BKP-02`: drop an event message → nightly reconciliation still copies the object. `T-BKP-03`: attempt to
overwrite a locked backup object → 409 `ObjectLockedByBucketPolicy`.

---

## 22. REL-04 — HIGH — recovery is designed, never proven, and there is no rehearsal environment

**Problem.** The RTO/RPO table is credible *as targets*. But D1 Time Travel restore is destructive and in-place,
there is no clone or branch of a database, and `d1 export` blocks other requests and cannot export FTS5 tables.
"Restore one table slice into staging" therefore requires parsing an export and re-inserting — a scripted,
testable procedure the package does not specify. D1's Time Travel window is also 30 days on Paid, which is the
ceiling on any PITR claim.

**Resolution.**

- A `backup-restore` CLI (P2 deliverable, not P10) with three verbs: `slice --workspace --from <export>`,
  `verify --export` (row counts, FK integrity, digest of `submission_files`), and `rebuild --export --target`.
- Exports include a `manifest.json` with per-table row counts and a schema digest; `verify` fails if counts differ.
- Drills are scheduled, not aspirational: monthly tenant-slice restore into staging, quarterly full rebuild into a
  scratch database created for the purpose, quarterly single-object R2 recovery. Every drill writes
  `ops_backup_log(kind, started_at, finished_at, source, rows_restored, objects_restored, result, notes)`.
- RTO is **measured, then published**: the first drill's duration replaces the promise in the operations document.
- Restoring a tenant slice inserts rows with `INSERT OR IGNORE` in batches of 1,000, re-asserting the tenant
  triggers, and writes an `audit_log` row visible to the customer.

**Proof.** `T-BKP-05`: a drill restores a 3-table slice with matching row counts and the app reads it.
`T-BKP-06`: a corrupted export fails `verify` before any write. `T-BKP-07`: `ops_backup_log` has one row per
drill and the alert fires when the last drill is older than 35 days.

---

## 23. ROAD-01 — HIGH — support access ships after the first customer

**Problem.** The MVP cut line excludes the platform admin surface and the consent-grant mechanism, but the MVP
launches to design-partner schools and operators will immediately need to diagnose their data. The only tool at
that point is raw D1 access — precisely what `SA-1` forbids. The control exists on paper and is violated from
day one.

**Resolution.** The **grant mechanism** — not the whole administration surface — moves into **P5**: the
`support_grants` table, the `SupportContext` variant, `POST/DELETE /w/{slug}/support-grants`, the banner
endpoint, per-read audit, and expiry. That is one table, one context variant, three endpoints and a cron. The
platform directory, analytics and audit search stay in P9.

**Proof.** `T-AUTH-09/10` run at P5 exit, and P5's acceptance criteria include "an operator cannot read tenant
data without an active grant".

---

## 24. SEC-08 — MEDIUM→HIGH in effect — session lifetime and role staleness exceed the stated policy

**Problem.** `AU-6` sets 7-day idle / 30-day absolute; OWASP recommends 2–5 minutes idle for high-value
applications and 4–8 hours absolute for a workday tool holding minors' data. Separately, the roles document
claims the server "caches membership for ≤ 60 s per session and busts it on role change" — Better Auth's cookie
cache has no per-session bust, and the package never sets `maxAge`, so the staleness window is whatever the
default is.

**Resolution.**

| Setting | Value | Rationale |
|---|---|---|
| `session.expiresIn` | 12 h | Idle window for a marking session; a marker's work is uninterrupted for hours, not days |
| `session.updateAge` | 1 h | Sliding refresh granularity |
| Absolute cap | 7 days, enforced in middleware against `session.createdAt` | Survives cookie-cache staleness |
| `cookieCache.maxAge` | **60 s** | The staleness bound, stated and testable |
| `disableCookieCache` | on sensitive routes | Role change, credential ops, support grant, export, deletion re-read the DB |
| Role change | session row updated, `cookieCache` invalidated by shortening `expiresAt` of the cached variant | Removed member is 401 on the next request, not in 60 s |

**Why not zero cache.** Every authenticated request would hit D1 for the session, adding a read to the hot path
for a control that is bounded at 60 s and bypassed on exactly the routes that matter. Sixty seconds is a
defensible, *published* number; "we bust the cache" was neither true nor measurable.

**Proof.** `T-AUTH-08`: demote a supervisor to assistant, then call an approve endpoint within 5 s → 403 on the
sensitive route (cache disabled) and consistent role everywhere within 60 s; delete the session row → 401 next
request.

---

## 25. COST-01 — HIGH — the cost model omits the component the architecture requires

**Problem.** The recommended PDF strategy is Workers Containers or a paid external API, yet the infrastructure
table has no container line, no external-service line, and the service table explicitly excludes Containers from
the MVP. Whichever option P1 selects adds a cost class the budget does not contain — for 15,000–30,000 reports a
month that is not rounding error.

**Resolution.** `ADR-017` costs both options with measured render time as a gate, and `COST-R §8` adds the line
as a required field before P5. The budget is not allowed to approve with a blank cell: the decision and the cost
are the same decision.

**Proof.** `T-OPS-05` measures render time and cost per report; the figure lands in `COST-R §8` before the P5 gate.

---

## 26. ARC-04/DB-01/DB-02/ARC-03 — the four decisions that are signatures, not designs

`ARC-03` (defer the DO), `ARC-04` (PDF host), `DB-01` (identity mapping) and `DB-02` (API keys) are fully
specified above. Each needs one owner decision to become binding, recorded as `C13`, `C7`, `C1` and `C5`
respectively in `OWNER_APPROVAL_DECISIONS.md`. Approving the specification is the decision; there is nothing left
to design.

---

## 27. What did not change, and why

Stated because a remediation document that only lists changes implies everything else was wrong:

| Survived review | Reason |
|---|---|
| Shared-schema tenancy with a branded `TenantContext` | Correct for D1; no cheaper alternative exists at this scale |
| Marking parity before design (`ADR-011`) | Best judgement in the package; unchanged |
| `needs_review` as a first-class state distinct from `failed` | Genuine domain modelling; now enforced in the schema |
| Ids-only queue messages | Correct answer to the 128 KB cap; still correct with an outbox |
| The retry classification table | Ported from V5 unchanged in intent |
| 404-not-403 | Correct, and now cheaper to keep correct because triggers stop the row existing |
| The isolation test harness | Excellent design; extended with trigger and shaper rows |
| Deferring billing while building metering | Right sequencing; made trustworthy by DB-07 |
| The design language and its refusal list | Not a remediation concern |
