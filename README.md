# Aetrix V5.5

**Repository:** [AetherRIP/Aetrix_V5.5](https://github.com/AetherRIP/Aetrix_V5.5)

**Aetrix V5.5 is the unified correction engine and platform repository for AI-assisted
mathematics marking.** It combines the engine implementation, the public frontend, the
frozen correction benchmark, and the product/architecture record in one repository.

> **Status: pre-release integration checkpoint.** The correction engine implements the
> tenant, blueprint, job, provider, ingestion, mapping, extraction and override substrate.
> Marking, verification, results, cohort intelligence and the authenticated workspace are
> not implemented. The public marketing surface is the only frontend in this repository.
> No production-readiness, marking-accuracy or live-structured-output claim is made.

## Components

| Path | What it is | Status |
|---|---|---|
| [`backend/`](backend/) | FastAPI correction engine, SQLAlchemy/Alembic schema, provider boundary, worker, tests | CP1–CP2 implemented |
| [`frontend/`](frontend/) | TanStack Start/React public marketing and sign-in-status surface on Cloudflare Workers | Marketing surface only; authenticated app not built |
| [`benchmark/`](benchmark/) | Frozen A/B/C correction-strategy benchmark and teacher-certified holdout intake | 207 tests; holdout at zero certified papers |
| [`docs/`](docs/) | Original product/architecture blueprint, audit and remediation set | Historical planning record |
| [`docs/engine/`](docs/engine/) | Implemented-engine architecture, deployment, security and acceptance evidence | CP2 evidence; live Gemini UNVERIFIED |
| [`docs/architecture/AETRIX_V5.5_SYSTEM.md`](docs/architecture/AETRIX_V5.5_SYSTEM.md) | Unified architecture and source-of-truth note | Current |
| [`docs/consolidation/CONSOLIDATION_REPORT.md`](docs/consolidation/CONSOLIDATION_REPORT.md) | Repository inventory, consolidation decisions and migration notes | Current |
| [`docs/audits/FINAL_VERIFICATION_REPORT.md`](docs/audits/FINAL_VERIFICATION_REPORT.md) | Final verification results and limitations | Current |

## Architecture

The **implemented authority** is `backend/` plus the engine ADRs and acceptance evidence in
`docs/engine/`. The engine uses PostgreSQL 15+ (Supabase in development), SQLAlchemy 2.0,
Alembic, a narrow `LLMProvider` boundary and versioned prompt assets. The API and worker are
separate processes; the worker leases jobs with `FOR UPDATE SKIP LOCKED`.

The original destination blueprint describes Cloudflare D1, Better Auth, R2, Queues and
Workflows. That set is preserved as history, not as the implemented data layer. ADR-001 records
the conflict; the engine uses PostgreSQL/Supabase and the frontend has no D1/R2/Queue bindings.
The authenticated app's hosting and identity decision remains a future integration point.

The public frontend is a marketing surface only. It does not call the engine, store student data
or claim that sign-in is enabled. The correction engine does not import frontend code or the
benchmark.

## Local setup

### Prerequisites

- Python 3.12–3.13.
- PostgreSQL 15+ (Supabase or another PostgreSQL service). SQLite is refused.
- Node.js 20+ and npm for the frontend.
- Optional: a Gemini API key for the bounded live probe. Never commit it.

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv/Scripts/python.exe -m pip install -e ".[dev,benchmark]"
# macOS/Linux:
# .venv/bin/python -m pip install -e ".[dev,benchmark]"
cp .env.example .env
# Fill AETRIX_DATABASE__URL, auth and encryption values in .env.
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest -q
```

Run the API with `python -m uvicorn app.main:app --port 8000` from `backend/`, or the
installed `aetrix-api` entry point. Run the worker separately with `aetrix-worker`.
The worker currently parks correction jobs with `PIPELINE_UNAVAILABLE`; that is deliberate.

### Frontend

```bash
cd frontend
npm ci
npm run typecheck
npm run build
npm run dev
```

`npm run test:e2e` requires Playwright browsers. The marketing site has no backend calls and no
secrets. Cloudflare deployment is not part of this checkpoint; `wrangler.jsonc` declares only
the marketing Worker.

### Benchmark

From the repository root:

```bash
python -m pytest benchmark/tests benchmark/holdout/tests -q
python -m benchmark.holdout.manifest --check-code
```

The benchmark needs `sympy` for its verifier; the `backend[benchmark]` extra installs it. It
also needs Pillow and NumPy, which are backend dependencies. Live benchmark runs require an
authorised provider key outside this repository; offline tests do not.

## Security and data handling

- **No secrets in Git.** `backend/.env`, `.dev.vars`, keys and certificates are ignored.
  `backend/.env.example` contains placeholders only. Use a secret store in production.
- **No raw student data.** The public consolidation keeps redacted benchmark page images but
  excludes the original student/scheme PDFs and temporary local renders. See
  [`benchmark/PUBLIC_DATA_NOTICE.md`](benchmark/PUBLIC_DATA_NOTICE.md).
- **Live provider spend is bounded.** The manual probe makes one request per invocation; the
  recorded post-change Gemini attempts were rejected at authentication and are reported as
  `UNVERIFIED`, not simulated.
- **Tenant isolation and append-only audit/usage** are implemented in repositories and database
  triggers, with PostgreSQL integration tests.

## Current limitations

- No marking, SymPy verification, results, selective review or cohort-intelligence pipeline.
- No authenticated workspace, workspace provisioning or D1/R2/Queue deployment.
- The live Gemini structured-output path is `UNVERIFIED` after provider 403 responses.
- The holdout has zero certified papers; no general marking-parity claim is possible.
- The frontend build and browser tests depend on a local Node runtime; see the final report for
  the checks that were actually executable.

## Repository history

This repository was formerly `WebPage_UI_V5.5`. The engine was developed in
[`Engine_V5.5`](https://github.com/AetherRIP/Engine_V5.5), which remains a recoverable source
repository. The final project version is **V5.5**. See the consolidation report for the exact
commits and preserved history.
