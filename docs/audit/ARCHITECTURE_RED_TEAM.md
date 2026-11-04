# Architecture Red Team

**Audit date:** 2026-11-03 · **Auditor:** independent review (did not author the plan)
**Scope:** every architectural decision in the package, tested against official documentation and against the
product's own promises. The original documents are unchanged; this file records findings only.

## 1. Platform reality check

Claims in the documents were re-verified against vendor documentation on 2026-11-03.

| # | Claim in the package | Verified reality | Verdict |
|---|---|---|---|
| 1 | TanStack Start 1.0 stable; Cloudflare path is the Vite plugin | **VERIFIED.** 1.0 announced 2026-10-13; Cloudflare's framework guide documents `@cloudflare/vite-plugin` + `@tanstack/react-start` with SSR, streaming and server functions; Wrangler auto-detects the framework | Holds |
| 2 | "SPA mode and prerendering are unsupported behind the Cloudflare plugin" (ADR-001) | **FALSE.** Static prerendering shipped 2025-12-19 (`tanstackStart({prerender:{enabled:true}})`, needs `react-start >= 1.138.0`); SPA mode is documented. One **open** bug (#7740) makes `_shell.html` a full SSR of the mask route | Correct the rationale |
| 3 | OpenNext is "maintenance mode"; vinext is beta | **IMPRECISE.** Cloudflare: "recommends vinext instead of OpenNext for new Next.js applications… use this guide to maintain an existing OpenNext application." vinext docs still say beta; Cloudflare's Sep-2026 blog calls vinext 1.0 "production-ready". Directionally right, factually softer | Tighten wording |
| 4 | D1: 10 GB hard cap, single-threaded, 50 MB result cap from 2026-11-04 | **VERIFIED**, including "the 10 GB limit … cannot be further increased" | Holds |
| 5 | `db.batch()` is atomic | **VERIFIED**, and stricter than stated: `BEGIN/COMMIT` across round trips is unsupported; a batch counts as **one** query and must finish inside the 30 s query limit | Holds, under-documented |
| 6 | Queues: 128 KB, at-least-once | **VERIFIED.** Also: `max_retries` defaults to **3**, ceiling 100; messages are **deleted** at max retries unless a DLQ is configured; consumer wall time 15 min, CPU default 30 s | Holds; DLQ gap |
| 7 | Workflows: durable steps, per-step retries | **VERIFIED.** 10,000 steps (Paid), 50,000 concurrent instances, per-step wall time unlimited, `step.sleep` ≤ 365 days; steps billed after 500k/month | Holds |
| 8 | Durable Objects: SQLite, hibernation, ~1,000 req/s soft | **VERIFIED.** Incoming WS messages bill at a **20:1** ratio; 32 MiB frame limit; 10 GB storage/object | Holds |
| 9 | R2 presigning needs long-lived credentials, so use Worker-signed URLs | **PARTLY FALSE.** R2 supports S3 presigned URLs with expiry **1 s – 7 days**; the Workers *binding* cannot generate them, but an S3 client using credentials in Workers Secrets can. This is a policy choice, not a platform limit | Restate the reason |
| 10 | R2 objects are "versioned by key prefix" and recoverable from a "replication bucket" (BACKUP §3, B4) | **FALSE.** R2 has **no object versioning and no native cross-bucket replication**. Recovery requires an event-notification → Queue → Worker copy pipeline | **Backup plan not implementable as written** |
| 11 | Workers Paid: 30 s CPU default, raiseable | **VERIFIED:** default 30 s, max 5 min per invocation, 15 min for cron/queue consumers via `limits.cpu_ms` | Holds |
| 12 | Cloudflare rate-limiting rules: 1 on Free | **VERIFIED** — and this constraint is ignored by the design (ARC-07) | Holds, under-used |

## 2. Findings

### ARC-01 — CRITICAL — No atomic boundary between the job row and the queue message
**Documents:** `BACKGROUND_PROCESSING.md` §2, `SYSTEM_ARCHITECTURE.md` §4.

The pipeline is `insert jobs row (status=queued, idempotency_key) [atomic]` **then** `enqueue {jobId,
workspaceId}`. The `[atomic]` annotation covers only the D1 insert; D1 and Queues share no transaction, and D1
has no interactive transactions to hold one open across the two calls. If the Worker dies, hits the CPU wall, or
the enqueue throws between those statements, the row sits in `queued` with **no message**. Nothing in the
documented cron set reclaims it — sweeps cover Classroom reconciliation, stale uploads, purge, export, usage
rollups and provider health, not orphaned jobs.

**Consequence:** silent, permanent job loss with a UI showing "Queued" forever. It breaks the stated promise of
≥ 99 % of jobs reaching a terminal state within 24 h, and monitoring cannot see it because no error is raised.

**Resolution:** transactional outbox — write `job_outbox(job_id, workspace_id, published_at NULL)` in the same
`db.batch()` as the job row; a cron publishes unpublished rows behind a `published_at` guard. Pair with ARC-02
so both halves of the failure are closed. Owner approval required: yes (schema change).

### ARC-02 — HIGH — No reaper for jobs stuck `running` with an expired lease
**Documents:** `BACKGROUND_PROCESSING.md` §2 §4, `MONITORING_AND_LOGGING.md` §1.

Claiming is `UPDATE … SET status='running', lease_until=… WHERE id=? AND status='queued'`. If the Workflow
instance is lost (creation failure, platform incident, deploy mid-flight, throw outside step retries), the row
stays `running`, the lease expires, and nothing enumerates expired leases — `idx_jobs_ws_lease` exists but no
consumer uses it.

**Consequence:** the same class of silent loss as ARC-01, plus double-processing risk if a reaper is added later
without an attempts guard.

**Resolution:** a 5-minute cron that re-queues or fails rows where `lease_until < now()` and no Workflow
instance exists, incrementing `attempts`; test that a killed Workflow converges to a terminal state within two
lease periods.

### ARC-03 — HIGH — The Durable Object decision is not justified by the numbers it cites
**Documents:** `REALTIME_ARCHITECTURE.md` §2 §8, `ADR-008`.

The argument is that hibernation keeps idle sockets off the duration bill. True — but the workload is 5–10
assistants per workspace, one tab each, on an **asynchronous handoff** product whose only real-time need is job
progress. Polling `/jobs/{id}` every 10 s costs ~6 requests/min/user; at 10 workspaces that is ~86k
requests/day, inside the included 10M/month at effectively zero marginal cost, with no second stateful system,
no ticket flow, no socket-auth surface, no replay cursors and no DO migration plan.

**Consequence:** a stateful component is introduced before any evidence that polling is insufficient — exactly
the "unnecessarily complicated" pattern this audit was asked to find.

**Resolution:** ship progress by polling in P5 (already the documented fallback), instrument perceived latency,
and promote to the DO only if polling misses the UX target. If the DO is kept, cost it properly (COST audit
COST-03) and document the class-rename migration `DEPLOYMENT_PLAN.md` §9 already warns about.

### ARC-04 — HIGH — The PDF compute question is deferred into the phase that depends on it
**Documents:** `SYSTEM_ARCHITECTURE.md` §7, `PRODUCT_ROADMAP.md` P1/P7.

Three options are listed and one recommended, but the recommendation depends on **Workers Containers**, whose
GA status the document itself says must be re-verified — while `CLOUDFLARE_ARCHITECTURE.md` §1 excludes
Containers from the MVP service list "unless the PDF decision selects them". That is circular: P1 selects an
option the cost and operational models exclude.

**Consequence:** report PDFs are a P6/P7 deliverable with no costed, verified host, and the cost model has no
line for it.

**Resolution:** in P1 record a dedicated ADR for PDF hosting with measured CPU/memory, cost per report, and a
data-processor review if an external render API is chosen; update `COST_AND_SCALABILITY.md` before P5.

### ARC-05 — MEDIUM — The R2 upload path contradicts its own rationale and multipart economics
**Documents:** `CLOUDFLARE_ARCHITECTURE.md` §4, `ADR-006`.

R2 presigned URLs exist (1 s – 7 days). The package rejects them because presigning "needs long-lived R2
credentials we are not going to hold" — yet the same package already holds a credential-encryption key, a
session-signing key and provider keys as Workers Secrets, so an R2 token is not a new class of risk. The chosen
path proxies every byte through the Worker, including multipart parts, while `SECURITY_REQUIREMENTS.md` IN-3
permits 200 MB uploads.

**Consequence:** Worker duration and request volume on the most expensive request type, no resumable upload
primitive, and a throughput ceiling that only appears under load. It also weakens upload validation, because
the Worker must buffer content rather than validate a completed object.

**Resolution:** either presigned PUT with a scoped R2 token in Secrets plus post-upload validation, or keep the
proxy capped at ~20 MB with an explicit multipart session for larger files. Delete the inaccurate rationale
either way.

### ARC-06 — MEDIUM — The dead-letter story depends on code the design never shows
**Documents:** `CLOUDFLARE_ARCHITECTURE.md` §5, `BACKGROUND_PROCESSING.md` §7.

"D1 is the DLQ" holds only if the consumer catches its own failures and writes `jobs.status='failed'` plus a
`job_attempts` row. A consumer that throws earlier (binding error, D1 unavailable, malformed message) is retried
up to `max_retries` — default 3 — and then the message is **deleted** unless a DLQ is configured. No DLQ queue
appears in the topology table.

**Resolution:** configure a real dead-letter queue, alarm on its depth, and specify the consumer's outer
try/catch as a requirement, not an implementation detail.

### ARC-07 — MEDIUM — Edge rate limits are specified against an unacknowledged plan constraint
**Documents:** `CLOUDFLARE_ARCHITECTURE.md` §7, `SECURITY_REQUIREMENTS.md` AB-1.

Four rules are listed (auth 10/min/IP, upload 60/min/user, API 600/min/user, WAF) but Cloudflare allows **1
rate-limiting rule on Free, 2 on Pro, 5 on Business, 100 on Enterprise**. Per-user limits also need a key
expression the plan never specifies, and counters are per-colo, so a distributed attacker gets N× the limit.

**Resolution:** state the required plan tier explicitly, or move per-user limiting into the Worker (DO or
`usage_events` counters). Do not let "600/min/user" read as a platform feature.

### ARC-08 — MEDIUM — Read replication is designed in for a scale that does not exist
**Documents:** `MULTI_TENANCY.md` §4 (session bookmarks), `CLOUDFLARE_ARCHITECTURE.md` §1.

Read replication is public beta and requires the Sessions API. At 100 workspaces the projection is ~11 req/s
average against a database that serves ~1,000 queries/s. The bookmark rule adds a correctness dependency on a
beta feature for no measured benefit.

**Resolution:** primary-only reads for MVP; keep the Sessions API behind one helper so replication can be
switched on later without touching call sites.

### ARC-09 — LOW — KV appears in the topology with no stated use
`SYSTEM_ARCHITECTURE.md` §1 §6 list KV; `CLOUDFLARE_ARCHITECTURE.md` calls it "short-lived, non-authoritative
caches only", and the storage table then caches class lists via D1 and HTTP ETags instead. An unused binding is
an unowned permission.

**Resolution:** remove KV from the MVP topology or name the exact cache it holds.

### ARC-10 — MEDIUM — Performance is untested until P10 while the platform punishes N+1 immediately
D1's 1,000-queries-per-invocation limit and single-threaded execution are documented in `DATABASE_DESIGN.md`
§9, but the first performance gate is `TEST_STRATEGY.md` L8, marked "Release".

**Resolution:** add p95 budget tests to the P5 exit criteria (queue list, assignment detail, grade matrix) so an
N+1 is caught while the queries are being written, not after the UI depends on them.

## 3. What genuinely holds up

- **Tenant-bound repository with a branded `TenantContext`** is the right structural answer on a database with
  no RLS, and "it fails to compile" is stronger than any review checklist.
- **Ids-only queue messages** — correct, and the reason the 128 KB cap is not a design constraint.
- **`automation_operations` tri-state with `needs_verification`** is genuine domain modelling carried from V5
  and the right answer to a non-idempotent remote API.
- **Metadata-only D1, blobs in R2** keeps the 10 GB wall far away. The storage arithmetic under-counts (COST-02)
  but the shape is right.
- **Closed status vocabularies mapped 1:1 to design tokens** removes an entire class of state-drift bugs.
- **Challenging the brief's phase order** (parity before design) is the strongest judgement in the package.

## 4. Subsystem verdicts

| Subsystem | Verdict | Blocking issue |
|---|---|---|
| Frontend (TanStack Start) | Sound | Rationale error only (ADR-001 review) |
| Topology (one Worker) | Sound | Marketing shares the deploy (ADR-002 review) |
| Data model / tenancy | Right shape, real gaps | Identity schema mismatch, missing key table (DB audit) |
| Job pipeline | **Not safe as written** | ARC-01, ARC-02 |
| Realtime | Over-built | ARC-03 |
| Files | Workable | ARC-05 |
| Reporting / PDF | Unresolved dependency | ARC-04 |
| Observability | Adequate for MVP | Missing stuck-job and outbox alerts (REL-02) |
