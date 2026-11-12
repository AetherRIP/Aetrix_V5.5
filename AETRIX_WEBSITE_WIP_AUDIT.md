# Aetrix V5.5 — Website Work-in-Progress Audit

**Audit date:** 8 November 2026  
**Scope:** the complete frontend website, its route/feature surface, and the backend contracts it depends on  
**Mode:** read-only product audit; no fixes implemented  
**Workspace:** `C:\Projects\Aetrix\Aetrix_V5.5-main`

> **What this report is.** A source- and runtime-based audit of what the website actually does. It does not accept
> marketing copy or planning documents as evidence of implementation. A feature is only marked **COMPLETE** when
> its visible contract and supporting code both exist and a relevant check passed. A screen that says “work in
> progress” is recorded as **UI ONLY** or **NOT IMPLEMENTED**, not as silently broken.

> **Amended 10 November 2026.** Google Classroom course discovery has since been implemented:
> OAuth with the read-only `classroom.courses.readonly` scope, encrypted token storage, refresh
> and revoked-access handling, and `POST /api/v1/classroom/sync`. The rows below that describe
> Classroom as unintegrated (A.2 bullet 7, screen 17, C27) are the 8 November audit record;
> roster import and grade publishing remain unimplemented.

---

## A. Executive summary

### A.1 What exists

The frontend has **33 route modules**: **30 page routes** plus the root, marketing and authenticated-app layouts.
It is a polished TanStack Start/React 19 application with:

- a complete marketing landing page, theme switcher, responsive navigation and product-preview mockup;
- Supabase authentication initiation (Google PKCE and email/password), a callback failure path, role-gated
  navigation for four account types, and account sign-out;
- a consistent authenticated shell with desktop rail, mobile tab bar, account sheet, skip link and reduced-motion
  handling;
- 17 authenticated screens that deliberately show “work in progress” states rather than invented data.

The Python/FastAPI engine has **55 HTTP operations** (3 health operations and 52 under `/api/v1`), **30 SQLAlchemy
tables** and **11 Alembic migrations**. It implements tenant lookup, exam/blueprint records, document ingestion and
mapping, correction-job lifecycle, provider credentials, contributor records, usage reads and audit writes.

### A.2 What does not exist

The central product does not exist yet:

- **marking** — the worker leases correction jobs but parks them with `PIPELINE_UNAVAILABLE`;
- **SymPy verification and marking results** — result tables exist, but no endpoint produces or exposes a mark;
- **review, override and approval** — no review canvas, no result API, no concurrency contract;
- **results, gradebook, reports, cohort intelligence** — screens are shells built on unavailable data;
- **most workspace APIs** — no dashboard, inbox, report, membership or settings endpoints;
- **object storage, signed uploads and malware scanning** — storage is local filesystem only;
- **Google Classroom integration, email/notifications, rate limiting and platform workspace/account**
  **administration APIs** — the provider fleet is the one admin area with real endpoints.

The real authentication identity and the engine’s identity are also not joined: Supabase issues a verified JWT, but
the engine only accepts a subject that already has a row in its own `users` table. There is no HTTP provisioning
flow to create that row. This is the most important integration blocker because it prevents an ordinary invited
user from using the authenticated data plane even after Google sign-in succeeds.

### A.3 Feature completion count

The numbered register in section C assesses **85 feature units**.

| Status | Count | Share |
|---|---:|---:|
| **COMPLETE** | 6 | 7.1% |
| **PARTIALLY IMPLEMENTED** | 16 | 18.8% |
| **UI ONLY** | 24 | 28.2% |
| **PLACEHOLDER** | 1 | 1.2% |
| **BROKEN** | 1 | 1.2% |
| **NOT IMPLEMENTED** | 33 | 38.8% |
| **BLOCKED** | 3 | 3.5% |
| **NOT TESTED** | 1 | 1.2% |
| **Total** | **85** | **100%** |

**Unfinished feature units: 79 of 85 (92.9%).**

The simple completion estimate is **7.1% fully complete**. Counting each partial implementation as half complete gives
**16.5%** (`(6 + 16/2) / 85`). This is a feature-count measure, not a production-readiness score. The visible shell is
much further ahead than the data plane: 30 page routes exist, but only 18 of the 54 numbered screens in
`docs/design/SCREEN_INVENTORY.md` are represented at all, and none of the core marking-data screens is functional.

The application has 30 page routes: 18 correspond to a numbered screen, and 12 do not — the workspace hub, the five
assistant pages, platform overview, the Gemini fleet, integrations, platform settings, the auth callback and analytics.
**Planned-screen intent coverage is 18/54 (33.3%)**, and none of those 18 renders live tenant data.

### A.4 Top ten issues

1. **No bridge from Supabase identity to an engine user/tenant.** The frontend authorizes from
   `app_metadata.aetrix_role`; the engine resolves a pre-existing `users` row by JWT subject and tenant. There is no
   sign-up, invite, provisioning or tenant-sync endpoint. Real invited users can sign in and still receive `403`.
2. **Marking is explicitly unimplemented.** `UnavailablePipeline.run()` raises; the runner parks the job. No mark,
   confidence, evidence or review state can be produced.
3. **No result or review API.** Existing result tables have no read/override/approve routes, so submission review,
   results, gradebook and reports cannot be connected.
4. **Frontend service contracts do not match the backend.** Assignment naming/fields, submission fields, role
   vocabulary and missing inbox/report/submission-list routes diverge. The service module is also unused by screens.
5. **The core marking workflow is absent.** There is no assignment editor, scheme upload/review, submissions table,
   batch upload, review canvas, class report or approval flow.
6. **No production file path.** Storage is local-only; there are no signed upload/download URLs, R2/Supabase Storage
   adapter, virus scan or durable file delivery.
7. **No workspace/Classroom administration.** Classes, students, membership, invitations, allocations, Classroom OAuth,
   roster sync and grade publishing have no endpoints or real screens.
8. **Platform administration is mostly a directory of placeholders.** Workspace, account, audit, settings, support
   grant and queue/DLQ read APIs do not exist.
9. **Verification is incomplete and not fully green.** Backend unit tests, Ruff, TypeScript and the production build
   pass, but Playwright has **1 failure** and 2 skips; backend integration tests cannot safely run without an isolated
   database, and live OAuth/provider flows were not exercised.
10. **Several public claims are false or stale.** Sign-in *is* enabled, the backend is Python/FastAPI rather than a
    Worker, submissions are not stored in R2, and provider configuration *is* exposed over HTTP. These are trust
    defects on a product whose marketing promises honest states.

### A.5 Material non-findings

- No cross-tenant data leak was found in static review. Tenant scoping is present in repository queries and is derived
  from the principal, not a request body. It is **not fully proven** here because the integration suite was not run.
- No fabricated dashboard metrics were found on authenticated screens; unavailable values are em dashes. The marketing
  product preview is synthetic and labelled as such in its surrounding section copy.
- No broken internal marketing links were found: the Playwright link-and-anchor test passed.
- No route-level 404 was found for pre-rendered nested routes: the auth and responsive suites loaded every tested route.

### A.6 Completion blockers

1. **Identity/tenant provisioning and role mapping** — blocks every authenticated API read and write.
2. **Marking pipeline and result persistence** — blocks the product’s reason to exist.
3. **API contract reconciliation plus missing workspace endpoints** — blocks wiring the visible screens.
4. **Object storage and signed file delivery** — blocks uploads, page viewing and reports.
5. **Isolated test database and live service credentials** — blocks trustworthy integration, OAuth and provider tests.
6. **Product decisions still marked RECOMMENDED** — the 54-screen inventory, 7-tab settings model, roles and support
   grants remain proposals, not frozen contracts.

---

## B. Page-by-page audit

All 30 page routes are listed. “E2E” records what the browser suites actually exercised; a route shell appearing is not
evidence that its data workflow works.

| # | Route | What the page is for | What actually works | Gaps and defects | Evidence | Status |
|---:|---|---|---|---|---|---|
| 1 | `/` | Public product landing page | Hero, workflow, features, security and CTA sections render; responsive layout, theme persistence, internal anchors, tabs, reduced-motion and axe checks pass | Three claims are stale or false (sign-in disabled, Worker-side key handling, R2 storage); no standalone features/pricing/security/FAQ/contact/docs/legal/status/changelog pages; hero preview relies on nearby copy to disclose synthetic data | `frontend/src/routes/_marketing.index.tsx`; `components/site/*`; `marketing.spec.ts` passed | **PARTIALLY IMPLEMENTED** |
| 2 | `/sign-in` | Google/email sign-in entry | Real Supabase PKCE authorize URL, email/password form, no self-serve signup copy, access-status panel, theme persistence; auth tests pass | Workspace provisioning labelled WIP; no signup, password reset, email verification or MFA; no invite acceptance; full Google consent not tested | `_marketing.sign-in.tsx`; `auth.spec.ts` passed; `SCREEN_INVENTORY` 15–19 | **PARTIALLY IMPLEMENTED** |
| 3 | `/auth/callback` | OAuth redirect landing | Exchanges session through Supabase client; cancelled/missing code produces “Sign-in did not complete” and no session; tested | Successful Google round trip not exercised; engine user row may not exist after success, so access can still fail at the API | `auth.callback.tsx`; `auth.spec.ts` passed; `backend/app/api/deps.py` | **PARTIALLY IMPLEMENTED** |
| 4 | `/dashboard` | Teacher workspace home | Role-aware greeting and shell; four metrics show em dashes; actions link to queue/workspace; session/health panels render | No dashboard API; service calls absent; “engine not deployed/no public API” copy is stale relative to the hosted Tailscale endpoint; no recent activity, workload or exceptions | `_app.dashboard.tsx`; `HubStats.tsx`; `HubHealth.tsx` | **UI ONLY** |
| 5 | `/workspace` | Workspace picker / membership context | Explains tenant, role and isolation model | No workspace list, selection, creation or role data; hard-coded “Not connected”; the frontend service exists but is unused | `_app.workspace.tsx`; `lib/services.ts`; `SCREEN_INVENTORY` 20–21 | **UI ONLY** |
| 6 | `/inbox` | Items needing a human | Honest explanation that the pipeline produces no inbox events; disabled filter tabs | No inbox endpoint, filters, counts, read/snooze actions; no empty-vs-error distinction because no request is made | `_app.inbox.tsx`; no `/workspaces/{id}/inbox` backend route | **UI ONLY** |
| 7 | `/queue` | Marking queue | Explains job state machine and parking behaviour; structural table with no rows | No `queueService` call; no job rows, filters, leasing action or progress; worker pipeline cannot produce work | `_app.queue.tsx`; `backend/app/jobs/pipeline.py`; `SCREEN_INVENTORY` 33 | **UI ONLY** |
| 8 | `/assignments` | Assignment list | Structural table and disabled “New assignment” action | No list request; no create/edit; endpoint exists but response schema does not match frontend `Assignment`; no search/filter | `_app.assignments.tsx`; `lib/api/types.ts`; `backend/app/schemas/api.py` | **UI ONLY** |
| 9 | `/assignments/$assignmentId` | Assignment overview | Route and record header survive refresh; three section tabs exist but are disabled | All content absent; assignments API can return a record, but frontend model expects fields the backend does not provide; no scheme, submissions, marking or settings tabs | `_app.assignments.$assignmentId.tsx`; `crud` route evidence in backend `exams.py` | **UI ONLY** |
| 10 | `/submissions/$submissionId` | Submission/review record | Record header and honest “correction review blocked twice” state; six empty page frames explicitly labelled non-fabricated | No marks, evidence, pages, review decisions or comments; endpoint exists but no result/review pipeline; page is not a usable review canvas | `_app.submissions.$submissionId.tsx`; `PIPELINE_UNAVAILABLE` | **PLACEHOLDER** |
| 11 | `/reports` | Cross-assignment reports | Explains intended report contents and why no chart exists | No report API, result data, filters, charts, export or insufficient-data state; no class report/PDF | `_app.reports.tsx`; no report backend route | **UI ONLY** |
| 12 | `/settings` | Account/session/workspace settings | Live Supabase profile, verified status, provider, account dates, user id; theme switch; sign-out; tested | Only account settings exist; no workspace general/branding/academic/corrections/notifications/retention tabs; no save, danger zone, sessions or notifications | `_app.settings.tsx`; `roles.spec.ts` sign-out passed | **PARTIALLY IMPLEMENTED** |
| 13 | `/students` | Classes and students | Two structural tables; explicit “no rosters” empty states | No class/student endpoints, roster import, student profile, counts or filters; no class allocation UI | `_app.students.tsx`; no class/student table in engine schema | **UI ONLY** |
| 14 | `/gradebook` | Marks across assignments | Metrics strip with blank values; empty marks table; explains missing pipeline | No marks, grade matrix, distribution, filters or export; no results API | `_app.gradebook.tsx`; `SCREEN_INVENTORY` 36 | **UI ONLY** |
| 15 | `/analytics` | Question/cohort analytics | Empty metrics and table; states that analytics requires marking | No cohort endpoint or aggregation; no date/class/assignment filters, charts or export | `_app.analytics.tsx`; `SCREEN_INVENTORY` 42 | **UI ONLY** |
| 16 | `/assistants` | Assistant roster and permissions | Capability explanation and structural table | No membership/list/invite endpoint; no assignment of classes or submissions; “available” capabilities are not backed by API enforcement tests | `_app.assistants.tsx`; no membership table/route | **UI ONLY** |
| 17 | `/classroom` | Google Classroom integration | Four-step conceptual flow and explicit “not integrated” state | No OAuth connect, token store, roster sync, allocation or grade publish; no external configuration | `_app.classroom.tsx`; no Classroom backend module | **UI ONLY** |
| 18 | `/platform` | Operator overview | Separate platform identity, role-aware navigation; empty platform ledger | No platform aggregate API; service status and provider copy are static; “no public deployment” is stale | `_app.platform.index.tsx`; no platform workspace/account API | **UI ONLY** |
| 19 | `/platform/workspaces` | Workspace directory/allocation | Allocation rules and empty table | No workspace directory, create/suspend, allocation or release endpoint; no operator action | `_app.platform.workspaces.tsx`; `API_DESIGN` §9 | **UI ONLY** |
| 20 | `/platform/users` | Account directory/roles | Correctly refuses to expose a role-writing control; explains identity-provider ownership | No account list; no invite/disable/remove; role changes only in Supabase; no operational support flow | `_app.platform.users.tsx`; `roles.spec.ts` passed | **UI ONLY** |
| 21 | `/platform/health` | Service health | Real `GET /health` and `GET /ready` client path; distinguishes unconfigured, unreachable and ready; check-again control; worker and provider explicitly not checked | No queue depth, DLQ, job loss, error-rate or provider health; current UI cannot be fully verified without the engine origin; health E2E skipped | `_app.platform.health.tsx`; `health.spec.ts` skipped 2 tests | **PARTIALLY IMPLEMENTED** |
| 22 | `/platform/audit` | Platform audit | Explains append-only audit storage; structural table | No audit read/search/export API; no filters or actor/subject detail; platform-level reads absent | `_app.platform.audit.tsx`; `API_DESIGN` §9 | **UI ONLY** |
| 23 | `/platform/gemini` | Provider fleet, keys, quota and contributors | Substantial real client (`gemini.ts`) and tabbed UI; API calls, key CRUD, contribution flows and honest quota confidence types | No live test; current engine is unreachable/401 in the E2E run; no route-driven server test; one Playwright assertion fails; no workspace-scoped credentials screen | `_app.platform.gemini.tsx`; `lib/api/gemini.ts`; `roles.spec.ts` failure | **PARTIALLY IMPLEMENTED** |
| 24 | `/platform/integrations` | Provider configuration summary | Links to Gemini fleet; explains one adapter and credential secrecy | Claims provider configuration is “not exposed over HTTP”, contradicting real `/api/v1/admin/providers` routes; no rotate/test controls here | `_app.platform.integrations.tsx`; `admin_providers.py` | **BROKEN** |
| 25 | `/platform/settings` | Platform defaults | Lists intended defaults and states no storage exists | No form, API, persistence or validation; no platform settings table | `_app.platform.settings.tsx`; no table in `models.py` | **UI ONLY** |
| 26 | `/assistant` | Assistant home | Personal overview, scope explanation, links to queue/tasks/inbox | No assigned-work API; all stats and tables empty; inbox and queue are themselves non-functional | `_app.assistant.index.tsx`; `roles.spec.ts` route content passed | **UI ONLY** |
| 27 | `/assistant/classes` | Assigned classes | Explains assignment-not-workspace scope; empty table | No membership/assignment table or endpoint; teacher cannot assign classes through UI | `_app.assistant.classes.tsx`; no `classes` table | **UI ONLY** |
| 28 | `/assistant/tasks` | Assistant task list | Task rules and empty structural table | No task table/endpoint; no create, complete, reassign or due-date flow | `_app.assistant.tasks.tsx`; no task backend | **UI ONLY** |
| 29 | `/assistant/work` | Assistant marking workspace | Explains how review would work; no fake marks | No script, page viewer, marks, comments or save path; pipeline unavailable | `_app.assistant.work.tsx`; `PIPELINE_UNAVAILABLE` | **UI ONLY** |
| 30 | `/assistant/progress` | Personal throughput | Defines review metrics and shows blank/em-dash values | No review event history or aggregation; no completion progress that can be measured | `_app.assistant.progress.tsx`; no review-event API | **UI ONLY** |

### B.1 Missing public/auth screens

The 54-screen inventory is not fully routed. The public site has only `/` and `/sign-in`; there is no custom 404/500
route. Missing public screens are features, pricing, use cases, security/privacy, FAQ, contact, docs index/article,
legal pages, status and changelog. Missing identity screens are signup, verify email, forgot/reset, MFA, invite
acceptance, workspace picker, create workspace, onboarding checklist and device/session management.

### B.2 Navigation and shell assessment

The shell is one of the strongest parts of the build. Role-specific navigation is real and tested: platform
operators see only platform destinations; teachers see the teaching rail; assistants see personal work and cannot
open teacher administration. The owner sees all three areas. The rail collapses, remembers its state, supports
keyboard focus, and collapses to a tested mobile tab bar. The workspace indicator is correctly marked **WIP** rather
than fabricated.

The shell does not provide global search, notifications, job activity, workspace switching, command palette or the
planned help/shortcut surface. The top bar is identity/page context only.

---
## C. Incomplete-feature register

**Counting rule.** This register assesses 85 feature units, including six controls that are complete so the
denominator is explicit. The 79 unfinished units are: 16 partially implemented, 24 UI only, 1 placeholder, 1 broken,
33 not implemented, 3 blocked and 1 not tested. Severity means product impact if the feature is used as advertised:
**Critical** blocks the core service; **High** blocks a primary workflow; **Medium** blocks a secondary workflow or
administration task; **Low** is public-site/content completeness.

### C.1 Public site, authentication and account (17)

| ID | Feature | Route | Status | Expected behaviour | Actual behaviour | Missing work / dependencies | Severity and evidence |
|---|---|---|---|---|---|---|---|
| P01 | Landing page, marketing shell, theme, responsive navigation | `/` | **COMPLETE** | A responsive product landing page with working navigation, theme and product preview | Renders and passes route, responsive, theme, tab, reduced-motion and axe checks | None for the page itself; broader public-site completeness is P04–P06 | Low. `_marketing.index.tsx`, `components/site/*`; 150-passing Playwright run |
| P02 | Accuracy of public product claims | `/` | **BROKEN** | Every claim describes the shipped architecture and feature state | CTA says sign-in is disabled; security copy says key handling happens in a Worker; workflow says submissions live in R2. In reality sign-in is enabled, the engine is Python/FastAPI, and storage is local filesystem | Rewrite three components against ADR-001 and the actual provider/storage boundary | High. `components/site/FinalCta.tsx`, `Security.tsx`, `Workflow.tsx`; `backend/app/storage/__init__.py` |
| P03 | Marketing product-preview data | `/` | **PLACEHOLDER** | Any demonstration figures are unmistakably synthetic | `ProductPreview` uses `lib/demo-data.ts`; the section note says every figure is synthetic, but the hero preview itself is not individually labelled | Keep demo data out of real screens; consider an in-context “synthetic” badge on the preview | Low. `_marketing.index.tsx`, `components/product/*`, `lib/demo-data.ts` |
| P04 | Features, pricing, use cases and FAQ pages | planned public routes | **NOT IMPLEMENTED** | Dedicated explanatory and commercial pages, including no-plans and insufficient-data states | Only one landing page; these are sections or absent | Product positioning, pricing decisions, copy, routes, metadata and states | Low. `docs/design/SCREEN_INVENTORY.md` screens 2–4, 6 |
| P05 | Security/privacy trust page, legal pages and contact | planned public routes | **NOT IMPLEMENTED** | Trust page with data location, retention, sub-processors and DPA; versioned terms/privacy/cookies; contact form with sent/error states | A marketing security section exists, but there is no standalone trust page, legal document route or contact workflow | Legal review, document versioning, form backend and retention decisions | Medium. `SCREEN_INVENTORY` 5, 7, 10; `docs/security/DATA_PRIVACY.md` |
| P06 | Docs/help centre, status and changelog | planned public routes | **NOT IMPLEMENTED** | Searchable help, article pages, component status/incidents and release notes | No routes; repository documentation is not exposed as product help | CMS or content pipeline, search, status source, release process | Low. `SCREEN_INVENTORY` 8–9, 11–12 |
| P07 | Custom 404/500, permission-denied and session interstitials | global | **NOT IMPLEMENTED** | Explain recovery, route back, preserve deep links and unsaved work; permission-denied distinct from 404 | Static hosts may return the site document for unknown routes; no custom error route; role refusal is an in-shell state, not a dedicated recovery page | Error boundary, custom 404/500 output, draft-preserving session interlude | Medium. `SCREEN_INVENTORY` 13 and extra states; `_app.tsx` role branch |
| P08 | Google/email sign-in initiation and callback failure handling | `/sign-in`, `/auth/callback` | **COMPLETE** | Real PKCE authorize request; email/password path; cancelled or code-less callback fails clearly; no session invented | Browser tests verify the provider host, callback, PKCE S256 challenge, POST form, error handling and absence of a stored session | Successful Google consent belongs to P09, not this item | High. `frontend/tests/auth.spec.ts` passed |
| P09 | Full Google OAuth round trip to an operational account | `/sign-in` → provider → `/auth/callback` → app | **NOT TESTED** | A real invited Google account signs in, receives a session, reaches its role home and uses the API | Tests seed a synthetic Supabase session; no interactive Google session was performed | Owner test account, allow-listed callback, engine user row, live browser run | Critical. Test comments and `roles.spec.ts` seeded-session helper |
| P10 | Backend user/tenant provisioning from authentication | sign-in/API boundary | **NOT IMPLEMENTED** | First successful invitation maps the verified subject to exactly one tenant and role, or returns a deliberate invite-required state | Engine looks up an existing `users` row; `create-user` CLI is the only creation path; no HTTP provisioning, invite or tenant-sync endpoint | Invitation model, provisioning transaction, idempotency, role mapping, audit event, cross-tenant tests | Critical. `backend/app/api/deps.py`; `backend/app/cli.py`; `docs/architecture/API_DESIGN.md` §3–4 |
| P11 | Role claims, navigation and route guards | authenticated shell | **COMPLETE** | Role comes only from identity-provider metadata; each role gets its own destinations; forbidden routes are refused or redirected | `app_metadata` is read; `user_metadata` cannot promote; operator, teacher and assistant rails and redirects pass browser tests | Engine role vocabulary and enforcement still need alignment; UI authorization is not the security boundary | High. `lib/auth/roles.ts`, `_app.tsx`; `roles.spec.ts` passed |
| P12 | Account profile, theme and sign-out | `/settings` | **COMPLETE** | Show verified identity, provider, account age and current session; persist theme; sign out clears the local session | These work from the Supabase session and pass browser tests | Workspace settings and session/device administration are separate items | Medium. `_app.settings.tsx`; `roles.spec.ts` |
| P13 | Signup, email verification, password reset and MFA | planned auth routes | **NOT IMPLEMENTED** | Controlled account creation, email confirmation, recovery tokens and step-up MFA | Explicitly no self-serve signup; no verify/reset/MFA routes; email/password can be used for pre-created accounts only | Identity-provider configuration, email delivery, recovery templates, MFA policy | High. `_marketing.sign-in.tsx`; `SCREEN_INVENTORY` 14, 16–18 |
| P14 | Invite acceptance, workspace picker, create workspace and onboarding | planned onboarding routes | **NOT IMPLEMENTED** | Single-use invite acceptance; membership cards; create first workspace; resumable checklist | Workspace page is explanatory prose; no invite token, picker, creation or onboarding state | Membership/invitation tables, email, tenancy creation, role assignment, checklist persistence | High. `_app.workspace.tsx`; `SCREEN_INVENTORY` 19–22 |
| P15 | Device and session manager | planned settings screen | **NOT IMPLEMENTED** | List active sessions/devices, revoke one, sign out everywhere | Only local sign-out exists | Session inventory API, revocation propagation, UI and audit | Medium. `SCREEN_INVENTORY` 23 |
| P16 | Session-expiry recovery and draft preservation | global auth | **PARTIALLY IMPLEMENTED** | Preserve intended URL and any unsaved override through re-authentication without overwriting concurrent work | Intended URL is stored in `sessionStorage`; no draft model, autosave, recovery or conflict rule | Server or local draft decision, debounce/replay policy, version conflict handling and tests | High. `AuthProvider.tsx`; `docs/audit/UX_PRODUCT_GAP_ANALYSIS.md` UX-01 |
| P17 | Responsive authenticated shell and reduced motion | app shell | **COMPLETE** | Rail on desktop, tab bar on phone, no horizontal overflow, keyboard operation and motion reduction | Browser tests cover 360/375/390/412/768/1024/1440/1920 widths, collapse persistence and reduced motion | Global search, job indicator and notifications are not part of this item | Medium. `AppShell.tsx`; `responsive.spec.ts`, `roles.spec.ts` passed |

### C.2 Core marking workspace (34)

| ID | Feature | Route | Status | Expected behaviour | Actual behaviour | Missing work / dependencies | Severity and evidence |
|---|---|---|---|---|---|---|---|
| C01 | Dashboard live ledger, exceptions and workload | `/dashboard` | **UI ONLY** | Real counts for submissions, marking, review and completion; exception list; recent activity | Four em-dash metrics and static health panels; no API request | Dashboard endpoint, query aggregation, loading/empty/error states, service wiring | High. `_app.dashboard.tsx`, `HubStats.tsx`, `lib/services.ts` |
| C02 | Inbox list, filters and actions | `/inbox` | **UI ONLY** | Review/failure events, type filters, age, mark-read and navigation to the record | Disabled tabs and explanation; no endpoint or request | Inbox event model/API, filters, counts, read state, deep links | High. `_app.inbox.tsx`; no inbox route in backend |
| C03 | Assignment list and filtering | `/assignments` | **UI ONLY** | Table with exam, state, submissions, blueprint, owner; search and filters | Empty table and disabled create button; no service call | List wiring, schema alignment, filters, loading/empty/error states | High. `_app.assignments.tsx`; `backend/app/api/v1/exams.py` |
| C04 | Assignment create/edit workflow | `/assignments/new`, edit route | **NOT IMPLEMENTED** | Metadata, exam, cohort, deadlines, defaults, validation and draft/publish states | No create/edit route; button disabled | Assignment editor, form validation, POST/PATCH endpoints, optimistic/version behavior | High. `SCREEN_INVENTORY` 28; `API_DESIGN` §6 |
| C05 | Assignment overview with state strip and next action | `/assignments/$id` | **UI ONLY** | Status, progress, blockers, tabbed submissions/scheme/marking, primary next action | Record header plus disabled tabs and prose; no data request | Detail wiring, backend field alignment, tabs, actions and state transitions | High. `_app.assignments.$assignmentId.tsx` |
| C06 | Scheme upload, page preview and extraction progress | assignment scheme route | **NOT IMPLEMENTED** | Upload PDF, preview pages, show extraction progress and mismatches | No UI route; backend document/blueprint endpoints exist but are not connected | Upload/storage path, progress contract, mismatch UI, error recovery | High. `SCREEN_INVENTORY` 29; `backend/app/api/v1/documents.py` |
| C07 | Scheme review, max marks, M/A/B and lock | assignment scheme review route | **NOT IMPLEMENTED** | Human confirms question structure before marking; lock fails on unresolved conflicts | No UI; approval endpoint exists, but no review canvas or conflict workflow | Question table, editing/approval API, version guard, conflict states, lock enforcement | Critical. `SCREEN_INVENTORY` 30; `API_DESIGN` §6; `REQUIREMENT_TRACEABILITY` R10 |
| C08 | Submissions table and bulk selection | assignment submissions route | **NOT IMPLEMENTED** | Rows per student with status, marks and assignee; bulk selection | No route, endpoint or table; services define a list that backend does not expose | Schema/API, pagination, filters, selection and bulk actions | High. `lib/services.ts`; `API_DESIGN` §7 |

| C09 | Bulk submission upload and ingest | assignment submissions route | **NOT IMPLEMENTED** | Drag-and-drop multipart upload with per-file validation, resumable progress, duplicate rejection and rejection reasons | No upload surface anywhere in the application. The engine has a single-submission `POST /submissions`, and no page calls it | Upload UI, multipart/chunking decision, per-file validation feedback, duplicate detection, ingest progress, storage write | Critical. `SCREEN_INVENTORY` 32; `backend/app/api/v1/exams.py`; no client call in `frontend/src` |
| C10 | Marking queue with next-script and filters | `/queue` | **UI ONLY** | Ordered queue, one-at-a-time card, keyboard advance, filters for state and assignee, paused/circuit-open states | Header, empty table with the correct five columns and a truthful explanation that the pipeline parks jobs as `PIPELINE_UNAVAILABLE`; no request is made | Queue query wiring, ordering and pagination, keyboard model, pause/resume, circuit-open state | High. `_app.queue.tsx`; `lib/services.ts` correction service unused |
| C11 | Review canvas: page, marks, explanation, override | submission review route | **NOT IMPLEMENTED** | PDF pane beside question-level marks, engine explanation, confidence, comment and reasoned override with actor and timestamp | Nothing exists; the submission screen explicitly says it will show nothing until marking exists | PDF renderer, per-question mark model, override endpoint with reason/actor/time, conflict and locked states, keyboard advance | Critical. `SCREEN_INVENTORY` 34; `REQUIREMENT_TRACEABILITY` R05/R06; `_app.submissions.$submissionId.tsx` |
| C12 | Submission detail record, history and files | `/submissions/$submissionId` | **UI ONLY** | Real record: owner, assignment, page count, quality report, marks, history, audit trail, file list | Record header echoes the raw URL parameter and shows a "Not loaded" chip; six empty page frames and prose. No fetch, and the route is reachable with any arbitrary id | Detail fetch, 404 handling for unknown or foreign ids, page image endpoint, history and file panels | High. `_app.submissions.$submissionId.tsx`; `unavailable` state correctly used for the marks |
| C13 | Grade matrix and cycle summary | `/gradebook` | **UI ONLY** | Pivot of students against assignments with totals, distribution, outliers and a provisional/approved marker | Four em-dash metrics and an empty five-column table; explanation that a gradebook needs marks | Matrix endpoint, aggregation, distribution rendering, export, empty and insufficient-data states | High. `_app.gradebook.tsx`; `API_DESIGN` §8; `REQUIREMENT_TRACEABILITY` R32 (no endpoint) |
| C14 | Printable class report PDF | reports area | **BLOCKED** | Reproducible, printable per-class report with a PDF preview, download and optional Classroom attachment | Not started. The requirement is blocked upstream: the document host is undecided, and a browser-side PDF would not be reproducible | Hosting decision for PDF generation, template, reproducibility guarantee, generation states, attachment path | High. `SCREEN_INVENTORY` 37; `REQUIREMENT_TRACEABILITY` R31 "host undecided — ARC-04, COST-01" |
| C15 | Reports hub, filters and export | `/reports` | **UI ONLY** | Cross-assignment analysis with filters, charts, evidence export and an insufficient-data state | A list of what a report *will* contain; no filters, charts, queries or export | Result endpoints, aggregation queries, chart components, export format, insufficient-data branch | High. `_app.reports.tsx`; `API_DESIGN` has no reports route |
| C16 | Classes list and class detail | `/students` (panels) | **UI ONLY** | Class table with year group, roster size and allocation, plus a detail view with roster and performance | One empty four-column table with an explanatory note; no class route, detail page or query | Class endpoints, allocation model surfaced read-only, detail route, roster and performance panels | Medium. `_app.students.tsx`; `SCREEN_INVENTORY` 38 |
| C17 | Student roster list | `/students` | **UI ONLY** | Imported roster with identifiers, submission counts and last activity, plus imported/empty states | Empty table labelled "students in the allocated classes"; text says rosters are not imported | Roster API, identifier mapping, counts, pagination, empty and not-imported states | Medium. `_app.students.tsx`; `SCREEN_INVENTORY` 39 |
| C18 | Student profile with history and trend | student detail route | **NOT IMPLEMENTED** | One student's submissions, marks over time, notes and a no-results state | No route, endpoint or component | Profile route, history query, trend chart, notes model, privacy scoping to the workspace | Medium. `SCREEN_INVENTORY` 40 |
| C19 | CSV bulk import with dry run | import route | **NOT IMPLEMENTED** | Template download, column mapping, dry-run preview, row-level errors, partial commit | Absent. Nothing in the frontend or the engine accepts a roster or marks CSV | Template, parser, mapping UI, dry-run endpoint, transaction strategy, error report | Medium. `SCREEN_INVENTORY` 41 |
| C20 | Cohort analytics and question-level performance | `/analytics` | **UI ONLY** | Mean, facility, discrimination, flagged questions and completion, derived from real marks | Four em-dash metrics and an empty five-column table; states that analytics cannot precede marking | Analytics queries, aggregation, chart components, flag thresholds, insufficient-data state | Medium. `_app.analytics.tsx`; cohort intelligence listed unimplemented in engine status |
| C21 | Assistant membership management | `/assistants` | **UI ONLY** | List assistants with assigned classes, queue depth and state; invite, suspend and remove actions | Empty table, a capability list that correctly separates allowed from refused actions, and no invite control | Membership tables and endpoints, invitation email, role assignment, suspension, audit events | High. `_app.assistants.tsx`; `SCREEN_INVENTORY` 44; no membership table in `models.py` |
| C22 | Assistant home and workload | `/assistant` | **UI ONLY** | Assigned classes, awaiting review, completed this week, overdue, and the newest assigned submissions | Em-dash stats, an empty table and scope prose built on `useAuth` only | Scoped queries for assigned work, workload counts, deep links into the queue | Medium. `_app.assistant.index.tsx` |
| C23 | Assistant assigned classes | `/assistant/classes` | **UI ONLY** | Only the classes the teacher assigned, with student and open-submission counts | Empty table plus a clear statement that class assignment is not implemented and scope is never inferred | Assignment-of-class model, scoped query, withdrawal semantics, empty state | Medium. `_app.assistant.classes.tsx` |
| C24 | Assistant marking workspace | `/assistant/work` | **UI ONLY** | Page viewer beside the marking surface, review notes written against the assistant's identity | No script can be opened; a three-item capability list marks the page viewer pending and the marking surface blocked | Everything in C11 plus assistant-scoped permissions and review attribution | High. `_app.assistant.work.tsx`; depends on C11 |
| C25 | Assistant task list | `/assistant/tasks` | **UI ONLY** | Teacher-assigned tasks pointing at a submission or class, with due dates and completion | Em-dash stats, empty eight-column table, and an explicit note that no task table exists and nothing is stored in `localStorage` | Task model and endpoints, assignment by teacher, completion recording, due-date handling | Medium. `_app.assistant.tasks.tsx` |
| C26 | Assistant throughput and progress | `/assistant/progress` | **UI ONLY** | Reviews per week and term, median time per script, flags, and per-class breakdown | Em-dash metrics and an empty table; the screen states that a plausible progress ring would be a claim no system made | Review-event recording, timing capture, aggregation, per-class breakdown, empty state | Medium. `_app.assistant.progress.tsx` |

| C27 | Google Classroom connection, course selection and roster sync | `/classroom` | **BLOCKED** | OAuth consent, course allow-list, roster import, token health and an explicit disconnected state | Three-item capability list and a four-step explanation, with no connect control. Blocked on a Google OAuth scope, a server-side token store and an engine sync route — none of the three exists | Scope approval, token encryption and refresh, sync job, course allow-list, disconnected/expired/forbidden states | High. `_app.classroom.tsx`; `SCREEN_INVENTORY` 48; `REQUIREMENT_TRACEABILITY` R29 (optional at every step) |
| C28 | Workspace hub: membership, selection and switching | `/workspace` | **UI ONLY** | List memberships with role, select a workspace, scope every screen, handle a single-membership and an empty account | Explanatory prose and a definition list describing selection, role and isolation; no membership read, no selector | Membership endpoint, selection persistence, tenant scoping of every downstream read, empty state, safe switching | High. `_app.workspace.tsx`; `REQUIREMENT_TRACEABILITY` R46 (workspace switching is a gap) |
| C29 | Workspace settings: general, corrections, notifications, retention | `/settings` | **NOT IMPLEMENTED** | Seven settings tabs with saved and unsaved-changes states, retention policy and marking defaults | Profile, appearance and session panels are real; the settings panel is a `wip` statement that roles and policy are server-side and not configurable here | Settings schema, read/write endpoints, validation, optimistic-save and conflict handling, audit of policy changes | High. `_app.settings.tsx`; `SCREEN_INVENTORY` 45 |
| C30 | Global search and command palette | app shell | **NOT IMPLEMENTED** | One field to reach assignments, submissions and students across the current workspace, with keyboard invocation and empty results | The shell has no search affordance at all; navigation is rail- and tab-based only | Search index or query endpoint, command registry, keyboard shortcut, result ranking, no-results and forbidden-scope states | Medium. `AppShell.tsx`; `SCREEN_INVENTORY` "screens the brief did not list" |
| C31 | Notifications and out-of-tab job progress | app shell | **NOT IMPLEMENTED** | Bell with unread count, notification preferences, and progress that survives a closed tab | No notification model, no shell indicator, no email delivery. The requirement's own trace says progress without a tab is deferred with the Durable Object work | Notification table and endpoints, email provider, preferences, shell badge, progress channel | High. `REQUIREMENT_TRACEABILITY` R28 (weak), R38 (gap: no endpoints, no prefs table) |
| C32 | Workspace activity and audit view | audit route | **NOT IMPLEMENTED** | Filterable log of approvals, overrides, job transitions and membership changes, exportable, with permission-denied distinct from empty | Only the *platform* audit screen exists, and it is a `wip` shell; there is no workspace-scoped audit route | Audit read endpoint scoped to tenant, filters, export, permission-denied state | Medium. `SCREEN_INVENTORY` 43; `REQUIREMENT_TRACEABILITY` R35 |
| C33 | Job detail, cancel and retry actions | queue / job drawer | **NOT IMPLEMENTED** | Inspect one job's attempts and error classification, cancel without leaving a partial result, retry when the classification allows | The backend implements list, detail, cancel and retry, and the state machine classifies retryable errors; no screen calls any of them | Job drawer, attempt history, error classification display, cancel/retry wiring, polling or stream, optimistic state | High. `backend/app/api/v1/corrections.py` (5 operations); `lib/services.ts` unused |
| C34 | Help centre and keyboard shortcuts sheet | help route | **NOT IMPLEMENTED** | Searchable help, a `?` shortcut overlay and a contact path inside the product | No help route and no shortcut model; the only documentation is in the repository | Help content pipeline, shortcut registry, overlay, contact handoff | Low. `SCREEN_INVENTORY` 50 |

### C.3 Platform administration and provider fleet (16)

| ID | Feature | Route | Status | Expected behaviour | Actual behaviour | Missing work / dependencies | Severity and evidence |
|---|---|---|---|---|---|---|---|
| A01 | Platform overview ledger | `/platform` | **UI ONLY** | Workspace, teacher, assistant and allocation counts, service status and recent operator activity | Em-dash stats, capability lists and a truthful note that the engine exposes tenant-scoped routes only; no request | Platform aggregation endpoint, counts query, service state feed, activity list | Medium. `_app.platform.index.tsx` |
| A02 | Workspace directory and class allocation | `/platform/workspaces` | **UI ONLY** | Operator table of workspaces with teacher, assistants, allocated classes and state; allocate, release and reassign actions | Empty five-column table plus the allocation rules as prose. No endpoint and therefore no action buttons | Workspace/assignment-of-class endpoints, one-active-allocation constraint surfaced, confirm and audit on reassignment | High. `_app.platform.workspaces.tsx`; `MULTI_TENANCY.md` |
| A03 | Account directory and role administration | `/platform/users` | **UI ONLY** | List accounts across workspaces with role and status; grant or revoke roles with audit | Empty table; role list explains that assignment happens only in the identity provider and that self-service elevation is refused | Account list endpoint, role write path with audit, suspension, invitation state | High. `_app.platform.users.tsx` |
| A04 | Platform health and queues | `/platform/health` | **PARTIALLY IMPLEMENTED** | Live API, worker, database and provider state; queue depth, dead-letter count, error rate, incident state | Real: `/health` and `/ready` are called in-browser, with latency, distinct unavailable vs error handling, a re-check control and a compiled-in endpoint host. Missing: worker state is hard-coded "Not checked", and there is no queue depth, DLQ, error rate or incident view | Worker heartbeat, queue metrics endpoint, DLQ inspection, error-rate aggregation, degraded/outage rendering | Medium. `_app.platform.health.tsx`; `SCREEN_INVENTORY` 52 |
| A05 | Platform audit log | `/platform/audit` | **UI ONLY** | Searchable, exportable platform event log with actor, action, workspace and subject | Empty five-column table; states that `audit_events`, `job_events` and `provider_usage` are written but no read route exists | Audit read endpoint, filters, pagination, export, retention enforcement | Medium. `_app.platform.audit.tsx`; `REQUIREMENT_TRACEABILITY` R35 |
| A06 | Provider configuration screen | `/platform/integrations` | **UI ONLY** | Provider list with key state, test, rotate and quota, plus switch between adapters | Capability list and a link to the fleet screen; no provider mutation is offered because no HTTP route exposes credentials | Key lifecycle endpoints (partly present under admin), rotation UI, test-connection action, second adapter | Medium. `_app.platform.integrations.tsx`; `SCREEN_INVENTORY` 46 |
| A07 | Platform defaults and retention settings | `/platform/settings` | **UI ONLY** | Persisted platform defaults: workspace template, script retention, who may read audit | Read-only prose listing three undecided defaults and stating no table stores them | Configuration table, read/write endpoints, validation, propagation to workspaces, audit | Medium. `_app.platform.settings.tsx` |
| A08 | Gemini fleet overview and project health | `/platform/gemini` | **PARTIALLY IMPLEMENTED** | Per-project capacity, confirmed vs estimated limits, health and rotation state for the shared key fleet | A 1,586-line screen with six real tabs (Overview, API keys, Contributors, Projects, Usage, Alerts) calling the admin fleet API, with explicit `CONFIRMED`/`ESTIMATED`/`UNKNOWN` labelling and no invented figures. It renders `unavailable`/`error` because no engine answers, and one browser assertion for this state fails | Working deployment, verified live quota source, and the failing assertion in F below | Medium. `_app.platform.gemini.tsx`; `lib/api/gemini.ts`; `admin_providers.py` |
| A09 | Fleet key add, import, validate, enable and delete | `/platform/gemini` (API keys tab) | **PARTIALLY IMPLEMENTED** | Import many keys, validate each, enable or disable, delete, with key material never returned | The client and the engine both implement all five operations, including fingerprint-only reads and per-key validation; untested end to end because the engine is unreachable and no live key was supplied | Reachable engine, live validation test, duplicate handling verification, rotation runbook | Medium. `lib/api/gemini.ts`; `backend/app/api/v1/admin_providers.py` (10 operations) |
| A10 | Fleet usage, quota alerts and contributor accounting | `/platform/gemini` (Usage, Alerts, Contributors) | **PARTIALLY IMPLEMENTED** | Request and token counts per project and key, remaining allowance with a confidence label, alerts and contributor summaries | Screens and API exist and degrade honestly; no verified data path, and quota is modelled per project as designed. Alerts are read-only with no acknowledgement workflow | Reachable engine, live quota source, alert acknowledgement, contributor attribution policy if ever needed | Low. `_app.platform.gemini.tsx`; `admin_contributions.py` (8 operations) |
| A11 | Support grants: consented, scoped, expiring access | platform area | **NOT IMPLEMENTED** | Operator requests time-boxed access, the owner consents, a banner shows the grant and it expires automatically | Absent from the frontend and the schema; the requirement is also scheduled after MVP, so this is a deliberate deferral rather than a regression | Grant table, consent flow, scope enforcement, expiry job, banner, audit | Medium. `SCREEN_INVENTORY` 53; `REQUIREMENT_TRACEABILITY` R21 |
| A12 | Workspace usage and quota view | settings / platform | **NOT IMPLEMENTED** | Storage, job and token consumption with per-assignment breakdown and near-limit/exceeded states | No screen. The engine has `GET /api/v1/usage` and admin usage reporting; nothing in the browser calls either | Usage screen, meter components, threshold states, per-assignment breakdown | Medium. `SCREEN_INVENTORY` 47; `backend/app/api/v1/usage.py` |
| A13 | Danger zone: export and delete a workspace | settings | **NOT IMPLEMENTED** | Tenant-scoped export, typed confirmation, 14-day grace, purge and tombstone | No route, endpoint or job | Export job and format, deletion workflow, grace period, purge, tombstone, restore drill | Medium. `SCREEN_INVENTORY` 49; `REQUIREMENT_TRACEABILITY` R33/R34 |
| A14 | Credential vault UI with test and rotate | settings | **NOT IMPLEMENTED** | Per-provider credential state, test, rotate and last-used, with no secret ever rendered | Only the admin fleet screen touches keys, and it does not rotate a workspace credential because the engine has no such endpoint | Credential endpoints per workspace, rotation, last-used display, audit | Medium. `SCREEN_INVENTORY` 46; `REQUIREMENT_TRACEABILITY` R19 |
| A15 | Operator authorization across the admin API and area | platform boundary | **PARTIALLY IMPLEMENTED** | Only an operator reaches `/platform/*` and `/api/v1/admin/*`; a teacher is refused, and refusal is auditable | The UI gate is real and tested (role rails and redirects pass). The engine gate is real too: `deps.get_principal` resolves the role from the `users` row, and the admin routers document an ADMIN-only rule. The two are not connected: the browser role lives in Supabase `app_metadata`, the engine role in its own table, and nothing writes one from the other, so a legitimate operator can be refused | One source of truth or a synchronisation path, plus a test that a Supabase operator reaches an admin route | Critical. `lib/auth/roles.ts`; `backend/app/api/deps.py`; `admin_providers.py` module docstring |
| A16 | Contributor self-service for contributed keys | contributor area | **NOT IMPLEMENTED** | A contributor lists their own keys, sees usage attribution and withdraws, without seeing anyone else's | The engine implements `/api/v1/contributions` with `/me`, `/me/keys` and `/me/withdraw` (4 operations); there is no frontend route or component | Contributor screen, scoped queries, withdrawal confirmation and effect explanation | Low. `backend/app/api/v1/contributions.py`; no matching route in `frontend/src/routes` |

### C.4 Backend, data and service layer (18)

| ID | Feature | Surface | Status | Expected behaviour | Actual behaviour | Missing work / dependencies | Severity and evidence |
|---|---|---|---|---|---|---|---|
| B01 | Liveness and readiness endpoints | `GET /health`, `GET /ready` | **COMPLETE** | Report service name and version, and database readiness via a real query, without leaking configuration | Both are implemented and consumed by `healthService`; the browser screen distinguishes not-configured, unreachable and answering states. Covered by the backend suite; the two Playwright health tests were skipped in this run for lack of a configured URL | None in the endpoint itself; deployment is what is missing | Medium. `frontend/src/lib/services.ts`; `_app.platform.health.tsx` |
| B02 | Workspace, exam and blueprint API | `/api/v1/workspaces*`, `/exams*` | **PARTIALLY IMPLEMENTED** | Tenant-scoped reads and writes for workspaces, exams and immutable blueprint versions | 14 operations in `exams.py` including `PUT /exams/{id}/blueprint`; all are tenant-scoped through `tenant_id`. No frontend calls any of them, and no test exercises the blueprint write from the UI | Client wiring, response-shape alignment, UI for blueprint editing, contract tests against the client types | High. `backend/app/api/v1/exams.py`; `lib/services.ts` |
| B03 | Assignment and submission API | `/assignments*`, `/submissions*` | **PARTIALLY IMPLEMENTED** | Create and read assignments, list an assignment's submissions, read one submission with its pages and quality report | Assignment create/read and submission create/read exist; there is **no** assignment-submissions list route, and no pagination or filtering. The frontend service expects a list the backend does not expose | List route with pagination and filters, submission page/file route, client types, tests | High. `API_DESIGN` §7; `lib/services.ts` vs `exams.py` |
| B04 | Correction job API and state machine | `/api/v1/corrections*` | **PARTIALLY IMPLEMENTED** | Create, list by workspace, read detail, cancel and retry, with terminal states and retry classification | All five operations exist, plus a documented lease/state machine with `FOR UPDATE SKIP LOCKED`; but a claimed job is parked with `PIPELINE_UNAVAILABLE`, so the machine terminates without a mark. No UI consumes any of it | The pipeline (B05); queue UI (C10/C33); terminal-state metrics | Critical. `corrections.py`; `jobs/states.py`; `jobs/pipeline.py` |
| B05 | Correction / marking pipeline | worker | **NOT IMPLEMENTED** | Produce question-level marks with evidence, confidence and verification, or `needs_review` — never a silent zero | `UnavailablePipeline` is the only implementation. The worker leases jobs and parks them; the configuration comment states selective review is unimplemented so the flag must not imply otherwise | The entire marking step, prompt and verification design, evidence model, result persistence, and a benchmark-gated evaluation | Critical. `jobs/pipeline.py`; `core/config.py:204`; AGENTS.md non-negotiable 1 |
| B06 | Scheme extraction, mapping and approval | `/api/v1/documents*`, `/schemes*` | **PARTIALLY IMPLEMENTED** | Turn an uploaded scheme PDF into a reviewed blueprint, map pages, approve explicitly and lock before marking | 9 operations cover document read, mapping, scheme read and approve, with an approval that is separate from editing. Extraction quality is unverified and no UI exists | Extraction verification, conflict detection, version guard UI, lock enforcement tests, review canvas (C07) | Critical. `documents.py`; `REQUIREMENT_TRACEABILITY` R10 (lock required before marking) |
| B07 | Document ingest, validation and page serving | storage + documents | **PARTIALLY IMPLEMENTED** | Validate type, size and page count, store the file, serve page images with tenant checks | Local-filesystem adapter with a storage interface; validation exists at the boundary. No page-image endpoint that a viewer could use, and no signed access | Page rendering and serving route, tenant-checked access, thumbnails, large-file handling | High. `backend/app/storage/base.py`, `local.py` |
| B08 | Object storage and signed access | storage | **BLOCKED** | Durable object storage with scoped, expiring URLs, independent of the app host | Only the local filesystem adapter exists. The historical blueprint's R2/Supabase Storage design is not the implemented data layer (ADR-001), so the host is a decision, not a task | Storage-host decision, adapter, signed URL strategy, lifecycle and retention, migration of any existing files | Critical. `backend/app/storage/__init__.py`; ADR-001; `REQUIREMENT_TRACEABILITY` R37 (files unrecoverable) |
| B09 | Upload safety: type sniffing, malware scan, quotas | ingest | **NOT IMPLEMENTED** | Magic-byte checks, size and page caps, malware scanning, quarantine on failure | Extension and size checks only, per the repository's own status note; no scanner, no quarantine, no per-tenant quota | Scanner integration, quarantine bucket, scan-result gating, quota enforcement, audit | High. AGENTS.md non-negotiable 1; `REQUIREMENT_TRACEABILITY` R22 |
| B10 | Worker leasing, retry and terminal-state guarantees | worker | **PARTIALLY IMPLEMENTED** | Every job reaches a terminal state within 24h; retryable errors back off, 401 never resends, a rate limit parks without consuming an attempt, cancel leaves no partial result | Leasing, backoff and error classification are implemented and unit-tested; the "terminal with a result" half is impossible without B05, and cancel/discard is unexercised from the UI | Pipeline completion, cancel discard test, dead-letter handling, job-loss alerting | Critical. `jobs/service.py`, `jobs/runner.py`, `jobs/states.py`; `REQUIREMENT_TRACEABILITY` R23 |
| B11 | Gemini adapter, credential encryption and provider boundary | providers | **PARTIALLY IMPLEMENTED** | One provider behind a protocol, deterministic parameters, encrypted keys, fingerprints only in responses, no key ever reaching the client | Adapter, pricing table, JSON handling, error taxonomy and encrypted credential storage exist; live responses are `UNVERIFIED` and the reachable engine answered 401 during this audit | A funded key and a deployed engine, then a recorded verification run; the adapter must stay server-side | Critical. `backend/app/providers/*`; `REQUIREMENT_TRACEABILITY` R07/R19 |
| B12 | Provider fleet and contribution administration | `/api/v1/admin/providers*`, `/admin/contributions*` | **PARTIALLY IMPLEMENTED** | Operator-only fleet administration: overview, keys, import, validate, enable, delete, projects, usage, alerts; contributor lifecycle with suspend, reinstate and withdraw | 18 operations exist across the two admin routers, role-gated in the engine and never returning key material; the frontend client covers them and the fleet screen calls them. Untested against a live engine, and gated by the role mismatch in A15 | Reachable engine, end-to-end key lifecycle test, confirmation that a teacher receives 403 from every admin route | Medium. `admin_providers.py` (10 operations), `admin_contributions.py` (8); `lib/api/gemini.ts` |
| B13 | Usage and quota reporting | `GET /api/v1/usage` | **PARTIALLY IMPLEMENTED** | Per-job metering with quota enforcement, aggregated daily, per assignment and per provider | A usage summary endpoint and a usage repository exist, and admin reporting is richer; no quota enforcement path is exercised, and the double-count risk recorded in the traceability audit is unresolved | Enforcement test, idempotent metering, per-assignment aggregation, UI (A12) | Medium. `usage.py`; `REQUIREMENT_TRACEABILITY` R36 (weak, DB-07) |
| B14 | Inbox, dashboard and report aggregation API | `/api/v1/*` | **NOT IMPLEMENTED** | Tenant-scoped counts and lists for the dashboard, an event inbox and reports | None of the three exists. The frontend names all three endpoints in its `wip` panels, which is honest but not an implementation | Aggregation design, endpoints, indexes for the counts, empty and insufficient-data contracts | Critical. `lib/services.ts`; no route in `backend/app/api/v1` |
| B15 | Notifications and email delivery | service layer | **NOT IMPLEMENTED** | Transactional email for invitations, review requests and failures, plus in-app notification records and preferences | No notification table, no mail transport, no templates | Transport choice, templates, preferences table, delivery retries, unsubscribe | High. `REQUIREMENT_TRACEABILITY` R38 (no endpoints, no preferences table) |
| B16 | Audit read, export and retention | service layer | **NOT IMPLEMENTED** | Read and export append-only audit events for 12 months, tenant-scoped for teachers and platform-wide for operators | Events are written (`audit_events`, `job_events`, `provider_usage`) but no read route exists; retention is not enforced by any job | Read endpoints, export, retention job, append-only enforcement verified at the database layer | Medium. `REQUIREMENT_TRACEABILITY` R35 (weak, DB-11) |
| B17 | Rate limiting and abuse controls | edge + API | **NOT IMPLEMENTED** | Bound authentication attempts, uploads and provider calls; park rather than fail on upstream rate limits | No limiter in the application. Upstream 429 classification exists inside the worker, which is a different concern | Limiter (edge or middleware), per-tenant budgets, 429 contract, tests | High. AGENTS.md non-negotiable 1; `REQUIREMENT_TRACEABILITY` R25 |
| B18 | Schema, migrations, constraints and isolation guard | data layer | **PARTIALLY IMPLEMENTED** | Every change as a reviewed migration; constraints that make invalid states unrepresentable; tenant isolation verified | 30 models and 12 revisions, no `create_all`, Alembic is the only path, and a row-level-security guard runs in CI. Gaps are recorded against specific requirements: no `CHECK` for mark ≤ maximum (R03), no constraint making cross-tenant child rows impossible (R13), and isolation is application-level in places | Constraint migrations, database-level isolation, and a dedicated test database so integration tests need not truncate a configured one | High. `backend/app/db/models.py`; `backend/migrations/versions`; `REQUIREMENT_TRACEABILITY` R03/R13 |
## D. Backend gaps

### D.1 What the engine exposes

The application has 52 operations under `/api/v1`, plus the service liveness and readiness routes at `/health` and `/ready` that the health screen calls. Distribution by router:

| Router | Operations | Purpose | Consumed by the browser? |
|---|---|---|---|
| `exams.py` | 14 | Workspaces, exams, blueprints, assignments, submissions, corrections by submission and workspace | No |
| `documents.py` | 9 | Document read, page mapping, scheme read and explicit approval | No |
| `admin_providers.py` | 10 | Fleet overview, keys, import, validate, enable, delete, projects, usage, alerts | Yes — `/platform/gemini` |
| `admin_contributions.py` | 8 | Contributor list, detail, suspend, reinstate, withdraw | Yes — `/platform/gemini` Contributors tab |
| `corrections.py` | 5 | Create, list, detail, cancel, retry a marking job | No |
| `contributions.py` | 4 | A contributor's own keys and withdrawal | No |
| `usage.py` | 2 | Usage summary and provider health | No |
| health (`main`) | 2 | Liveness and readiness | Yes — `/platform/health` |

Seven of eight routers have no client caller. The engine is substantially more complete than the interface that fronts it, and the reverse is also true: the interface names endpoints (dashboard, inbox, reports) that the engine does not have.

### D.2 Endpoints the interface requires and the engine lacks

| Interface expectation | Where it is named | Present? |
|---|---|---|
| `GET /api/v1/workspaces/{id}/dashboard` | `/dashboard` state panel | No |
| `GET /api/v1/workspaces/{id}/inbox` | `/inbox` state panel | No |
| `GET /api/v1/workspaces/{id}/reports` | `/reports` state panel | No |
| Assignment's submission list | `/assignments/$id` Submissions tab, `lib/services.ts` | No — only `GET /submissions/{id}` and `GET /submissions/{id}/corrections` |
| Workspace settings read/write | `/settings` state panel | No |
| Classes, students, rosters | `/students`, `/classroom` | No |
| Membership, invitations, assistants | `/assistants`, `/assistant/classes` | No — no membership or invitation table in the schema |
| Platform workspaces, accounts, audit | `/platform/workspaces`, `/users`, `/audit` | No |
| Tasks and review events | `/assistant/tasks`, `/assistant/progress` | No |
| Submission page images | `/submissions/$id` page grid | No |
| Export and deletion | danger zone | No |
| Search | app shell | No |

### D.3 Contract and configuration mismatches

1. **Role vocabulary and source of truth.** The browser reads `app_metadata.aetrix_role` with four values (`owner`, `platform_operator`, `supervisor`, `assistant`). The engine reads `users.role`, and its admin routers compare that against an ADMIN constant. No code writes a Supabase role into the engine, and `backend/app/cli.py`'s `create-user` is the only creation path, so a correctly provisioned identity-provider operator can still receive 401/403 from `/api/v1/admin/*`.
2. **Tenant resolution.** The engine resolves the tenant from the verified subject's `users` row in `api/deps.py`; it does not read a tenant from the request. That is correct and must not change. It also means an authenticated user without an engine row cannot read anything, which is why P10 is the first blocker in practice.
3. **Build-time API origin.** `VITE_AETRIX_API_URL` is compiled in. A build without it produces a permanently unconfigured client, which is why the health screen renders its `UnconfiguredHealth` branch and two health tests were skipped.
4. **Service layer versus schemas.** `lib/services.ts` declares workspace, assignment, submission, queue, inbox and report services with hand-written types; only `healthService` is called by any screen. The declared shapes were never reconciled against the backend response models, so wiring them today would surface type drift rather than data.
5. **Deployment artefact.** `vite build` emits `dist/server/.dev.vars`. It must never be published or committed; the audit did not read it.

### D.4 Data layer

30 mapped tables across 12 Alembic revisions. Migrations are the only schema path: no `create_all`, no SQLite fallback. The audit found no table for memberships, invitations, tasks, notifications, preferences, support grants, workspace settings, platform configuration, search, or result rows that marking would populate. Audit tables exist and are written but have no read route, so the guarantee is one-directional: history cannot be rewritten through the API because it cannot be read through the API. Two requirement-level defects are already recorded in the repository's own traceability audit — no database `CHECK` that a mark cannot exceed its question maximum, and no constraint that makes a cross-tenant child row impossible.

### D.5 Worker, storage and providers

The worker leases jobs with `FOR UPDATE SKIP LOCKED`, classifies errors and backs off, and is unit-tested. Its terminal outcome for a claimed job is `PIPELINE_UNAVAILABLE`: the pipeline object is a deliberate stub, and the configuration file records that selective review is unimplemented so its flag must not imply otherwise. Storage is a local-filesystem adapter behind an interface, with no object store, no signed URLs and no page-serving route. The Gemini adapter, pricing table, JSON handling and encrypted credential storage are real, but the live path is `UNVERIFIED`; the reachable engine rejected requests with 401 during this audit. There is no rate limiter, no malware scanner and no notification transport anywhere in the system.
## E. Specification comparison

### E.1 Method and counts

`docs/design/SCREEN_INVENTORY.md` enumerates screens numbered 1–54, although its own header claims 48; the numbered list is authoritative here. The application has 30 page routes across 33 route files (the three extra files are `__root`, the `_marketing` layout and the `_app` layout). Comparing route to screen is not one-to-one: several screens share a route, several routes have no screen, and eight routes (workspace hub, the five assistant pages, Gemini fleet, integrations, platform settings) either exceed the inventory or map only loosely to it.

| Inventory cluster | Screens specified | Present as a route | Assessment |
|---|---|---|---|
| Public (1–13) | 13 | 1 | Landing exists. Features, pricing, use cases, trust, FAQ, contact, docs, legal, status, changelog and error pages are absent |
| Auth and onboarding (14–23) | 10 | 1 | Login exists (the callback route is not a numbered screen). Signup, verification, reset, MFA, invite acceptance, workspace picker, create workspace, onboarding checklist and device manager are absent |
| Core app (24–44) | 21 | 11 | Home dashboard, inbox, assignment list and overview, marking queue, submission detail, grade matrix, classes, students, reports hub and members exist as layouts. Assignment editor, scheme upload, scheme review, submissions table, upload submissions, review canvas, class report, student profile, bulk import and activity log do not |
| Settings, admin and help (45–54) | 10 | 5 | Settings, classroom, platform workspaces, platform health and platform audit exist. Credentials, usage and quotas, danger zone, help and support grants do not |

Eighteen of 54 specified screens exist as routes, and none of the eighteen yet renders live tenant data. The two most consequential omissions are the review canvas (screen 34) and scheme review (screen 30): they are the human half of the product's central promise, and without them no mark can be confirmed or locked, whatever the pipeline does.

### E.2 Requirement traceability against the delivered interface

The repository's own trace audits 46 requirements: 24 traced (52%), 10 weak (22%), 12 gaps (26%). That document measures whether a requirement is traceable to a design and an architectural mechanism, not whether the interface ships it, so it reads more optimistically than the running product. Cross-checking it against this audit produces three corrections:

1. **Traced is not shipped.** R05 and R06 (override needs reason, actor and time; approval is a separate permission) are marked traced, and the tables and API error codes exist, but no screen can perform an override or an approval. The requirement is unimplementable from the product as it stands.
2. **Interface gaps sit inside "traced" clusters.** R32 (grade matrix, no endpoint), R33/R34 (export and deletion), R38 (notifications, no endpoints and no preferences table) and R46 (safe workspace switching) are recorded as gaps, and this audit confirms each on the client side as well.
3. **Two requirement failures are structural, not missing screens.** R03 (a mark may never exceed the maximum) has no database `CHECK`, and R13 (cross-tenant child rows impossible) has no constraint; both are data-layer defects that would survive any amount of UI work.

### E.3 Blueprint divergence and public claims

`docs/` preserves the historical blueprint: Cloudflare D1, Better Auth, R2 and Queues. ADR-001 records that this is not the implemented data layer; the delivered system is FastAPI, SQLAlchemy 2.0, Alembic and PostgreSQL, with a local filesystem adapter. The AGENTS.md instruction is explicit that the blueprint is history. Three marketing components still describe the superseded design as if it were live — a disabled-sign-in notice, key handling inside a Worker, and submissions living in R2 — which is why P02 is filed as **BROKEN** rather than a cosmetic defect: the page is factually wrong about the product's own architecture.

### E.4 State coverage

The interface handles absence unusually well for a pre-release build. `ApiResult` carries an `unavailable` state distinct from an error, em dashes are used instead of zeros, empty tables say why they are empty, and the health screen separates not-configured from unreachable. What is missing is the other half of state design: saved and unsaved-changes states, permission-denied as a dedicated surface, insufficient-data branches in reports and analytics, and conflict states for concurrent review — all specified, none built.
## F. Testing results

Every result below was produced during this audit by running the command shown. Nothing is inferred from documentation, and no test was modified, skipped or relaxed to obtain a pass.

| Check | Command | Result |
|---|---|---|
| Backend unit tests | `.venv/Scripts/python.exe -m pytest -q` in `backend/` | **84 passed in 61.64s** |
| Backend lint | `.venv/Scripts/python.exe -m ruff check app tests` | **All checks passed** |
| Frontend types | `node_modules/typescript/bin/tsc --noEmit` | **exit 0**, no diagnostics |
| Frontend build | `node_modules/vite/bin/vite.js build` | **exit 0**, 35 prerendered pages; one non-fatal `[SOURCEMAP_BROKEN] … vite:css-post` warning |
| Browser suite | `node_modules/@playwright/test/cli.js test` against a local preview | **150 passed, 1 failed, 2 skipped** (153 tests, ~2.3 min) |

### F.1 The failure

`frontend/tests/roles.spec.ts:130`, test *"states the fleet data gap rather than showing figures"*. The assertion at line 139 expects text matching `/no public HTTPS deployment yet|The engine rejected the request \(401\)/` and the locator resolved to nothing. The fleet screen rendered, but neither phrasing appeared, so the component and its test have drifted apart: the screen now reports absence through its `unavailable`/`error` branch with different wording. This is a genuine failing check and is left failing rather than adjusted, because deciding which wording is correct is a product decision, not an audit one. It is the only red result in the suite.

### F.2 The two skips

Both are in `health.spec.ts` and were skipped by the suite itself because the test process had no `VITE_AETRIX_API_URL`. A skipped test is not a pass: engine liveness and readiness were therefore **NOT TESTED** in a browser during this audit, even though `/health` and `/ready` are implemented.

### F.3 Not tested, and why

| Area | Why it was not tested |
|---|---|
| Full Google OAuth round trip (P09) | No interactive Google session was performed; the suite seeds a synthetic Supabase session. No owner test account or allow-listed callback was available |
| Live Gemini or any provider call (B11) | The reachable engine rejected requests with 401 and no funded key was supplied, so no live response exists to verify |
| Backend integration tests against a database | `backend/tests/conftest.py` has an autouse fixture that truncates all application tables in the configured database. With no dedicated `AETRIX_TEST_DATABASE_URL`, running them would destroy development data, so they were not run |
| Deployment, Cloudflare Workers compatibility, production health | No deployed engine and no operational credentials; deployment was out of scope for this audit |
| Malware scanning, rate limits, quota enforcement | Not implemented, so there is no behaviour to test |
| Cross-tenant enforcement at runtime | Requires two provisioned tenants and a reachable engine; the code path was read, not exercised |

### F.4 Limitations of this audit

Static source review cannot prove runtime behaviour, and no claim here should be read as one. Findings about absent features are strong, because absence is directly observable in the route table, the client layer and the engine's routers. Findings about partially implemented features rest on reading code paths and on unit-level tests, not on end-to-end execution. The count of 52 engine operations comes from the decorator inventory; it is a count of routes, not of verified working endpoints. The audit changed no application code, configuration, migration or test.
## G. Recommended roadmap

The ordering below is by dependency, not by visibility. Each phase has an exit criterion that can be observed, and a phase is not done because its screens exist but because its criterion holds. Two rules govern the sequence: correctness of identity precedes any data read, and marking precedes every result screen.

| Phase | Work | Why it comes here | Exit criterion |
|---|---|---|---|
| **0. Make the claims true** | Rewrite `FinalCta` (sign-in is enabled), `Security` (the engine is Python; no Worker decrypts keys) and `Workflow` (storage is a local adapter, not R2); resolve the failing fleet assertion by choosing the honest wording | The public page currently states the opposite of the architecture. It costs almost nothing and it is the only defect that misleads a reader today | Public copy matches ADR-001; the browser suite is green with no assertion weakened |
| **1. Identity and tenancy** | Engine user provisioning from the verified subject (P10); one role vocabulary shared by Supabase and the engine (A15); invitation acceptance (P14) | Every tenant-scoped read depends on an engine user row. Until this exists, a real invited user can sign in and then read nothing, and an operator can be refused the admin API | An invited Google account signs in, is provisioned exactly once, reaches its role home and successfully calls one engine endpoint; a second account cannot read the first's records and receives 404, not 403 |
| **2. The read path** | Dashboard, inbox, assignment list/detail and submission list endpoints (B14, B03); wire C01–C05, C10, C12; job detail with cancel and retry (C33) | These are the screens a teacher uses first, and they need no marking to be useful — a queue of pending jobs is real work even while marking is unimplemented | A teacher sees their own assignments, submissions and jobs with real counts; every empty state is a fact, not a placeholder |
| **3. Scheme to blueprint** | Scheme upload, page preview, extraction progress (C06); review canvas for the blueprint (C07); lock enforcement (B06) | Marking cannot be honest without a human-confirmed question structure and max marks | A PDF becomes a reviewed blueprint, approval is explicit and separate from editing, and marking is refused with 409 while the scheme is unlocked |
| **4. Marking** | The correction pipeline (B05), result persistence, evidence and verification | This single phase unblocks the largest block of features: review canvas, gradebook, reports, analytics, assistant progress and the exportable trail. It is also the only phase with a genuine research risk | On a frozen benchmark, marks are produced with per-question evidence, `needs_review` is used instead of zero, a repeat run is identical, and no mark exceeds its maximum — enforced in the database, not only the API |
| **5. Review and results** | Review canvas with override (C11), grade matrix (C13), class report (C14), reports hub (C15) | These consume Phase 4's output; building them earlier guarantees rework | An examiner overrides a mark with a reason, actor and timestamp; the gradebook and a reproducible class report reflect it |
| **6. Assistants and Classroom** | Assistant membership (C21), scoped assistant work (C22–C26), Classroom OAuth and roster sync (C27) | Assistants need something to review, and rosters need classes to attach to; both depend on Phases 2–5 | An assistant sees only assigned classes and submissions; withdrawal removes access immediately; a Classroom course syncs into exactly one workspace |
| **7. Administration and operations** | Workspace and account directories (A02, A03), audit read (A05, B16), usage (A12, B13), export and deletion (A13), rate limiting and upload safety (B09, B17), notifications (B15, C31) | Operators can run the service only once there is data and marking to observe; several of these are also compliance prerequisites for real student scripts | An operator can allocate a class, suspend an account, read the audit trail and export a tenant; limits and scans reject abusive or unsafe uploads with a clear state |
| **8. Public completeness** | Features, pricing, trust, legal, docs, status, changelog, contact, error pages (P04–P07) | Marketing depth is worth building only when the product behind it can be described truthfully | Every public claim links to shipped behaviour or is labelled as planned |

### G.1 What not to do next

Do not wire the empty screens to the engine before Phase 1. The client types were never reconciled with the response models, and the role mismatch means the first integration attempt would fail as an authorization bug that looks like a data bug. Do not populate any screen with sample rows to demonstrate progress: the `unavailable` state and the em dashes are the most trustworthy part of this build, and replacing them would trade the project's main asset for a screenshot. Do not build report or analytics surfaces before Phase 4 — they have no input, and their absence is currently honest.
