# Architecture Decision Records

Format: context → decision → alternatives → consequences → revisit trigger.
These ADRs bind the build unless explicitly superseded.

**Labels.** Every ADR records a **RECOMMENDED** decision. The platform facts cited inside Context, Alternatives
and Consequences are **VERIFIED** against official Cloudflare, TanStack and Better Auth documentation (citations
in `../operations/COST_AND_SCALABILITY.md` and `../architecture/CLOUDFLARE_ARCHITECTURE.md`). Forward-looking
statements — storage growth, cost per script, whether a beta matures — are **ASSUMPTION**. Provider behaviour we
have not measured first-hand is **UNKNOWN**.

---

## ADR-001 — Frontend: TanStack Start 1.0 on Workers

**Context.** SSR-capable React with minimal platform friction; V5 is React 18 + Vite.
**Decision.** TanStack Start 1.0 (stable 2026-10-13) via the Cloudflare Vite plugin, one Worker.
**Alternatives.** React Router v8 — equally supported, but SPA mode and prerendering are unsupported behind the
Cloudflare plugin; Next.js via OpenNext — Cloudflare now documents it as maintenance mode and steers to
vinext; vinext — beta, with real gaps in cache components/PPR and build-time image/font optimisation;
SvelteKit/Nuxt — would abandon the team's React skills.
**Consequences.** Native bindings (`cloudflare:workers`), workerd-accurate dev, no adapter shim. Youngest of
the stable set, mitigated by a phase-1 spike.
**Revisit if.** Start proves unstable in phases 2–3.

## ADR-002 — Topology: one Worker first

**Decision.** Apex Custom Domain serving marketing + app + `/api/v1`; split marketing to `app.` later.
**Alternatives.** Two Workers day one (two deploys, OAuth callback across zones); Routes in front of a Custom
Domain (same-zone `fetch` then needs a service binding).
**Consequences.** One deploy, shared design system. Watch: Custom Domains are exact-hostname, so `www` needs a
redirect rule; SPA navigations bypass the Worker, so the OAuth callback needs a static helper page.
**Revisit if.** Marketing release cadence diverges or a CMS is introduced.

## ADR-003 — Database: D1 with a shared schema

**Decision.** One D1 database; `workspace_id` on every tenant table; tenant-bound repository.
**Alternatives.** Database-per-tenant — 10 GB hard cap and **no dynamic bindings**, plus fan-out reporting and
N migrations; Postgres + Hyperdrive — real RLS and JSONB, but ~50 ms/query, a second vendor, and a 25-config
limit.
**Consequences.** Cheapest to run, one migration path, cheap cross-tenant aggregates. Isolation is
application-enforced, so the isolation suite is a shipping gate.
**Revisit if.** A contract requires database-level isolation (→ enterprise tier) or a database nears 10 GB
(not projected: ≈0.75 GB at 100 workspaces).

## ADR-004 — Isolation: four layers with a server-minted `TenantContext`

**Decision.** Session → membership → `TenantContext` → `workspace_id` in every predicate; 404 not 403.
**Alternatives.** Middleware-only scoping (leaks on one missed route); Postgres RLS (unavailable in SQLite).
**Consequences.** A handler cannot express an unscoped query. Cost: repositories take a context object and
every new table must carry `workspace_id`.
**Revisit if.** A leak occurs despite the suite — the response is structural, not another review.

## ADR-005 — Auth: Better Auth, self-hosted

**Decision.** Better Auth on Workers + D1 with the organization plugin, TOTP MFA, passkeys, DB sessions plus a
short signed cookie cache.
**Alternatives.** Clerk (≈$25 + $100 B2B/mo, member caps); Auth0 (per-org caps, per-connection upsells);
WorkOS (free AuthKit, $125/connection for SSO); Supabase Auth (bundles a Postgres we do not want); Cloudflare
Access (not customer auth — no signup, no organizations).
**Consequences.** No licence cost, full data control. scrypt hashing requires Workers **Paid**: the Free tier's
10 ms CPU cannot hash a password. We own upgrades.
**Revisit if.** Enterprise SSO is sold → add WorkOS as a bolt-on rather than replacing auth.

## ADR-006 — Files: R2 with Worker-signed URLs

**Decision.** Keys `ws/{workspaceId}/…`; uploads via 15-minute Worker-signed targets; downloads via 5-minute
signed URLs; multipart above 50 MB.
**Alternatives.** S3 presigning (needs long-lived R2 credentials we will not hold); `r2.dev` public buckets
(test-only and rate-limited); streaming every byte through the Worker (workable, but ranges and CPU suffer).
**Consequences.** Free egress, no public bucket, keys server-derived so path traversal is impossible.
**Revisit if.** Per-object CDN audit becomes a requirement.

## ADR-007 — Jobs: Queues + Workflows with ids-only messages

**Decision.** The API enqueues `{jobId, workspaceId}`; a consumer claims a lease and starts an eight-step
idempotent Workflow; retry classification is ported from V5 unchanged in intent.
**Alternatives.** Work inside the request (CPU limits, tab closure); one long Queue consumer (no durable
multi-step state); DO alarms (couples orchestration to state).
**Consequences.** Queues are at-least-once, so idempotency keys and lease claims are mandatory. The 128 KB
message cap is irrelevant because payloads live in R2.
**Revisit if.** Workflow limits bite at high fan-out.

## ADR-008 — Realtime: one hibernating Durable Object per workspace

**Decision.** WebSocket hub per workspace; single-use 30-second ticket; coalesced progress; polling fallback.
**Alternatives.** SSE only (no fan-out primitive); polling only (kept as fallback, not default); presence and
live cursors (deferred — no value at 5–10 assistants).
**Consequences.** Idle sockets are cheap; membership changes close sockets; the DO is never authoritative.
**Revisit if.** Presence becomes a genuine requirement.

## ADR-009 — Billing deferred, metering built now

**Context.** Charging requires pricing, tax, dunning and a vendor decision. Usage must be attributable from the
first job or the history is lost forever.
**Decision.** No billing in the MVP. `usage_events` (append-only, per job/model/tokens/cost) and `usage_daily`
(rollup) ship with P5; quotas are enforced per workspace.
**Alternatives.** Stripe from day one (blocks P1–P4 on a commercial decision while adding webhook, invoice and
tax surface); no metering (cannot price retroactively); third-party metering service (extra vendor for a table
we can write ourselves).
**Consequences.** Costs are observable and prices can be set later from real data. Quota enforcement is a
financial control, not a paywall, and must fail closed.
**Revisit if.** Pricing is decided → add Stripe behind the existing usage tables; no schema change needed.

## ADR-010 — Design language: continue "Instrument"

**Decision.** Build on `docs/ui-identity-v6.md`: ink-graphite surfaces, cyan-teal accent, ledger-style tables,
Space Grotesk / Plus Jakarta Sans / Cascadia Mono, plus an annotation callout for review-reason display and a
denser markbook table.
**Alternatives.** A new identity (discards an approved direction for cosmetic novelty); generic admin template
(reads as a tool, not a markbook).
**Consequences.** Design tokens, typography and density are constrained by an existing document, which is a
feature. The annotation callout is the only additive component.
**Revisit if.** Accessibility testing contradicts the contrast pairs (fix tokens, not the direction).

## ADR-011 — Marking parity before redesign

**Decision.** P1 ports the V5 engine and proves parity against V5 output on a fixed fixture set **before** the
design system is built or any screen is redrawn.
**Alternatives.** Build UI first (marks are the product; a beautiful surface over drift is worse than no
surface); parallel tracks (a drift bug found in P3 invalidates P2's screens).
**Consequences.** The visual layer starts later but lands once. The parity fixture set becomes a permanent
regression gate.
**Revisit never.** This is the load-bearing sequencing decision.

## ADR-012 — One shared schema, no soft delete on jobs

**Decision.** Corrections/results are soft-deleted (`deleted_at`) for recovery; jobs are terminal-state rows
kept forever; papers and answer files are hard-deleted from R2 on workspace deletion.
**Alternatives.** Soft delete everywhere (rows accumulate, every query needs a filter); hard delete everywhere
(one-click data loss, no audit trail).
**Consequences.** Every tenant query must filter `deleted_at IS NULL` — enforced in the repository layer, not
by memory.
**Revisit if.** Row growth from retained jobs becomes material.

## ADR-013 — Testing: isolation as a compile-time and CI gate

**Decision.** The tenant repository is the only DB entry point; a lint rule forbids raw `env.DB` outside it; the
isolation suite runs on every PR and blocks merge on failure.
**Alternatives.** Review discipline (fails silently); runtime assertions only (catch the leak after deploy).
**Consequences.** Some legitimate cross-tenant admin queries need an explicit escape hatch (`systemContext`)
that is itself audited and tested.
**Revisit if.** The escape hatch starts appearing in feature code.

## ADR-014 — Observability: platform-native first

**Decision.** Workers Logs, Analytics Engine for domain counters, `usage_events` for cost, plus a `/health`
route and structured `requestId`-correlated logs. No third-party APM until P6.
**Alternatives.** Sentry/Datadog day one (cost and a second vendor before there is traffic to observe).
**Consequences.** Debugging relies on `wrangler tail` and log search; no distributed tracing across the Queue →
Workflow boundary beyond correlated ids.
**Revisit if.** An incident takes longer to diagnose than the tooling cost would have.

## ADR-015 — Migration from V5 is export/import, not shared storage

**Decision.** V5 remains the source of truth until P1 parity passes; migration reads V5 SQLite exports and writes
through the public API path, not by copying tables.
**Alternatives.** Direct table copy (schema and identity differ; skips validation); dual-write (two sources of
truth during the riskiest phase).
**Consequences.** Imports are slower and exercise real code paths, which is the point. `CH1L1`-style lesson
identities are preserved as external references.
**Revisit if.** A pilot customer's dataset is too large for API-paced import.

---

## Decision index

| ADR | Area | Status |
|---|---|---|
| 001 | Frontend | Accepted |
| 002 | Topology | Accepted |
| 003 | Database | Accepted |
| 004 | Isolation | Accepted |
| 005 | Auth | Accepted |
| 006 | Files | Accepted |
| 007 | Jobs | Accepted |
| 008 | Realtime | Accepted |
| 009 | Billing / metering | Accepted |
| 010 | Design language | Accepted |
| 011 | Delivery order | Accepted |
| 012 | Data lifecycle | Accepted |
| 013 | Testing gates | Accepted |
| 014 | Observability | Accepted |
| 015 | V5 migration | Accepted |

Superseding an ADR requires a new numbered record that names the one it replaces; editing an accepted record in
place is not allowed. Unresolved items live in `OPEN_QUESTIONS.md`, not here.
