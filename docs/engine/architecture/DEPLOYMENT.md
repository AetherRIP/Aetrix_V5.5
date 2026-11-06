# Deployment Guide — Aetrix V5.5 (Checkpoints 1-2)

This guide covers the CP1-CP2 engine: API, worker, PostgreSQL schema, ingestion,
provider extraction/mapping and tests. Marking is not implemented; a created job
parks with `PIPELINE_UNAVAILABLE`.

---

## 1. Prerequisites

- Python 3.12-3.13 (tested on 3.13.7).
- A PostgreSQL 15+ database. The development target is Supabase PostgreSQL
  17.11 in `eu-west-2`.
- Network access to the Supabase pooler (the direct host is IPv6-only on some
  networks).
- No Docker is required. Docker is not installed on the development machine.

The repository's portable interpreter `.tools/python/python.exe` lacks the
`venv` module. The engine environment was created with `virtualenv`:

```bash
.tools/python/python.exe -m pip install virtualenv
.tools/python/python.exe -m virtualenv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"
```

---

## 2. Database setup

1. Create a Supabase project (the development project is `aetrix-v55-dev`,
   region `eu-west-2`).
2. Use the **session pooler** for migrations and long-lived worker sessions:

   ```
   postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require
   ```

   Transaction mode (`:6543`) also connects, but session mode is used because
   DDL and prepared statements are simpler there.
3. Store the URL only in `backend/.env` (git-ignored) or a secret store. Never
   commit it.
4. If the direct host `db.<ref>.supabase.co` does not resolve (Supabase direct
   connections are IPv6-only for this project) and the network has no usable
   IPv6, use the pooler. This was the case in development.

---

## 3. Configuration

Copy `backend/.env.example` to `backend/.env` and fill in values. The important
groups:

| Variable | Purpose | Production rule |
|---|---|---|
| `AETRIX_ENV` | `development`, `test`, `production` | Set `production` |
| `AETRIX_DEBUG` | Verbose behavior | Must be `false` |
| `AETRIX_DATABASE__URL` | PostgreSQL DSN | Must be `postgresql...`; SQLite refused |
| `AETRIX_AUTH__JWKS_URL` | Supabase JWKS endpoint | Preferred verification |
| `AETRIX_AUTH__JWT_SECRET` | Legacy HS256 secret | Only if JWKS is unavailable |
| `AETRIX_AUTH__JWT_AUDIENCE` | Expected audience | Default `authenticated` |
| `AETRIX_AUTH__DEV_MODE` | Development principal | Must be `false` |
| `AETRIX_SECURITY__ENCRYPTION_KEY` | Fernet key for provider credentials | Required; dev key refused |
| `AETRIX_CORS_ORIGINS` | Comma-separated frontend origins | Wildcard refused |
| `AETRIX_FEATURES__LIVE_PROVIDER` | Provider gate | `false` until credentials are provisioned |
| `AETRIX_STORAGE__ROOT` | Local document/page storage root | Durable, access-controlled volume |
| `AETRIX_INGESTION__*` | Render DPI, page/pixel limits, quality thresholds | Tune per deployment |
| `AETRIX_QUOTA__*` | Per-key minute/day limits, cooldown, reservation TTL | Keep provider-safe |
| `AETRIX_PROVIDER__MODEL_PRIMARY` | Model for extraction/mapping | Approved model only |
| `AETRIX_PROVIDER__MODEL_RATES` | List-price table for cost accounting | Review before production |
| `AETRIX_WORKER__*` | Concurrency, poll, lease, heartbeat, attempts | Heartbeat < lease |
| `AETRIX_TEST_DATABASE_URL` | Integration tests only | Never used by the app |

Generate a production Fernet key:

```bash
backend/.venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store it in the deployment secret store; do not put it in `.env.example` or chat.

---

## 4. Migrate

From `backend/`:

```bash
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic current
```

The migrations are transactional. The head is `0005_rls_lockdown`; the chain adds
the CP2 document/mapping/override/quota tables, repairs the approved-blueprint
immutability trigger, adds the Phase 2 `tenants.is_demo` and
`audit_events.actor_label` columns, and locks the `public` schema down for the
Supabase Data API. `alembic check` should report no new operations.

To inspect history:

```bash
.venv/Scripts/python.exe -m alembic history --verbose
```

Rollback is possible with `alembic downgrade -1`, but review it first: dropping
tenant tables destroys production data. Take a backup before any downgrade.

---

## 5. Seed a development identity

```bash
.venv/Scripts/python.exe -m app.cli seed-dev
```

This creates the tenant and user referenced by
`AETRIX_AUTH__DEV_TENANT_ID` and `AETRIX_AUTH__DEV_USER_ID`. It does not create
papers or marks and is refused in production.

For a real tenant/user:

```bash
.venv/Scripts/python.exe -m app.cli create-tenant --name "School" --slug "school"
.venv/Scripts/python.exe -m app.cli create-user --tenant <uuid> --subject <supabase-sub> --role TEACHER
```

The `subject` must match the Supabase JWT `sub` claim for that user.

---

## 6. Run

### API

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

or, after installation:

```bash
backend/.venv/Scripts/aetrix-api
```

Check:

```bash
curl -s localhost:8000/health
curl -s localhost:8000/ready
curl -s localhost:8000/version
```

`/ready` returns 503 if the database is unreachable. Route on `/ready`, not
`/health`.

### Worker

```bash
cd backend
.venv/Scripts/python.exe -m app.worker
```

or `backend/.venv/Scripts/aetrix-worker`.

The worker runs `AETRIX_WORKER__CONCURRENCY` threads, each with a unique worker
id. It claims with `FOR UPDATE SKIP LOCKED`; a SIGINT/SIGTERM stops new claims
and waits for the current job to reach a safe boundary.

A created job will be claimed and parked:

```
state=RETRY_SUSPENDED
error_code=PIPELINE_UNAVAILABLE
```

This is expected until a real pipeline exists. No marks are written.

### Document and scheme endpoints

The ingestion, mapping, scheme, extraction and override routes are synchronous
in this checkpoint. Upload a PDF/image as multipart form data; PDFs are rendered
page-by-page and the response includes every page with its typed quality and
ordering reasons. A rejected upload returns `DOCUMENT_REJECTED` and persists a
`REJECTED` document with its reasons.

Provider-backed extraction and image mapping require:

1. `AETRIX_FEATURES__LIVE_PROVIDER=true`;
2. at least one encrypted provider credential in the tenant (or a global one);
3. a processed mark-scheme document and, for mapping, an approved blueprint.

Without these, the endpoint returns a typed provider-unavailable error; it does
not fabricate output.

---

## 7. Scaling and restarts

- Scale the API independently of the worker.
- Run one or more worker processes; the database lease prevents two workers from
  claiming the same job concurrently.
- Keep `heartbeat_seconds` comfortably below `lease_seconds` (validated at boot).
- A worker crash is recovered after lease expiry; the job's attempt counter
  increments. Exhausted attempts become `FAILED`.
- Do not run migrations while old workers are mid-job unless the migration is
  backward compatible.

---

## 8. Production hardening

- `AETRIX_ENV=production`, `AETRIX_DEBUG=false`.
- Disable dev auth; configure JWKS.
- Set a real encryption key; remove the development key.
- Restrict CORS to the frontend origin.
- Run the API behind TLS; terminate at the edge and forward only trusted headers.
- Store the database URL and provider keys in a secret store, not a file on a
  shared disk.
- Restrict database network access to the API/worker.
- Ship logs to a restricted store; no request bodies or prompts.
- Configure `/ready` probes and restart policies.
- Back up the database and rehearse a restore.
- Keep the benchmark in CI; do not edit its frozen digests.

---

## 9. Oracle portability

The application avoids SQLite and uses SQLAlchemy 2.0 types. Portable pieces:

- `Uuid`, `String`, `Integer`, `Float`, `Numeric`, `JSON`, `DateTime(timezone=True)`.
- The lease query uses `FOR UPDATE SKIP LOCKED`, supported by Oracle 11g+.

What still needs an Oracle pass:

- `JSON` maps to a LOB/CLOB on Oracle; queries and indexes need review.
- `server_default=now()` becomes `CURRENT_TIMESTAMP`; the Alembic migration is
  PostgreSQL-specific and would need an Oracle branch.
- UUID generation is client-side; that is portable.
- Case-sensitive string checks and `ILIKE` (not used) would need review.
- A connection pool and driver (`oracledb`) are not configured.

Do not claim Oracle support from this checkpoint; only the application structure
is portable.

---

## 10. CI commands

```bash
# Engine
cd backend
.venv/Scripts/python.exe -m ruff check app tests migrations scripts
.venv/Scripts/python.exe -m pytest -q

# Frozen benchmark (run from the repository root, using the harness interpreter)
.tools/python/python.exe -m pytest benchmark/tests benchmark/holdout/tests -q
.tools/python/python.exe -m benchmark.holdout.manifest --check-code
```

Integration tests need `AETRIX_TEST_DATABASE_URL` (or the development
`backend/.env`). They truncate the public tables between tests. **Never point
them at a production database.**

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `getaddrinfo failed` for `db.<ref>.supabase.co` | Direct host is IPv6-only; network has no IPv6 | Use the session pooler |
| `tenant/user postgres.<ref> not found` | Wrong pooler region/host | Use the host that matches the project (`aws-0-eu-west-2` here) |
| `invalid connection option "postgresql+psycopg://..."` | Passed a SQLAlchemy URL to psycopg directly | Strip `+psycopg` for raw psycopg; keep it for SQLAlchemy |
| Alembic `KeyError` for a revision | A migration references a deleted revision | Restore/re-pin the revision; do not edit `alembic_version` manually |
| `relation ... does not exist` during migration | Circular FK ordering | Break the cycle or use `use_alter`; the scheme→document FK was removed for this reason |
| API returns 503 on `/ready` | Database unreachable or pooler paused | Check Supabase status and the DSN |
| Worker repeatedly parks jobs | No pipeline in Phase 1 | Expected; wait for Phase 5 or inject a test pipeline |
| `RuntimeError: no validator found` / config error | Missing env var or invalid production setting | Read the validation message; fix `.env` or the secret store |
| Tests truncate unexpectedly | `clean_tables` runs against the configured test URL | Point `AETRIX_TEST_DATABASE_URL` at a disposable database |

---

## 12. Known deployment limitations

- No Docker image or container orchestration is defined.
- No reverse proxy/TLS configuration is included.
- No metrics/tracing/alerting is configured.
- The worker is intentionally idle-parking because marking is not implemented.
- Supabase Storage integration is not implemented; storage is the local
  filesystem adapter behind the `Storage` protocol.
- The frontend is not built; CORS is configured but unused.
- Ingestion and provider calls are synchronous; a large scan or a slow model call
  occupies an API request. Move them to the job runner before production.

---

## 13. Bounded live-provider probe

The acceptance probe is intentionally not part of the test suite and is not run
in CI:

```bash
cd backend
.venv/Scripts/python.exe scripts/smoke_gemini.py
```

It reads the authorized V5 key file read-only, tries at most three keys and one
request per key, and prints no key material. The canonical extraction probe is:

```bash
cd backend
.venv/Scripts/python.exe scripts/live_extraction.py --key-index 4
```

It makes one request, uploads and approves a generated scheme, and creates a
`DRAFT` only if the provider returns a valid blueprint. A successful call is
evidence of transport/authentication/accounting and extraction, not a marking or
accuracy claim. As of CP2 the post-change probe was rejected at authentication
(503/503/403 and 403), so live extraction is **UNVERIFIED**. See
`docs/audits/CP2_ACCEPTANCE.md` for the observed output.
