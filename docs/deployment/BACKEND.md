# Production backend — Aetrix V5.5 on `arm-free-1`

The FastAPI correction engine and its worker run on the existing Oracle A1 VM.
The public frontend (`https://aetrix.pages.dev`) reaches it through a Tailscale
Funnel, so no inbound port is opened and no OCI networking change is needed.

- **Public API origin:** `https://arm-free-1.tail06bb75.ts.net`
- **VM:** `arm-free-1`, `139.185.60.57` / `10.0.0.45`, Ubuntu 24.04.5, aarch64
- **SSH:** `ssh -i "C:\Projects\AETRIX A1\arm-free-1" ubuntu@139.185.60.57`
- **Database:** the existing Supabase project (no new database was created)

## Topology

```text
Browser  https://aetrix.pages.dev   (Cloudflare Pages, project `aetrix`)
   │   authenticated fetch, Bearer <Supabase access token>
   ▼
https://arm-free-1.tail06bb75.ts.net   Tailscale Funnel, Let's Encrypt cert
   │   terminates TLS, forwards to loopback only
   ▼
nginx  127.0.0.1:8080   size limit 60 MB, 300 s proxy timeout, secure headers
   │
   ▼
uvicorn  127.0.0.1:8000   aetrix-api.service  (app.main:app)
   │
   ├── PostgreSQL  → Supabase pooler (aws-0-eu-west-2.pooler.supabase.com)
   ├── JWKS        → Supabase project (JWT verification, tenancy from the claim)
   └── documents   → /opt/aetrix/shared/documents

aetrix-worker.service  (app.worker) — installed, DISABLED by default
```

The API and the worker are separate processes and separate systemd units. The API
never starts a worker: `app/main.py` has no worker import, and marking runs only in
`aetrix-worker`. They share configuration through `/opt/aetrix/shared/.env`, the
same database, and the same document root.

## Directory layout on the VM

```text
/opt/aetrix/
├── releases/<release-id>/     one isolated tree per release (own .venv)
├── current -> releases/<id>   atomic symlink, swapped with `mv -Tf`
├── shared/
│   ├── .env                   root:aetrix 0640, never in Git
│   ├── documents/             persistent student documents (outside releases)
│   ├── logs/                  api.log, worker.log
│   └── persistent-data/
└── deploy/
    ├── aetrix-deploy.sh       install / activate / rollback / status
    ├── active                 release currently serving
    ├── previous               release `rollback` returns to
    └── staged                 last installed release
```

Persistent data is outside every release, so activating or rolling back an
application release cannot touch documents, logs or secrets.

## Services

| Unit | Runs as | Bind | Enabled |
|---|---|---|---|
| `aetrix-api.service` | `aetrix` | `127.0.0.1:8000` | yes |
| `aetrix-worker.service` | `aetrix` | — | **no** (quota/real-submission safety) |
| `nginx` | `www-data` | `127.0.0.1:8080` | yes |
| `tailscaled` (Funnel → 8080) | root | `:443` via Tailscale | yes |

Both units write to `/opt/aetrix/shared/logs/`; `journalctl -u aetrix-api` holds
service lifecycle messages only.

## Environment

Production configuration is generated from the developer `.env` by
`deploy/gen_env.py`, which applies these overrides and drops development-only keys:

| Variable | Production value | Why |
|---|---|---|
| `AETRIX_ENV` | `production` | enables the production validation rules |
| `AETRIX_DEBUG` | `false` | refused in production otherwise |
| `AETRIX_STORAGE__ROOT` | `/opt/aetrix/shared/documents` | absolute; was cwd-relative `data/documents` |
| `AETRIX_CORS_ORIGINS` | `https://aetrix.pages.dev` | the real site origin only |
| `AETRIX_FEATURES__LIVE_PROVIDER` | `false` | no provider calls until approved |

Dropped: `AETRIX_TEST_DATABASE_URL`, `AETRIX_AUTH__DEV_MODE`,
`AETRIX_AUTH__DEV_TENANT_ID`, `AETRIX_AUTH__DEV_USER_ID`,
`AETRIX_PROVIDER__PINNED_CREDENTIAL_ID`.

Production refuses to boot without `AETRIX_AUTH__JWKS_URL` (or a JWT secret),
a non-development `AETRIX_SECURITY__ENCRYPTION_KEY`, and a CORS list without `*`.
`AETRIX_SECURITY__ENCRYPTION_KEY` must be the same key that encrypted the provider
credentials already in the database; rotating it makes those credentials unreadable.

`AETRIX_AUTH__OPEN_ACCESS=true` is currently carried over from development. It is
an admission policy, not a token check: any *verified* Supabase identity is placed
in the single `pilot` workspace as `TEACHER`, and every such admission is audited.
Set it to `false` to require an existing invitation instead.

## Deploy a new backend release (from Windows)

```powershell
cd C:\Projects\Aetrix\Aetrix_V5.5-main
.\deploy\aetrix.ps1 deploy              # committed HEAD only
.\deploy\aetrix.ps1 deploy -AllowDirty  # working tree, labelled <sha>-local
```

The command refuses an unclean tree unless `-AllowDirty` is passed, runs a local
import check, builds the artifact (`git archive`, or a filtered tar for a dirty
tree), uploads it, creates a new release directory, installs dependencies into a
private venv, then activates it and waits for `/health` **and** `/ready`.

Never deployed: `backend/.env`, `backend/.venv`, `backend/tests`,
`backend/data/documents` (student scans stay out of release artifacts).

### What activation does

1. Records the current release in `deploy/previous`.
2. Swaps `/opt/aetrix/current` atomically.
3. `systemctl restart aetrix-api`.
4. Polls `http://127.0.0.1:8000/health` and `/ready` for up to 60 s.
5. On failure: prints the journal, points `current` back at the previous release,
   restarts, re-checks, and exits 2 either way.

The database is **never** downgraded by a rollback.

## Rollback

```powershell
.\deploy\aetrix.ps1 rollback
```

Switches to the release recorded in `deploy/previous`, restarts the API, verifies
health, and records the release it left so the rollback can be undone. Documents,
logs, secrets and database rows are untouched.

## Migrations

Production is at Alembic revision `0039_credential_pools` (head) and no migration
is pending. When one is required:

```powershell
# inspect first, read-only
cd backend; .venv\Scripts\python.exe -m alembic current
```

then run `alembic upgrade head` against the production DSN from
`/opt/aetrix/shared/.env` **before** activating the release that needs it. A
migration that drops or rewrites data needs the owner's approval and a verified
backup first; never downgrade automatically.

## Logs and troubleshooting

```powershell
.\deploy\aetrix.ps1 status
.\deploy\aetrix.ps1 health
.\deploy\aetrix.ps1 logs api 200
.\deploy\aetrix.ps1 releases
```

| Symptom | First check |
|---|---|
| `status=200/CHDIR` in journal | `/opt/aetrix` must stay `0755` so the `aetrix` user can traverse |
| service starts then exits 1 | `/opt/aetrix/shared/logs/api.log` holds the Python traceback |
| `/health` 200 but `/ready` 503 | database reachability from the VM: `curl -sS 127.0.0.1:8000/ready` |
| public HTTPS fails but loopback works | `sudo tailscale funnel status`; re-run `tailscale funnel --bg --https=443 http://127.0.0.1:8080` |
| CORS error in the browser | `AETRIX_CORS_ORIGINS` must contain the exact origin, no trailing slash |

## Worker activation (deliberately gated)

The worker spends provider quota and processes real submissions. Enable it only
after all of these hold:

- `/ready` reports the database healthy and `AETRIX_FEATURES__LIVE_PROVIDER` is
  intentionally set to `true`;
- credential pools in the database decrypt with the current encryption key;
- quota limits in `AETRIX_QUOTA__*` match the plan you are willing to spend;
- a synthetic (not student) submission has been marked end to end and stopped in
  `REVIEW_REQUIRED` as expected.

```bash
sudo systemctl enable --now aetrix-worker
sudo journalctl -u aetrix-worker -f
```

Run exactly one worker process until concurrency, leasing and memory are measured.

## Frontend coordination

`VITE_AETRIX_API_URL` is compiled into the Pages bundle at build time. Set it in
the Pages project (production **and** preview) to
`https://arm-free-1.tail06bb75.ts.net`; changing a dashboard variable does not
change an already-published bundle, so a rebuild is required.

Safe order for a change that touches the contract:

1. Deploy the backend first when it is backwards compatible with the current
   frontend (new optional fields, new routes).
2. Publish the frontend second.
3. Remove the old behaviour only after the frontend build that stopped using it
   is live.

Emergency manual publish (see `docs/deployment/PRODUCTION.md` for detail):

```bash
cd frontend && npm ci && VITE_AETRIX_API_URL=https://arm-free-1.tail06bb75.ts.net npm run build && npm run deploy:manual
```

## Security posture

- Only `:22` (SSH) and the Tailscale Funnel `:443` are reachable from the internet;
  uvicorn and nginx listen on loopback.
- `/docs` and `/redoc` are disabled by the production build and blocked at nginx.
- CORS allows exactly one origin with credentials; `*` is refused at boot.
- `.env` is `root:aetrix 0640` outside every release; it is not in Git.
- The service account is unprivileged, has no shell, and the units set
  `NoNewPrivileges`, `ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp`,
  `MemoryMax` and `LimitNOFILE`.
- Provider keys, the service-role key and the database password never reach the
  browser bundle.
