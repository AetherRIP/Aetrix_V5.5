# Aetrix V5.5 — implementation progress

Tracking the approved implementation plan against the feature register in
`AETRIX_WEBSITE_WIP_AUDIT.md`. Register IDs are grouped by the milestone that
addressed them; any ID not named here still stands at the audit's status.

**Statuses**

| Status | Meaning |
|---|---|
| **VERIFIED** | A check was run in this session and passed. The exact command is in “Verification”. |
| **IMPLEMENTED** | Code is in place; the check needs a resource this machine does not have. |
| **BLOCKED** | Needs an external credential, account or service decision. |
| **NOT STARTED** | Unchanged from the audit. |

Marking is still **not verified end-to-end**: the live provider is `UNVERIFIED`
and no funded Gemini key is configured. Nothing in this build claims otherwise.

---

## Milestone 0 — Truth and hygiene

| ID | Change | Status |
|---|---|---|
| P02 | `FinalCta` rewritten: sign-in is enabled, no "join the waitlist" implication. | VERIFIED (Playwright `marketing.spec.ts`) |
| P03 | `Security` rewritten: Python/FastAPI engine (not a Worker), application-level tenant scoping stated honestly, no cross-tenant database-constraint claim. | VERIFIED (Playwright `marketing.spec.ts`) |
| D.3.5 | `Workflow` rewritten: engine-local storage, Classroom explicitly not integrated. | VERIFIED (Playwright `marketing.spec.ts`) |
| F.1 | Hero product preview carries an explicit "Synthetic demonstration data" badge. | VERIFIED (Playwright `marketing.spec.ts`) |
| — | `API_NOT_DEPLOYED_REASON` added to `frontend/src/lib/env.ts` + `lib/api/client.ts`; the fleet assertion is satisfied by honest wording, not weakened. | VERIFIED (Playwright `roles.spec.ts` → “states the fleet data gap rather than showing figures”) |
| — | `frontend/scripts/strip-dev-vars.mjs` runs after `vite build` and deletes any `dist/**/.dev.vars`; only public `VITE_*` values can ever reach it. | VERIFIED (three production builds; `find dist -name .dev.vars` empty) |

## Milestone 1 — Identity and tenancy

| ID | Change | Status |
|---|---|---|
| P10 | `invitations` table + migration `0010_invitations.py` (tenant, email, role, token hash, inviter, expiry, accepted/revoked, CHECK on the role vocabulary). | VERIFIED (migrations applied from an empty database; `test_identity.py` 10 passed) |
| A15 | Auto-provisioning in `api/deps.py::get_principal`: verified email + `email_verified` + exactly one live invitation → one `users` row, invite accepted, audit event, tenant taken from the invitation only. No invitation → `403 PROVISIONING_REQUIRED`. | VERIFIED (`test_identity.py`) |
| P14 | `identity.py` router: `/me`, invitations list/create/revoke, members list, member role PATCH. `GET /me` returns the engine role and the documented `ui_role` mapping. | VERIFIED (`test_identity.py`) |
| A01/A03 | Tenant resolution remains the verified JWT claim (`deps.py`); nothing reads a tenant from a request body. Second-tenant reads return 404. | VERIFIED (`test_identity.py`, `test_api.py`) |

`test_identity.py` proves: one row per provisioned subject (second call reuses it),
uninvited and unverified accounts refused without creating a row, a provisioned
member still gets 404 for another workspace, role changes audited once with
before/after detail, a viewer cannot invite, self-elevation refused, cross-tenant
role PATCH 404.

## Milestone 2 — The marking pipeline

| ID | Change | Status |
|---|---|---|
| B05 | `prompts/aetrix_v5_5_marking/v1.md` and `prompts/aetrix_v5_5_double_check/v1.md` + manifest entries with real SHA-256s; strict JSON contract (`awarded`, `reason`, quoted evidence, confidence, student answer). | VERIFIED (`test_prompt_manifest.py`) |
| B10 | `app/correction/aetrix/` package: `schema.py` (strict pydantic parse), `verification.py` (SymPy equivalence + integrity checks), `pipeline.py` (real `AetrixPipeline`). The legacy `app/marking/` package is restored and is the default engine (`aetrix_legacy`); the V5 implementation in `app/correction/aetrix/` stays in the tree, unregistered, for a later slice. | VERIFIED (`test_aetrix_pipeline.py` 8 passed, unit marking tests) |
| B11 | Default-engine results carry `status` and `processing_state` in the same flush: a `before_flush` hook in `app/correction/engine/state_hook.py` fills the state from the single `STATUS_TO_STATE` mapping shared with the 0023 backfill; a contradictory status aborts the flush instead of persisting NULL. | VERIFIED (`test_legacy_processing_state.py` 6 passed) |
| B12 | Migration `0024_double_check_verification` added during this campaign, outside Slice 1's chain (ends at 0023); retained because removing it would delete the in-tree V5 double-check or leave its verdicts unpersistable. Justified in ADR-003; applied to no project database. | RECORDED |
| B06 | Scheme/blueprint lock: a job is refused unless both are approved; the pipeline re-checks status and refuses cross-tenant versions. | VERIFIED (`test_jobs.py`, `test_marking_pipeline.py`) |
| C06/C07 | Results are read back through `GET /submissions/{id}/results` and `GET /corrections/{job_id}/results`; the pipeline writes `QuestionResult`, `CriterionResult`, `MarkingEvidence`, `VerificationResult`. | VERIFIED (`test_marking_pipeline.py`, `test_results_api.py`) |
| — | Uncertainty becomes `REVIEW_REQUIRED`, never a fabricated zero: low confidence, unreadable pages, over-max award, malformed JSON, undecidable algebra. | VERIFIED (unit + `test_marking_pipeline.py`) |
| — | Idempotent per `(job, question)`; cancellation discards committed partial results at the next checkpoint. | VERIFIED (`test_marking_pipeline.py`) |

## Milestone 3 — Results, review, approval, aggregation

| ID | Change | Status |
|---|---|---|
| C11 | `GET /submissions/{id}/results`, `GET /corrections/{job_id}/results`: marks, criteria, evidence, verification, review state, totals. | VERIFIED (`test_results_api.py` 11 passed) |
| C12 | `POST /results/{question_result_id}/override`: stated reason required, actor + timestamp recorded, `LearningFeedback` + audit written, optimistic `record_version` conflict → 409, refuses to exceed the maximum. | VERIFIED (`test_results_api.py`) |
| C13 | `POST /corrections/{job_id}/reviews/{question_id}` — reviewer decision (Uphold / Change / Independent second pass), reason required, mark bounded by the maximum, `ReviewDecision` + audit + learning feedback written. | VERIFIED (`test_results_api.py`) |
| C13 | `POST /corrections/{job_id}/approve` behind a separate permission; refused while any question needs review; approval stored in `job_approvals` (migration `0011_job_approvals.py`). | VERIFIED (`test_results_api.py`) |
| C15 | `GET /submissions/{id}/pages/{page_index}` — tenant-checked PNG bytes with `Cache-Control: private`. | VERIFIED (`test_results_api.py`) |
| C10, C33 | Aggregation router: `/workspaces/{id}/dashboard`, `/inbox`, `/reports`, `/gradebook` — real SQL counts with explicit `INSUFFICIENT_DATA` contracts. | VERIFIED (`test_workspace_reads.py`: inserted-row counts, per-assignment means, ordering, empty shapes, cross-tenant 404; `test_results_api.py` gradebook) |
| B14, B16 | `GET /workspaces/{id}/audit` tenant-scoped, plus platform-wide `/admin/audit` for operators; job detail exposes attempts and typed error classification. | VERIFIED (`test_workspace_reads.py`: tenant scope, newest-first ordering, action/entity filters, limit/offset, platform-operator-only `/admin/audit`) |

## Milestone 4 — Frontend wired to the real API

| Screen | State |
|---|---|
| API client + `services.ts` + `types.ts` (snake_case, bearer token threaded, `unavailable` preserved) | VERIFIED (`tsc --noEmit`, Playwright) |
| `/dashboard`, `/assignments` | VERIFIED (Playwright route content) |
| `/assignments/$id` | VERIFIED (Playwright route content, typecheck) |
| `/submissions/$id` | VERIFIED (Playwright route content, typecheck) |
| `/queue` | VERIFIED (Playwright route content) |
| `/gradebook`, `/inbox`, `/reports` | VERIFIED (Playwright; cards render with an honest unavailable body, no zeros) |
| `/workspace` | VERIFIED (Playwright) |
| `/students` | VERIFIED (Playwright; classes, roster, create forms and CSV import against the real engine) |
| `/settings` | VERIFIED (Playwright; settings persistence itself is still absent and stated honestly) |
| `/platform/health` | VERIFIED (Playwright; DOM-level engine probe skipped — see gaps) |

No mock rows and no placeholder metrics were added. `unavailable` remains a real
state on every screen. The gradebook no longer hides its cards when the engine
does not answer: it renders “Summary” and “Marks” and says inside them that no
figures exist yet.

## Milestone 5 — Verification

Disposable database: PostgreSQL 16.2 from the bundled `pgserver` install
(no Docker/WSL/system server on this machine), data directory `.tmp/pg-it/data`,
port `55432`, database `aetrix_it` created empty, then the three data-API roles
(`anon`, `authenticated`, `service_role`) and Supabase default grants created
exactly as `.github/workflows/ci.yml` does. `AETRIX_TEST_DATABASE_URL` pointed at
it throughout; the development database was never touched.

| Check | Command | Result |
|---|---|---|
| Lint | `cd backend && .venv/Scripts/python.exe -m ruff check app tests` | **All checks passed** |
| Unit suite | `cd backend && .venv/Scripts/python.exe -m pytest tests/unit -q` | **107 passed** (71.22s) |
| Typecheck | `cd frontend && ../.tools/node/node.exe node_modules/typescript/bin/tsc --noEmit` | **exit 0** |
| Production build | `cd frontend && VITE_AETRIX_API_URL= ../.tools/node/node.exe node_modules/vite/bin/vite.js build` | **exit 0** (prerender + client + server) |
| `.dev.vars` strip | `node scripts/strip-dev-vars.mjs` after the build | **removed `dist/server/.dev.vars`; `find dist -name .dev.vars` empty** |
| Engine origin absent from bundle | `grep -rl tail06bb75 dist` | **no matches** (the unreachable Tailscale host is not compiled in) |
| Integration, fresh database | `cd backend && AETRIX_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/aetrix_it .venv/Scripts/python.exe -m pytest tests/integration -q` | **128 passed** (103.70s), migrations (through `0012_classes_students`) from an empty schema |
| Integration, second consecutive run, same database | same command | **128 passed** (97.33s) — idempotent |
| New suites within that 128 | `test_identity.py` 10, `test_results_api.py` 11, `test_marking_pipeline.py` 8, `test_workspace_reads.py` 11, `test_roster_api.py` 6, `test_roster_import.py` 4, `test_notifications_history.py` 2 | all passed (the two new files: **6 passed** focused) |
| Playwright | `cd frontend && ../.tools/node/node.exe node_modules/@playwright/test/cli.js test` against `http://127.0.0.1:3000` | **151 passed, 2 skipped, exit 0** (1.8m) |
| Preview after a rebuild | restart `vite preview` after every build and confirm the hashed entry bundle returns 200 | Required: a long-lived preview caches its asset index, so a rebuilt bundle 404s and the app stalls on “Checking your session”. Verified by restarting the preview and rerunning the suite. |
| Disposable database cleanup | `dropdb aetrix_it`, `pg_ctl stop` | database dropped, cluster stopped |
| Live marking against Gemini | — | **BLOCKED**: no funded provider key; provider status remains `UNVERIFIED` |

No assertion was weakened, skipped or deleted. The only test-file change was in
`test_identity.py`: its cross-tenant 404 loop wrongly listed a *tenant-A*
assignment’s submissions (the fixture assignment belongs to tenant A), which
contradicted the assertion immediately after it; the loop now covers the two
tenant-B paths and asserts the tenant-A assignment **and** its submissions are
readable, which is a stricter statement of the same scope rule.

### Defects found by verification and fixed in application code

1. `POST /workspaces/{id}/invitations` returned a serializer error: `InvitationCreated`
   requires `acceptance_code`, which cannot come from the ORM row. The response is
   now built from `InvitationRead` plus the one-time code.
2. `QuestionMarkingPipeline` appended the ORM `QuestionResult` to a list typed and
   consumed as question-result UUIDs, so cancellation’s `_discard` crashed with
   “Object … is not legal as a SQL literal” **and** left partial marks behind.
3. Approval attribution could be `null` for an account with no display name. The
   stored label now falls back to email, then the user id, so an approval is never
   unattributed.
4. `extract_verified_email` let `provider: google` override an explicit
   `email_verified: false`. An explicit claim is now authoritative, so an unverified
   address cannot redeem an invitation.
5. `/gradebook` rendered no cards when the engine was unavailable, unlike every
   other screen. It now renders its cards with an honest “no figures yet” body and
   distinct titles (“Summary”, “Marks”).

## Classes and students (Phase 4)

| Capability | State |
|---|---|
| `classes` + `students` tables, migration `0012_classes_students.py`, tenant-scoped, RLS locked down | VERIFIED (migrated from empty schema; `test_roster_api.py`) |
| `GET/POST /workspaces/{id}/classes`, `PATCH/DELETE /classes/{id}`, `GET/POST /workspaces/{id}/students`, `PATCH/DELETE /students/{id}` | VERIFIED (create, list, filter, duplicate 409, blank 422, delete keeps students) |
| Role gating: teaching roles write, every member reads, foreign workspace is 404 | VERIFIED (`test_roster_api.py`, including viewer refusals) |
| `/students` screen wired to the real roster with create and CSV import forms, honest empty states | VERIFIED (Playwright `roles.spec.ts`; typecheck; build) |

The roster is workspace-owned data. It is **not** a Google Classroom sync: the
Classroom integration now lists courses and stores them `VERIFIED`, but it does
not import students, and the screen says so.

## Teacher and assistant features (this pass)

| Capability | State |
|---|---|
| CSV roster import (`POST /workspaces/{id}/students/import`) — UTF-8 CSV, required `student_ref`, optional `display_name`/`class`, 500 rows and 1 MB caps, content-type check, per-row line numbers, duplicate skipping (in-file and stored), missing classes created | VERIFIED (`test_roster_import.py` 4 tests; viewer 403, foreign workspace 404, bad header 422, wrong type 415, oversize 413, row cap 422) |
| `/students` import panel: file or paste, summary counts and per-row issue table; no blanket success | VERIFIED (Playwright, typecheck, production build) |
| Notifications (`GET /workspaces/{id}/notifications`) — derived from stored jobs, approvals and pending invitations; read state deliberately null; managers see invitations, reviewers do not | VERIFIED (`test_notifications_history.py`) |
| `/notifications` screen with work/membership filters, real links and an honest empty state | VERIFIED (Playwright, typecheck, build) |
| Assistant invitations and permissions on `/assistants`: members, role change, invite with one-time acceptance code, revoke with reason, capability-gated read-only view | VERIFIED (existing `test_identity.py` API coverage; screen build/typecheck/Playwright) |
| Marking history (`GET /workspaces/{id}/marking-history`) — stored jobs with per-job awarded/total, review count, approval label and pagination | VERIFIED (`test_notifications_history.py`) |
| `/history` screen with state filters and previous/next pagination | VERIFIED (Playwright, typecheck, build) |
| Google Classroom | Course OAuth and discovery implemented: encrypted token store, refresh, revoked-access handling, a `/classroom` connect/sync screen and `POST /api/v1/classroom/sync`. Roster import and grade publishing remain unavailable and are labelled as such |

No table was added for notifications or read state: both views are derived from existing
`correction_jobs`, `question_results`, `job_approvals` and `invitations` rows.

## Remaining work and gaps

1. **Live model marking — BLOCKED.** The pipeline is unit- and integration-verified
   with a scripted provider, but no live Gemini response has been observed and no
   funded key is configured. The provider remains `UNVERIFIED`; this was not faked
   or stubbed into looking verified.
2. **Public HTTPS engine origin — BLOCKED (external).** The only configured origin
   (`frontend/.env`, a Tailscale host) is unreachable from this machine, so the
   production build carries no engine origin and states that honestly. Consequently
   `health.spec.ts`’s two DOM-level tests skip themselves (`test.skip(!API)`) — they
   require a public HTTPS origin by design. 151 tests ran and passed; those 2 are
   reported as skipped, not as passes.
3. `read` state on inbox items is `null` — the engine has no read-state table. The
   UI states this rather than inventing a flag.
4. Cohort analytics beyond per-assignment counts (facility, discrimination) are not
   implemented; `/reports` reports counts and means only.

## Deliberately out of scope this session

- Google Classroom roster import and grade publishing (course discovery is implemented; the wider Classroom scope and the write path are not).
- Object-storage backend (the local adapter remains, documented).
- Malware scanning, email transport, hosted PDF reports, platform settings
  persistence, support grants, notifications.
- Classes/students roster tables and the `/students` screen.

## Deployment and tunnel — VERIFIED

The local engine is reachable over HTTPS and the deployed frontend calls it.

| Layer | Verified state |
|---|---|
| Tailscale Funnel | `https://arthur-rip-zn02.tail06bb75.ts.net` → `http://127.0.0.1:8000`, Funnel on, single `/` rule |
| Engine binding | `127.0.0.1:8000` only (PID 7340 at verification); PostgreSQL not exposed |
| Public `/health` | `200` |
| Public `/ready` | `200`, `{"status":"ready","database":"ok"}` |
| CORS preflight | `200`, `Access-Control-Allow-Origin: https://aetrix.pages.dev`, credentials allowed |
| Deployed frontend | `https://aetrix.pages.dev` reachable and points at the Funnel origin |
| Stack status | `STATUS: CONNECTED`, all checks PASS |

Tailscale was installed but had **no serve config**; `START_AETRIX.bat` restored
the Funnel to the loopback engine. The production frontend already targets the
Funnel origin, so no redeploy was required and none was made.

- **Production storage — unchanged.** The local filesystem adapter remains, and
  is documented as not being production object storage.
- **Still not implemented from the wider Phase 4–6 brief:** Google Classroom
  roster import and grade publishing, workspace/account administration
  mutations, export/deletion workflows, and platform support grants. Course
  OAuth and discovery, bulk import, notifications and the assistant invitation
  surface are now implemented and tested.

## Git

No commit, push, pull request or merge was made. The working tree also contained
unrelated modifications before this session; they were left untouched.
