# ADR Review — ADR-001 to ADR-015

**Audit date:** 2026-11-03. Each accepted ADR was treated as a proposal requiring evidence. Verdicts:
**ACCEPT** · **ACCEPT WITH CHANGES** · **DEFER** · **REJECT**. The originals are unmodified; proposed
replacements are written here, not applied.

---

## ADR-001 — Frontend: TanStack Start 1.0

**Decision (as written).** SSR React on Workers via the Cloudflare Vite plugin; React Router v8 fallback.

**Evidence for.** 1.0 shipped 2026-10-13 with an explicit API-stability commitment after a ~13-month RC.
Cloudflare maintains a first-party framework guide (plugin order, `main: @tanstack/react-start/server-entry`,
`nodejs_compat`, custom entrypoints for Queues/DO/Workflows, bindings via `cloudflare:workers`) — i.e. our exact
worker shape is the documented path. Middleware is mature and carries context across server functions, which is
where `TenantContext` must live. The team's React skills transfer from V5.

**Evidence against.** The stated alternative rationale is **factually wrong**: SPA mode and static prerendering
*are* supported with the Cloudflare plugin (prerender since 2025-12-19; requires `react-start >= 1.138.0`). An
open bug (#7740) means `_shell.html` is a full SSR of the mask route, and Start emits `/_shell.html` where
Cloudflare Static Assets expects `/index.html` for a SPA fallback. Rsbuild-based projects are unsupported on
Cloudflare. RSC support is opt-in and its author does not use it on tanstack.com. A reflected-XSS CVE
(CVE-2026-102989) was fixed 2026-09-30 and there was an npm supply-chain compromise in May 2026 — this stack
requires disciplined patch uptake. No first-party auth (the docs partner with WorkOS/Clerk and point DIY
implementers at Better Auth).

**Alternatives.** React Router v8 (equally supported, more conservative, weaker SSR story); Next.js + OpenNext
(Cloudflare now positions OpenNext as the path for *existing* apps); vinext (docs say beta, blog says 1.0 —
unresolved); SvelteKit/Nuxt (skills loss).

**Recommendation.** **ACCEPT WITH CHANGES.** Keep TanStack Start. Replace the false claim in the rationale with
the real trade-off: *React Router v8 is the safer, less capable option; Start is the better fit and its Cloudflare
path is first-party*. Pin exact versions, and make "upgrade within 7 days of a security release" a standing
policy.

**Confidence.** High. **Follow-up.** Correct ADR-001 text; add patch-policy requirement to
`SECURITY_REQUIREMENTS.md`; verify the shell bug before choosing SPA mode over SSR.

---

## ADR-002 — Topology: one Worker first

**Decision.** Apex Custom Domain serves marketing + app + `/api/v1`; split to `app.` later.

**Evidence for.** One deploy, shared design system, no cross-zone OAuth callback. Custom Domains are
exact-hostname, so `www` needs a redirect rule and `app.` is added later without re-architecture.

**Evidence against.** Marketing changes then share a release train with authentication. A typo in a landing page
can take down sign-in, and marketing wants faster, riskier deploys than an auth surface. The document's own
trigger ("when release cadence diverges") is a certainty, not a risk. Static asset navigations bypass the Worker,
so the marketing pages may not even need the Worker — they could ship as a separate static Worker or Pages
project at near-zero cost.

**Alternatives.** Two Workers from the start (OAuth callback across zones — solvable with a static callback
page, which the design already requires); marketing on a separate static host; marketing in the same Worker but
behind a build-time split.

**Recommendation.** **ACCEPT WITH CHANGES.** Keep one Worker for the app, but split marketing to static assets
or a second Worker at **P3**, not "later". Cheap now, removes a whole failure mode.

**Confidence.** Medium-high. **Follow-up.** Add the split as a P3 deliverable and note the static callback page
requirement in the deployment plan.

---

## ADR-003 — Database: one D1 database, shared schema

**Decision.** `workspace_id` on every tenant table, tenant-bound repository.

**Evidence for.** 10 GB hard cap and *no dynamic bindings* genuinely kill database-per-tenant. Single-threaded
execution and a 50 MB result cap are compatible with metadata-only storage. One migration path, trivial
cross-tenant aggregates, cheapest to operate.

**Evidence against.** No RLS and no interactive transactions: multi-statement invariants must be expressed as a
single `db.batch()`, which also counts as one query against the 1,000-per-invocation budget and must finish
inside 30 s. A batch cannot span requests, so *any* read-modify-write needs a version guard. The 10 GB wall is
real but farther than the cost doc claims (see COST-02). D1 has no clone/branch, so schema experiments happen
against exports.

**Alternatives.** Database-per-tenant (rejected correctly); Postgres + Hyperdrive (rejected on latency and a
second vendor — the reasoning is sound at this scale); libSQL/Turso (not evaluated in the package — worth a
sentence, since it offers SQLite semantics with more headroom).

**Recommendation.** **ACCEPT.** Add the missing constraints the design implies: `CHECK (awarded BETWEEN 0 AND
max_marks)`, tenant-consistency triggers, and a documented batch-size policy.

**Confidence.** High. **Follow-up.** See DATABASE_API_AUDIT DB-01…DB-12.

---

## ADR-004 — Isolation: four layers, server-minted `TenantContext`

**Decision.** Session → membership → context → `workspace_id` in every predicate; 404 not 403.

**Evidence for.** The only defensible model without RLS. A branded type makes an unscoped call inexpressible,
which is stronger than review. 404-not-403 is correctly chosen and the isolation suite tests for it explicitly.

**Evidence against.** The "fails to compile" property depends on a lint rule and a branded type that do not exist
yet — as written it is an intention. Nothing at the database layer rejects a cross-tenant row: a bug in one
INSERT path writes a `submission` whose `assignment_id` belongs to another workspace, and every subsequent
scoped read by that workspace will not see it (the leak is *downward*, into the wrong tenant's data, and it is
invisible to the isolation suite because the row is queried by its own `workspace_id`).

**Alternatives.** Postgres RLS (unavailable); per-tenant DBs (rejected); **SQLite triggers** (available and not
mentioned) — a `BEFORE INSERT` trigger can assert `EXISTS(SELECT 1 FROM assignments WHERE id=NEW.assignment_id
AND workspace_id=NEW.workspace_id)` and `RAISE(ABORT)`.

**Recommendation.** **ACCEPT WITH CHANGES.** Keep the model; add database-level tenant-consistency triggers on
every child table (see DB-03). This closes the one hole the type system cannot.

**Confidence.** High. **Follow-up.** Add trigger DDL to the schema, plus a test that a cross-tenant parent FK is
rejected at write time.

---

## ADR-005 — Auth: Better Auth, self-hosted

**Decision.** Better Auth on Workers + D1, organization plugin, TOTP MFA, passkeys, DB sessions + short cookie
cache.

**Evidence for.** Native D1 support since 1.5 (`database: env.DB`, batch-based atomicity). The organization
plugin covers invitations, roles, `membershipLimit` (default 100, function-configurable) and **teams** as a
sub-organisation layer. 2FA plugin is GA; passkeys GA via `@better-auth/passkey`. No licence cost, full data
control.

**Evidence against (all verifiable, none hypothetical).**
1. **In-memory rate limiting by default** — the docs warn it is unsuitable for serverless; per-isolate counters
   mean the auth brute-force protection silently does nothing across isolates. Storage must be set to database.
2. **2FA does not gate passkey, OAuth/social, magic-link or email-OTP sign-in** by default. `AU-4` ("MFA
   required for owner and platform_operator") is therefore **not achievable by configuration alone**.
3. **No absolute session timeout** and a 7-day sliding default; OWASP recommends 4–8 h absolute for an
   office-hour application holding minors' data. `AU-6`'s "7-day idle / 30-day absolute" is far outside that.
4. **Cookie-cache staleness**: revoked sessions and changed roles remain usable until `maxAge` expires. The
   package claims the server "busts it on role change" — Better Auth provides no such per-session bust; the
   window is `maxAge`, full stop.
5. **scrypt cost parameters are unpublished**, and third-party evidence puts them at `N=2^14`, below OWASP's
   `N=2^17` recommendation; hashing on Workers needs `nodejs_compat`.
6. **Advisory history**: an organization-invitation ownership issue (GHSA-fmh4-wcc4-5jm3, High, fixed 1.6.11),
   OAuth account-linking ownership (High), device-flow binding (High), and critical SSO/OIDC issues in the SSO
   and OAuth-provider sub-packages (not used here, but they illustrate the cadence). Pin **≥ 1.7.16** and audit
   scoped packages, not just `better-auth`.
7. **No interactive transactions on D1** weakens password-reset/session-revocation atomicity.

**Alternatives.** Clerk (~$25 + $100 B2B/mo, member caps, best DX); Auth0 (org caps, upsell per connection);
WorkOS (free AuthKit, $125/connection for SSO — right as a bolt-on, not as the base); Supabase Auth (drags in
Postgres); Cloudflare Access (correctly rejected: not customer auth).

**Recommendation.** **ACCEPT WITH CHANGES.** Keep Better Auth, but add a mandatory *auth configuration ADR* that
pins: rate-limit storage = database, `maxAge` ≤ 60 s (or cookie cache disabled), session `expiresIn` ≤ 12 h with
an absolute cap enforced by a custom field, scrypt parameters raised and measured, `__Host-` cookie prefixes,
`advanced.ipAddress.ipAddressHeaders: ['cf-connecting-ip']`, and explicit 2FA hooks for passkey/OAuth sign-in.

**Confidence.** Medium-high. **Follow-up.** These become blocking acceptance criteria for P2 (SEC-02…SEC-05).

---

## ADR-006 — Files: R2 with Worker-signed URLs

**Decision.** `ws/{workspaceId}/…` keys, 15-minute upload targets, 5-minute downloads, multipart above 50 MB.

**Evidence for.** Workspace-prefixed keys are the right tenancy mechanism and make traversal impossible when
server-derived. Free egress is a genuine cost advantage. No public bucket, no `r2.dev` in production.

**Evidence against.** The economic rationale is wrong (R2 presigning exists, 1 s – 7 days). Proxying every byte
through the Worker is the expensive path for 50–200 MB uploads and is not resumable. `Range` requests against
static assets return the full body, so the design already concedes ranged PDF streaming must go through the
Worker.

**Alternatives.** S3 presigned PUT/GET with a scoped token in Secrets; hybrid (proxy < 20 MB, presign above).

**Recommendation.** **ACCEPT WITH CHANGES.** Choose the hybrid and correct the rationale. Keep the 5-minute
download TTL — it is defensible and cheap.

**Confidence.** Medium. **Follow-up.** Measure Worker duration for a 40 MB upload in P1; if it exceeds 2 s of
CPU, presigning is mandatory.

---

## ADR-007 — Jobs: Queues + Workflows, ids-only messages

**Decision.** Ids-only messages, lease claim, 8-step idempotent Workflow, classified retry ported from V5.

**Evidence for.** Correct separation; ids-only is the right answer to the 128 KB cap; Workflows provide durable
multi-step state with unlimited per-step wall time and `step.sleep` up to 365 days, which is exactly the park
primitive V5 needs. Porting the retry classification verbatim is the single best decision in the package.

**Evidence against.** ARC-01 (no outbox) and ARC-02 (no reaper) make the pipeline lossy in exactly the cases the
product promise covers. Workflow step retries must be explicitly disabled for the provider step or they will
double-charge. Queues' default `max_retries` of 3 with no DLQ means a poison message disappears.

**Alternatives.** Durable Object alarm orchestration (rejected — couples state and orchestration, and the DO is
already over-used); single long consumer (no durable step state).

**Recommendation.** **ACCEPT WITH CHANGES.** Outbox + lease reaper + real DLQ + explicit per-step retry
configuration. With those four, this ADR becomes the strongest part of the architecture.

**Confidence.** High after changes. **Follow-up.** Add to P5 acceptance: kill a Workflow mid-run and assert
convergence.

---

## ADR-008 — Realtime: one hibernating Durable Object per workspace

**Decision.** WS hub per workspace, 30 s single-use ticket, coalesced progress, polling fallback.

**Evidence for.** The ticket design correctly closes the classic WebSocket auth hole, and `membership.changed`
closing sockets is a genuinely good control. Hibernation does remove idle duration billing.

**Evidence against.** ARC-03: at 5–10 users per workspace on an asynchronous product, polling is cheaper and
simpler, and the DO adds a stateful surface (tickets, per-message permission rechecks, replay cursors, class
migrations) before any measured need. The cost model for the DO is also missing from the cost doc.

**Alternatives.** Polling only (documented as the fallback); SSE from the Worker (no fan-out); DO as designed.

**Recommendation.** **DEFER.** Implement polling in P5, keep the DO design as the documented upgrade path, and
re-open the ADR if P5 telemetry shows progress latency is a problem. This is the one place the package
over-engineers, and the fix is to build less.

**Confidence.** Medium-high. **Follow-up.** Move the ticket/socket requirements out of P5 acceptance criteria.

---

## ADR-009 — Billing deferred, metering now

**Decision.** No billing in MVP; `usage_events` + `usage_daily` + quotas from P5.

**Evidence for.** Correct sequencing; retrofitting metering is impossible, retrofitting billing is routine.
Keeping pricing out avoids blocking P1–P4 on a commercial decision.

**Evidence against.** `usage_events` has no uniqueness constraint, so a retried step or replayed message can
double-count and corrupt the only data pricing will ever be based on (DB-07). Quota enforcement "must fail
closed" is stated but no failure path is designed for the case where the quota check itself fails.

**Alternatives.** Stripe from day one (blocks on pricing); no metering (unforgivable).

**Recommendation.** **ACCEPT WITH CHANGES.** Add `UNIQUE(workspace_id, job_id, attempt_no, kind)` and a
documented quota-check failure mode.

**Confidence.** High. **Follow-up.** DB-07; add a metering-reconciliation test (sum of events = rollup).

---

## ADR-010 — Design language: continue "Instrument"

**Decision.** Build on `ui-identity-v6.md` with an annotation callout and denser markbook table.

**Evidence for.** The direction is specified to token level, degrades gracefully to print, and is the only one in
the package with prior validation. The refusal list (no gradient heroes, no nested cards, no pill statuses) is
specific and useful. Contrast pairs mostly check out: recomputation gives roughly 4.8:1 for `cyan.600` on
`paper.50` and 4.66:1 for `amber.700` — both pass AA for normal text, though the document's stated 5.1:1 and
4.8:1 are slightly optimistic and should be measured, not asserted.

**Evidence against.** 11 px uppercase micro-labels are the smallest type in the system and carry table headers;
at 125 % OS scaling common in schools this needs verification, not assumption. Dark-theme status hues are claimed
to "shift +1 step lighter to hold 4.5:1" without values — a claim without a number.

**Alternatives.** D2/D4/D5/D6 evaluated in the source document with a defensible scoring table.

**Recommendation.** **ACCEPT.** Add measured contrast values for dark-theme status tokens and a minimum-size
rule for micro labels.

**Confidence.** High. **Follow-up.** Token contrast test in P3 acceptance (already gated by axe, but axe will not
catch a 4.4:1 pair behind a custom token).

---

## ADR-011 — Marking parity before redesign

**Decision.** P1 proves V5 parity on ≥ 20 fixtures before the design system or any screen is redrawn.

**Evidence for.** The strongest sequencing call in the package. Marks are the product; a beautiful surface over
drift is worse than no surface. It also forces the PDF/container decision early.

**Evidence against.** Parity on the happy path is not parity: the value of V5 lives in the *failure* paths —
`needs_review` on a missing question, the result guard refusing an overwrite, the park/retry table. P1's
acceptance criteria (`ACCEPTANCE_CRITERIA.md` §2) test the happy path plus missing-question handling, but not
retry/park parity or guard behaviour.

**Alternatives.** Design first (rejected correctly); parallel tracks (invalidated by drift).

**Recommendation.** **ACCEPT WITH CHANGES.** Add to P1: replay a recorded 429/503/401 sequence and assert the
same classification and budget behaviour as V5; assert the overwrite guard blocks a valid-mark replacement.

**Confidence.** High. **Follow-up.** Extend P1 acceptance criteria.

---

## ADR-012 — Data lifecycle: soft delete entities, keep jobs, hard-delete files

**Decision.** `deleted_at` on corrections/results; terminal job rows retained; R2 hard delete on workspace purge.

**Evidence for.** Recovery matters more than row hygiene at this scale; audit needs the trail.

**Evidence against.** Soft delete collides with the workspace-scoped uniqueness constraints: `submissions` has
`UNIQUE(ws, assignment_id, student_id)`, so a soft-deleted submission blocks a legitimate re-upload for the same
student and assignment. The same applies to `memberships` (re-inviting a removed member) and `classes`.
Nothing in the package resolves this.

**Alternatives.** Hard delete with audit (loses recovery); soft delete with partial unique indexes
(`UNIQUE(ws, assignment_id, student_id) WHERE deleted_at IS NULL` — supported by SQLite).

**Recommendation.** **ACCEPT WITH CHANGES.** Convert the affected unique constraints to partial indexes.

**Confidence.** High. **Follow-up.** DB-04.

---

## ADR-013 — Testing: isolation as a compile-time and CI gate

**Decision.** Repository is the only DB entry point; lint bans raw `env.DB`; isolation suite blocks merge.

**Evidence for.** Correct and cheap. The 16-resource matrix with three request shapes each is thorough, and
asserting 404-not-403 in the *body* is the right level of rigour.

**Evidence against.** C2 (simultaneous approval) is explicitly left undecided — "409 or 200, decided behaviour" —
inside a suite that is declared blocking. A blocking test cannot contain an undecided assertion. C5 relies on
leases that ARC-02 shows do not exist yet.

**Alternatives.** Review-only discipline (rejected correctly).

**Recommendation.** **ACCEPT WITH CHANGES.** Decide C2 now: idempotent `200` for the same actor, `409` for a
different actor. Add a trigger-level test (ADR-004).

**Confidence.** High. **Follow-up.** Close C2 in `TENANT_ISOLATION_TESTS.md`.

---

## ADR-014 — Observability: platform-native first

**Decision.** Workers Logs, Analytics Engine, `usage_events`, `/health`, correlated ids; no third-party APM until
P6.

**Evidence for.** Right-sized for a small team; the log field allowlist with a canary test is better than most
commercial setups; audit-vs-log separation is correct.

**Evidence against.** The signal list omits the two failure modes that actually threaten the promise: jobs stuck
in `queued` with no message (ARC-01) and jobs stuck `running` past lease (ARC-02). Signal #3 (queue depth) will
look healthy in both cases because the queue is empty.

**Alternatives.** Sentry/Datadog day one (premature).

**Recommendation.** **ACCEPT WITH CHANGES.** Add "jobs older than 15 min in `queued` with no outbox publish" and
"leases expired > 10 min" as paging signals.

**Confidence.** High. **Follow-up.** REL-02.

---

## ADR-015 — V5 migration is export/import, not shared storage

**Decision.** V5 stays source of truth until P1 parity; migration reads V5 SQLite exports and writes through the
public API path.

**Evidence for.** Exercising real code paths during import is the right instinct; preserving `CH1L1` identities
as external references is correct.

**Evidence against.** It **contradicts two other documents**: `OPEN_QUESTIONS.md` Q5 defaults to "**No automatic
migration**; document a manual path", and `DATABASE_DESIGN.md` §8 states "No V5 data is migrated
automatically". One of the three must give. It also commits engineering effort (an importer that writes through
the API, at API pace) before Q5 is answered.

**Alternatives.** No importer (Q5 default); direct table copy (rejected correctly); dual-write (rejected
correctly).

**Recommendation.** **DEFER.** Downgrade to "if Q5 answers yes, the importer's *shape* is API-mediated" and
remove the implication that migration is built. Keep the identity-preservation rule.

**Confidence.** High. **Follow-up.** DOC-04.

---

## Summary

| ADR | Verdict | Blocking? |
|---|---|---|
| 001 Frontend | Accept with changes | No |
| 002 Topology | Accept with changes | No |
| 003 Database | Accept | No |
| 004 Isolation | Accept with changes | **Yes** (DB-03) |
| 005 Auth | Accept with changes | **Yes** (SEC-02…05) |
| 006 Files | Accept with changes | No |
| 007 Jobs | Accept with changes | **Yes** (ARC-01/02) |
| 008 Realtime | **Defer** | No |
| 009 Billing/metering | Accept with changes | No |
| 010 Design | Accept | No |
| 011 Parity first | Accept with changes | No |
| 012 Lifecycle | Accept with changes | **Yes** (DB-04) |
| 013 Testing | Accept with changes | No |
| 014 Observability | Accept with changes | No |
| 015 V5 migration | **Defer** | No |
