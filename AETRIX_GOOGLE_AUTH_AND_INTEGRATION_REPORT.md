# Aetrix V5.5 — Google OAuth and integration report

**Date:** 9 November 2026  
**Workspace:** `C:\Projects\Aetrix\Aetrix_V5.5-main`  
**Production frontend:** <https://aetrix.pages.dev>  
**Engine:** <https://arthur-rip-zn02.tail06bb75.ts.net> (loopback bind `127.0.0.1:8000`)  
**Deployment:** Cloudflare Pages project `aetrix`, production deployment `870aebff`

## Status vocabulary

- **PASS** — exercised against the real implementation and the stated evidence exists.
- **PARTIAL** — implemented and/or partly exercised, but a required external condition is missing.
- **FAIL** — exercised and incorrect.
- **BLOCKED** — cannot be completed without a missing credential, account, legal/infrastructure decision or provider setting.
- **NOT TESTED** — no valid execution evidence exists.

No feature is marked PASS merely because its page returned 200. Marking, live provider calls and a successful Google consent round trip were not fabricated.

## 1. OAuth configuration

| Item | Result | Evidence |
|---|---|---|
| Download location | PASS | `C:\Users\rudro\Downloads\client_secret_147306392871-id2c614ia6ri4r5voi9rt2tjt84tnpss.apps.googleusercontent.com.json` |
| Client type | PASS | JSON contains a `web` client |
| Google Client ID | PASS | `147306392871-id2c614ia6ri4r5voi9rt2tjt84tnpss.apps.googleusercontent.com` |
| Client Secret present | PASS | Present in the original JSON; value was never printed, copied into source, or logged |
| Authorized redirect URI | PASS | Exactly `https://wswsibspyjrhlahxcefs.supabase.co/auth/v1/callback` |
| Authorized JavaScript origin | PASS | `https://aetrix.pages.dev` |
| Google authorize endpoint | PASS | `302` to `accounts.google.com` with the downloaded client ID and redirect URI |
| Google client/secret validity | PASS | Token endpoint returned `400 invalid_grant` for a deliberately fake code, not `invalid_client`; the credentials are recognized |
| Supabase Google provider enabled | PASS | Supabase authorize endpoint returns `302` to Google; `/auth/v1/settings` reports `external.google: true` |
| Supabase callback | PASS | Supabase sends redirect URI `https://wswsibspyjrhlahxcefs.supabase.co/auth/v1/callback` |
| Supabase provider uses downloaded client | **FAIL** | Supabase authorize response contains the old client ID `375945975403-l6eb84ra1k7jfc8pkt0hfkq7ndtd90kn.apps.googleusercontent.com`, not the downloaded `147306…` client |
| OAuth scopes | PASS | Supabase sends the identity scopes `email profile`; no additional Google permissions were added |
| Full interactive Google sign-in | **BLOCKED** | No Google test account/consent was available; the provider mismatch must also be corrected first |

### Exact provider blocker

The downloaded Google client and its secret are valid, but Supabase's Google provider is still configured with a different OAuth client. The local tooling can read the downloaded secret without displaying it, but the available Supabase management integration requires the secret to be supplied as an API argument, which would expose it in the agent/tool transcript. I did not send the secret through that channel.

**Manual action (owner, in Supabase):**

1. Open **Supabase Dashboard → Project `wswsibspyjrhlahxcefs` → Authentication → Providers → Google**.
2. Set **Client ID** to `147306392871-id2c614ia6ri4r5voi9rt2tjt84tnpss.apps.googleusercontent.com`.
3. Set **Client Secret** to the value in the downloaded JSON. Do not paste it into chat, source, `.env` committed to Git, or a public Pages variable.
4. Confirm the authorized redirect URI in Google Cloud is exactly `https://wswsibspyjrhlahxcefs.supabase.co/auth/v1/callback`.
5. Confirm Supabase's site URL is `https://aetrix.pages.dev` and the redirect allowlist includes `https://aetrix.pages.dev/auth/callback`.
6. Complete one real Google sign-in with an invited test account and verify the callback, session, `/api/v1/me`, role and workspace membership.

## 2. Credential handling

- The original downloaded JSON was preserved unchanged and was not added to Git.
- `frontend/.env` and `backend/.env` are ignored by `.gitignore`; only `.env.example` files are tracked.
- `git log --all -S 'GOCSPX'`, the downloaded client ID, and `external_google_secret` found no committed credential history.
- The production build step removed `dist/server/.dev.vars`; `find dist -name .dev.vars` returned nothing.
- The client secret was never printed in this report, the application, browser JavaScript, network responses or logs.
- `VITE_SUPABASE_ANON_KEY` is present in the client as intended; it is a publishable key, not a service-role key.
- The public API base URL is compiled into the client (`arthur-rip-zn02.tail06bb75.ts.net`); the client does not carry a database password or admin credential.

## 3. Google sign-in and Supabase authentication tests

| Check | Status | Evidence |
|---|---|---|
| Sign-in page renders and offers Google | PASS | Production Playwright `auth.spec.ts` |
| Google button starts a real Supabase PKCE authorize request | PASS | Production Playwright; Supabase response `302` to Google |
| Provider callback path is correct | PASS | Supabase response redirect URI is the configured callback |
| Cancelled authorization is reported, not treated as success | PASS | Production Playwright |
| Callback without a code does not claim a session | PASS | Production Playwright |
| Signed-out protected-route rejection | PASS | Production Playwright, `/dashboard`, `/workspace`, `/inbox`, `/queue`, `/assignments`, `/reports`, `/settings` |
| Session persistence and sign-out | PASS | Production Playwright |
| Real Google consent and Supabase-issued session | **BLOCKED** | No interactive Google account was available; provider client mismatch must be fixed |
| Engine validates a real Supabase JWT | **NOT TESTED** | No real Supabase user session was available; tests use the existing signed test-token fixture |
| Forged/invalid JWT rejected at production boundary | PASS | `GET /api/v1/me` without a token → `401`; with `Bearer forged.invalid.jwt` → `401` |
| JWT issuer/audience/signature unit coverage | PASS | Backend suite, 235 tests |
| Cross-tenant isolation | PASS | Backend integration suite, including identity/provisioning and workspace reads |

The frontend uses Supabase PKCE and stores the session under `aetrix:auth`. The engine remains the authorization boundary: the browser role is a routing hint, and the engine's `/api/v1/me` `ui_role` is the fallback when the browser claim is absent.

## 4. Frontend/backend integration

| Check | Status | Evidence |
|---|---|---|
| Production client calls the intended engine | PASS | Built bundle contains `arthur-rip-zn02.tail06bb75.ts.net`; canonical Pages asset `index-6SaE3nDL.js` |
| Engine `/health` | PASS | `200`, `{"status":"ok","service":"aetrix-engine","version":"0.1.0"}` |
| Engine `/ready` | PASS | `200`, `{"status":"ready","database":"ok","detail":null}` |
| CORS preflight | PASS | `OPTIONS /api/v1/me` with `Origin: https://aetrix.pages.dev` → `200`; allow-origin and allow-headers present |
| Protected route without JWT | PASS | `401` |
| Forged bearer token | PASS | `401` |
| API base URL and methods | PASS | Existing typed client and backend tests; no request-body tenant selection |
| Real dashboard data after Google sign-in | **BLOCKED** | Requires a real invited Google user; the UI correctly shows unavailable/error states rather than fabricated values |
| File upload/download and object storage | **PARTIAL/BLOCKED** | Local filesystem adapter exists; production object storage/signed delivery is not implemented |

## 5. Features completed or corrected in this pass

| Feature | Status | Evidence |
|---|---|---|
| Engine role fallback when Supabase `app_metadata.aetrix_role` is absent | PASS | New Playwright test opens the shell from engine `ui_role: supervisor`; `roles.spec.ts` |
| Invitation-required gate for an authenticated but unprovisioned account | PASS | New Playwright test receives `403 PROVISIONING_REQUIRED` and sees the invitation gate, not a blank dashboard |
| `VIEWER` account type | PASS | Frontend role metadata, permissions, navigation, allowlist and engine mapping; typecheck/build |
| Invitation acceptance code redemption | PASS | Existing backend identity flow plus new browser gate |
| Sign-in provisioning copy | PASS | Changed “Work in progress” to “Invitation required”; auth test updated and passing |
| Assistants screen static capability guidance under engine failure | PASS | Removed the early return that hid “What an assistant may do”; full Playwright route test |
| Fleet screen honest data-gap state | PASS | Production Playwright accepts the real “engine could not be reached” state; no figures invented |
| Production deployment | PASS | Pages preview `bf23b6ea` verified, then production `870aebff`; canonical host serves `index-6SaE3nDL.js` |

## 6. Features partially completed / blocked / not tested

| Area | Status | Detail |
|---|---|---|
| Real Google OAuth provider configuration | **BLOCKED** | Supabase still uses old Google client ID `375945…`; manual secret update required |
| Real Google consent → Supabase session → `/me` | **BLOCKED** | No interactive Google account and no invited engine membership |
| Marking end to end | **BLOCKED** | Pipeline code and test fixtures exist, but the live provider is `UNVERIFIED` and no funded provider key is configured; no marks were produced or claimed |
| Live Gemini provider connectivity | **BLOCKED** | No funded key; provider status remains `UNVERIFIED` |
| Human review/approval of a real marked submission | **BLOCKED** | Depends on real marking results |
| Production object storage, malware scanning, email | **NOT IMPLEMENTED** | Local filesystem storage remains; no production object-store adapter or scanner |
| Google Classroom | **PARTIAL** | Course OAuth, encrypted token storage, refresh, revoked-access handling and `POST /api/v1/classroom/sync` are implemented; roster import and grade publishing are not, and the screen states that |
| Workspace/account administration, support grants, hosted PDF reports | **NOT IMPLEMENTED** | No corresponding backend mutations/APIs |
| Real authenticated dashboard/roster/report data | **BLOCKED** | Requires the real Google/Supabase/engine user path above |

The earlier `AETRIX_WEBSITE_WIP_AUDIT.md` remains the feature register (85 units, 79 unfinished at audit time). This pass did not convert the marking provider or the many data-plane shells into live functionality.

## 7. Database changes and migrations

- No schema migration was introduced by this pass.
- Existing migrations were applied to the disposable local PostgreSQL 16.2 instance and the full backend suite passed from that database.
- The engine uses Alembic; no `create_all` or SQLite fallback was added.
- The disposable test database was loopback-only on `127.0.0.1:55432`; the shared Supabase database was never used for destructive tests.
- Tenant-scoped and invitation/provisioning tests passed (235 total backend tests).

## 8. Security findings

1. **Provider mismatch (open):** Supabase is still configured with the old Google client ID. This is a functional/security configuration defect until corrected manually.
2. **No credential exposure found:** no client secret in Git history, tracked files, client bundle, production assets or logs.
3. **Build artifact hygiene:** `dist/server/.dev.vars` was removed before publication; client source maps were absent.
4. **Authorization boundary:** production `/api/v1/me` returns 401 without a valid token and 401 for a forged token; CORS is restricted to the Aetrix origin for the protected route.
5. **Tenant isolation:** backend tests cover cross-tenant reads, invitation-only provisioning, unverified email refusal and role escalation refusal.
6. **Remaining risk:** the client is a static Pages deployment; the engine is exposed only through the existing Tailscale Funnel. No PostgreSQL or admin port was opened.

## 9. Tests executed and exact results

| Check | Command / target | Result |
|---|---|---|
| Backend lint | `backend/.venv/Scripts/python.exe -m ruff check app tests migrations scripts` | **All checks passed (exit 0)** |
| Backend suite | `AETRIX_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/postgres pytest -q` | **235 passed, 1 warning, 0 failed (3m15s)** |
| Frontend typecheck | `tsc --noEmit` | **exit 0** |
| Production build | `vite build` | **exit 0**; 39 routes prerendered |
| Build hygiene | `strip-dev-vars.mjs` + `legal-clean-urls.mjs` | **exit 0**; `.dev.vars` removed; clean legal URLs emitted |
| Local Playwright | `BASE_URL=http://127.0.0.1:3102 playwright test` | **153 passed, 2 skipped** (1.9m) |
| Local auth/roles | 42 tests | **42 passed** |
| Preview Playwright | `BASE_URL=https://codebuff-oauth-integration.aetrix.pages.dev` | **42 passed** |
| Production Playwright | `BASE_URL=https://aetrix.pages.dev` | **42 passed** (52.8s) |
| Google authorize probe | Node fetch, `redirect: manual` | **302 → accounts.google.com** |
| Google token probe | fake code with downloaded secret | **400 `invalid_grant`** (credentials recognized) |
| Supabase authorize probe | real anon key | **302 → accounts.google.com, old client `375945…`** |
| Production health/readiness | curl | **200 / 200** |
| Production CORS | curl OPTIONS | **200** |
| Production no-token/forged JWT | curl | **401 / 401** |

The two Playwright skips are `health.spec.ts`’s DOM-level engine tests, which skip when `VITE_AETRIX_API_URL` is not supplied to the test process. They are reported as skipped, not passes.

## 10. Production deployment

- Pages project: `aetrix`
- Preview branch deployment: `bf23b6ea` — <https://codebuff-oauth-integration.aetrix.pages.dev>
- Production deployment: `870aebff` — <https://870aebff.aetrix.pages.dev>
- Canonical production: <https://aetrix.pages.dev>
- Canonical production asset verified: `/assets/index-6SaE3nDL.js`, matching the deployed bundle.
- Production public auth/role suite: **42/42 passed**.

## 11. Infrastructure status

Direct checks after deployment:

| Component | Status | Evidence |
|---|---|---|
| Backend process | PASS (running) | PID 5920 in managed state; loopback listener PID 15244 on `127.0.0.1:8000` |
| Worker | PASS (running) | PID 7536 in managed state; process present |
| Supervisor/monitor | PASS (running) | PID 8564 in managed state; process present |
| Tailscale Funnel | PASS | Public `/health` and `/ready` return 200 |
| PostgreSQL | PASS | `/ready` reports `database: ok`; disposable test server separately on loopback 55432 |
| Deployed frontend | PASS | Canonical Pages host 200 and new asset |

`STATUS_AETRIX.bat` completed with **STATUS: CONNECTED** (exit 0). It reported backend PID 5920 running, Tailscale Funnel running, worker PID 7536 running, monitor PID 8564 running, local `/health`, local `/ready`, public `/health`, public `/ready`, CORS/protected-route, and deployed-frontend checks all PASS. `STOP_AETRIX.bat` was not run.

## 12. Remaining manual steps

1. Correct the Supabase Google provider client ID/secret as described in §1; complete a real invited Google sign-in.
2. Create/invite the intended test account in the engine and ensure its Supabase `app_metadata.aetrix_role` or engine membership is present.
3. Configure a funded Gemini provider key before claiming live marking; keep the provider status honest until then.
4. Complete the outstanding object-storage, Classroom, email, PDF-report and platform-administration work if those features are required.
5. No stack restart is required: `STATUS_AETRIX.bat` returned `STATUS: CONNECTED`.

## Bottom line

The Aetrix frontend and engine are connected and deployed, with the public/auth/role surface verified in the browser and the backend suite green. The downloaded Google client is valid, but **real Google OAuth is not complete** because Supabase still points at a different Google client and no interactive Google account/invited user was available. Marking remains unverified against a live provider. The remaining provider configuration is a manual secret-transfer step, documented above, and the system does not claim otherwise.
