---
name: aetrix-architecture
description: Load before any non-trivial Aetrix change to decide which layer owns it and what may truthfully be claimed. Covers the backend/frontend/benchmark boundaries, the historical-vs-implemented documentation split, the seven engine invariants, and which capabilities are still unimplemented. Use when planning work, adding a feature, reviewing a change, or writing any status, README, UI copy or report about Aetrix.
license: Proprietary (Aetrix project skill)
metadata:
  author: Aetrix
  version: '1.0.0'
---

# Aetrix architecture and truth

Aetrix V5.5 is a pre-release integration checkpoint for AI-assisted mathematics marking.
It is **not** a production service, and no marking-accuracy or production-readiness claim
is supported by the repository.

## The one rule that overrides everything

**Describe what the repository does, never what it is meant to do.**

Every screen, document and commit message must match implemented behaviour. The most
common failure mode in this repository is prose that implies marking works because the
architecture supports it. It does not work; the pipeline is explicitly unavailable.

## Repository layout

| Path | Role | Truth status |
|---|---|---|
| `backend/` | FastAPI correction engine, SQLAlchemy 2.0 models, Alembic history, worker, tests | **Implemented authority** (CP1–CP2) |
| `backend/migrations/` | Alembic history, constraints, triggers, RLS guard | Implemented; PostgreSQL-specific |
| `frontend/` | TanStack Start marketing surface plus the app shell | Marketing real; authenticated data screens WIP |
| `benchmark/` | Frozen A/B/C correction-strategy benchmark, 207 tests | Frozen; no production imports |
| `docs/` | Original product blueprint (D1, Better Auth, R2, Queues) | **History, not implementation** |
| `docs/engine/`, `docs/architecture/AETRIX_V5.5_SYSTEM.md` | Implemented-engine evidence and system overview | Current |

ADR-001 records the conflict: the blueprint specifies Cloudflare D1 / Better Auth / R2 /
Queues, while the engine is PostgreSQL/Supabase with SQLAlchemy and Alembic. Never
describe the D1 blueprint as the current data layer, and never "restore" it.

## Implemented vs not implemented

Implemented: tenancy and JWT verification, canonical blueprint approval and overrides,
persistent jobs with leases and audit, provider quota and append-only usage, document
ingestion/rendering, page mapping, draft extraction, safe provider errors, migrations.

**Not implemented — do not build UI or docs that pretend otherwise:** marking, SymPy
verification, results, selective review, cohort intelligence, Supabase Storage, malware
scanning, rate limiting, the authenticated data frontend, Cloudflare data bindings,
production deployment. The live provider is `UNVERIFIED`; the benchmark holdout has zero
certified papers.

## Seven invariants

1. A correction job requires an approved, immutable blueprint version. Extraction creates
   only `DRAFT`; an override creates a new version.
2. Every tenant-owned row is scoped by `tenant_id`. Cross-tenant reads must look
   nonexistent, not forbidden-with-detail.
3. `audit_events`, `job_events` and `provider_usage` are append-only at the database layer.
4. Provider credentials are encrypted at rest; only fingerprints and health are returned.
5. Provider output is untrusted until parsed and schema-validated. Malformed output
   creates no blueprint.
6. The worker claims with a real PostgreSQL lease and records every attempt. It parks
   honestly (`PIPELINE_UNAVAILABLE`) rather than inventing marks.
7. The benchmark's frozen digests and pre-registered scoring are never modified.

## Boundaries

- Production code never imports `benchmark/`; the frontend never imports engine code.
- Vendor SDK types never cross `backend/app/providers/` — the boundary is the
  `LLMProvider` protocol.
- The API and worker are separate processes with separate crash domains.
- `docs/` history is preserved; corrections are appended as ADRs, not by rewriting history.

## Routing a change

| The work is about… | Load |
|---|---|
| Python, FastAPI, SQLAlchemy, Alembic, worker, providers | `aetrix-backend`, then `modern-python` |
| React, TanStack, routing, styles, animation, e2e | `aetrix-frontend`, then `vercel-react-best-practices` |
| Authentication, authorization, tenant isolation, secrets, uploads | `aetrix-security`, then `supabase` |
| Schema, migrations, indexes, RLS, query performance | `supabase-postgres-best-practices` |
| Workers build, wrangler, deployment config | `wrangler`, `workers-best-practices`, `frameworks-on-cloudflare` |
| Claiming work is done | `aetrix-verification`, then `verification-before-completion` |
| Terminology, glossary, ADR wording | `domain-modeling` (keep Aetrix nouns: tenant, blueprint, job, submission, page, override) |

## When the architecture is the problem

If a fix needs cross-layer change (schema + API + UI) or three fixes in one area keep
revealing new coupling, stop and write the decision down before coding:
`docs/decisions/` holds ADRs. Use `codebase-design` to find the seam, and record the
choice as an ADR with the rejected alternatives.

## Language

Use the project's nouns exactly: workspace/tenant, class, assignment, submission, page,
blueprint, blueprint version, extraction, override, job, lease, run, marker, reviewer.
"Grade", "score" and "result" are unimplemented concepts — say so when they come up.
