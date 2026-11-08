# Aetrix V5.5

**Repository:** [AetherRIP/Aetrix_V5.5](https://github.com/AetherRIP/Aetrix_V5.5)

**Aetrix V5.5 is the unified correction engine and platform repository for AI-assisted
mathematics marking.** It combines the engine implementation, the public frontend, the
frozen correction benchmark, and the product/architecture record in one repository.

> **Status: pre-release integration checkpoint.** The correction engine implements the
> tenant, blueprint, job, provider, ingestion, mapping, extraction and override substrate.
> The frontend implements the marketing surface, Supabase sign-in, the role-scoped
> dashboards and a live `/health` + `/ready` screen. Marking, verification, results and
> cohort intelligence are not implemented, and most dashboard data has no engine endpoint.
> No production-readiness, marking-accuracy or live-structured-output claim is made.

## Components

| Path | What it is | Status |
|---|---|---|
| [`backend/`](backend/) | FastAPI correction engine, SQLAlchemy/Alembic schema, provider boundary, worker, tests | CP1–CP2 implemented |
| [`frontend/`](frontend/) | TanStack Start/React marketing surface and role-scoped dashboards on Cloudflare Pages | Marketing + role shell; one live engine screen |
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

The frontend is a static TanStack Start build deployed to Cloudflare Pages. It signs in with
Supabase and calls the engine only when `VITE_AETRIX_API_URL` was set at build time; today
`/platform/health` is the one screen wired to a live engine endpoint. It stores no student
data. The correction engine does not import frontend code or the benchmark.

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

On Windows, the two scripts at the repository root wrap that command:

```bat
START_BACKEND.bat   :: starts uvicorn on http://127.0.0.1:8000 if it is not already up
STOP_BACKEND.bat    :: stops only the process the start script began
```

`START_BACKEND.bat` reads `backend\.env`, refuses to run without it, binds the loopback
interface only, and reports `/health` and `/ready`. `/ready` returning 503 means the API is up
but the database in `backend\.env` is not reachable. Both scripts keep a PID file under
`backend\`; stopping verifies the process command line (`uvicorn app.main:app` on port 8000)
before ending it, so unrelated Python services are untouched.

### Local full stack with an HTTPS tunnel

A deployed HTTPS page cannot call `http://127.0.0.1:8000`. `START_AETRIX.bat` starts the
loopback backend, opens a free Cloudflare quick tunnel, waits for `/health`, verifies the
public URL, and prints it:

```bat
START_AETRIX.bat   :: backend + tunnel; prints the public HTTPS origin
STOP_AETRIX.bat    :: stops only the recorded tunnel and backend PIDs
```

The quick-tunnel hostname is new on every start, so after a restart put it in `frontend/.env`
as `VITE_AETRIX_API_URL` (it is compiled into the bundle), rebuild and redeploy.
`AETRIX_CORS_ORIGINS` must list the exact frontend origins
(`https://aetrix.pages.dev,http://localhost:3000,http://127.0.0.1:3000`); a wildcard is
refused in production and is never used for authenticated endpoints. A stable hostname
needs a named tunnel bound to a Cloudflare-managed domain:

```bash
cloudflared tunnel login
cloudflared tunnel create aetrix
cloudflared tunnel route dns aetrix api.example.com
cloudflared tunnel run aetrix   # config points at http://127.0.0.1:8000
```

### Frontend

```bash
cd frontend
npm ci
npm run typecheck
npm run build
npm run dev
```

`npm run test:e2e` requires Playwright browsers and a running preview. The browser bundle
carries no service-role key, JWT secret or provider credential. Cloudflare Pages deployment is
described in `.github/workflows/deploy-frontend.yml`; `wrangler.jsonc` only declares the
frontend Worker.

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
- No authenticated workspace data: the role shell exists, but the engine exposes no
  workspaces, assignments, inbox, reports or gradebook endpoints, and no R2/D1/Queue
  binding is declared.
- The live Gemini structured-output path is `UNVERIFIED` after provider 403 responses.
- The holdout has zero certified papers; no general marking-parity claim is possible.
- The frontend build and browser tests depend on a local Node runtime; see the final report for
  the checks that were actually executable.

## Repository history

This repository was formerly `WebPage_UI_V5.5`. The engine was developed in
[`Engine_V5.5`](https://github.com/AetherRIP/Engine_V5.5), which remains a recoverable source
repository. The final project version is **V5.5**. See the consolidation report for the exact
commits and preserved history.
