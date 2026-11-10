# Aetrix V5.5 — Full live integration and acceptance audit

**Date:** 2026-11-08
**Deployed frontend:** <https://aetrix.pages.dev> (Pages build from commit `70f3410`)
**Backend:** laptop FastAPI process on `127.0.0.1:8000`, published through a Cloudflare quick tunnel
**Database:** live Supabase PostgreSQL project, plus disposable isolated databases for destructive tests
**Overall verdict:** **NOT READY AS A COMPLETE APPLICATION.** This is a working pre-release
integration checkpoint. Authentication, tenant-scoped API reads, the correction-job lifecycle, the
worker and the database controls are real. The marking product, results, reports and authenticated
data frontend do not exist. Two critical gaps remain on the live deployment: account-role
provisioning, and a credential-URL defect in the currently deployed sign-in bundle.

This report records only behavior that was executed. Nothing is inferred from a file merely existing.

---

## 1. What was executed

| Area | Evidence |
|---|---|
| Deployed frontend | 48 JavaScript assets fetched; all 48 returned 200 |
| Frontend suite | **150 passed, 2 skipped** in the deployed run; the two skipped live-health tests were run separately and **2 passed** |
| Frontend build | TypeScript `tsc --noEmit` **PASS**; Vite production build **PASS**, 35 prerendered pages |
| Real Supabase sign-in | Email/password sign-in against the live Supabase project succeeded; session stored, reload restored it, sign-out cleared it |
| Live identity | Real Supabase JWT accepted by the laptop API through the public tunnel; viewer JWT accepted separately |
| Backend tests | **160 passed**, one deprecation warning, 575 s |
| Backend lint | Ruff **PASS** |
| Live API boundary | **55 operations** discovered; all **52 protected operations returned 401** without a token |
| Live read sweep | **28 GET operations** with the owner token: 9×200, 7×403, 12×404, **0×5xx** |
| Live authorization matrix | **18/18 checks passed** after restarting the stale API process |
| Live workflow | Exam → blueprint → scheme → assignment → submission → PDF upload → correction → cancel/retry → worker claim |
| Database | 31 tables; **31/31 RLS enabled**; zero `anon`/`authenticated` grants; three append-only triggers |
| Alembic | Head `0009_verification_grants`; `alembic check` reports no drift |
| Security scan | Zero secret markers and zero localhost API markers in 48 deployed assets |
| CORS | Deployed origin allowed; foreign origin rejected; loopback development origin allowed |
| Latency | Tunnel `/health` p50 150.1 ms, p95 272.8 ms; `/ready` p50 446.2 ms, p95 448.3 ms |

Destructive backend tests used disposable PostgreSQL databases (`aetrix_acceptance_*`). The live
workflow used a dedicated tenant and two dedicated users; no pre-existing user data was modified.

---

## 2. Critical findings

### 2.1 Deployed sign-in can put the password in the URL

**Severity: Critical. Reproduced on the deployed site.**

Submitting the email/password form before React hydrated caused the browser's native **GET**
submission:

```text
https://aetrix.pages.dev/sign-in?email=<redacted>&password=<redacted>
```

No session was created. This exposes the password to browser history, screenshots, referrer paths,
proxy logs and anyone who sees the URL.

**Root cause:** the form relied entirely on a React `onSubmit` handler with no safe native fallback.
Before hydration, the browser performed the default GET.

**Fix applied locally:** `frontend/src/routes/_marketing.sign-in.tsx` now uses:

```html
<form method="post" action="/sign-in" onSubmit={submitPassword} noValidate>
```

The React handler still prevents the native submission once hydrated. The fallback can no longer put
credentials in the query string.

**Regression coverage:** `frontend/tests/auth.spec.ts` now disables JavaScript, submits the native
form, and asserts that the request is `POST`, has an empty query string, and contains neither the
email nor the password in its URL. The test passed against the fixed local server.

**Important limitation:** the fix is **not deployed**. The Pages build still serves the vulnerable
pre-fix form. A redeploy is required before the public site can be considered safe.

### 2.2 Real sign-in dead-ends because no Aetrix role is provisioned

**Severity: Critical. Reproduced with a real Supabase account.**

The live user authenticated successfully. Its Supabase session was stored as `aetrix:auth`, survived
reload and was cleared by sign-out. The engine database also had a matching user row with an owner
role. The UI nevertheless displayed:

> **No account role assigned**

**Root cause:** the frontend reads only `user.app_metadata.aetrix_role` (or
`app_metadata.aetrix.role`). The Supabase account has neither claim. The engine's `users.role` is not
used by the frontend, and there is no provisioning endpoint or admin flow that writes the
identity-provider claim.

**Impact:** a correctly provisioned engine user cannot open any dashboard or call a data screen.
This blocks the entire authenticated UI.

**Required fix:** provision `app_metadata.aetrix_role` in Supabase for each accepted user, with a
matching engine role, before inviting them. This requires the identity-provider admin API; a browser
session must not be able to grant it. No such provisioning workflow exists in the product.

### 2.3 The API process serving the tunnel was stale

**Severity: Critical operationally; fixed during this audit.**

Before restart, the live API:
- returned **404** for every new workspace/assignment/submission read route; and
- allowed the real **viewer** to cancel a correction with **202**.

The process had been started before the current code was loaded. It was stopped and replaced with
the current backend on `127.0.0.1:8000`. After restart:
- the same reads returned **200**;
- no-token reads returned **401**;
- the viewer received **403** for create, cancel and retry;
- the owner received **202** for cancel.

The tunnel stayed up. This is a deployment/process-management failure, not a source-code failure: a
running service must be restarted or reloaded when its code changes.

### 2.4 The marking product does not exist

**Severity: Critical.**

The worker starts, claims jobs, moves them through `CREATED → VALIDATING`, and parks them at
`RETRY_SUSPENDED` with `PIPELINE_UNAVAILABLE`, `retryable=true`, and no result rows. That is honest
behavior, not marking. There is no correction pipeline, no SymPy verification, no result endpoint,
no mark review, no report, no gradebook data and no cohort output.

---

## 3. Fixes applied during this audit

1. **Viewer job authorization** — `backend/app/jobs/service.py` now calls `ensure_reviewer` in both
   `cancel` and `retry`. Live viewer requests now return 403.
2. **Tenant-scoped read API** — `backend/app/api/v1/exams.py` adds workspace, workspace assignment,
   workspace correction, assignment, assignment submission, submission and submission correction
   reads. Repositories and `WorkspaceRead` were extended. Cross-tenant and random IDs return 404.
3. **PostgreSQL lease query** — `CredentialRepository.claim_candidates` uses an `EXISTS` predicate
   instead of an outer join, so PostgreSQL accepts `FOR UPDATE` with the lease query.
4. **Contributor summary conversion** — `backend/app/api/v1/admin_contributions.py` returns the
   validated summary schema rather than a raw shape.
5. **Schema test fixture** — `backend/tests/integration/test_schema.py` supplies the required
   `project_id`.
6. **Sign-in URL-leak fix and regression test** — described in §2.1.
7. **Regression coverage for read contracts and viewer denial** — `backend/tests/integration/test_api.py`
   adds authenticated read, cross-tenant and viewer-role tests.

`ruff`, the full backend suite, TypeScript, the production build and the focused frontend regression
all pass after these changes.

---

## 4. Requirements-to-implementation matrix

Statuses: **PASS** = executed and verified; **FAIL** = executed and broken; **PARTIAL** = some real
behavior, acceptance criteria not fully met; **BLOCKED** = dependency unavailable; **NOT
IMPLEMENTED** = absent; **NOT TESTED** = no execution.

| # | Planned feature | Status | Actual implementation / evidence |
|---:|---|---|---|
| 1 | Public marketing site | **PASS** | 30 route URLs loaded; responsive, theme, accessibility and navigation tests pass; deployed 200 |
| 2 | Email/password authentication | **PARTIAL** | Real Supabase login, reload and sign-out pass on fixed source; deployed bundle still has the pre-fix URL-leak form |
| 3 | Google OAuth sign-in | **PARTIAL** | Real PKCE authorize request is built and callback failure states render; interactive Google consent was not completed |
| 4 | Session persistence and sign-out | **PASS** | Real session survived reload; sign-out cleared storage; protected route returned to sign-in |
| 5 | JWT signature/issuer verification and auth enforcement | **PASS** | Real Supabase JWT accepted; all 52 protected operations 401 without a token; forged/`alg:none` tests pass |
| 6 | Role-aware shell, navigation and route guards | **PASS** | Four roles plus no-role verified; forbidden-route panels, redirects, responsive rail and keyboard behavior pass |
| 7 | Real identity-provider role provisioning | **BLOCKED** | Supabase account has no `app_metadata.aetrix_role`; no product provisioning flow exists |
| 8 | Tenant isolation and scoped reads | **PASS** | Live cross-tenant and random IDs return 404; workspace reads return only the caller's tenant; 160 backend tests pass |
| 9 | Workspace membership, invitations and switching | **NOT IMPLEMENTED** | No membership/invite/switch endpoint or UI |
| 10 | Exam creation and listing | **PASS** | Live create 201 and list 200 through the tunnel; viewer create 403 |
| 11 | Blueprint draft, approval and overrides | **PARTIAL** | Live draft/approve and immutable-hash checks pass; override list/create exists but was not exercised live and has no UI |
| 12 | Mark-scheme upload and approval | **PASS** | Live PDF upload 201, approval 200, read 200 through the tunnel |
| 13 | Assignment and submission registration | **PASS** | Live assignment 201, submission 201, document upload 201, read 200 |
| 14 | PDF ingestion and local document storage | **PASS** | Real one-page PDFs ingested and read; storage remains local filesystem, not Supabase Storage |
| 15 | Page mapping and blueprint extraction | **PARTIAL** | Code and tests exist; live extraction/mapping requires the disabled provider and was not executed |
| 16 | Correction job lifecycle | **PASS** | Create 201, duplicate 200 with same ID, cancel 202, retry 409 when terminal; worker parks honestly |
| 17 | Worker leases, attempts and retry policy | **PASS** | Worker claimed the live job, recorded attempt 1, parked with `PIPELINE_UNAVAILABLE`; manual retry reset the budget intentionally |
| 18 | Marking engine | **NOT IMPLEMENTED** | `CorrectionPipeline` unavailable; worker deliberately invents no marks |
| 19 | SymPy verification | **NOT IMPLEMENTED** | No pipeline and no verification results |
| 20 | Results, selective review and mark overrides | **NOT IMPLEMENTED** | No result endpoint, mark review surface or mark override |
| 21 | Reports, gradebook and analytics | **NOT IMPLEMENTED** | UI shells only; no engine data or result aggregation |
| 22 | Cohort intelligence | **NOT IMPLEMENTED** | No cohort implementation |
| 23 | Provider fleet administration | **PARTIAL** | 18 operations and a full UI exist; seven fleet GETs returned 403 for the test engine role `OWNER`, and no real `PLATFORM_OWNER` token was used |
| 24 | Contributor key programme | **PARTIAL** | Backend and UI exist; not exercised with a real platform-owner token |
| 25 | Live Gemini provider | **BLOCKED** | `LIVE_PROVIDER=false`; no key; all provider behavior remains `UNVERIFIED` |
| 26 | Google Classroom integration | **NOT IMPLEMENTED** | UI explains the gap only |
| 27 | Supabase Storage | **NOT IMPLEMENTED** | Local filesystem adapter is the only storage backend |
| 28 | Malware scanning and upload resource limits | **NOT IMPLEMENTED** | No scanner, decompression limits or quota enforcement |
| 29 | Rate limiting | **NOT IMPLEMENTED** | No rate-limit middleware or headers |
| 30 | RLS and Data API lockdown | **PASS** | 31/31 tables RLS; zero `anon`/`authenticated` grants; anon Data API reads rejected |
| 31 | Append-only audit, job events and usage | **PARTIAL** | Three database triggers exist and rows are append-only; no read API or UI |
| 32 | Notifications and inbox | **NOT IMPLEMENTED** | No notifications/results to deliver; inbox is an unavailable-state shell |
| 33 | Classes, students and CSV import | **NOT IMPLEMENTED** | UI shells only |
| 34 | Comments and collaboration | **NOT IMPLEMENTED** | Absent |
| 35 | Plans and billing | **NOT IMPLEMENTED** | Deferred |
| 36 | D1/R2/Queues historical blueprint | **NOT IMPLEMENTED** | Historical only; ADR-001 selects PostgreSQL/SQLAlchemy |
| 37 | Deployment pipeline | **PARTIAL** | Pages serves the build, but the deployed bundle predates the security fix and the live API process had to be restarted manually |
| 38 | Observability | **PARTIAL** | JSON logs and request IDs; no external monitoring/alerting |
| 39 | Backup and restore | **NOT TESTED** | No backup/restore drill was run |
| 40 | Accessibility | **PARTIAL** | Axe passes public pages; authenticated shells have keyboard/overflow tests but no axe pass |
| 41 | Responsive layout | **PASS** | Seven viewports; no horizontal overflow on tested routes |
| 42 | Performance | **PARTIAL** | Current-scale latency measured; no target-scale load test or tunnel/DB failure recovery |

**Counts:** 13 PASS · 11 PARTIAL · 2 BLOCKED · 15 NOT IMPLEMENTED · 1 NOT TESTED.

---

## 5. Frontend

- **Route URLs:** 30. All returned HTTP 200 on the deployed host.
- **Prerendered pages:** 35, including route anchors and duplicate directory forms.
- **Route coverage:** public, workspace, platform, assistant, detail routes, sign-in, callback and
  unknown IDs.
- **Interaction coverage:** navigation, role redirects, forbidden panels, search/filter tabs,
  theme persistence, rail collapse, phone tab bar, reduced motion, keyboards, sign-out, empty and
  error states.
- **Deployed suite:** 150 passed, 2 skipped. The two skipped live-engine health tests passed when run
  with `VITE_AETRIX_API_URL` set.
- **Console/network:** the real sign-in page had zero console errors and zero failed requests. The
  full deployed suite had no reported failures. `/platform/health` was separately verified against
  the live tunnel.
- **Real login:** real Supabase email/password authentication works after hydration. It reaches the
  no-role gate because role provisioning is absent.
- **Deployed security defect:** the pre-hydration GET described in §2.1 is still live until redeploy.

Only three surfaces call the engine: the health screen, the provider-fleet screen and the sign-in
surface. Every workspace, assignment, submission, queue, report, gradebook, analytics and inbox
screen is a designed unavailable-state shell; none reads engine data.

---

## 6. Backend

### Registered surface

**55 operations:** 3 public (`/health`, `/ready`, `/version`) and 52 protected under `/api/v1`.

- All **52 protected operations** were called without a token and returned **401**.
- All 28 GET operations were called with a real owner JWT. No operation returned 5xx.
  - 9 returned 200.
  - 7 provider-fleet reads returned 403 because the live test user is engine role `OWNER`, not
    `PLATFORM_OWNER`; this is correct least-privilege behavior, but the platform-owner fleet path
    remains unverified with a real token.
  - 12 returned 404 for substituted random UUIDs, including cross-tenant objects.
- The 18-check post-restart matrix covered the new workspace/assignment/submission reads, no-token
  401s, viewer 403s, owner 202s, validation 422s and cross-tenant 404s.

### Real authenticated workflow

| Step | Result |
|---|---|
| `POST /api/v1/exams` | 201 |
| direct blueprint approval before a draft | 409, correct |
| blueprint draft | 200 |
| blueprint approval | 200 |
| scheme PDF upload | 201 |
| scheme approval | 200 |
| assignment creation | 201 |
| submission registration | 201 |
| submission PDF upload | 201 |
| correction creation | 201 |
| duplicate correction with same idempotency key | 200, same job ID |
| owner cancel | 202 |
| retry a cancelled job | 409, correct |
| worker claim | `CREATED → VALIDATING → RETRY_SUSPENDED` |
| worker error | `PIPELINE_UNAVAILABLE`, retryable, no result rows |

### Worker

The live worker booted with `pipeline: unavailable`, claimed the controlled job, recorded attempt 1,
and parked it. A manual retry reset the attempt budget by design; the second claim also recorded
attempt 1, not attempt 2. The worker did not produce a mark. The worker process was stopped after
verification; no graceful-shutdown assertion was captured.

---

## 7. Security and data integrity

| Check | Result |
|---|---|
| Real JWT accepted through tunnel | PASS |
| Missing token on 52 protected operations | 401 for all |
| Invalid/forged/`alg:none` tokens | 401 (integration coverage) |
| Viewer cannot create exam | 403 |
| Viewer cannot cancel or retry | 403 after current API restart |
| Cross-tenant workspace/assignment/submission | 404 |
| CORS: `https://aetrix.pages.dev` | 200, matching `Access-Control-Allow-Origin` |
| CORS: `https://evil.example` | 400, no allow-origin |
| CORS: `http://127.0.0.1:3000` | 200, development origin |
| Secret markers in 48 deployed assets | 0 for `service_role`, `SUPABASE_SERVICE`, `JWT_SECRET`, `ENCRYPTION_KEY`, `sk-proj-`, `AIzaSy` |
| Localhost API markers in deployed assets | 0 |
| RLS | 31/31 tables |
| `anon`/`authenticated` table grants | 0 |
| Append-only triggers | 3 |
| Public API docs | `/docs` and `/api/v1/openapi.json` return 200 because the live environment is `development` |
| Rate limiting | absent |
| Upload malware scanning | absent |

The **credential URL leak** is the only critical security defect found in frontend code during this
audit. It is fixed in the working tree and covered by a regression test, but is **not deployed**.
The exposed test password should be treated as compromised and the dedicated test account removed or
rotated.

---

## 8. Failure and recovery

| Scenario | Result |
|---|---|
| Worker pipeline unavailable | PASS — parks with a classified, retryable error; no fabricated marks |
| Backend process stale/restarted | PASS after restart — reads and viewer authorization corrected; tunnel stayed connected |
| Health screen with unreachable engine | PASS — explicit unreachable state |
| Invalid API payload | PASS — typed 422 |
| Cross-tenant object | PASS — 404 |
| Tunnel interruption | NOT TESTED |
| Database outage | NOT TESTED |
| Expired Supabase session | NOT TESTED |
| Malformed provider output | PARTIAL — isolated tests only; no live provider |
| Backup/restore | NOT TESTED |

---

## 9. Outstanding issues

| Severity | Issue | Root cause | Required action |
|---|---|---|---|
| **Critical** | No marking, results, SymPy verification or reports | Pipeline deliberately unavailable | Implement and prove the correction pipeline before calling the product functional |
| **Critical** | Deployed sign-in can put the password in the URL before hydration | Native GET fallback on the pre-fix form | Deploy the fixed `method="post"` form and regression test; rotate the exposed test credential |
| **Critical** | Real user cannot open a dashboard | No `app_metadata.aetrix_role`; no provisioning flow | Add identity-provider role provisioning with engine-role parity and audit |
| **High** | No authenticated data frontend | Workspace/assignment/submission screens are shells | Wire the new read APIs into the UI with loading, empty and error states |
| **High** | Quick tunnel URL is ephemeral | No Cloudflare-managed zone/named tunnel | Use a stable named tunnel and controlled hostname for demos |
| **High** | Live Gemini is disabled and unverified | `LIVE_PROVIDER=false`, no key | Keep `UNVERIFIED`; do not claim model accuracy |
| **Medium** | Public `/docs` and OpenAPI on the tunnel | `AETRIX_ENV=development` | Use production configuration or disable docs on exposed hosts |
| **Medium** | No rate limiting or malware scanning | Not implemented | Add edge/API limits and upload scanning before untrusted exposure |
| **Medium** | Platform fleet not verified with a real token | Test engine user is `OWNER`, not `PLATFORM_OWNER` | Provision a real platform-owner identity and exercise the fleet |
| **Medium** | No backup/restore or external monitoring | Operational work not started | Add backups, alerting and a restore drill |
| **Medium** | Isolated acceptance tenant remains in the live database | Test rows include append-only events | Remove under a controlled append-only-aware cleanup, or retain as named test data |
| **Low** | No axe pass on authenticated shells | Public pages only | Add authenticated accessibility checks |
| **Low** | Frontend service declarations name paths without screens | Contract written ahead of UI | Implement the screens or remove the unused declarations |

---

## 10. Acceptance criteria

| # | Criterion | Result |
|---:|---|---|
| 1 | Deployed frontend communicates with the laptop backend | **PASS** — health, readiness and authenticated API calls through the tunnel |
| 2 | Backend communicates with its database and identity provider | **PASS** — live PostgreSQL; real Supabase JWT accepted |
| 3 | All accessible routes tested | **PASS** — 30 route URLs; 150 deployed tests plus 2 live-health tests |
| 4 | Every endpoint attempted or documented blocked | **PASS as process** — 52 protected operations rejected without a token; 28 reads swept; authenticated writes exercised through the workflow |
| 5 | Every planned feature compared with its specification | **PASS** — 42-row matrix above |
| 6 | All critical user workflows pass | **FAIL** — role provisioning, marking, review and results are unavailable |
| 7 | Authentication and authorization work correctly | **PARTIAL** — real JWT, viewer denial, cross-tenant 404 and session persistence pass; live role provisioning blocks the UI; deployed sign-in has the fixed-in-tree credential leak |
| 8 | No critical security failures remain | **FAIL** — the deployed bundle still contains the credential-URL defect |
| 9 | No critical frontend/backend integration failures remain | **FAIL** — the live UI cannot open a workspace because no role is provisioned |
| 10 | All fixes regression-tested | **PARTIAL** — backend, build and focused sign-in regression pass; full frontend suite was not rerun after the form change, and the fix is not deployed |

---

## 11. Verdict

**Aetrix V5.5 is not a complete, integrated application and is not ready for operational use.**

What is real and verified: the deployed marketing site, Supabase authentication and session
mechanics, role-aware shell under provisioned sessions, live health screen, JWT verification,
tenant-scoped API reads, exam/blueprint/scheme/assignment/submission ingestion, idempotent correction
jobs, PostgreSQL leases, the worker's honest refusal to invent marks, RLS and Data API lockdown, and
the corrected viewer authorization.

What is missing or unsafe: the marking product, results, reports, cohort intelligence and data
frontend; real account-role provisioning; a safe deployed sign-in form; a stable API hostname; and
production hardening for docs exposure, rate limiting, malware scanning, backups and monitoring.

The current system is an **integration checkpoint**, not a marking platform. Declaring it accepted
would contradict both the execution evidence above and the explicit product boundary in the
architecture documents.
