# Recommendations — Prioritised

**Audit date:** 2026-11-03. Every recommendation names the finding it closes, the effort it implies, and whether
the product owner must approve it. Nothing here has been applied; the original documents are untouched.

Effort: **S** ≤ 1 day of design work · **M** 2–5 days · **L** > 1 week (or a schema/architecture change).

## Gate 1 — Required before the architecture is approved

These change the shape of the system or the schema. Approving the architecture without them means approving
something already known to be unsafe.

| # | Recommendation | Closes | Effort | Owner |
|---|---|---|---|---|
| 1 | Add a **transactional outbox** (`job_outbox`) written in the same `db.batch()` as the job row, with a publisher cron | ARC-01, REL-01 | M | **Yes** |
| 2 | Add a **lease reaper** cron that re-queues or fails `running` jobs with expired leases and no Workflow instance | ARC-02, REL-02 | M | No |
| 3 | Reconcile the identity schema with **Better Auth's required tables** (`account`, `verification`, `passkey`, `twoFactor`, `member`) and document the mapping | DB-01 | L | **Yes** |
| 4 | Specify the **support-grant context** as a first-class, scope-checked, per-read-audited variant — not a session flag | SEC-01 | M | **Yes** |
| 5 | Add **tenant-consistency triggers** on every child table, plus a mismatched-FK test | DB-03, SEC-05, R13 | M | No |
| 6 | Add `CHECK (awarded BETWEEN 0 AND max_marks)` and the override trigger | DB-05, R03 | S | No |
| 7 | Correct the **false platform claims**: TanStack prerender/SPA support, R2 presigning, R2 versioning/replication, OpenNext "maintenance mode" | ARC-01…05 (platform table), ADR-001/006 | S | No |
| 8 | Replace the unimplementable R2 backup story with an explicit replication pipeline, or an explicit statement that files are not backed up | REL-03, R37 | M | **Yes** (cost) |

## Gate 2 — Required before phase 2 (tenancy and auth)

| # | Recommendation | Closes | Effort | Owner |
|---|---|---|---|---|
| 9 | Pin Better Auth **≥ 1.7.16** and write an auth-configuration ADR: rate-limit storage = database, `cookieCache.maxAge` ≤ 60 s, absolute session cap, scrypt parameters raised and measured, `__Host-` cookies, `cf-connecting-ip` | SEC-03, SEC-08, ADR-005 | M | **Yes** (session length) |
| 10 | Implement MFA for **every enabled sign-in method** (or disable passkey/social for owner and operator) | SEC-02, R16 | M | **Yes** (UX trade-off) |
| 11 | Extend the policy function to a **resource-aware** check, or delete permission footnotes ² ⁴ ⁶ and accept the weaker policy | SEC-04, R14, DOC-02 | L | **Yes** |
| 12 | Add the `api_keys` table with hashed keys and scope validation | DB-02, R20 | S | **Yes** |
| 13 | Convert soft-delete uniqueness to **partial unique indexes** | DB-04 | S | No |
| 14 | Declare the six roles as Better Auth dynamic-access-control roles; generate the matrix and the policy code from one definition | SEC-07 | M | No |
| 15 | Decide **C2** (double approval): idempotent `200` for the same actor, `409` naming the approver for a different one | UX-02, ADR-013 | S | **Yes** |
| 16 | Move the **support-grant mechanism** into P5/P6, before the first external workspace | ROAD-01 | M | **Yes** |
| 17 | Ship the **restore script** as a P2 deliverable and run the first drill before the first customer | REL-04, R37 | M | No |

## Gate 3 — Required before phase 5 (jobs and files)

| # | Recommendation | Closes | Effort | Owner |
|---|---|---|---|---|
| 18 | Configure a **real dead-letter queue**, alarm on depth, and specify the consumer's outer try/catch | ARC-06, REL-10 | S | No |
| 19 | Count attempts **only on a successful claim**, and test 5 redeliveries → 1 attempt | REL-07 | S | No |
| 20 | Add a **provider-recovery sweep** on circuit close | REL-05 | M | No |
| 21 | Decide the R2 upload path: presigned with a scoped token, or proxy capped at ~20 MB. Measure a 40 MB upload's Worker duration | ARC-05, ADR-006 | M | **Yes** |
| 22 | Add `UNIQUE(ws, job_id, attempt_no, kind)` on `usage_events` and define the rollup as replace-from-events | DB-07, R36 | S | No |
| 23 | Add `version` to `mark_schemes` and guard scheme edits with `If-Match` | UX-04 | S | No |
| 24 | Resolve the review-draft story (server-side draft **or** replay-with-diff) | UX-01, R44 | M | **Yes** |
| 25 | Add the missing endpoints: results list/summary, exports, notifications + preferences, automation operations, bulk-cap | API-01, API-02, API-03, API-04, API-06 | M | No |
| 26 | Add p95 performance tests to the P5 exit criteria | ARC-10 | S | No |

## Gate 4 — Required before launch

| # | Recommendation | Closes | Effort | Owner |
|---|---|---|---|---|
| 27 | Decide the **PDF render host** with measured cost and a data-processor review; add the line to the budget | ARC-04, COST-01, R31 | L | **Yes** |
| 28 | Correct the storage arithmetic and add the two missing cost lines (PDF host, file replication, edge plan tier) | COST-01, COST-02, COST-04, DOC-12 | S | No |
| 29 | Name the Cloudflare plan tier the rate-limit/WAF design requires | DOC-12, COST-04 | S | **Yes** (purchase) |
| 30 | Define **student erasure with published marks** (anonymise, retain numerics, annotate reports) | UX-07, R34 | M | **Yes** (legal) |
| 31 | Add the seven missing journeys (sampling, MFA recovery, password recovery, workspace switch, member departure, student erasure, scheme concurrency) | DOC-16 §2 | M | No |
| 32 | Add the missing permission keys (`notification.*`, `workspace.export`, `view.*`, `audit.export`, `quota.write`, `job.read`) | DOC §3 | S | No |
| 33 | Add audit-log immutability triggers and a cron heartbeat table | DB-11, REL-12 | S | No |
| 34 | Add the two paging signals for stuck jobs and the outbox | REL-02 | S | No |

## Gate 5 — Defer or cut (do not build in the MVP)

| # | Recommendation | Rationale |
|---|---|---|
| 35 | **Defer the Durable Object**; ship polling for progress (ADR-008 → Defer) | ARC-03: the workload does not justify a stateful component |
| 36 | Cut the `viewer` role, or restrict it to aggregates only and say so | SEC-04: its restrictions cannot be enforced |
| 37 | Defer `saved_views`, the analytics hub beyond two charts, the public status page and changelog | UX-12: no MVP value |
| 38 | Defer the V5 importer until Q5 is answered | DOC-01 |
| 39 | Defer `double_check` consistently (feature inventory and Q14 disagree) | DOC-10 |
| 40 | Remove KV from the topology unless a specific cache is named | ARC-09 |

## Sequencing

```
Gate 1 (8 items)  ──▶ architecture approval ──▶ P1 parity spike
                                                   │
Gate 2 (9 items)  ────────────────────────────────▶ P2 tenancy + auth
                                                   │
Gate 3 (9 items)  ────────────────────────────────▶ P5 jobs + files
                                                   │
Gate 4 (8 items)  ────────────────────────────────▶ launch
```

Gates 1–3 are cheap relative to what they prevent: two tables, two crons, four constraints, a schema
reconciliation, and a handful of configuration decisions. Gate 4 contains the only genuinely expensive item —
the PDF host — which must be resolved in P1 anyway.

## What should **not** change

It is as important to say what survived review:

- The **shared-schema tenancy model** and the branded `TenantContext` — correct for D1, and no cheaper alternative
  exists.
- **Marking parity before design** — the best decision in the package; keep it.
- **Classroom as phase 6** and optional at every step.
- **`needs_verification` as a distinct state** — preserve it exactly.
- The **ids-only queue message** design and the **retry classification table** ported from V5.
- The **design direction (D1) and token architecture**, including the closed status vocabulary.
- The **decision to defer billing while building metering**.

A reviewer who recommended changing these would be trading a real strength for a hypothetical improvement.
