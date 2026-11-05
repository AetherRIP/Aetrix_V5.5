# Aetrix V5.5 — Product & Architecture Blueprint (historical UI_V5.5 set)

**Status:** planning only. No application code, no Cloudflare resources, no dependencies installed.
**Workspace:** `TEMP` (future `UI_V5.5`) · **Prepared:** 2026-11-03
**Product:** MathChecker — AI-assisted marking for Edexcel IGCSE 4MA1, becoming a multi-tenant SaaS.

> **Consolidation note (2026-11-05):** This is the original planning, audit and
> remediation set, retained for history. It predates the unified repository. The
> implemented correction engine uses PostgreSQL/Supabase and lives in `backend/`;
> its current documentation is under [`engine/`](engine/README.md). Where this set
> and the engine conflict, the engine ADRs and implementation docs govern.

---

## What this package is

A decision-oriented blueprint for turning MathChecker V5 (a local-first FastAPI + React + SQLite
application with a WPF companion) into a multi-tenant SaaS hosted on Cloudflare.

Every major decision states the alternatives considered, why one was chosen, and what would force a
revisit. Nothing here claims that proposed functionality already exists in V5; where V5 behaviour is
described it was read from `C:\Projects\MATH_CHECKER_V5` (`README.md`, `docs/ARCHITECTURE.md`,
`backend/app/schema.sql`, `docs/ui-identity-v6.md`).

## The ten decisions that matter

| # | Decision | Choice | Confidence |
|---|---|---|---|
| 1 | Frontend framework | **TanStack Start 1.0** (SSR React) on Workers; React Router v8 as fallback | High |
| 2 | Topology | One Worker first; split to `app.` Custom Domain when release cadence diverges | Medium |
| 3 | Database | **D1, shared schema, `workspace_id` on every tenant table** | High |
| 4 | Isolation | Row-level, enforced in a typed tenant-scoped data layer + composite indexes | High |
| 5 | Auth | **Better Auth** self-hosted on Workers + D1 (orgs, MFA, passkeys) | High |
| 6 | Files | **R2**, workspace-prefixed keys, Worker-signed short-TTL URLs, multipart uploads | High |
| 7 | Background work | **Queues + Workflows**; queue messages carry ids only | High |
| 8 | Real-time | **One hibernating Durable Object per workspace** + polling fallback | Medium |
| 9 | AI access | Provider abstraction; per-workspace keys encrypted at rest; server-side only | High |
| 10 | Billing | **Out of MVP**; meter usage from day one so billing is a migration, not a rewrite | High |

## Reading order

1. [`product/PRODUCT_VISION.md`](product/PRODUCT_VISION.md) — who it is for, what changes, what is out of scope.
2. [`product/FEATURE_INVENTORY.md`](product/FEATURE_INVENTORY.md) — ground truth: what V5 does; preserved / redesigned / new / deferred.
3. [`architecture/SYSTEM_ARCHITECTURE.md`](architecture/SYSTEM_ARCHITECTURE.md) — the shape of the system.
4. [`architecture/MULTI_TENANCY.md`](architecture/MULTI_TENANCY.md) — the isolation model and how it is enforced.
5. [`architecture/DATABASE_DESIGN.md`](architecture/DATABASE_DESIGN.md) — schema, ERD, V5→V5.5 migration map.
6. [`design/DESIGN_DIRECTIONS.md`](design/DESIGN_DIRECTIONS.md) — six directions, one recommendation.
7. [`decisions/OPEN_QUESTIONS.md`](decisions/OPEN_QUESTIONS.md) — what only the product owner can answer.

## Document map

```
docs/
  README.md                     this file
  product/     PRODUCT_VISION · FEATURE_INVENTORY · USER_ROLES_AND_PERMISSIONS
               USER_JOURNEYS · PRODUCT_ROADMAP
  design/      DESIGN_DIRECTIONS · DESIGN_SYSTEM · INFORMATION_ARCHITECTURE
               SCREEN_INVENTORY · RESPONSIVE_DESIGN · ACCESSIBILITY
  architecture/SYSTEM_ARCHITECTURE · MULTI_TENANCY · DATABASE_DESIGN · API_DESIGN
               CLOUDFLARE_ARCHITECTURE · BACKGROUND_PROCESSING · REALTIME_ARCHITECTURE
  security/    THREAT_MODEL · SECURITY_REQUIREMENTS · DATA_PRIVACY
  operations/  DEPLOYMENT_PLAN · MONITORING_AND_LOGGING · BACKUP_AND_RECOVERY
               COST_AND_SCALABILITY
  testing/     TEST_STRATEGY · TENANT_ISOLATION_TESTS · ACCEPTANCE_CRITERIA
  decisions/   OPEN_QUESTIONS · ARCHITECTURE_DECISIONS · ASSUMPTIONS_AND_RISKS
```

## Label discipline

- **VERIFIED** — read from official documentation in this pass; source cited.
- **RECOMMENDED** — our judgement; alternatives documented in `decisions/ARCHITECTURE_DECISIONS.md`.
- **ASSUMPTION** — unverified; tracked in `decisions/ASSUMPTIONS_AND_RISKS.md`.
- **UNKNOWN** — needs the product owner; tracked in `decisions/OPEN_QUESTIONS.md`.

## Hard constraints honoured by this package

- No Cloudflare resource created, no domain or DNS configured, no account registered, no deployment.
- No application dependency installed; no framework scaffolded; no `package.json`, no `wrangler.toml`.
- The V5 repository was inspected read-only and is untouched.
- `TEMP` was not renamed.
- Cost figures are estimates with stated assumptions; Cloudflare unit prices are cited from official
  pricing pages read on 2026-11-03 and will drift.
