# Aetrix V5.5 — unified system architecture

**Status:** pre-release integration checkpoint. This document describes what exists in the
repository, not a production service.

## 1. Source of truth

The unified repository has two layers of documentation:

- `docs/` is the original hosted-platform blueprint, audit and remediation set. It records the
  D1/Better Auth/R2/Queues direction and remains useful as product and design history.
- `docs/engine/` and `backend/` are the implemented correction-engine authority. The engine uses
  PostgreSQL/Supabase, SQLAlchemy 2.0, Alembic and a provider-neutral model boundary.

ADR-001 records the architecture conflict. The engine's PostgreSQL decision is implemented;
the authenticated frontend's data/auth layer is not. Do not describe the D1 blueprint as the
current engine implementation.

## 2. Runtime shape

```text
Browser
  └── frontend/  (TanStack Start + React; marketing surface only today)
          │  HTTPS + Bearer JWT (future authenticated app)
          ▼
backend/ FastAPI API  ──────────────┐
  │  SQLAlchemy 2.0                 │
  ▼                                 ▼
PostgreSQL/Supabase              Gemini REST adapter
  ▲                                 ▲
  │  FOR UPDATE SKIP LOCKED         │  prompt assets + credential lease
backend/ worker ────────────────────┘
  └── CorrectionPipeline (currently unavailable; jobs park honestly)
```

The API and worker are separate processes with separate crash domains. Ingestion, mapping,
scheme extraction and overrides are synchronous in this checkpoint. Marking is not implemented.
The benchmark is a separate, frozen harness; production code does not import it.

## 3. Components and boundaries

| Component | Responsibility | Boundary |
|---|---|---|
| `frontend/` | Public marketing and sign-in-status pages | No engine calls, no student data, no Cloudflare bindings beyond the marketing Worker |
| `backend/app/api/` | HTTP routes, authentication dependency, typed errors | Tenant resolved from verified identity, never request body |
| `backend/app/db/` | SQLAlchemy models, tenant-scoped repositories, PostgreSQL leases | No SQLite production path |
| `backend/app/documents/` | Validation, rendering, quality, ordering, mapping, extraction | Uploads are untrusted; every page persisted with reasons |
| `backend/app/providers/` | `LLMProvider` protocol and Gemini REST adapter | No SDK/vendor types cross the boundary |
| `backend/app/services/` | Blueprint/scheme/override and provider-call orchestration | Quota, prompt provenance and append-only usage |
| `backend/app/jobs/` | Job state machine, leases, worker | Pipeline is explicitly unavailable |
| `backend/migrations/` | Alembic history and constraints/triggers | PostgreSQL-specific; no hidden schema creation |
| `benchmark/` | A/B/C strategy benchmark and holdout intake | Frozen dataset/digests; not a production dependency |
| `docs/` + `docs/engine/` | Product blueprint/history and implemented-engine evidence | Historical conflict is explicit |

## 4. Key invariants

1. A correction job requires an **approved, immutable blueprint version**; extraction creates
   only `DRAFT` and overrides create a new version.
2. Every tenant-owned row is scoped by `tenant_id`; cross-tenant reads look nonexistent.
3. `audit_events`, `job_events` and `provider_usage` are append-only at the database layer.
4. Provider credentials are encrypted at rest; only fingerprints and health are returned.
5. Provider output is untrusted until parsed and schema-validated. Malformed output creates no
   blueprint.
6. The worker claims with a real PostgreSQL lease and records every attempt. It does not invent
   marks when the pipeline is unavailable.
7. The benchmark's frozen digests and pre-registered scoring are not changed by consolidation.

## 5. Current implementation status

- **Implemented:** tenancy/auth verification, canonical blueprint approval and overrides,
  persistent jobs/leases/audit, provider quota/usage, document ingestion/rendering, page
  mapping, draft extraction, safe provider errors, Alembic migrations, tests.
- **Not implemented:** marking, SymPy verification, results, selective review, cohort
  intelligence, Supabase Storage, malware scanning/rate limiting, authenticated frontend,
  Cloudflare data bindings, production deployment.
- **Live provider:** `UNVERIFIED`; post-change requests returned 503/503/403 and 403. No live
  `DRAFT` exists. The pre-change prose response is evidence of transport only.
- **Benchmark:** 207 tests pass; the holdout has zero certified papers, so no accuracy or
  production-readiness claim follows.

See [`../engine/architecture/SYSTEM_OVERVIEW.md`](../engine/architecture/SYSTEM_OVERVIEW.md) and
[`../audits/FINAL_VERIFICATION_REPORT.md`](../audits/FINAL_VERIFICATION_REPORT.md).
