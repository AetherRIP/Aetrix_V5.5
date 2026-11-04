# Background Processing

**Status:** RECOMMENDED. Preserves V5's job semantics on Cloudflare Queues + Workflows.

## 1. Why a job system, not a request

A correction is: fetch a file, prepare it, call an AI provider (seconds to minutes, rate-limited, sometimes
failing), verify the result against a blueprint, reconcile, persist, and fan out progress. None of that may
run inside an HTTP request — Workers cap CPU time, and a user closing a tab must not cancel marking.

**The browser never marks.** No provider key, prompt or mark scheme is ever sent to the client.

## 2. Pipeline

```
POST /corrections
  → validate (permission, submission status, quota)
  → insert jobs row (status=queued, idempotency_key)          [atomic]
  → enqueue { jobId, workspaceId }                            [ids only]

queue consumer
  → claim: UPDATE jobs SET status='running', lease_until=... WHERE id=? AND status='queued'
  → start Workflow(instanceId = jobId, params = { jobId, workspaceId })

Workflow steps (each retryable, each idempotent)
  1 validate_input      object exists in R2, mime/size ok, sha256 matches
  2 load_scheme         read locked blueprint; abort if unlocked (never guess)
  3 prepare_input       rasterise/optimise, page map, question evidence (cache by sha256)
  4 call_provider       temperature 0, fixed seed, model from workspace config
  5 parse_response      strict schema; reject on shape error (no partial marks)
  6 verify              reconcile against blueprint; missing question → needs_review
  7 persist             results + question_results + usage_events     [atomic]
  8 distribute          DO progress event, notification, index update
```

Step 3 caches by content hash so retries never re-download or re-upload — this is V5's "prepared input"
optimisation, preserved because it is the single biggest retry cost saver.

## 3. Retry policy (ported from V5, unchanged in intent)

| Failure class | Examples | Policy |
|---|---|---|
| Rate limit / high demand | 429, "overloaded" | **Park** on cooldown; attempts unchanged; resume automatically |
| Transient network / timeout | socket, 5xx, 504 | **One** bounded retry with exponential backoff + jitter, honour `Retry-After` |
| Auth / invalid / context too large | 401, 403, invalid argument | **Never resend** — fail with an actionable code |
| Provider circuit open | sustained 5xx | Pause all jobs for that workspace/provider; resume when closed |
| Schema/verification failure | unparsable, missing questions | **No auto-retry**; mark `needs_review` for a human |

Guards: per-job retry budget (V5 used a 15-minute park budget), global max attempts, and a hard stop so a
misconfigured job can never loop. Every attempt is recorded in `job_attempts` with its class and duration.

## 4. Idempotency

- `UNIQUE(workspace_id, idempotency_key)` on `jobs`; a duplicate POST returns the existing job (`202` with the
  same id) rather than creating work.
- Claim uses a conditional `UPDATE … WHERE status='queued'` so two consumers cannot both run it.
- If a successful result already exists for the submission and model, the job attaches it instead of
  re-marking (V5 behaviour; prevents duplicate AI spend).
- Persist step is one batch guarded by `version`, so a replay cannot double-apply.

## 5. Progress and visibility

| State | Meaning | UI |
|---|---|---|
| `queued` | Accepted, not started | Position in queue, "Queued" |
| `running` | Step executing | Step name + elapsed, live via DO |
| `parked` | Rate-limited, will resume | Resume time, counts preserved |
| `retrying` | Transient failure, retrying | Attempt n of m |
| `needs_verification` | Interrupted; remote state unknown | "Check status" action (reconcile) |
| `succeeded` / `failed` / `cancelled` | Terminal | Result link / reason / — |

Progress is pushed to the workspace Durable Object; polling `/jobs/{id}` is the fallback and the source of
truth after a reconnect.

## 6. Cancellation

`POST /jobs/{id}/cancel` sets a cancel flag; the Workflow checks it before each step and at each provider
boundary. A provider call already in flight is allowed to finish (no money is refunded by killing a socket),
and its result is **discarded**, recorded as `cancelled`, not silently kept.

## 7. Dead letters

After the retry budget: `jobs.status='failed'`, `error_code` from the closed set, one `job_attempts` row per
attempt, and a `notifications` row for the owner. The DLQ is therefore **queryable in D1** (jobs + attempts),
not a separate opaque store — this is deliberate: operators need to see *why*, not just *that*.

## 8. Other background work

| Task | Mechanism | Frequency |
|---|---|---|
| Classroom reconciliation | Cron → Workflow per workspace with open `needs_verification` | every 15 min |
| Stale upload cleanup | Cron | hourly |
| Deletion purge | Workflow (batched deletes + R2 prefix) | on schedule after grace |
| Tenant export | Workflow → R2 zip → signed link | on demand |
| Usage rollups | Cron → aggregate into `usage_daily` | hourly |
| Provider health probe | Cron (per configured credential) | 5 min |

## 9. Limits honoured (VERIFIED)

- Queue message 128 KB → **ids only**; prepared artefacts live in R2/D1.
- Queue at-least-once → consumers idempotent.
- Workflow step retries are separate from our classified policy: disable unconditional step retries for the
  provider step so our table is authoritative.
- Durable Object ~1,000 req/s soft per object → progress events are coalesced (max 4/s per job, 20/s per
  workspace) rather than emitted per step-per-token.
- Workers CPU 30 s default → rasterising a 40-page PDF may exceed it; that work goes to the container
  service decided in phase 1, or is chunked per page across steps.
