# Cloudflare Architecture

**Status:** RECOMMENDED, with VERIFIED limits/pricing from official documentation read 2026-11-03.
Prices drift; treat every figure as a snapshot and re-check before budgeting.

## 1. Service decisions

| Service | Use here | Essential? | Notes (VERIFIED) |
|---|---|---|---|
| **Workers** (Paid) | SSR, API, queue consumers | **Yes** | Free = 100k req/day, **10 ms CPU**; Paid $5/mo incl. 30M CPU-ms, default 30 s CPU. Password hashing does not fit 10 ms → Paid is mandatory |
| **Static Assets** | SPA/SSR assets in the same Worker | Yes | Static asset requests are **free and unlimited**; 20k files (Free) / 100k (Paid); 25 MiB/file. **Navigation requests bypass the Worker** and are non-billable |
| **D1** | All tenant metadata | Yes | 10 GB **hard cap** per DB; 1M DBs/account (Paid); single-threaded per DB; 50 MB result cap from 2026-11-04 |
| **R2** | PDFs, images, reports, exports | Yes | $0.015/GB-mo, Class A $4.50/M, Class B $0.36/M, **egress free**, 10 GB free tier |
| **Queues** | Job dispatch, notifications | Yes | **128 KB message cap**; 5,000 msg/s/queue; 24 h retention (Free) / 4–14 days (Paid); 1M ops/mo included |
| **Workflows** | Multi-step correction + purge + export | Yes | Durable steps; retries per step; ideal for a 7-step marking pipeline |
| **Durable Objects** | One hub per workspace (WS fan-out) | Recommended | SQLite-backed, 10 GB/object (Paid), **hibernation** to avoid duration billing, ~1,000 req/s soft per object |
| **KV** | Short-lived, non-authoritative caches only | Optional | Never authoritative; eventual consistency makes it wrong for permissions |
| **Cron Triggers** | Reconciliation sweeps, digest emails, cleanup | Yes | 5 (Free) / 250 (Paid); UTC only; 15 min propagation |
| **Turnstile** | Signup/contact bot defence | Yes | Free, unlimited challenges, WCAG 2.2 AA |
| **Rate limiting rules** | Auth brute force, upload abuse | Yes | **1 rule on Free**, 2 Pro, 5 Business, 100 Enterprise; counters are per-colo, so it is a coarse control |
| **Cloudflare Access** | Internal `/admin` and staging only | Optional | **Not customer auth** — no signup, no per-tenant orgs. Use it to gate our own staff surfaces |
| **Workers for Platforms** | Future: per-tenant isolated compute | No | $25/mo; relevant only if a tenant demands code-level isolation |
| **Hyperdrive** | Not used | No | Would be needed only if we adopted Postgres |

**Explicitly not used in MVP:** Containers (unless the PDF decision in `SYSTEM_ARCHITECTURE.md` §7 selects
them), Images, Stream, Pages (legacy path for this app), Workers AI (model choice must stay pluggable).

## 2. Topology

```
example.com            ─┐
www.example.com         ├─▶ Worker "mc-web" (SSR + /api/v1) ── custom domain
app.example.com        ─┘        │
                                 ├─ D1 (primary, single region)
                                 ├─ R2 bucket (per env)
                                 ├─ Queue(s): corrections, notifications, maintenance
                                 ├─ Workflows: correction, purge, export
                                 └─ DO namespace: WorkspaceHub (idFromName(workspaceId))
```

**Start with one Worker on one Custom Domain** (apex), with `www` redirected by a Redirect Rule. Split
marketing to a static Astro Worker later if release cadence diverges. Use **Custom Domains, not Routes**: a
Custom Domain can be `fetch`ed same-zone without a service binding; a Route cannot.

Gotcha to plan for: Custom Domains are exact-hostname only — `example.com` does not serve
`www.example.com`. Add the redirect rule and a proxied placeholder record on day one.

## 3. Environments

| Env | Worker | D1 | R2 | Queue | DO | Access |
|---|---|---|---|---|---|---|
| Local | `wrangler dev` (workerd) | local D1 | local R2 | local queue | local DO | – |
| Dev | `mc-web-dev` | `mc-db-dev` | `mc-files-dev` | `mc-jobs-dev` | `mc-hub-dev` | – |
| Staging | `mc-web-staging` | `mc-db-staging` | `mc-files-staging` | `mc-jobs-staging` | `mc-hub-staging` | Access-gated |
| Production | `mc-web` | `mc-db-prod` | `mc-files-prod` | `mc-jobs-prod` | `mc-hub-prod` | – |

No production data in staging. Staging seeds synthetic workspaces only.

## 4. Upload path (R2)

1. Client asks `POST /submissions/upload-url` with filename, size, sha256 and mime.
2. Worker validates size/mime against policy, creates a `submission_files` row in `pending`, returns a
   **Worker-signed** upload URL (HMAC, 15 min TTL) — not an S3 presign, because presigning needs long-lived
   R2 credentials we are not going to hold.
3. Client uploads directly to R2 via the Worker route (single) or multipart for > 50 MB.
4. Client calls `POST /submissions` to finalise; Worker verifies the object exists, records `bytes`/`sha256`,
   and enqueues validation.
5. `r2.dev` is **never** used in production (test-only, rate-limited); downloads go through a Worker route
   that checks membership and issues a 5-minute signed URL.

`Range` requests: static assets do **not** support them (they return 200 with the full body), so any ranged
PDF streaming must go through the Worker route, not static hosting.

## 5. Queue topology

| Queue | Producer | Consumer | DLQ handling |
|---|---|---|---|
| `corrections` | API | Workflow launcher | message → `jobs.status='failed'` + `job_attempts` row |
| `notifications` | Domain events | Email/in-app fan-out | retry 3×, then `notifications.failed_at` |
| `maintenance` | Cron | Cleanup, purge, reconciliation | alert only |

Queues are **at-least-once**: every consumer must be idempotent on `jobId`, enforced by the
`UNIQUE(ws, idempotency_key)` constraint and a claim/lease on the job row.

## 6. Failure scenarios and behaviour

| Failure | Consequence | Mitigation |
|---|---|---|
| D1 primary unavailable | All writes fail; reads may serve from replicas (beta) | Surface a clear degraded banner; retry with jitter; no data loss (requests fail closed) |
| D1 database at 10 GB | Writes rejected — no graceful mode | Storage alarms at 70/85%; metadata-only design keeps us far below |
| Queue backlog | Jobs delayed | Depth alarm; consumer concurrency; visible "waiting" state (never a spinner) |
| DO unavailable | Live progress stops; sockets drop | Client falls back to polling `/jobs/{id}`; D1 remains the authority |
| Provider outage | Jobs park | Circuit breaker per provider/workspace; banner; resume when closed |
| R2 upload interrupted | Partial multipart | Abort + resume; `pending` rows expire after 24 h |
| Cron not firing | Sweeps delayed | Sweeps are idempotent and also run opportunistically on request paths |
| Deploy regression | Bad Worker live | Versioned deploys + instant rollback to previous version |

## 7. Security controls at the edge

- WAF managed rules + a custom rule set; **rate limits**: `/auth/*` 10/min/IP, `/submissions/upload-url`
  60/min/user, `/api/*` 600/min/user.
- Turnstile on signup, contact and password reset.
- HSTS, `X-Content-Type-Options`, `Referrer-Policy`, strict `Content-Security-Policy` (no inline script;
  `connect-src` limited to self + the realtime origin), `Permissions-Policy` denying camera/mic.
- No `Access-Control-Allow-Origin: *` on any authenticated route.
