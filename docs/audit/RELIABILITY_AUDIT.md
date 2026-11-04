# Reliability Audit

**Audit date:** 2026-11-03. Tested by asking one question of every component: *what state is lost, and who finds
out?* The package is strong on documenting failure states and weak on the two failures that are silent.

## 1. Findings

### REL-01 — CRITICAL — Job loss is silent and undetected (ARC-01)
**Documents:** `architecture/BACKGROUND_PROCESSING.md` §2, `operations/MONITORING_AND_LOGGING.md` §1.
No atomic boundary between the `jobs` row and the queue message, and no sweep for orphaned `queued` rows. The
queue is empty and the job never starts, so queue depth (signal 3) reads healthy. Full analysis in
`ARCHITECTURE_RED_TEAM.md` ARC-01.
**Resolution:** outbox table + publisher; alert on `queued` rows older than 15 minutes with `published_at IS NULL`.

### REL-02 — HIGH — Monitoring cannot see a stuck job
**Documents:** `operations/MONITORING_AND_LOGGING.md` §1.
Twelve signals are defined; none detects a job that stopped advancing. Signals 1–3 (success rate, p95 time to
terminal, queue depth) all trend **healthy** during total job loss, because nothing completes and nothing queues.
**Resolution:** two signals — (a) `jobs` in `queued` > 15 min with no outbox publish, (b) `running` with
`lease_until` expired > 10 min — both paging. Add "age of oldest non-terminal job" as a first-class metric.

### REL-03 — HIGH — The file backup plan is not implementable
**Documents:** `operations/BACKUP_AND_RECOVERY.md` §2 B4, §3.
The plan states R2 objects are "versioned by key prefix" and recoverable from a "replication bucket" with
"continuous (on write)" replication. **R2 has neither object versioning nor native cross-bucket replication**
(verified 2026-11-03). There is no undo for an overwritten or deleted object.
**Consequence:** a support engineer deleting the wrong prefix, or a customer deleting a workspace whose grace
period has passed, destroys scripts irrecoverably — and the document promises otherwise.
**Resolution:** implement replication explicitly (bucket event notification → Queue → Worker `put` to a second
bucket, with a checksum), or state plainly that files are **not** backed up beyond the retention window and price
the risk. Note that a copy pipeline doubles R2 storage cost — which the cost model does not include.

### REL-04 — HIGH — Recovery is designed but never proven, and D1 gives no rehearsal environment
**Documents:** `operations/BACKUP_AND_RECOVERY.md` §6, `architecture/DATABASE_DESIGN.md` §9.
The RTO/RPO table is credible *as targets*. Supporting facts: D1 Time Travel restore is **destructive and
in-place**; there is no clone or branch of a D1 database; `d1 export` blocks other requests and does not support
FTS5. Therefore "restore one table slice into staging" requires parsing an export and re-inserting — a scripted,
testable procedure that the package does not specify.
**Resolution:** ship the restore script as a deliverable of P2 (not P10), with a monthly drill that runs against a
**separate staging database**, and record the drill's row counts in `ops_backup_log`. Publish the measured RTO
after the first drill rather than before.

### REL-05 — MEDIUM — A provider outage longer than the park budget has no recovery path
**Documents:** `architecture/BACKGROUND_PROCESSING.md` §3, `user_journeys` J6.
Rate-limit parks preserve attempts and resume on a cooldown; a circuit breaker pauses the workspace. But when the
circuit **closes**, nothing re-drives the jobs that failed or were parked during the window — the document says
"resume when closed" without a mechanism, and the cron list has no provider-recovery sweep.
**Resolution:** on circuit close, enqueue a recovery pass over jobs in `parked`/`failed(provider_*)` for that
workspace, bounded by a per-workspace concurrency cap so recovery does not become a thundering herd.

### REL-06 — MEDIUM — The D1 outage story assumes a replica that is not enabled
**Documents:** `architecture/CLOUDFLARE_ARCHITECTURE.md` §6 ("reads may serve from replicas (beta)").
Read replication is optional, beta, and not part of the MVP plan (ARC-08). With it off, a D1 outage means **all
reads and writes fail**, so the "degraded banner" is the entire product experience, and `/health/ready` will fail
its own D1 probe.
**Resolution:** describe the real behaviour (hard failure), give the edge a static maintenance page that does not
need D1, and remove the replica implication.

### REL-07 — MEDIUM — Redelivery can exhaust a job's attempt budget
**Documents:** `architecture/BACKGROUND_PROCESSING.md` §4.
The lease claim protects against double execution, but a redelivered message increments `attempts` before the claim
fails, so an at-least-once redelivery storm can push a healthy job to `max_attempts` and fail it without a single
provider call.
**Resolution:** count attempts only on a successful claim (`attempts = attempts + 1 WHERE status='queued' AND
lease_until IS NULL` → affected rows check), and assert in tests that 5 redeliveries produce 1 attempt.

### REL-08 — MEDIUM — Cancellation discards a paid result without telling the user
**Documents:** `architecture/BACKGROUND_PROCESSING.md` §6.
"In-flight call is allowed to finish … its result is discarded, recorded as `cancelled`". Correct engineering, but
the UI implication is unstated: a marker who cancels at 80 % has paid for a token spend they cannot use.
**Resolution:** cancel dialog states "the current AI call may still complete and will not be reused"; meter the
spend (it is real); optionally allow "keep result, don't publish".

### REL-09 — MEDIUM — Migration rollback is forward-only, with no rehearsal
**Documents:** `operations/DEPLOYMENT_PLAN.md` §3.
Expand → migrate → contract is the right pattern; "D1 has no down-migrations" is correct. What is missing is
rehearsal: no step runs the migration against a copy of production data, and no clone exists. A `NOT NULL` addition
on a 400k-row table is forbidden by the document (good), but a slow backfill is not bounded.
**Resolution:** every migration runs against the latest export in staging as a pipeline step, with a timing capture;
abort if it exceeds 50 % of the 30 s query limit.

### REL-10 — MEDIUM — The dead-letter queue is a table nobody watches
**Documents:** `architecture/CLOUDFLARE_ARCHITECTURE.md` §5.
No DLQ queue is configured and no alert watches `jobs.status='failed'` rate or `notifications.failed_at`. See
ARC-06. A poison message can disappear entirely: Queues deletes a message after `max_retries` (default 3) when no
DLQ is configured.
**Resolution:** configure a DLQ queue, alert on its depth, and add a daily "failed jobs by error class" digest.

### REL-11 — MEDIUM — Log retention is shorter than the investigations it must serve
**Documents:** `operations/MONITORING_AND_LOGGING.md` §3 (logs 30 days) vs `security/DATA_PRIVACY.md` §8
(preserve logs as evidence during an incident).
A cross-tenant leak discovered in day 40 has no request logs. Audit rows survive (12 months) but carry no request
context beyond `requestId`.
**Resolution:** on incident declaration, export the relevant window to R2 (encrypted, access-controlled) as a
documented step; state the 30-day limit in the privacy page so it is a disclosed property, not a surprise.

### REL-12 — LOW — Cron sweeps run at 15-minute propagation but nothing checks they ran
`CLOUDFLARE_ARCHITECTURE.md` notes 15-minute cron propagation and "sweeps are idempotent and also run
opportunistically". Without a heartbeat row (`ops_cron_runs(name, last_run_at)`), a silently disabled cron is
invisible until a customer notices stale reconciliation.
**Resolution:** heartbeat table + alert if any sweep has not run in 2× its period.

## 2. Failure matrix (as designed vs after fixes)

| Failure | Designed behaviour | Verdict |
|---|---|---|
| Worker crash between D1 write and enqueue | Job stuck `queued`, silent | **Broken → REL-01** |
| Workflow lost mid-run | Job stuck `running`, silent | **Broken → ARC-02** |
| Queue poison message | Deleted after 3 tries, no DLQ | **Broken → REL-10** |
| Provider 429 | Parked with resume time | Sound |
| Provider 5xx | One retry, then circuit | Sound |
| Provider outage > budget | Jobs fail; no re-drive on close | Gap → REL-05 |
| D1 unavailable | Hard failure, banner | Understated → REL-06 |
| R2 object deleted | Unrecoverable | **Broken → REL-03** |
| Bad deploy | Version rollback in seconds | Sound |
| Bad migration | Forward fix or destructive Time Travel | Risky, rehearsable → REL-09 |
| Duplicate message | Lease prevents double run | Sound, attempts caveat → REL-07 |
| Cancel mid-job | Terminal `cancelled`, no partial | Sound, disclose cost → REL-08 |
| DO unavailable | Polling fallback | Sound |
| Classroom timeout | `NEEDS_VERIFICATION` + read-only reconcile | **Best-in-class** |
| Student row cascade | Undefined with published marks | Gap → UX-07 |

## 3. Verdict

The design is **reliable where it is synchronous** (request validation, approval concurrency, remote-write
reconciliation) and **unreliable where it is asynchronous**, in exactly the two places nothing observes: the
handoff from D1 to the queue, and the handoff from a dead Workflow back to the world. Both are closed by adding an
outbox and a reaper — two tables and two crons. Until then, the promise "≥ 99 % of jobs reach a terminal state" is
not supportable.
