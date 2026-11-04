# Durable Object Deferment Plan

**Decision:** `ADR-008` moves from **ACCEPTED** to **DEFERRED**. P5 ships polling. The Durable Object design is
preserved, versioned and costed, and is promoted only when a stated threshold is met.

**Status:** proposed; ratification is owner decision `C13`. No infrastructure is removed — it was never built.

---

## 1. Why this is the right call, in numbers

| Quantity | Value | Source |
|---|---|---|
| Assistants per workspace | 5–10 | brief, assumed (A1) |
| Concurrent tabs | × 1.5 | assumed |
| Sockets at 10 workspaces | ~120 | derived |
| Socket at 100 workspaces | ~1,200 | derived |
| Polling cost at 10 workspaces, 10 s cadence, 8 h/day | ~86 k requests/day | derived |
| Workers Paid included requests | 10 M/month | verified |
| **Marginal cost of polling at 10 workspaces** | **≈ $0** | derived |
| DO requests at 100 workspaces (1 upgrade + coalesced broadcasts + 20× incoming) | order of 1–3 M/month | derived |
| DO cost at 100 workspaces (audit's own figure, underived) | ~$24/month | `COST-03` |
| Latency difference for a 3-minute job | 2 s vs < 1 s | — |

The product's collaboration pattern is **asynchronous handoff**: an assistant marks, a supervisor reviews later.
Nobody is typing in the same document at the same time. The only thing that genuinely benefits from sub-second
updates is progress on a job that takes minutes — and a 2-second poll is indistinguishable from live for that.

**What the DO actually costs, beyond dollars:** a stateful component with its own auth (tickets), its own
authorization (per-message permission rechecks), its own consistency model (replay cursors), its own deployment
hazard (class renames are not automatic — the deployment plan already warns about this), and its own failure mode
(connections drop when the object is evicted). Each of those is a thing to build, test, monitor and explain.

---

## 2. What ships instead

### 2.1 Server contract

`GET /w/{slug}/jobs/{id}` returns `ETag`, `Cache-Control: private, max-age=0, must-revalidate`, and
`retryAfterMs`. A `304` costs a conditional read and no body.

`GET /w/{slug}/notifications/unread-count` returns a single integer, cacheable for 10 s.

Both are ordinary tenant-scoped routes: they inherit the repository, the policy check and the isolation suite.
That is the real advantage of the deferment — the progress mechanism is not a second security surface.

### 2.2 Client cadence ladder

| Condition | Interval |
|---|---|
| Job `running` | 2 s |
| Job `queued` | 5 s (position may change) |
| Job `parked` | 30 s (resume time is known) |
| Job terminal | stop |
| Tab hidden | pause entirely |
| Tab visible again | immediate refetch, then resume ladder |
| Network error | exponential backoff 2 s → 60 s, cap 5 attempts, then a discreet "updates paused" |
| Offline event | pause; resume on `online` |

Rules: at most one in-flight poll per resource; polling stops when the queue is empty and the count is zero;
no polling on the marketing surface; no polling for users without a workspace context.

### 2.3 UX contract (what must not regress)

| Requirement | Polling implementation |
|---|---|
| Progress is visible without a tab open | Unchanged — the job runs server-side; returning to the tab shows the current state |
| A parked job shows a resume time, not a spinner | `parked` carries `resumeAt`; displayed from the first response |
| A failed job offers one clear action | `nextAction` field: `retry` \| `change_model` \| `mark_manually` |
| A cancelled job leaves no partial result | Unchanged |
| Notifications arrive "soon enough" | 10 s badge poll while active; email for anything that matters if the tab is closed |
| A 200-job batch does not flood | One summarised progress object per assignment (`completed/total`), not per-job events |

`T-UX-05` asserts the visible-and-restored path; `T-JOB-13` asserts 200 concurrent jobs produce one summary and
no request storm (measured: ≤ 2 requests/second/user regardless of job count).

---

## 3. The preserved Durable Object design (not built)

Retained verbatim from `REALTIME_ARCHITECTURE.md` §§2–5, with three amendments forced by this phase:

1. **Ticket minting requires MFA assurance** for operators and for any workspace mutation — the original design
   minted a ticket from `workspace.read` alone.
2. **`membership.changed` closes sockets**, and because role changes now invalidate the session cache, the socket
   must re-resolve the membership rather than trust the ticket's role claim after 60 s.
3. **Notification payloads are filtered per socket by `user_id`** (`SEC-06`) — the original left this implicit.

Everything else stays: one object per workspace (`idFromName(workspaceId)`), hibernation API, ring buffer of 200
events, coalescing at 4/s per job and 20/s per workspace, `cursor` replay, polling as the fallback that remains
the source of truth.

**Costing the preserved design properly** (what `COST-03` asked for):

| Driver | Assumption | 100 workspaces |
|---|---|---|
| Upgrades | 1,200 sockets × 2/day | 72 k/month |
| Outgoing messages (batched) | 4/s per active job, coalesced to 1/s per workspace during bursts | ~1.1 M/month |
| Incoming messages (billed 20:1) | cursor + ack, ~2 per socket-hour | ~0.3 M → 6 M billed |
| Duration | hibernated except during bursts | ~40 k GB-s |
| **Estimated** | | **$3–30/month**, dominated by incoming-message billing |

The range is wide because the incoming-message ratio punishes chatty clients; a client that sends heartbeats
would multiply it. That is recorded so a future build does not repeat the original document's silent `$24`.

---

## 4. Promotion thresholds

The DO is built when **any** of these is measured over a two-week window. They are numeric so the decision is not
a matter of taste:

| # | Threshold | Measurement | Why this number |
|---|---|---|---|
| P1 | p95 job-progress staleness **> 15 s** for users with a job in flight, and ≥ 3 support tickets/week citing stale progress | client beacon + ticket tag | 15 s is where a marker stops trusting the screen |
| P2 | ≥ 3 workspaces explicitly request **presence** ("who is reviewing this") in writing | support log | a request, not an inference |
| P3 | Polling exceeds **25 %** of monthly Workers requests, or adds **> $40/month** at ≤ 50 workspaces | usage report | the DO must be cheaper than the thing it replaces |
| P4 | Review becomes genuinely simultaneous (two reviewers on one script) in ≥ 10 % of sessions | session analytics | that is a different product shape, and it changes more than transport |
| P5 | A customer contract requires push notifications to a non-browser client | sales | contractual, not technical |

**Anti-thresholds** — conditions that do **not** justify it: a competitor has live cursors; a stakeholder likes
sockets; "realtime" appears in a pitch deck. Each of those has been the reason a stateful component was added to
a product that did not need one.

---

## 5. Migration path (if a threshold is met)

Ordered so that the work is additive and reversible:

1. **Schema first.** Add `event_seq` to the tables that emit events (`jobs`, `notifications`) — a per-workspace
   monotonic counter is enough; it costs one column and makes replay exact.
2. **Server.** Add `POST /w/{slug}/events/ticket` (30 s, single-use, bound to `{userId, workspaceId,
   membershipVersion}`) and the `WorkspaceHub` class. Both deployed but unused.
3. **Dual-write.** Publish events to the DO *and* keep polling. Verify replay, dedupe and reconnect against
   real traffic without changing the client.
4. **Client.** Enable the socket behind a flag per workspace; keep the polling ladder as the fallback path and
   as the recovery path (unchanged code).
5. **Remove nothing.** Polling remains the source of truth after a disconnect, exactly as the original design
   specified.
6. **Class migration.** Use a versioned class name (`WorkspaceHubV1`) from day one; the deployment plan warns
   that class renames are not automatic.

Estimated effort: **8–12 days**, of which 4 are the client and tests. Reversible at every step because the DO is
never authoritative.

---

## 6. What changes in the plan

| Document area | Change |
|---|---|
| `PRODUCT_ROADMAP` P5 exit criteria | Socket requirements removed; `T-UX-05` and `T-JOB-13` added |
| `ACCEPTANCE_CRITERIA` §6 | "live progress" replaced with "progress visible within 2 s of a state change while the tab is visible" |
| `MONITORING_AND_LOGGING` signal 11 (DO churn) | Suspended until the DO exists; replaced by poll-rate and `304`-ratio signals |
| `COST_AND_SCALABILITY` §4 | DO line removed; PDF line added (`ADR-017`) |
| `SECURITY_REQUIREMENTS` SE-6 | Marked "not applicable while deferred", retained for the promotion path |
| `TENANT_ISOLATION_TESTS` | Socket rows retained as `skip` with a reason, so they are not lost |
| `REALTIME_ARCHITECTURE.md` | Retained as the promotion specification; three amendments in §3 above |

---

## 7. Risk of being wrong

| If… | Then | Cost of being wrong |
|---|---|---|
| Markers find 2 s polling too slow | Add the DO at P6 | 8–12 days, no rework, because the client contract (state, `nextAction`, `resumeAt`) is transport-agnostic |
| Presence turns out to matter for the buyer | Add it on the DO later | Same |
| Polling volume is higher than modelled | Requests are the cheapest thing on the bill | $ tens per month |
| A competitor's live feel wins deals | The threshold table fires and we build it | Delay, not damage |

The asymmetry is the argument: deferring costs days if wrong. Building now costs a stateful surface, a security
review, a migration plan and a monitoring story **before** there is evidence it is needed — which is exactly the
"unnecessarily complicated" failure this remediation exists to remove.

---

## 8. Decision record

- `ADR-008` → **DEFERRED** (`REVISED_ARCHITECTURE_DECISIONS.md` §1).
- Owner ratification: `C13` in `OWNER_APPROVAL_DECISIONS.md` — options: ratify the deferral (recommended), build
  it now (with the costed figure above), or defer with a hard date.
- Re-entry: any threshold in §4, reviewed at every phase gate using the two-week measurement, not opinion.
