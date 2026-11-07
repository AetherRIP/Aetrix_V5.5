---
name: aetrix-backend
description: Engineering conventions for the Aetrix FastAPI correction engine. Use when adding or changing Python code in backend/ — API routes, SQLAlchemy models or repositories, Alembic migrations, job state machine or worker, document ingestion and mapping, LLM provider adapters, prompt assets, settings, or backend tests. Also use for pytest and ruff commands in this repository.
license: Proprietary (Aetrix project skill)
metadata:
  author: Aetrix
  version: '1.0.0'
---

# Aetrix backend conventions

Python 3.12–3.13, FastAPI, SQLAlchemy 2.0, Alembic, psycopg 3, pydantic 2 /
pydantic-settings, PyJWT, PyMuPDF, pytest, ruff. PostgreSQL only — SQLite is refused by
design and there is no SQLite code path to add.

## Layout

| Module | Owns |
|---|---|
| `app/api/` (`deps.py`, `v1/`) | HTTP routes, identity dependency, typed errors |
| `app/core/` | `config.py` settings, `errors.py` (`AppError`, `ErrorCode`), `security.py` JWT, `ids.py`, `logging.py`, `email.py` |
| `app/db/` | `models.py`, tenant-scoped `repositories.py`, `session.py` |
| `app/documents/` | Upload validation, rendering, quality, ordering, mapping, extraction |
| `app/services/` | Blueprint/scheme/override orchestration, provider calls, quota |
| `app/jobs/` | `states.py`, `service.py`, `runner.py`, `pipeline.py` (pipeline unavailable) |
| `app/providers/` | `base.py` protocol, `gemini.py` REST adapter, `factory.py`, `errors.py` |
| `app/prompts/` | Versioned prompt registry and assets |
| `app/storage/` | Storage abstraction (Supabase Storage not implemented) |
| `migrations/versions/` | Alembic revisions, constraints, triggers, grants |

## Hard rules

1. **Tenant comes from verified identity, never from a request body or query parameter.**
   Resolve it in `deps.py`; scope every repository call with it.
2. **A schema change means a migration.** Edit `models.py` *and* add an Alembic revision
   that a fresh `alembic upgrade head` reproduces. No `create_all` at runtime, no hidden DDL.
3. **Append-only tables stay append-only.** `audit_events`, `job_events`,
   `provider_usage` accept inserts only; enforce at the database layer, not just in Python.
4. **Provider output is untrusted.** Parse and schema-validate before persisting anything;
   malformed output must create no blueprint.
5. **Vendor types stop at the provider boundary.** Return domain objects from
   `LLMProvider` implementations; never leak Gemini response shapes into services or routes.
6. **Errors are typed.** Raise `AppError(ErrorCode.X, "safe message")` — no bare
   `HTTPException`, no stack traces or upstream payloads in client-visible text.
7. **Never invent progress.** The worker parks jobs honestly; do not synthesize marks,
   counts, or success states when the pipeline is unavailable.

## Style

- `from __future__ import annotations` at the top of every module.
- Line length 100; ruff `select = ["E","F","I","UP","B","SIM","RUF"]`, `ignore = ["B008"]`
  (FastAPI `Depends` in defaults is expected). Run `python -m ruff check app tests`.
- Full type hints on public functions; `uuid.UUID` typed ids; no untyped dict payloads
  crossing module boundaries.
- Settings are nested pydantic-settings with the `AETRIX_` prefix and `__` nesting, e.g.
  `AETRIX_DATABASE__URL`, `AETRIX_AUTH__JWT_AUDIENCE`.
- Log through `app.core.logging`, which carries `tenant_id_var`; never log tokens, keys or
  document contents.

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q                 # unit + integration (unit only without a DB)
.venv/Scripts/python.exe -m pytest tests/unit -q      # fast, no database
.venv/Scripts/python.exe -m ruff check app tests
.venv/Scripts/python.exe -m pytest tests/integration -q -m integration   # needs AETRIX_TEST_DATABASE_URL
```

- `tests/conftest.py` sets the environment before importing the app; integration tests are
  marked `integration` and require `AETRIX_TEST_DATABASE_URL`.
- `filterwarnings = ["error::DeprecationWarning:app.*"]` — a deprecation warning in app code
  fails the suite. Fix the cause; do not add a filter.
- Mirror the existing test style: `tests/unit/test_<area>.py`, `tests/support.py` helpers,
  one behaviour per test with explicit assertions.
- A bug fix ships with the failing test that proves it, plus the fix.

## Do not

- Do not add SQLite support, an ORM shortcut, or a second migration path.
- Do not weaken a test, skip it, or mark it xfail to make the suite pass.
- Do not put engine logic in route handlers; orchestration belongs in `app/services/`.
- Do not claim the pipeline, marking or the live provider works. It does not.
