# Aetrix V5.5 — System-wide acceptance test

**Date:** 2026-11-08
**Deployed frontend:** <https://aetrix.pages.dev> (Pages commit `70f3410`)
**Backend:** laptop FastAPI process on `127.0.0.1:8000`, published through a Cloudflare quick tunnel
**Database:** Supabase PostgreSQL 17.11 (`aws-0-eu-west-2.pooler.supabase.com`)
**Verdict:** **NOT READY AS A COMPLETE APPLICATION.** It is a working pre-release integration
checkpoint: the public site, role-aware shell, live health screen, auth verification, database and
provider-fleet API are real. The core marking workflow does not exist, and no authenticated engine
request could be executed with a real user token.

This report records what was actually run. Nothing below is inferred from the presence of a file.

---

## 1. Infrastructure

| Check | Result | Evidence |
|---|---|---|
| Cloudflare Pages frontend | PASS | `GET https://aetrix.pages.dev/` → 200 `text/html`; deployed bundle fetched |
| Deployed bundle API origin | PASS | tunnel origin present; `127.0.0.1:8000` / `localhost:8000` matches = 0 |
| Secret markers in deployed bundle | PASS | `service_role`, `SUPABASE_SERVICE`, `JWT_SECRET`, `ENCRYPTION_KEY` matches = 0 |
| Public tunnel | PASS | `/health` and `/ready` → 200; protected route → 401 |
| Local FastAPI | PASS | `/health`, `/ready`, `/version`, `/docs`, `/api/v1/openapi.json` → 200 |
| Liveness | PASS | `{"status":"development","service":"aetrix-engine","version":"0.1.0"}` |
| Readiness | PASS | `{"status":"ready","database":"ok","detail":null}` |
| PostgreSQL | PASS | SQLAlchemy query through the production URL; 31 tables |
| Alembic | PASS | head `0009_verification_grants`; `alembic check` → “No new upgrade operations detected” |
| Supabase Auth settings | PASS | `/auth/v1/settings` 200; Google enabled, email enabled, signup not disabled |
| Supabase JWKS | PASS | 200, one key |
| Google authorize endpoint | PASS | 302 to `accounts.google.com` with the configured callback |
| CORS allowed origin | PASS | preflight from `https://aetrix.pages.dev` → 200, matching ACAO |
| CORS local origin | PASS | preflight from `http://127.0.0.1:3000` → 200, matching ACAO |
| CORS foreign origin | PASS | preflight from `https://evil.example` → 400, no ACAO |
| Rate limiting | NOT IMPLEMENTED | no `RateLimit` / `Retry-After` headers; no middleware |
| Stable tunnel hostname | BLOCKED | quick tunnel is ephemeral; a named tunnel needs a Cloudflare-managed domain |

**Configuration observed:** `AETRIX_ENV=development`, `debug=false`, `auth.dev_mode=false`,
JWKS configured, no HS256 secret, `LIVE_PROVIDER=false`, storage backend `local`.

Because the environment is `development`, **`/docs` and `/api/v1/openapi.json` are publicly
reachable through the tunnel**. They contain no secrets, but they expose the full API schema and
should be disabled before any untrusted exposure.

---

## 2. Frontend

### Routes

**30 route URLs discovered and 30 loaded in Chromium:**

| Area | Routes |
|---|---|
| Public | `/`, `/sign-in`, `/auth/callback` |
| Workspace shell | `/dashboard`, `/workspace`, `/inbox`, `/queue`, `/assignments`, `/assignments/example`, `/submissions/example`, `/reports`, `/settings`, `/students`, `/gradebook`, `/analytics`, `/assistants`, `/classroom` |
| Platform | `/platform`, `/platform/workspaces`, `/platform/users`, `/platform/health`, `/platform/audit`, `/platform/gemini`, `/platform/integrations`, `/platform/settings` |
| Assistant | `/assistant`, `/assistant/classes`, `/assistant/work`, `/assistant/tasks`, `/assistant/progress` |

All returned HTTP 200 and rendered their own heading. A whole-route console/network audit found:

- **0 page errors**
- **0 failed requests**
- **0 unexpected HTTP ≥ 400**
- **1 expected console entry:** `/platform/gemini` logs the 401 returned when the seeded test
  token is deliberately invalid. The screen handles it and states “The engine rejected the
  request (401)”; this is the honest failure state, not a broken page.

### Interaction and state coverage

- Navigation, role redirects, forbidden-route panels, collapsed rail, mobile tab bar, theme
  persistence, reduced motion, search/filter tabs, empty/unavailable states and error states.
- Session persistence and sign-out were added as a regression test: a stored session survives a
  fresh page, sign-out removes it, and a subsequent protected route stays at `/sign-in`.
- Responsive: every public/protected route was loaded at 375, 390, 412, 768, 1024, 1440 and
  1920 px; role homes were specifically checked at 360/390 px with zero horizontal overflow.
- Accessibility: axe passes on the landing page (light/dark) and sign-in page; the authenticated
  shells have keyboard/overflow tests but **no axe pass**.

### What the screens actually do

Only two areas call the engine:

| Screen | Calls | State |
|---|---|---|
| `/platform/health` | `GET /health`, `GET /ready` | Full success, loading and unreachable states; real latency and DB readiness displayed |
| `/platform/gemini` | the 18 provider-fleet endpoints | Real search, tabs, key add/import/validate/enable/disable/remove, contributor actions and usage tables; receives 401 with the seeded token |
| Every workspace/assistant screen | **none** | Honest “engine does not expose this data yet” / unavailable states; no student data, no invented figures |

`frontend/src/lib/services.ts` additionally declares workspace, assignment, submission, queue,
inbox and report services against paths such as `/api/v1/workspaces`. **Those backend routes do
not exist.** No screen imports those services, so there is no runtime failure, but the module is a
misleading contract and should be either wired to real routes or removed.

---

## 3. Backend API

**47 registered operations** were read from the live OpenAPI document (71 schemas).

| Category | Count | Result |
|---|---|---|
| Public (`/health`, `/ready`, `/version`) | 3 | 200 |
| Protected (`/api/v1/**`) | 44 | **401 `UNAUTHORIZED`** for every one |
| Total | 47 | all attempted |

The 44 protected operations were swept with substituted UUID path parameters, missing bodies and
no token. Every one rejected the request with the same typed error. No endpoint returned 500 or
leaked data.

Additional checks:

- Forged HS256 JWT signed with a wrong key → **401**
- `alg: none` JWT → **401**
- Malformed `Authorization: Basic` → **401**
- Unknown route → **404**
- Disallowed method (`DELETE /api/v1/exams`) → **405**
- `X-Request-ID` echoed when valid; overlong value truncated to 80 characters
- CORS and tunnel responses preserve the 401 boundary
- No rate-limit headers

**Authenticated contract testing is BLOCKED.** The engine verifies Supabase JWKS. There is no
interactive Google session, no Supabase-issued JWT for a seeded user, and no admin/service
credential available for test user creation. Consequently the happy path, validation errors,
permission 403s, writes, database effects, idempotency and cross-tenant 404s on the 44 protected
routes were **not executed**. This is the largest assurance gap after the missing marking feature.

Database contains 5 users across 4 tenants (including one `PLATFORM_OWNER`), but none could be
authenticated from this test environment. No user data was modified.

---

## 4. Database and non-destructive security

| Check | Result |
|---|---|
| Public tables | 31 |
| RLS enabled | 31 / 31 |
| RLS policies | 0 (engine uses its own DB role; Data API is deny-all) |
| `anon` / `authenticated` table grants | **0** after fix |
| Default ACL grants for Data API roles | 0 |
| Append-only triggers (`audit_events`, `job_events`, `provider_usage`) | 3 |
| `users.role` check | includes `OWNER`, `ADMIN`, `TEACHER`, `REVIEWER`, `VIEWER`, `PLATFORM_OWNER` |
| Data rows | 4 tenants, 5 users, 0 exams, 0 assignments, 0 submissions, 0 jobs, 0 documents, 0 provider credentials, 0 provider usage, 0 verification results, 47 audit events |
| Anon Data API reads | 401 `42501` for `users`, `provider_credentials`, `exams` |

**Fix applied:** `verification_results` was the only table still granting `SELECT` to
`authenticated`. RLS with no policies meant it was not readable, but it violated the lockdown
posture. Migration `0009_verification_grants` revokes it; it was applied to the live database and
`alembic check` is clean. Grants are now zero.

The database contains residual demo/E2E tenants and users. They are real rows, not fixtures
created by this test; no cleanup was attempted because deleting user data was not authorised.

---

## 5. Performance and reliability

Measured against the live processes:

| Path | n | Success | p50 | p95 | max |
|---|---:|---:|---:|---:|---:|
| Local `/health`, sequential | 30 | 30 | 1.5 ms | 2.4 ms | 7.8 ms |
| Local `/health`, 10-way concurrent | 30 | 30 | 9.8 ms | 15.1 ms | 28.9 ms |
| Local `/ready` (DB query), sequential | 10 | 10 | 216.6 ms | 482.0 ms | 574.2 ms |
| Tunnel `/health`, sequential | 10 | 10 | 139.1 ms | 241.6 ms | 448.9 ms |
| Tunnel `/health`, 10-way concurrent | 10 | 10 | 314.6 ms | 455.2 ms | 659.5 ms |
| Tunnel `/ready`, sequential | 5 | 5 | 387.0 ms | 572.6 ms | 746.4 ms |

- The tunnel adds roughly 140 ms to a trivial request; `/ready` is dominated by the Supabase
  pooler round trip (p95 482 ms), not by application work.
- The worker starts with `pipeline: unavailable` and the warning that live provider calls are
  disabled. It claims nothing and parks jobs rather than producing a simulated mark.
- No load test at target scale, no tunnel-interruption recovery, no backend-restart recovery and
  no backup/restore drill were performed.

---

## 6. Feature classification

Statuses: **FULLY** = implemented and demonstrated; **PARTIAL** = some real behaviour, not the
complete feature; **NOT** = absent; **BLOCKED** = cannot be executed without an external
dependency.

| Planned feature | Status | Actual evidence / gap |
|---|---|---|
| Marketing site | FULLY | All sections, links, theme, responsive layouts, axe |
| Sign-in page and Google authorize start | PARTIAL | Real Supabase PKCE request and callback failure states; consent not completed |
| JWT signature/issuer verification | FULLY | Forged, `alg:none`, malformed and missing tokens all 401 |
| Google account end-to-end login | BLOCKED | Requires interactive Google consent |
| Role-aware shell, navigation and guards | FULLY | 4 roles + no-role; 152 frontend tests |
| Session persistence and sign-out | FULLY | New regression test passes |
| Live engine health screen | FULLY | Real `/health` + `/ready`, latency and DB state |
| Health/readiness/version endpoints | FULLY | 200 with expected bodies |
| Tenant/user/role schema | PARTIAL | 4 tenants, 5 users; no memberships, invites or switching |
| Tenant isolation | PARTIAL | RLS/grants and repository design verified; live cross-tenant request blocked |
| Exam and blueprint API | PARTIAL | Routes and invariants exist; no authenticated execution, no UI |
| Mark-scheme upload/approval | PARTIAL | Routes exist; no authenticated execution, no UI |
| Assignments and submissions | PARTIAL | Routes exist; no UI or workflow |
| Document ingestion/rendering/mapping | PARTIAL | Backend code and tests; local disk storage; no live authenticated run |
| Correction job lifecycle | PARTIAL | State machine and worker exist; worker parks every job |
| Marking engine | NOT | `CorrectionPipeline` unavailable |
| SymPy verification | NOT | No pipeline |
| Results, reports, gradebook, analytics | NOT | UI shells only; **no result endpoint exists** |
| Selective review and mark overrides | PARTIAL | Blueprint overrides exist; mark review/selective review does not |
| Cohort intelligence | NOT | Disabled table/flag only |
| Provider fleet admin | PARTIAL | 18 endpoints and a full UI; 0 keys; no authenticated execution |
| Contributor key programme | PARTIAL | Backend + UI; no authenticated execution |
| Live Gemini provider | BLOCKED | `LIVE_PROVIDER=false`; no key; all prior live calls UNVERIFIED |
| Google Classroom | NOT | UI explanation only |
| Supabase Storage | NOT | Local filesystem adapter only |
| Malware scanning | NOT | Absent |
| Rate limiting | NOT | Absent |
| RLS / Data API lockdown | PARTIAL | RLS on all tables, deny-all, grants revoked; no tenant policies (intentional) |
| Authenticated data frontend | NOT | No screen reads engine data |
| Platform workspaces/users/audit UI | PARTIAL | UI only; no corresponding engine endpoints |
| MFA, session list, invites, workspace switching | NOT | Absent |
| CSV import, classes, students | NOT | Absent |
| Comments and notifications | NOT | Absent |
| Plans/billing | NOT | Absent |
| D1/R2/Queues | NOT | Historical blueprint only (ADR-001) |
| Deployment pipeline | FULLY | Pages build/deploy; current production commit `70f3410` |
| Worker process | PARTIAL | Starts and idles correctly; no pipeline |
| Audit log | PARTIAL | Append-only 47 rows; no read API/UI |
| Observability | PARTIAL | JSON logs/request IDs; no external monitoring |
| Backup/restore | NOT | Documentation only |
| Accessibility | PARTIAL | axe on public pages; no axe on authenticated shell |
| Responsive layout | FULLY | 7 viewports, no overflow on tested routes |
| Error/empty/loading states | FULLY | Verified on health, Gemini, role and unavailable screens |
| Frozen benchmark | PARTIAL | `benchmark/tests`: 28 passed in 8.83 s; the full 207-test frozen suite was not rerun |

---

## 7. Automated tests and build

| Check | Result |
|---|---|
| TypeScript `tsc --noEmit` | PASS |
| Vite production build | PASS; 35 pages prerendered, client bundle 498 KB (145 KB gzip) |
| Full Playwright suite | **150 passed, 2 skipped** (health tests need the tunnel env) |
| Live health tests with tunnel | **2 passed** |
| Production Playwright (`health` + `auth`) | **19 passed** |
| Role/session suite | PASS, including new sign-out regression |
| Backend Ruff (`app`, `tests`, `migrations`) | “All checks passed!” |
| Alembic `check` | No drift |
| Worker boot | Starts; warns live provider disabled; pipeline unavailable |
| `benchmark/tests` | 28 passed |
| Backend pytest | **NOT RUN** — `backend/tests/conftest.py` truncates the configured database, and no disposable PostgreSQL/Docker is available |

The 2 skips in the full run are not failures: they are guarded live-engine tests that skip unless
`VITE_AETRIX_API_URL` is set. They passed when run with the tunnel URL.

---

## 8. Fixes applied during this acceptance

1. **`0009_verification_grants`** — revokes the leftover `SELECT` grant on
   `verification_results` from `anon`/`authenticated`; applied to the live database; grants now 0.
2. **`selective_review` flag** — changed from `True` to `False`; the feature is not implemented,
   and the flag must not imply that it is.
3. **Session/sign-out regression test** — proves the stored session is restored on a fresh page,
   removed on sign-out, and not resurrected for a later protected route.
4. **Architecture documents corrected** — both `docs/architecture/AETRIX_V5.5_SYSTEM.md` and
   `docs/engine/architecture/SYSTEM_OVERVIEW.md` now state that a marketing site, role-aware
   shell and live health screen exist, while the authenticated data frontend and marking do not.
5. Earlier in the same acceptance: exact CORS origins, live health screen, honest
   unavailable copy, README/env examples and the Pages workflow variable.

---

## 9. Remaining issues

| Severity | Issue | Root cause | Recommended fix |
|---|---|---|---|
| **Critical** | No marking, SymPy verification, results, reports or cohort output | Pipeline intentionally unavailable; worker parks every job | Implement the correction pipeline before calling the product functional |
| **High** | 44 protected endpoints never exercised with a valid JWT | No interactive Google session or admin-issued test token | Provision a dedicated test Supabase user/JWT and run the authenticated contract suite |
| **High** | No authenticated data frontend | Workspace screens are shells; only health and Gemini call the engine | Wire exams, blueprints, uploads, jobs and results to real endpoints |
| **High** | No workspace lifecycle | No membership, invite, role-assignment or switching endpoints/UI | Add memberships, invitations and role management with policy tests |
| **High** | Storage is local filesystem only | Supabase Storage adapter not implemented | Implement the storage adapter before any hosted upload |
| **Medium** | `/docs` and OpenAPI are public through the tunnel | `AETRIX_ENV=development` enables them | Use production config or disable docs for the tunnel |
| **Medium** | No rate limiting; `/ready` is public and queries the DB | Middleware absent | Add rate limiting at the edge/API |
| **Medium** | Quick tunnel URL is ephemeral | No Cloudflare-managed domain/named tunnel | Use a named tunnel on a controlled hostname for demos |
| **Medium** | Backend test suite cannot run against the configured DB | `conftest.py` truncates; no disposable PostgreSQL | Add a disposable test database/CI service |
| **Medium** | `frontend/src/lib/services.ts` names non-existent routes | Contract written ahead of the engine | Implement those routes or remove the unused services |
| **Medium** | No malware scanning or upload decompression limits | Not implemented | Add scanning and resource limits before accepting untrusted files |
| **Medium** | No backup/restore or external monitoring | Operational work not started | Add scheduled backups and monitoring/alerting |
| **Low** | `/platform/gemini` logs an expected 401 in tests | Seeded test token is intentionally invalid | None; real session removes it |
| **Low** | Residual demo/E2E tenants and users | Prior test data was not cleaned | Decide retention and clean with authorisation |
| **Low** | No axe pass on authenticated shells | Only public pages covered | Add axe checks to the app shell |

---

## 10. Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Deployed frontend communicates with the laptop backend | **PASS** — production health screen fetches tunnel `/health` + `/ready` |
| 2 | Backend communicates with required database/services | **PASS for PostgreSQL and Supabase Auth; PARTIAL overall** — Gemini is disabled |
| 3 | Every accessible frontend route tested | **PASS** — 30 routes |
| 4 | Every registered endpoint tested or documented blocked | **PASS as process** — 3 public tested, 44 rejected/tested unauthenticated, authenticated paths documented blocked |
| 5 | Every planned feature compared with its specification | **PASS** — table above |
| 6 | All critical user workflows pass | **FAIL** — authentication completion, upload, marking, review and results are unavailable |
| 7 | Authentication and authorisation work correctly | **PARTIAL** — JWT verification and role guards pass; real login and authenticated 403/404 paths were not executed |
| 8 | No critical security failures remain | **PASS for the tested surface** — no secret exposure, CORS locked down, Data API deny-all; medium risks remain |
| 9 | No critical frontend/backend integration failures remain | **PASS for implemented paths**; core integration paths do not exist yet |
| 10 | All fixes regression-tested | **PASS** — migration applied and verified; sign-out test and full suite pass |

---

## 11. Verdict

**Aetrix is not a complete, integrated application and is not ready for operational use.**

What is real and working: the deployed marketing site, sign-in surface, role-aware shell, session
handling, live health screen, Supabase auth verification/JWKS, PostgreSQL schema with RLS and
locked-down Data API grants, the provider-fleet API/UI, the correction-job state machine, and the
worker’s honest refusal to invent marks.

What is missing is the product: no marking, no verification, no results, no reports, no cohort
analysis, no authenticated data screens, and no executed authenticated API path. The current
system is an **integration checkpoint**, not a marking platform. Declaring full readiness would
contradict both the code and the evidence in this report.
