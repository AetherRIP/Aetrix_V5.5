# Monitoring and Logging

**Status:** RECOMMENDED. Observability is sized to a small team: few signals, each with an owner and an
action. A dashboard nobody reads is worse than no dashboard.

## 1. Signals that matter

| # | Signal | Why | Threshold |
|---|---|---|---|
| 1 | Correction success rate | The product's promise | < 98% over 1 h → page |
| 2 | Job p95 time-to-terminal | Perceived speed | > 6 min → investigate |
| 3 | Queue depth / age of oldest message | Stalled pipeline | depth > 200 or age > 10 min → page |
| 4 | Provider error rate by class | 429 vs 5xx need different responses | 5xx > 5% for 10 min → circuit + page |
| 5 | D1 error rate + p95 query latency | Everything depends on it | errors > 0.5% or p95 > 50 ms → page |
| 6 | 5xx rate at the edge | Broad breakage | > 1% for 5 min → page |
| 7 | Auth failures per IP/account | Attack signal | > 50/min → auto-block + notify |
| 8 | Cross-tenant 404 rate anomaly | Possible probing | spike vs baseline → security alert |
| 9 | R2 upload failures | Users blocked | > 3% → investigate |
| 10 | AI spend per hour | Denial of wallet | > 150% of 7-day mean → alert |
| 11 | DO connection count / churn | Realtime health | churn > 50/min/workspace → investigate |
| 12 | Storage growth (D1 + R2) | Capacity | D1 > 70% of 10 GB → plan |

## 2. Log schema (field allowlist)

```json
{ "ts": "...", "level": "info", "event": "job.transition",
  "requestId": "...", "workspaceId": "...", "userId": "...", "jobId": "...",
  "from": "running", "to": "parked", "errorClass": "rate_limit", "durationMs": 1240 }
```

Allowed: ids, states, durations, counts, error classes, route templates, status codes.
**Forbidden in logs:** student names or ids, filenames, file contents, prompts, marks per student, tokens,
cookies, provider keys, request bodies, full URLs with query strings that may carry tokens.

Redaction is applied by the logger itself (not by discipline), and a CI test asserts that a canary string in a
request body never appears in captured logs.

## 3. Audit vs logs

| | Audit (`audit_log`) | Logs |
|---|---|---|
| Purpose | Accountability; who did what | Diagnosis |
| Content | Actor, action, target, before/after | Technical events |
| Retention | 12 months | 30 days |
| Mutability | Append-only | Rotating |
| Exposure | Workspace admins (`audit.read`) | Internal only |

## 4. Tracing

- `requestId` generated at the edge, returned in responses and attached to every log line.
- Jobs carry `jobId` and `workspaceId` through every Workflow step and attempt.
- Each provider call records: provider, model, attempt, error class, duration, token counts (no content).
- A "trace view" in the platform admin joins `requestId` → job → attempts → automation operations.

## 5. Dashboards

1. **Service health** — request rate, 5xx, p50/p95, D1 latency/errors.
2. **Marking pipeline** — queue depth, jobs by state, time-to-terminal, failure classes, parks.
3. **Providers** — per provider/workspace: success, 429, 5xx, circuit state, spend.
4. **Tenancy** — active workspaces, storage per workspace, usage vs quota.
5. **Security** — auth failures, cross-tenant 404s, support grants active, credential rotations.

## 6. Alert routing

| Severity | Channel | Response |
|---|---|---|
| P1 (product down, data risk) | Page + phone | Immediate; incident commander |
| P2 (degraded: pipeline stalled, provider outage) | Page (business hours: chat) | 1 h |
| P3 (capacity, cost, single-tenant issue) | Chat + ticket | Next business day |
| P4 (informational) | Weekly digest | Backlog |

Every alert links to a runbook section. An alert without a documented action is deleted, not muted.

## 7. Health endpoints

- `GET /health` — liveness only (200 always if the Worker is up).
- `GET /health/ready` — checks D1 (`SELECT 1`), R2 (HEAD a sentinel object), Queue (binding present). Returns
  503 with a component breakdown; never leaks internal detail publicly (platform-only).
- `/status` (public) reports coarse component state, driven by the same checks with a 5-minute cache.

## 8. Cost and cardinality discipline

- No per-user metric labels (cardinality explosion); per-workspace only for a bounded set (< 200).
- Sampling: 100% of errors, 10% of successful requests at high volume.
- Log retention 30 days; audit 12 months; usage events 24 months.

## 9. What we deliberately do not build in MVP

- Full distributed tracing (OpenTelemetry spans) — request/job correlation is enough until scale demands more.
- Real-user monitoring SDK on the client — server timings plus a small performance beacon suffice.
- Log search UI of our own — use the platform's.
