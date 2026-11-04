# Revised Architecture Decisions

**Status:** RECOMMENDED. `decisions/ARCHITECTURE_DECISIONS.md` is unmodified and remains the record of what was
decided in Phase 1. This document is the Phase-2 record: for each ADR, the original decision, the evidence that
survived review, the proposed decision and its status.

**Statuses** (closed vocabulary): `ACCEPTED` · `ACCEPTED WITH CHANGES` · `DEFERRED` · `REJECTED` ·
`REQUIRES OWNER APPROVAL`.

No accepted decision was changed silently. Every change below names the finding that forced it and the evidence
that supports it.

| ADR | Area | Phase-1 status | Phase-2 status |
|---|---|---|---|
| 001 | Frontend | Accepted | **ACCEPTED WITH CHANGES** |
| 002 | Topology | Accepted | **ACCEPTED WITH CHANGES** |
| 003 | Database | Accepted | **ACCEPTED** (constraints added under 004) |
| 004 | Isolation | Accepted | **ACCEPTED WITH CHANGES** |
| 005 | Auth | Accepted | **ACCEPTED WITH CHANGES** |
| 006 | Files | Accepted | **ACCEPTED WITH CHANGES** |
| 007 | Jobs | Accepted | **ACCEPTED WITH CHANGES** |
| 008 | Realtime | Accepted | **DEFERRED** |
| 009 | Billing / metering | Accepted | **ACCEPTED WITH CHANGES** |
| 010 | Design language | Accepted | **ACCEPTED** |
| 011 | Parity before design | Accepted | **ACCEPTED WITH CHANGES** |
| 012 | Data lifecycle | Accepted | **ACCEPTED WITH CHANGES** |
| 013 | Testing gates | Accepted | **ACCEPTED WITH CHANGES** |
| 014 | Observability | Accepted | **ACCEPTED WITH CHANGES** |
| 015 | V5 migration | Accepted | **DEFERRED** |
| 016 | Auth configuration | — | **REQUIRES OWNER APPROVAL** (new) |
| 017 | Report rendering host | — | **REQUIRES OWNER APPROVAL** (new) |
| 018 | Permission model | — | **ACCEPTED WITH CHANGES** (new) |
| 019 | Backup architecture | — | **REQUIRES OWNER APPROVAL** (new) |
| 020 | Support access | — | **ACCEPTED WITH CHANGES** (new) |
| 021 | Job durability | — | **ACCEPTED** (new) |
| 022 | API keys | — | **ACCEPTED** (new) |
| 023 | Platform operator identity | — | **ACCEPTED** (new) |

---

## 1. The original fifteen

### ADR-001 — Frontend: TanStack Start 1.0

**Original decision.** TanStack Start 1.0 (SSR React) on Workers via the Cloudflare Vite plugin; React Router v8
as the fallback.
**Original reasoning.** 1.0 shipped 2026-10-13 after a long RC with an API-stability commitment; Cloudflare
documents the exact worker shape used here (plugin order, server entry, `nodejs_compat`, custom entrypoints for
Queues/DO/Workflows); middleware carries context across server functions, which is where `TenantContext` must
live. React Router was rejected because "SPA mode and prerendering are unsupported behind the Cloudflare plugin".
**Audit findings.** `ADR_REVIEW` ADR-001; the rejection rationale is factually wrong. `ARC platform table` #2.
**Independently verified.** Prerendering shipped 2025-12-19 (`prerender: { enabled: true }`, needs
`react-start ≥ 1.138.0`); SPA mode is documented. One **open** bug (#7740) makes `_shell.html` a full SSR of the
mask route, and Cloudflare's static-asset layer expects `/index.html` for a SPA fallback. OpenNext is documented
for *maintaining* existing Next apps — not "maintenance mode" in the sense the package used. vinext is beta in
docs and "1.0 production-ready" in Cloudflare's blog: unresolved, and therefore not a basis for a decision.
**Proposed decision.** **ACCEPTED WITH CHANGES.** Keep Start. Replace the false rationale with the real
trade-off: *React Router v8 is the safer, less capable option; Start fits better and its Cloudflare path is
first-party.* Pin exact versions; adopt "upgrade within 7 days of a security release" as a standing policy
(the reflected-XSS CVE fixed 2026-09-30 and the May-2026 npm compromise are the reason).
**Alternatives rejected.** React Router v8 (viable, weaker SSR story — retained as the written fallback); Next.js
+ OpenNext (wrong for greenfield); vinext (status unresolved); SvelteKit/Nuxt (skills loss).
**Trade-offs.** Youngest stable option; requires disciplined patch uptake; SSR-only (SPA mode not used).
**Consequences.** `SECURITY_REQUIREMENTS` gains a patch-policy requirement; the shell bug is checked before
choosing SPA mode.
**Confidence.** High. **Approval.** Not required (correction of rationale, not of decision).

### ADR-002 — Topology: one Worker first

**Original decision.** Apex Custom Domain serving marketing + app + `/api/v1`; split to `app.` later.
**Original reasoning.** One deploy, shared design system, no cross-zone OAuth callback problem.
**Audit findings.** `ADR_REVIEW` ADR-002: marketing shares a release train with authentication, and the stated
trigger ("when release cadence diverges") is a certainty rather than a risk. Static navigations bypass the
Worker, so marketing may not need it at all.
**Independently verified.** Custom Domains are exact-hostname, so `www` needs a redirect rule; static asset
navigations are non-billable and bypass the Worker; the OAuth callback page can be static.
**Proposed decision.** **ACCEPTED WITH CHANGES.** Keep one Worker for the app; split marketing to static assets
or a second Worker at **P3**, not "later".
**Alternatives rejected.** Two Workers day one (OAuth across zones — solvable but unnecessary); Routes in front
of a Custom Domain (same-zone fetch needs a service binding).
**Trade-offs.** A second deploy target early; slightly more CI wiring.
**Consequences.** A landing-page typo can no longer take down sign-in. The static callback page becomes a P2
deliverable.
**Confidence.** Medium-high. **Approval.** Not required.

### ADR-003 — Database: one D1 database, shared schema

**Original decision.** `workspace_id` on every tenant table; tenant-bound repository.
**Original reasoning.** The 10 GB hard cap and the absence of dynamic bindings genuinely kill database-per-tenant;
metadata-only storage fits comfortably; one migration path.
**Audit findings.** `ADR_REVIEW` ADR-003 **ACCEPT**; `DATABASE_API_AUDIT` adds constraints and corrects the
storage arithmetic.
**Independently verified.** 10 GB cannot be raised; no dynamic bindings; single-threaded; 50 MB result cap from
2026-11-04; `db.batch()` is one transaction and counts as one query.
**Proposed decision.** **ACCEPTED.** Unchanged. The constraints the design implies are added under ADR-004 and
ADR-012, and the storage projection is corrected (4.4–6.1 KB/submission, ~3–4 years to the wall at 100
workspaces with the stated retention).
**Alternatives rejected.** Database-per-tenant (dead on dynamic bindings and the cap); Postgres + Hyperdrive
(~50 ms/query, second vendor, 25-config limit) — correct rejection at this scale, and still the escape hatch if a
contract ever demands database-level isolation.
**Trade-offs.** Isolation stays application-enforced. Accepted, with triggers and a typed repository as
compensating controls.
**Consequences.** Nothing structural. The alternative "libSQL/Turso" is worth one paragraph in the record and was
not evaluated in Phase 1; it is not adopted because it trades a verified platform for an unverified one.
**Confidence.** High. **Approval.** Not required.

### ADR-004 — Isolation: four layers with a server-minted `TenantContext`

**Original decision.** Session → membership → context → `workspace_id` in every predicate; 404 not 403.
**Original reasoning.** The only defensible model without RLS; a branded type makes an unscoped query
inexpressible.
**Audit findings.** `SEC-05`, `DB-03`: the "impossible by construction" claim is a code convention, and the
resulting row is invisible to the isolation suite because it is written with the *wrong* tenant's
`workspace_id`.
**Independently verified.** SQLite supports `BEFORE INSERT`/`BEFORE UPDATE OF` triggers with `RAISE(ABORT)`;
triggers may reference `NEW` columns; a trigger check is an indexed primary-key probe.
**Proposed decision.** **ACCEPTED WITH CHANGES.** Keep the model; add tenant-consistency triggers on every child
table (23 tables, both insert and update variants), plus a schema-enumeration test that fails when a new table
arrives without one.
**Alternatives rejected.** Composite FKs on `(workspace_id, id)` — valid, but doubles parent index size and yields
an opaque error; triggers chosen for diagnosability.
**Trade-offs.** One primary-key probe per write; triggers must be maintained as the schema grows.
**Consequences.** The `TenantContext` type is strengthened from a convention-plus-review into a convention-plus-
constraint. `T-DB-01/02` prove it.
**Confidence.** High. **Approval.** Not required (schema hardening).

### ADR-005 — Auth: Better Auth, self-hosted

**Original decision.** Better Auth on Workers + D1, organization plugin, TOTP, passkeys, DB sessions + short
cookie cache.
**Original reasoning.** Native D1 support, org/invitation/role primitives, no licence cost, full data control.
**Audit findings.** `SEC-02` (2FA does not gate passkey/OAuth), `SEC-03` (in-memory rate limiting), `SEC-08`
(session lifetime, no cache bust), `DB-01` (schema mismatch), `SEC-07` (three roles vs six).
**Independently verified (this phase).** Version **1.7.16** (2026-11-03 security release). Columns are
**camelCase** by default and renameable via `fields`; the password lives in `account.password` for
`providerId='credential'`; TOTP secrets in `twoFactor`; `twoFactor.failedVerificationCount` and `lockedUntil`
already exist; `member.role` is a comma-separated string and custom roles are declared with
`createAccessControl`; `rateLimit.storage = "database"` is supported with a `rate_limit` table; 1.7 requires
date-typed timestamps (text breaks `max_age`); **runtime schema validation is on by default in production**, so a
mismatched schema rejects every request; revocation deletes the session row, so only the cookie cache is stale.
**Proposed decision.** **ACCEPTED WITH CHANGES.** Keep Better Auth; pin `>= 1.7.16`; adopt its schema as canonical
with product columns via `additionalFields`; move MFA enforcement into an application assurance gate; set
`cookieCache.maxAge = 60`, 12 h idle / 7 d absolute; `rateLimit.storage = "database"` plus application-level
per-account lockout; declare five workspace roles.
**Alternatives rejected.** Clerk (cost, member caps), Auth0 (org caps), WorkOS (right as an SSO bolt-on, wrong as
the base), Supabase Auth (drags in Postgres), Cloudflare Access (not customer auth).
**Trade-offs.** We own upgrades and schema; the library's 2FA is a mechanism, not a policy.
**Consequences.** Session lifetime and MFA trade-off are owner decisions (`C2`, `C3`); see ADR-016.
**Confidence.** Medium-high. **Approval.** Required for the two product-visible settings.

### ADR-006 — Files: R2 with Worker-signed URLs

**Original decision.** `ws/{workspaceId}/…` keys; 15-minute upload targets; 5-minute download URLs; multipart
above 50 MB.
**Original reasoning.** Correct tenancy in keys, free egress, no public bucket. Presigning rejected because it
"needs long-lived R2 credentials we will not hold".
**Audit findings.** `ARC-05`, `REL-03`: the presigning rationale is false; proxying every byte makes the most
expensive request type more expensive and blocks validation; and the backup story depended on R2 versioning that
does not exist.
**Independently verified.** Presigned URLs exist (1 s–7 days). `CopyObject`/`UploadPartCopy` are server-side,
Class A, no egress. Per-key write concurrency is ~1/s. R2 has no versioning or replication. Bucket locks exist
(prefix-scoped, up to 1,000 rules, strictest wins). `CRC64NVME` with `FULL_OBJECT` is the only whole-object
checksum for multipart; multipart ETags are not a reproducible whole-object MD5.
**Proposed decision.** **ACCEPTED WITH CHANGES.** **Hybrid transport:** downloads proxied through the Worker with
`Range` (no bearer URLs); uploads ≤ 20 MB proxied, > 20 MB presigned `PUT` with a scoped token and a single key,
15-minute expiry. Keys unchanged. Multipart above 50 MB retained.
**Alternatives rejected.** Presign everything (worse validation, worse UX for the common small file); proxy
everything (200 MB through a Worker, no resumability).
**Trade-offs.** Two upload paths is one more code path; the proxy keeps authorisation revocable.
**Consequences.** `ADR-019` supplies the backup half. `T-FILE-01…05` cover both paths.
**Confidence.** Medium (the hybrid ratio is a judgement; the 20 MB threshold is revisited after measuring a 40 MB
upload).
**Approval.** Required — it changes the upload path (`C4`).

### ADR-007 — Jobs: Queues + Workflows with ids-only messages

**Original decision.** Enqueue `{jobId, workspaceId}`; consumer claims a lease; eight-step idempotent Workflow;
retry classification ported from V5.
**Original reasoning.** Correct separation, correct answer to the 128 KB cap, durable multi-step state,
`step.sleep` for parks.
**Audit findings.** `ARC-01` (**CRITICAL**), `ARC-02`, `ARC-06`, `REL-05/07/10`: the pipeline loses work silently
in two places and a poison message disappears.
**Independently verified.** Queues are at-least-once; `max_retries` defaults to 3; the message is deleted at max
retries unless a DLQ is configured; Workflow instance ids are unique, so re-queuing a job whose instance still
exists cannot double-start it.
**Proposed decision.** **ACCEPTED WITH CHANGES.** Add the transactional outbox, the lease reaper, a real DLQ with
a consumer, attempts-on-claim, and a provider-recovery sweep. Keep ids-only messages and the retry table.
**Alternatives rejected.** Retry loop around `send()` (closes half the failure); second queue (moves the
boundary, does not create one); DO alarms (couples orchestration to state).
**Trade-offs.** Up to 60 s publisher latency; two extra tables and two crons.
**Consequences.** The ≥ 99 %/24 h promise becomes supportable and observable. `ADR-021` records the mechanism.
**Confidence.** High after changes. **Approval.** Required for the schema change (`C5` bundles it).

### ADR-008 — Realtime: one hibernating Durable Object per workspace

**Original decision.** WS hub per workspace, 30 s single-use ticket, coalesced progress, polling fallback.
**Original reasoning.** Hibernation removes idle duration billing; the ticket closes the classic socket-auth hole.
**Audit findings.** `ARC-03`, `COST-03`, `UX-12`: the workload (5–10 users per workspace, asynchronous handoff)
does not justify a stateful component, and the DO line in the cost model is underived.
**Independently verified.** DO incoming WS messages bill at 20:1; ~1,000 req/s soft per object; hibernation works
as described; polling `/jobs` from 10 users every 10 s is ~86 k requests/day, inside the included allowance.
**Proposed decision.** **DEFERRED.** P5 ships polling with an ETag ladder. The DO design is preserved in
`DURABLE_OBJECT_DEFERMENT_PLAN.md` with numeric promotion thresholds.
**Alternatives rejected.** Build it now (spends a stateful surface on an unmeasured need); SSE from a Worker (no
fan-out primitive, same operational surface without the benefit).
**Trade-offs.** Progress granularity is seconds, not sub-second; presence is unavailable.
**Consequences.** P5 acceptance criteria lose the socket requirements; the ticket design is retained on paper.
**Confidence.** Medium-high. **Approval.** Required to ratify the deferral (`C13`).

### ADR-009 — Billing deferred, metering built now

**Original decision.** No billing in the MVP; `usage_events` + `usage_daily` + quotas from P5.
**Original reasoning.** Retrofit metering is impossible; retrofit billing is routine.
**Audit findings.** `DB-07` (double counting, undefined rollup), `COST-06` (AI dominance implicit), `AB-3`
(fail-closed quota with no failure path).
**Independently verified.** Append-only events with no uniqueness can double-count under at-least-once delivery;
`ON CONFLICT DO UPDATE` gives replace semantics; SQLite treats NULLs as distinct in unique indexes, so a partial
index is required for job-keyed idempotency.
**Proposed decision.** **ACCEPTED WITH CHANGES.** `UNIQUE(ws, job_id, attempt_no, kind) WHERE job_id IS NOT NULL`,
`UNIQUE(ws, source_key, kind) WHERE source_key IS NOT NULL`, day rollup recomputed from events over a two-day
window, quota check inside the job-creation batch.
**Alternatives rejected.** Stripe day one (blocks on pricing); no metering (unforgivable).
**Trade-offs.** A couple of index rows per job; a two-day recompute each hour.
**Consequences.** The metering data is now safe to price from.
**Confidence.** High. **Approval.** Not required.

### ADR-010 — Design language: continue "Instrument"

**Original decision.** Build on `ui-identity-v6.md`; ink-graphite, cyan-teal, ledger tables, specified type stack.
**Original reasoning.** The only direction with prior validation; refusal list is specific and useful.
**Audit findings.** `ADR_REVIEW` ADR-010 **ACCEPT**, with two measurement gaps: 11 px micro-labels at 125 % OS
scaling, and dark-theme status hues asserted to hold 4.5:1 without values.
**Independently verified.** Recomputing the stated pairs gives ~4.8:1 and ~4.66:1 — both pass AA, both slightly
better than claimed in one case and worse in another, which is exactly why measurement beats assertion.
**Proposed decision.** **ACCEPTED.** Add a measured contrast table for dark-theme status tokens and a 12 px floor
for micro-labels.
**Alternatives rejected.** A new identity (discards an approved direction for novelty); a generic admin template.
**Trade-offs.** Slightly less dense tables at 12 px; measurable accessibility.
**Consequences.** P3 acceptance gains a token-contrast test that axe cannot perform on custom tokens.
**Confidence.** High. **Approval.** Not required.

### ADR-011 — Marking parity before redesign

**Original decision.** P1 proves V5 parity on ≥ 20 fixtures before the design system or any screen.
**Original reasoning.** Marks are the product; a beautiful surface over drift is worse than none.
**Audit findings.** `ADR_REVIEW` ADR-011: parity on the happy path is not parity — V5's value lives in the
failure paths (`needs_review`, the overwrite guard, the park/retry table), and P1's criteria test only the happy
path plus missing-question handling.
**Independently verified.** Reading `FEATURE_INVENTORY` §1–2 confirms the failure-path machinery is classified
`A` (preserve as-is), i.e. it is in scope and untested by the stated criteria.
**Proposed decision.** **ACCEPTED WITH CHANGES.** P1 additionally replays a recorded 429/503/401 sequence and
asserts identical classification and budget behaviour to V5, and asserts the overwrite guard blocks a valid-mark
replacement.
**Alternatives rejected.** Design first (rejected correctly in Phase 1); parallel tracks.
**Trade-offs.** P1 grows by perhaps two days.
**Consequences.** Parity becomes a permanent regression gate covering behaviour, not just totals.
**Confidence.** High. **Approval.** Not required.

### ADR-012 — Data lifecycle: soft delete entities, keep jobs, hard-delete files

**Original decision.** `deleted_at` on corrections/results; terminal job rows retained; R2 hard delete on purge.
**Original reasoning.** Recovery matters more than row hygiene; audit needs the trail.
**Audit findings.** `DB-04` (soft delete collides with every workspace-scoped unique constraint), `UX-07`
(no erasure path that respects published marks), `DB-11` (append-only audit has no mechanism).
**Independently verified.** SQLite supports partial unique indexes with deterministic predicates; `CHECK` may
reference other columns of the same row; triggers can maintain a parent's derived columns.
**Proposed decision.** **ACCEPTED WITH CHANGES.** Partial unique indexes on `submissions`, `member`, `students`,
`invitation`; student erasure = anonymise + retain numerics + annotate reports; audit `UPDATE` blocked by
trigger and `DELETE` permitted only inside a maintenance window.
**Alternatives rejected.** Hard delete everywhere (loses recovery and audit); soft delete everywhere (rows
accumulate and every query needs a filter).
**Trade-offs.** Partial indexes are slightly less obvious in review; the maintenance-window pattern is unusual
and must be documented where the purge runs.
**Consequences.** Re-upload, re-invite and erasure all work without hard deletes.
**Confidence.** High. **Approval.** Required for the erasure policy (`C11`).

### ADR-013 — Testing: isolation as a compile-time and CI gate

**Original decision.** Repository is the only DB entry point; lint bans raw `env.DB`; isolation suite blocks
merge.
**Original reasoning.** Correct and cheap; asserting 404 in the body is the right rigour.
**Audit findings.** `UX-02`: C2 is undecided inside a blocking suite; `ARC-02`: C5 depends on leases that did not
exist.
**Independently verified.** A blocking suite cannot contain an undecided assertion; both are now decided.
**Proposed decision.** **ACCEPTED WITH CHANGES.** C2 decided (same actor `202`, different actor `409`); add
trigger-level rows (`T-DB-02`), shaper rows (`T-PERM-01`), schema-enumeration (`T-DB-01`) and the route-manifest
test (`T-PERM-08`).
**Alternatives rejected.** Review-only discipline (fails silently); runtime assertions only (catch it after
deploy).
**Trade-offs.** The suite grows by ~15 tests and a few seconds.
**Consequences.** The suite now covers the three failures it previously could not see: a wrongly-scoped row, a
wrongly-shaped response, and an undeclared route.
**Confidence.** High. **Approval.** Not required.

### ADR-014 — Observability: platform-native first

**Original decision.** Workers Logs, Analytics Engine, `usage_events`, `/health`, correlated ids; no third-party
APM until P6.
**Original reasoning.** Right-sized for a small team; allowlisted logs; audit separated from logs.
**Audit findings.** `REL-02`, `REL-10`, `REL-12`: the signal set cannot see the two failures that threaten the
promise (a job with no message; a job with an expired lease), because both look like an empty, healthy queue.
**Independently verified.** Queue depth is genuinely unchanged during a total job loss; the outbox and lease
ages are the only observable proxies.
**Proposed decision.** **ACCEPTED WITH CHANGES.** Add four signals: oldest `job_outbox.published_at IS NULL` age
(paging > 5 min), count of expired leases older than 10 min (paging), oldest non-terminal job age (gauge), DLQ
depth (paging). Add `ops_cron_runs` and a stale-cron alert.
**Alternatives rejected.** Sentry/Datadog day one (premature); full tracing (correlation is enough at this size).
**Trade-offs.** Four more alerts to triage; each has a runbook.
**Consequences.** The monitoring plan can now detect the CRITICAL failure mode it previously could not.
**Confidence.** High. **Approval.** Not required.

### ADR-015 — V5 migration is export/import, not shared storage

**Original decision.** V5 remains the source of truth until P1 parity; migration reads V5 SQLite exports and
writes through the public API path.
**Original reasoning.** Exercising real code paths during import is right; `CH1L1` identities preserved.
**Audit findings.** `DOC-01`: it contradicts `OPEN_QUESTIONS` Q5 ("no automatic migration") and
`DATABASE_DESIGN` §8 ("no V5 data is migrated automatically"). An accepted ADR outranks an open default, so a
reader could start building an importer.
**Independently verified.** Also: an API-paced importer **must not** be run concurrently with marking in the
same workspace at any meaningful volume, which the original decision did not state.
**Proposed decision.** **DEFERRED.** One normative statement replaces three positions: no automatic migration;
if Q5 is answered yes, the importer's *shape* is API-mediated and `CH1L1` identities are preserved, but no
importer is built until that decision is made.
**Alternatives rejected.** Direct table copy (rejected correctly); dual-write (two sources of truth during the
riskiest phase).
**Trade-offs.** V5 users get no continuity by default; the decision is deferred, not removed.
**Consequences.** P1 does not carry importer work. `C15` records the question.
**Confidence.** High. **Approval.** Required — it is a scope change (`C15`).

---

## 2. Why D1 was revisited and kept

The mission asked for particular attention to D1. The outcome is **ACCEPTED**, and the reasoning is worth
recording explicitly because "one shared database for all tenants" looks like a cost decision and is actually a
constraint-driven one:

| Question | Answer |
|---|---|
| Could we give each tenant a database? | No. Bindings are static; opening a new tenant's database at runtime requires a redeploy. The REST fallback is capped at 1,200 requests/5 min per account. |
| Is 10 GB per database enough? | Yes — the schema stores ~4.4–6.1 KB per submission; 100 workspaces grow ~0.35–0.45 GB/month, so ~3–4 years to the wall with the stated retention, not ">10 years". |
| Is single-threaded execution enough? | At 100 workspaces the projection is ~11 req/s average against ~1,000 queries/s. Peak bulk upload is the binding constraint, not steady state. |
| Do we need read replication? | No. It is beta, requires the Sessions API, and solves a problem we do not have. Primary-only reads, behind one helper. |
| What is the escape hatch? | Postgres + Hyperdrive (real RLS) or per-tenant databases for an enterprise tier — both designed for, neither needed below ~250 workspaces. |

The one thing the audit got right that the original did not say: **a batch must also finish inside the 30 s query
limit**, so `db.batch()` is not a licence to do unbounded work in one transaction.

---

## 3. New decisions

### ADR-016 — Authentication configuration

**Context.** `ADR-005` chose the library; it did not pin the settings that decide whether the library's defaults
are safe on Workers. `SEC-02`, `SEC-03` and `SEC-08` are all configurations the package never made.
**Decision.** Pin, in one place: `>= 1.7.16`; `rateLimit.storage = "database"`; `cookieCache.maxAge = 60`;
`expiresIn = 12 h`, `updateAge = 1 h`, absolute 7 d enforced in middleware; `freshAge = 15 min` for step-up;
`__Host-` cookie prefix; `advanced.ipAddress.ipAddressHeaders = ['cf-connecting-ip']`; assurance gate for MFA;
D1-scoped schema generated once and committed.
**Alternatives rejected.** Library defaults (proven unsafe here); a bespoke auth implementation (re-implements
what `ADR-005` bought); cookie cache disabled entirely (one D1 read per request for a 60 s bound).
**Trade-offs.** Twelve-hour sessions mean a marker re-authenticates daily; 60 s is a published staleness window
rather than an invisible one.
**Consequences.** Session length and the 60 s bound are owner decisions (`C2`); everything else is configuration.
**Confidence.** High. **Approval.** **REQUIRES OWNER APPROVAL.**

### ADR-017 — Report rendering host

**Context.** V5 uses ReportLab + PyMuPDF, neither of which runs in a Worker. The package deferred the choice into
the phase that depends on it and costed none of the options.
**Decision.** Three options, one gate. **A** Workers Containers running the existing Python (full parity; gate on
GA and measured cost); **B** a managed render API (full parity; requires a DPA and a sub-processor listing);
**C** client-side print (zero cost, no reproducibility — viewing only, never the authoritative artefact).
P1 measures render time and cost per report; the measured figure enters the budget before P5.
**Alternatives rejected.** C as the authoritative path (a report attached to Classroom must be reproducible and
must exist without a browser); deferring again (P7 cannot start).
**Trade-offs.** A adds an operational surface; B adds a processor holding student data.
**Consequences.** `COST-R §8` cannot be approved with a blank PDF line.
**Confidence.** Medium (option A's GA status is the swing factor). **Approval.** **REQUIRES OWNER APPROVAL.**

### ADR-018 — Permission model: resource-aware, shaper-enforced

**Context.** `SEC-04`/`DOC-02`: three permission footnotes cannot be expressed by `permission → role`.
**Decision.** Two dimensions: `can(ctx, key, resource?)` for scope, and audience-derived `PiiLevel` in the only
serializers. Five roles; `platform_operator` is not a role.
**Alternatives rejected.** Delete the footnotes and accept a weaker policy (loses the cover-staff persona but is
simpler — retained as an owner option in `C12`); per-audience endpoint variants (doubles the route table and the
isolation matrix).
**Trade-offs.** Every result-bearing route must use the shaper; a bypass is a regression risk caught by
`T-PERM-05`.
**Consequences.** The matrix in `USER_ROLES_AND_PERMISSIONS.md` becomes generated, and `T-PERM-04` asserts the
generated matrix equals the policy's behaviour.
**Confidence.** High. **Approval.** **ACCEPTED WITH CHANGES** (the alternative remains open under `C3`).

### ADR-019 — Backup architecture

**Context.** `REL-03`: the documented plan depends on R2 versioning and replication, which do not exist.
**Decision.** Event-notification → Queue → server-side `CopyObject` into a separate, bucket-locked backup bucket,
with a `backup_objects` manifest, nightly reconciliation, sampled digest verification, and rehearsed restores.
Full design in `R2_BACKUP_AND_RECOVERY_DESIGN.md`.
**Alternatives rejected.** State that files are not backed up (honest, but a support engineer deleting a prefix
would be unrecoverable — and the product stores children's scripts); off-provider copy (correct for account-loss
but not needed for MVP).
**Trade-offs.** Storage roughly doubles for scripts; a copy is not a consistent snapshot.
**Consequences.** A new cost line and a new failure surface (the copier), both monitored.
**Confidence.** High (the primitives are documented and verified). **Approval.** **REQUIRES OWNER APPROVAL**
(cost and retention period, `C6`).

### ADR-020 — Support access as a scoped context

**Context.** `SEC-01`: the only deliberate cross-tenant door had no mechanism.
**Decision.** A `support` principal variant bound to a grant id, re-validated per request, read-only by type,
scope-checked per permission, audited per read, visible to the workspace, capped at 72 h, owner-created with
step-up.
**Alternatives rejected.** A session flag (applies to every workspace, survives navigation — the exact failure
`SA-1` exists to prevent); a separate admin UI with direct queries (bypasses the repository and therefore every
tenant control).
**Trade-offs.** More machinery than a flag; three endpoints and one table.
**Consequences.** Moves into P5 (`ROAD-01`) so the control exists before the first external workspace.
**Confidence.** High. **Approval.** **ACCEPTED WITH CHANGES** (timing is `C14`).

### ADR-021 — Job durability: outbox, reaper, DLQ

**Context.** `ARC-01`/`ARC-02`/`ARC-06`.
**Decision.** Outbox row in the same batch as the job; publisher cron with a `published_at` guard; 2-minute lease
reaper with attempts guarded by a single-statement claim; real DLQ with a consumer; provider-recovery sweep on
circuit close; `ops_cron_runs` heartbeat.
**Alternatives rejected.** Retry loop (half a fix); DLQ as a status only (a message that never reaches a consumer
cannot write a status); periodic full rescan of `jobs` without leases (N+1 and still racy).
**Trade-offs.** ~60 s added latency; two tables, three crons.
**Consequences.** The ≥ 99 %/24 h promise becomes measurable and enforceable.
**Confidence.** High. **Approval.** **ACCEPTED** (schema change bundled in `C5`).

### ADR-022 — API keys: hashed, scoped, never role-bearing

**Context.** `DB-02`.
**Decision.** `api_keys` with a lookup prefix and a SHA-256 secret hash, scopes intersected with an allow-list,
a deny-list applied after, 12-month default expiry, `last_used_at` throttled to one write per minute.
**Alternatives rejected.** Storing the key encrypted and reversible (a database read becomes a credential leak);
scrypt (no dictionary to slow down, and a per-request cost); role-bearing keys (the privilege escalation the
permission document forbids).
**Trade-offs.** A key cannot be displayed again; rotation is create-then-revoke.
**Consequences.** `T-PERM-07` proves the deny-list.
**Confidence.** High. **Approval.** **ACCEPTED** (schema bundled in `C5`).

### ADR-023 — Platform operator identity

**Context.** `platform_operator` existed as a role with no table, which meant a support grant had a grantor with
no record.
**Decision.** `platform_operators(user_id, status, created_by, created_at)`; operators are never workspace
members; `SUPER_ADMIN`-style bootstrap is a migration, not a UI action.
**Alternatives rejected.** A membership row with a flag (would make operators subject to workspace permissions
and vice versa); an environment allowlist (no audit trail of who was an operator when).
**Trade-offs.** One more table and a manual grant process.
**Consequences.** `SEC-01` has a principal with a record.
**Confidence.** High. **Approval.** **ACCEPTED.**

---

## 4. Removed from the architecture

| Item | Reason | Finding |
|---|---|---|
| KV binding | Listed with no stated use; an unused binding is an unowned permission | ARC-09 |
| Durable Object (MVP) | Deferred; polling covers the measured need | ARC-03 |
| Read replication | Beta, unnecessary at this scale; seam retained | ARC-08 |
| Presence, live cursors, collaborative editing | Correctly deferred in Phase 1; still deferred | UX-12 |
| `saved_views`, analytics hub beyond overview, status page, changelog | No MVP value | UX-12 |
| `double_check` | Cost, and no stated product need | DOC-10 |
| V5 importer | Q5 open | DOC-01 |
| `/admin/impersonate` | Never exists; support access is the only path | SEC-01 |

---

## 5. Decision hygiene

1. Superseding requires a new numbered record naming the one it replaces — unchanged from Phase 1.
2. This document **does not edit** the Phase-1 ADRs. Where a decision changed, the change is recorded here and the
   Phase-1 text remains as the historical record; a reader implementing the system follows this document.
3. Every `REQUIRES OWNER APPROVAL` item is listed with options and consequences in
   `OWNER_APPROVAL_DECISIONS.md`, and none of them is marked decided.
4. Any assumption in `ASSUMPTIONS_AND_RISKS.md` that this remediation falsified is named in
   `REMEDIATION_READINESS_REPORT.md` §5 rather than quietly dropped.
