# Aetrix V5.5 — agent instructions

Pre-release integration checkpoint for an AI-assisted mathematics-marking platform.
The correction engine is real: **`aetrix_legacy` is the shipped default and `aetrix_v5_5` is
registered and selectable**, while `mathchecker_v5` is registered but raises
`EngineNotImplemented`. Nothing may be described as working beyond what the code and a
passing check demonstrate.

## Non-negotiables

1. **Describe what the code does.** Marking, SymPy verification, results, teacher review,
   overrides and approvals are implemented through `aetrix_legacy` and, when selected,
   `aetrix_v5_5`. Cohort intelligence,
   Supabase Storage, malware scanning, rate limiting, the authenticated data frontend,
   Cloudflare data bindings and production deployment are **not implemented**.
   The live provider is `UNVERIFIED`; the benchmark holdout has zero certified papers.
2. **Tenant isolation is not optional.** Resolve the tenant from the verified JWT claim in
   `backend/app/api/deps.py`; never from a request body. Cross-tenant reads must look
   nonexistent.
3. **Schema changes ship as Alembic migrations** (edit `models.py` *and* add a revision).
   No `create_all`, no SQLite path.
4. **No invented data in the UI.** `ApiResult` has an `unavailable` state — use it. Never
   render zeros, sample rows or placeholder metrics.
5. **Never weaken a check** to make a change pass: no skipped tests, relaxed assertions,
   `--no-verify`, or lint/type suppressions.
6. Preserve the historical blueprint in `docs/` (D1 / Better Auth / R2 / Queues). It is
   history, not the implemented data layer (ADR-001).

## Layout

| Path | What lives there |
|---|---|
| `backend/` | FastAPI engine, SQLAlchemy 2.0, Alembic, worker, pytest (`backend/tests`) |
| `frontend/` | TanStack Start + React 19 on Cloudflare Workers, Playwright (`frontend/tests`) |
| `benchmark/` | Frozen correction benchmark — never imported by production code |
| `docs/` | Product blueprint history; `docs/engine/` + `docs/architecture/` are current |
| `.agents/skills/` | Project agent skills (this file's routing table points into them) |

## Commands

`node`/`python` are not on PATH here.

```bash
cd backend  && .venv/Scripts/python.exe -m ruff check app tests
cd backend  && .venv/Scripts/python.exe -m pytest -q
cd frontend && ../.tools/node/node.exe node_modules/typescript/bin/tsc --noEmit
cd frontend && ../.tools/node/node.exe node_modules/vite/bin/vite.js build
cd frontend && ../.tools/node/node.exe node_modules/@playwright/test/cli.js test   # needs preview on :3000
```

## Skills

Project skills live in `.agents/skills/<name>/SKILL.md` (Agent Skills format: read the whole
file when its description matches the task). They are enumerated when a session starts, so a
newly added skill appears in the next session. Read the specific skill before working in its
area — do not read all of them.

| Task | Read first |
|---|---|
| Any non-trivial change, or any status claim | `aetrix-architecture` |
| Backend Python, API, models, migrations, worker, providers | `aetrix-backend`, `modern-python` |
| Frontend routes, shell, components, styles, motion, e2e | `aetrix-frontend`, `vercel-react-best-practices` |
| Auth, authorization, tenant isolation, uploads, secrets | `aetrix-security`, `supabase` |
| SQL, schema design, indexes, RLS, query performance | `supabase-postgres-best-practices` |
| Workers build/deploy, wrangler config | `wrangler`, `workers-best-practices`, `frameworks-on-cloudflare` |
| Debugging a failure | `diagnosing-bugs`; the account-level systematic-debugging skill covers general bugs |
| Before claiming completion | `aetrix-verification`, `verification-before-completion` |
| Reviewing a diff | `code-review`, `find-bugs`, `security-review` |
| Simplify / redesign a module boundary | `code-simplifier`, `codebase-design` |
| Terminology, glossary, ADR wording | `domain-modeling` |
| Writing or editing a skill / this file | `writing-for-agents`, `agents-md` |
| Design, UI critique, motion, accessibility | `frontend-design`, `impeccable`, `design-motion-design`, `accessibility-inclusive-design` |
| Browser-driven checks / Playwright traces | `playwright-cli` (CLI binary is optional; see its SKILL.md) |

Catalog, licenses and rationale: `docs/agent-skills/SKILL_CATALOG.md`.
