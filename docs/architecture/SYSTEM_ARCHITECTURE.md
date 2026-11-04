# System Architecture

**Status:** RECOMMENDED. Target platform: Cloudflare Workers (see `CLOUDFLARE_ARCHITECTURE.md`).

## 1. Context

```
Users ──▶ Browser (React SSR + client) ──▶ Cloudflare edge
                                            │
                                            ├─▶ Worker (SSR + /api/v1)
                                            │     ├─▶ D1  (tenant metadata, jobs, audit)
                                            │     ├─▶ R2  (PDFs, images, report files)
                                            │     ├─▶ KV  (rare, non-authoritative caches)
                                            │     ├─▶ Queues ──▶ Workflows / consumer Workers
                                            │     └─▶ Durable Object (per-workspace hub)
                                            │
                                            ├─▶ External: Google Classroom API
                                            └─▶ External: AI providers (server-side only)
```

## 2. Logical layers

| Layer | Responsibility | Must not |
|---|---|---|
| Presentation | Routes, components, form state, optimistic UI | Decide permissions, hold secrets, call AI |
| API (`/api/v1`) | Auth, tenant resolution, validation, policy, shaping | Contain business rules that jobs also need |
| Domain services | Marking orchestration, scheme blueprint, publishing, reporting | Know about HTTP |
| Data access | Tenant-scoped queries, transactions, migrations | Accept an unscoped query |
| Job runtime | Queues, Workflows, retry, idempotency, progress | Block a request |
| Integration | Classroom, AI providers, email | Leak provider errors verbatim |

Domain services are **shared** between the request path and the job path. This is the single most important
structural rule: if approval logic exists twice, one copy will drift.

## 3. Request path (synchronous)

```
Request → edge (WAF, rate limit)
        → Worker router
        → session resolve (Better Auth)            [401 if none]
        → workspace resolve (membership)            [404 if not a member]
        → permission check (policy)                 [403 only for member-without-permission]
        → schema validation (zod)                   [422]
        → domain service → tenant-scoped repository → D1
        → response shaping (never raw rows)
        → security headers, cache-control: private
```

Target budgets: p50 60 ms, p95 250 ms at the edge excluding D1 time; D1 query p95 < 15 ms; total p95 < 400 ms.

## 4. Asynchronous path (correction)

```
POST /corrections            → create job (idempotency_key) → enqueue message {jobId, workspaceId}
Queue consumer               → claim job (lease) → Workflow instance
Workflow steps               → fetch input → prepare → call provider → verify → reconcile → persist
                             → publish progress to workspace DO → on terminal, notify + index
Failure                      → classified retry / park / fail → DLQ row + notification
```

Queue messages carry **ids only** (Queues cap messages at 128 KB; a prepared payload would not fit and would
be stale anyway).

## 5. Data flow and ownership

| Data | Store | Authority | Retention |
|---|---|---|---|
| Accounts, sessions | D1 | D1 | session TTL; audit 12 months |
| Workspaces, memberships | D1 | D1 | life of workspace |
| Students, classes, assignments | D1 | D1 | life of workspace |
| Scripts (PDF/JPG) | R2 | R2, referenced by D1 row | per retention policy |
| Marks, overrides, approvals | D1 | D1 | life of workspace + audit |
| Job state | D1 (job row) + DO (live) | **D1** | 90 days after terminal |
| Reports | R2 + D1 row | R2 | life of assignment |
| Audit | D1 (append-only) | D1 | 12 months (configurable) |
| Provider credentials | D1 (encrypted blob) | D1 + KMS secret | until rotated/deleted |

The Durable Object is **never** the authority for anything durable. It is a fan-out hub; if it dies, the
client refetches from D1.

## 6. Stack

| Concern | Choice | Notes |
|---|---|---|
| Runtime | Cloudflare Workers (Paid) | Free tier's 10 ms CPU cannot hash passwords |
| Framework | TanStack Start 1.0 (SSR React) | Stable 2026-10-13; alternative React Router v8 |
| Language | TypeScript strict | No `any` at the API boundary |
| DB | D1 (SQLite) | 10 GB/database hard cap |
| ORM / query | Thin typed query layer over `d1.prepare` | No heavy ORM: D1's model is SQL-first |
| Files | R2 | Free egress |
| Jobs | Queues + Workflows | Durable multi-step |
| Realtime | Durable Objects (hibernating WS) | Progress + notifications |
| Auth | Better Auth + D1 | Organizations, MFA, passkeys |
| Validation | zod (shared client/server) | One schema, two consumers |
| PDF rendering | **External service or container** | ReportLab/PyMuPDF are Python-native |
| Email | Transactional provider | Invites, notifications, security alerts |
| Payments | Deferred | Metering only in MVP |

## 7. Why the PDF question is architectural, not incidental

V5 renders reports with ReportLab and inspects PDFs with PyMuPDF. Neither runs in a Worker. Three options:

1. **Containers (Workers Containers)** — run a small Python service; full parity, but new operational surface
   and cost, and its GA status should be re-verified before dependending on it.
2. **External render service** — e.g. a managed PDF API; simplest, but sends student data to another
   processor (privacy + DPA impact).
3. **Reduce the need** — client-side PDF rendering for viewing (pdf.js), and generate reports as HTML/CSS
   printed to PDF in the browser; no server-side rendering at all.

**Recommendation:** option 3 for viewing, and option 1 for authoritative report PDFs, because a
server-generated report must be reproducible and attachable without a browser. This is decided in phase 1
(`../product/PRODUCT_ROADMAP.md`), not discovered in phase 7.

## 8. Cross-cutting rules

- **No secret ever reaches the client.** Credentials decrypt only inside the Worker for an outbound call.
- **Every query is workspace-scoped.** Enforcement lives in the data layer (see `MULTI_TENANCY.md`).
- **Errors are typed.** A domain error maps to one HTTP problem code; provider errors are wrapped, never
  passed through.
- **Everything long is a job.** Request handlers may not wait on an AI call.
- **Everything remote is eventually consistent.** Classroom and provider state is reconciled, not assumed.
