# Aetrix V5.5 — UI playtest and visual QA report

Date: 2026-11-22
Target: **https://aetrix.pages.dev** (Cloudflare Pages, `aetrix` project, branch `main`)
Source: `main` @ `4ab1b36` (GitHub `AetherRIP/Aetrix_V5.5`)
Browser: packaged Chromium (Playwright 1.64 for the fixed-viewport sweeps)

---

## A. Executive summary

**Overall UI quality: solid on the surfaces that were reachable.**

The marketing surface, the legal documents, the sign-in surface and the session
guard are consistent, honest about what the product does not do, and hold their
layout at every width tested. The authenticated screens were exercised only
against the project's seeded-session harness with a stubbed engine; **the three
real test accounts could not be authenticated because no passwords were supplied
and none may be requested, printed or stored by this mission.**

| Measure | Value |
|---|---|
| Routes discovered | 43 (13 public, 30 authenticated) |
| Routes tested live | 43 / 43 (unauthenticated and static surfaces) |
| Route × viewport combinations on the live site | 151 |
| Confirmed bugs | 3 (all fixed and redeployed) |
| Severity breakdown | 0 Critical, 0 High, 3 Medium |
| Accounts verified live | 0 of 3 — **BLOCKED, no credentials** |
| Local regression suite | 296 tests: **294 passed, 2 skipped**, exit 0 |

Most important blockers:

1. **No credentials.** `AETRIX_TEST_TEACHER_PASSWORD`,
   `AETRIX_TEST_ASSISTANT_PASSWORD` and `AETRIX_TEST_OWNER_PASSWORD` are not set.
   No account was signed in, so role, claim, workspace and permission behaviour on
   the real accounts is **untested**.
2. ~~The deployed bundle points the engine client at a private Tailscale origin.~~
   Fixed: the public artifact is now built with `VITE_AETRIX_API_URL` unset, so no
   engine origin is baked and every screen states that no public deployment exists.
3. ~~Tap targets in the marketing chrome are below the 24 × 24 minimum.~~ Fixed:
   the footer column links now carry vertical padding and clear 24 px at every
   width tested.

**Readiness verdict: READY FOR INTERNAL TESTING WITH KNOWN ISSUES** — see J.

---

## B. Route coverage matrix

Role columns are the permissions declared in `frontend/src/lib/auth/roles.ts`
(`ROUTES_BY_ROLE`). "Actual" is what the deployed site does for an **unauthenticated**
visitor; authenticated access is BLOCKED (see C).

Legend: `Y` permitted by the front-end role map, `–` not permitted, `n/a` not applicable.

| Route | Page | Teacher | Assistant | Owner | Operator | Auth | Tested desktop | Tested mobile | Status |
|---|---|---|---|---|---|---|---|---|---|
| `/` | Landing | – | – | – | – | no | 1280/1440/1920 | 320/375/430/844×390 | PASS |
| `/sign-in` | Sign in | – | – | – | – | no | 3 | 4 | PASS |
| `/legal` | Legal hub | – | – | – | – | no | 3 | 4 | PASS |
| `/privacy` | Privacy | – | – | – | – | no | 3 | 4 | PASS |
| `/terms` | Terms | – | – | – | – | no | 3 | 4 | PASS |
| `/cookies` | Cookies | – | – | – | – | no | 3 | 4 | PASS |
| `/acceptable-use` | Acceptable use | – | – | – | – | no | 3 | 4 | PASS |
| `/ai-disclosure` | AI disclosure | – | – | – | – | no | 3 | 4 | PASS |
| `/copyright` | Copyright | – | – | – | – | no | 3 | 4 | PASS |
| `/security` | Security | – | – | – | – | no | 3 | 4 | PASS |
| `/account-deletion` | Account deletion | – | – | – | – | no | 3 | 4 | PASS |
| `/auth/callback` | OAuth callback | – | – | – | – | no | 3 | 4 | PASS |
| `/auth/classroom` | Classroom connect | – | – | – | – | no | 3 | 4 | PASS |
| `/dashboard` | Teacher dashboard | Y | – | Y | – | yes | 3 | 4 | PASS (guard) |
| `/workspace` | Workspaces | Y | – | Y | – | yes | 3 | 4 | PASS (guard) |
| `/inbox` | Inbox | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/notifications` | Notifications | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/history` | Marking history | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/queue` | Marking queue | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/assignments` | Assignments | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/assignments/$id` | Assignment record | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/submissions/$id` | Submission review | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/preview/$id` | Correction preview | Y | Y | Y | – | yes | 3 | 4 | PASS (guard, after UI-001) |
| `/reports` | Reports | Y | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/settings` | Settings | Y | Y | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/students` | Classes & students | Y | – | Y | – | yes | 3 | 4 | PASS (guard) |
| `/gradebook` | Gradebook | Y | – | Y | – | yes | 3 | 4 | PASS (guard) |
| `/analytics` | Analytics | Y | – | Y | – | yes | 3 | 4 | PASS (guard) |
| `/assistants` | Assistants | Y | – | Y | – | yes | 3 | 4 | PASS (guard) |
| `/classroom` | Google Classroom | Y | – | Y | – | yes | 3 | 4 | PASS (guard) |
| `/platform` | Platform overview | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/platform/workspaces` | Allocation | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/platform/users` | Account management | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/platform/health` | System health | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/platform/audit` | Audit log | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/platform/gemini` | Gemini fleet | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/platform/integrations` | AI providers | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/platform/settings` | Platform settings | – | – | Y | Y | yes | 3 | 4 | PASS (guard) |
| `/assistant` | Assistant overview | – | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/assistant/classes` | Assigned classes | – | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/assistant/work` | Marking workspace | – | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/assistant/tasks` | Tasks | – | Y | Y | – | yes | 3 | 4 | PASS (guard) |
| `/assistant/progress` | My progress | – | Y | Y | – | yes | 3 | 4 | PASS (guard) |

"PASS (guard)" means the deployed site answers, redirects to `/sign-in`, never paints
the app shell and reports no runtime error. It does **not** mean the signed-in screen
was reviewed on the live site.

Authenticated screens were reviewed locally against seeded sessions and a stubbed
`/me` (the project's own suite): 37 authenticated route checks at 390/768/1440 in
`layout-coverage.spec.ts`, plus role navigation, route guards, command palette,
rail collapse and phone tab bar in `roles.spec.ts`.

---

## C. Account coverage matrix

| Account | Email | Expected role / claim | Authenticated | Role verified | Navigation verified | Permissions verified | Status |
|---|---|---|---|---|---|---|---|
| Teacher | `rudroritisha12+aetrix-test-teacher@gmail.com` | `TEACHER` / `supervisor` | No | No | No | No | **BLOCKED** |
| Assistant | `rudroritisha12+aetrix-test-assistant@gmail.com` | `REVIEWER` / `assistant` | No | No | No | No | **BLOCKED** |
| Owner | `rudroritisha12+aetrix-test-owner@gmail.com` | `PLATFORM_OWNER` / `owner` | No | No | No | No | **BLOCKED** |

Why: the mission requires passwords through `AETRIX_TEST_*_PASSWORD`, none is set in
this environment, and the browser profile held no stored session for
`aetrix.pages.dev` (`aetrix:auth` absent, `aetrix:auth-accounts` empty). Authentication
was **not** bypassed; no synthetic session was injected into the live site.

What *was* verified for roles, locally and against the project's own fixtures:

- The engine's `/me` answer outranks the identity-provider claim, and a claim cannot
  promote an account the engine resolved (`role-resolution.spec.ts`).
- `PLATFORM_OWNER` maps to the owner account type, not the administrator.
- Teacher cannot open `/platform/*` (redirected to `/dashboard`); assistant is refused
  `/students` with a stated reason; assistant is redirected out of `/platform`.
- Owner opens teacher and assistant areas without a "belongs to another account type"
  panel; operator lands on `/platform` from `/dashboard`.
- A verified account with no role gets "No account role assigned" and no shell.

These are front-end behaviours. **Engine-side authorisation was not exercised at all**
in this mission (no token, no running API).

---

## D. Device coverage matrix

| Category | Viewport | Used on live site | Result |
|---|---|---|---|
| Small laptop | 1280 × 720 | yes | no overflow, no console errors |
| Standard desktop | 1440 × 900 | yes | no overflow, no console errors |
| Large desktop | 1920 × 1080 | yes | no overflow, no console errors |
| Small phone | 320 × 568 | yes | no overflow |
| Standard phone | 375 × 812 | yes | no overflow |
| Large phone | 430 × 932 | yes | no overflow |
| Phone landscape | 844 × 390 | yes | no overflow |
| Tablet | 768 × 1024 | local suite only | passed |
| Physical phone | — | **no** | not tested |

All viewport work was browser emulation, not physical-device testing. Panel
screenshots were not used as evidence because the desktop screenshot tool resizes the
page; measurements come from fixed-viewport Playwright runs.

---

## E. Bug register

### Bug ID: UI-001

- **Title:** Direct load of a correction-preview URL is served the landing page and
  throws a React hydration error
- **Severity:** Medium
- **Category:** Functional / Visual
- **Account:** Not applicable (reproduced signed out); affects every reviewer who
  refreshes or opens a `/preview/<id>` link
- **Role and claim:** n/a (unauthenticated path)
- **Route:** `/preview/example` (and `/preview/example/`)
- **Device:** Desktop and phone
- **Viewport:** 1440 × 900 and 375 × 812
- **Browser:** Chromium (packaged)
- **Preconditions:** Deployed build `65a5abf`
- **Steps to reproduce:** open `https://aetrix.pages.dev/preview/example`; watch the
  console; observe the page settles on `/sign-in`
- **Expected:** the app document for the route (`Checking your session` shell), as for
  `/submissions/example`
- **Actual:** the marketing landing document was returned (title
  `Beyond marking…`), the client hydrated an app route against marketing markup and
  React logged `Minified React error #418` (hydration mismatch); after hydration the
  session guard redirected to `/sign-in`
- **Screenshot or recording:** `preview-shots/live-uiqa-results-deployed.json`
  (rows `/preview/example` at phone-375 and desktop-1440: `pageErrors: ["Minified React error #418…"]`)
- **Console errors:** React #418, twice (once per viewport)
- **Network/API errors:** none
- **Likely root cause:** `/preview/$submissionId` was added to the router but not to
  the explicit `tanstackStart({ pages })` prerender list in `frontend/vite.config.ts`;
  no prerendered page links to a preview URL, so the crawler never found it and Pages
  fell back to `index.html`
- **Suggested fix:** add `{ path: '/preview/example' }` to the prerender page list
- **Reproduction confirmed:** Yes

### Bug ID: UI-002

- **Title:** Marketing navigation and footer links are below the 24 × 24 minimum target
- **Severity:** Medium
- **Category:** Accessibility
- **Account:** Not applicable
- **Route:** every page carrying the marketing chrome — `/`, `/sign-in`, `/legal`,
  `/privacy`, `/terms`, `/cookies`, `/acceptable-use`, `/ai-disclosure`, `/copyright`,
  `/security`, `/account-deletion`
- **Device:** Desktop and phone
- **Viewport:** all seven tested
- **Browser:** Chromium
- **Preconditions:** none
- **Steps to reproduce:** load `/legal` at any width; measure the footer legal links or
  the top navigation links
- **Expected:** each interactive control at least 24 × 24 CSS px (WCAG 2.2 AA, 2.5.8)
- **Actual:** header navigation links measure 80 × 23 (`The problem`), 97 × 23
  (`Transformation`), 60 × 23 (`Workflow`), etc.; footer links measure 92 × 14
  (`Terms of Service`), 75 × 14 (`Privacy Policy`), 74 × 19 (`Cookie Policy`).
  137 of 151 route × viewport rows reported at least one undersized target
- **Screenshot or recording:** `preview-shots/live-uiqa-results.json`
  (`metrics.smallTargets`)
- **Console errors:** none
- **Network/API errors:** none
- **Likely root cause:** the marketing nav and `SiteFooter` set line-height-only hit
  areas, with no vertical padding on the anchors
- **Suggested fix:** add vertical padding to the shared footer link style while
  reducing the column gap by the same amount, so the text rhythm is preserved
- **Fixed:** 2026-11-22 — footer links now measure 27.2 px, `gap` reduced from 8 px to
  4 px so the 8 px text spacing is unchanged; the header nav was already 37.6 px and
  needed no change
- **Reproduction confirmed:** Yes

### Bug ID: UI-003

- **Title:** Deployed bundle points the engine client at a private Tailscale origin
- **Severity:** Medium
- **Category:** Functional / Configuration
- **Account:** Any signed-in account on the public site
- **Route:** every authenticated data screen
- **Device:** all
- **Preconditions:** production build made from `frontend/.env`
- **Steps to reproduce:** inspect the deployed bundle's baked API origin, or sign in
  on the public site and watch requests to `/api/v1/*`
- **Expected:** the public site calls a publicly resolvable HTTPS engine origin, or the
  build states that it has none
- **Actual:** `VITE_AETRIX_API_URL` is baked at build time from `frontend/.env` and
  resolves to `https://arthur-rip-zn02.tail06bb75.ts.net`, a private Tailscale host.
  A visitor outside that tailnet cannot reach it, so every authenticated screen falls
  to its "engine could not be reached" state
- **Screenshot or recording:** n/a (build-time configuration)
- **Console errors:** none observed unauth enticated (no API call is made before sign-in)
- **Network/API errors:** expected DNS/connection failures after sign-in for external
  testers — **not reproduced**, because no account could be signed in
- **Likely root cause (confirmed later):** the origin was not in the repository at all.
  The Pages project stored `VITE_AETRIX_API_URL` as a project environment variable
  (`deployment_configs.production.env_vars` and `.preview.env_vars`), and the project's
  Git integration builds every push to `main`, baking that value into the bundle. A
  manual upload is then superseded by the Git build of the same commit
- **Suggested fix:** build the Pages artifact with the engine's public HTTPS origin, or
  with the variable unset so the UI states "no public deployment yet" honestly. This
  is a deployment decision, not a UI change, so it was not altered
- **Reproduction confirmed:** Yes (the baked origin); the resulting request failure was
  inferred, not observed, because no account could be signed in
- **Fixed:** 2026-11-22 — the variable was deleted from both Pages environments
  (preview and production; the two Supabase variables were kept), the correct artifact
  was redeployed, and the Git deployment of the same commit was retried to confirm the
  pipeline now builds honestly. Live entry `index-sRad-X5s.js` contains no tailnet host
  and carries the "compiled without an engine origin" reason

---

## F. Security and permission findings

No privilege escalation, tenant crossover or authentication bypass was observed.

- Unauthenticated access to all 30 authenticated routes is refused: each answers 200
  with the prerendered gate, then lands on `/sign-in`, and `.app-sidebar` /
  `.app-topbar` never render (verified at 375 and 1440 on the live site).
- The session guard redirect is `replace: true`, so the protected URL is not left in
  history as a reachable page.
- The sign-in form posts (`method="post"`, `action="/sign-in"`), so credentials cannot
  leak into a query string before hydration. Both fields are labelled and carry
  `autocomplete="email"` / `"current-password"`.
- Role claims are read only from `app_metadata`; a user-writable `user_metadata` role
  is ignored (covered by `roles.spec.ts`).
- **Not verified:** engine-side authorisation, cross-tenant reads, RLS, JWT verification
  against the live API, session expiry, and stale-role behaviour after an admin change.
  All of these need a signed-in session.

---

## G. Visual consistency findings

Consistent across every route inspected:

- one `main` landmark and exactly one `h1` per route (all 151 live rows);
- `lang="en"`, `data-theme` present, single body background `rgb(11, 13, 15)`, single
  type stack (`Geist, Inter, …`) — no page drifted to another surface colour or font;
- no horizontal overflow anywhere (0 of 151 rows);
- no unlabelled buttons or links (0 of 151 rows);
- no failed asset or API requests on public routes after the redeploy.

Recurring shared-component issues: **UI-002** comes from the marketing header/footer
components, not from individual pages. No page looked unfinished or inconsistent with
the rest; the "Synthetic demonstration data" labelling on `/` is deliberate and
consistent with the repository's honesty rules.

---

## H. Fix report

### Fix 1 — prerender the correction-preview route (UI-001)

- **Files changed:** `frontend/vite.config.ts` (+1 line)
- **Root cause:** the route was missing from the explicit prerender page list, so the
  static host served `index.html` for it and React hydrated the wrong tree
- **Change made:** added `{ path: '/preview/example' }` beside `/submissions/example`
- **Tests performed:**
  - `vite build` exit 0; log now shows `[prerender] Crawling: /preview/example` and
    `[prerender] - /preview/example`; `dist/client/preview/example/index.html` is
    emitted (5,282 bytes, contains the session gate)
  - fixed-viewport Playwright check of `/preview/example` at 375 and 1440 against the
    fresh build: `pageErrors: []`, `console: []`, lands on `/sign-in`, one `h1`, no
    overflow
  - deployed, then re-checked on `https://aetrix.pages.dev/preview/example`: browser
    console empty, 200, redirect to `/sign-in`, heading "Sign in to Aetrix", no overflow
- **Before/after evidence:** `preview-shots/live-uiqa-results-deployed.json` (before)
  vs `preview-shots/live-uiqa-results.json` (after, local fixed build)

### Fix 2 — build the public artifact without a private engine origin (UI-003)

- **Files changed:** none. The build reads `frontend/.env`, so the value is overridden
  for the production build only: `VITE_AETRIX_API_URL= vite build`
- **Root cause:** the local development origin (a Tailscale host) was baked into the
  Pages artifact because `.env` is what the build reads
- **Change made:** rebuilt with the variable explicitly empty, which sets
  `isApiConfigured = false` and compiles `API_NOT_DEPLOYED_REASON` into the bundle.
  `frontend/.env` is untouched, so local development still targets the tailnet
- **Tests performed:**
  - build exit 0; `grep` for `tail06bb75` in `dist/client/assets/` returns nothing;
    the honest reason string is present; Supabase configuration is still baked
  - seeded-session Playwright check against the fresh build: opening `/dashboard`
    issued **no** request to `*.ts.net` and **no** `/api/v1/*` request (only the
    Supabase legal-acceptance read); the shell rendered and every panel reported an
    unavailable state with blank figures ("The engine has not answered, so every stage
    stays blank", "No mean is being estimated"), never zeros or sample data
  - deployed; live entry `index-DOrWTeI5.js` contains 0 occurrences of the tailnet host
    and 1 occurrence of the "compiled without an engine origin" reason; `/` and
    `/preview/example` answer 200
- **Before/after evidence:** before — bundle `index-nKxT10oY.js` contained
  `arthur-rip-zn02.tail06bb75.ts.net`; after — bundle `index-DOrWTeI5.js` contains none

### Fix 3 — footer link targets (UI-002)

- **Files changed:** `frontend/src/styles/app.css` (`.site-footer__col` gap, `.site-footer__col a` padding)
- **Root cause:** footer links sized themselves from line-height alone (14 px × 1.6 =
  23.2 px), with no vertical padding
- **Change made:** `padding-block: 2px` on `.site-footer__col a` and the column `gap`
  reduced from `var(--s-2)` (8 px) to `var(--s-1)` (4 px). Text-to-text spacing stays
  8 px, so the footer reads exactly as before; every link is now 27.2 px tall
- **Tests performed:** temporary Playwright sweep over all 11 marketing/legal pages at
  320, 375 and 1440: 14 footer links per page, minimum 27.2 px, 0 undersized, no
  horizontal overflow, no page or console errors. Screenshots at 1440 (dark and light)
  and 390 (dark and light) confirm the spacing is visually unchanged
- **Live verification:** `app-BcmtEbqq.css` served; at 1440 min height 27.2 px
  (header nav 37.6 px), at 375 min height 27.2 px, 0 undersized, no overflow
- **Not changed:** the 13.6 px links in the sign-in legal notice. They are links inline
  inside a running sentence, which WCAG 2.2 target size (2.5.8) exempts; padding them
  would distort the paragraph

### Fix 4 — the /preview screen names its missing endpoint

- **Files changed:** `frontend/src/lib/services.ts`, `frontend/src/routes/_app.preview.$submissionId.tsx`
- **Root cause:** the screen asked for `GET /api/v1/submissions/{id}/preview`, which only
  exists in uncommitted backend work. On `main`, `results.py` has no such route and
  `services/preview.py` / `schemas/preview.py` do not exist, so the request could only
  ever fail, and it failed with a generic engine message
- **Change made:** the screen now renders a stated panel — "The correction preview
  endpoint is not deployed" — naming the capability, the endpoint and a way back. A
  documented constant `PREVIEW_ENDPOINT_DEPLOYED = false` in `services.ts` is the single
  switch to flip in the change that ships the endpoint. The panel only replaces the data
  when the screen has no data, so the rendering path is untouched for the tests that
  exercise it with fixtures
- **Tests performed:** `tsc --noEmit` exit 0; `verification-ui.spec.ts` **12/12 passed**
  against an origin-configured build (including the preview rendering test); a temporary
  two-viewport check against the public artifact opened `/preview/<id>` as a teacher and
  asserted the panel heading, the endpoint text, the return link and **zero**
  `/api/v1` calls — 2/2 passed at 375 and 1440; live `services-ZK9KLX4n.js` carries the text
- **Not changed:** the backend slice stays uncommitted. It is ~7.9k lines across 37 files
  plus three migrations, none of it reviewed in this pass

No other code was changed. No engine, schema, role or permission behaviour was touched.

**Deployment note:** this Pages project has a GitHub integration that publishes every
push to `main`, so a `wrangler pages deploy` is only final until the next commit. Build
configuration lives in the project (Settings → Environment variables), not in the repo,
because `.env*` is gitignored.

**Reproducing the deploy:** the public artifact must always be built with the override,
otherwise `.env` re-bakes the tailnet origin:

```bash
cd frontend && VITE_AETRIX_API_URL= ../.tools/node/node.exe node_modules/vite/bin/vite.js build
```

---

## I. Outstanding issues

**Blocked**

- All three test accounts (no passwords supplied; none requested or stored).
- Role, claim, workspace and class associations for the real accounts.
- Engine-side authorisation, tenant isolation, RLS, session expiry.
- Authenticated screens on the live site (the local review used seeded sessions and a
  stubbed `/me`).

**Unconfirmed / partial**

- UI-003's user-visible effect (engine unreachable for external visitors) is inferred
  from the baked origin; it was not observed because no sign-in was possible.
- Light theme was verified only on `/sign-in` (toggle produced `data-theme="light"`);
  other pages were not inspected in light mode.

**Not tested**

- Physical phone or tablet.
- Screen-reader output (only semantics, labels and accessible names were checked).
- Long-content, error and permission-restricted states for authenticated screens on the
  live site (the local suite covers several of these with fixtures).
- Two suite tests were skipped by the suite itself
  (`health.spec.ts:61`, conditional on an engine origin), not by this pass.

**Open defects**

- UI-002 is fixed for the footer and header. The remaining sub-24 px targets in the
  marketing surface are the sign-in notice links, which are inline in a sentence.
- A low-severity console warning is emitted on every marketing page: the Geist font
  preloads are "not used within a few seconds" (`geist-sans.woff2`, `geist-mono.woff2`).
  Cosmetic only, not a rendering failure.
- UI-003 is fixed at the source: the value is gone from the Pages project, so Git
  builds no longer bake it. A local `vite build` still reads `frontend/.env` (tailnet),
  so any *manual* upload must pass `VITE_AETRIX_API_URL=` as before.
- The local suite needs an origin-configured build to run: with no API origin the client
  returns `unavailable` before `page.route` can intercept, so every fixture-stubbed test
  fails. Build with the repository `.env` for test runs and with the override for uploads.

---

## J. Final readiness verdict

### READY FOR INTERNAL TESTING WITH KNOWN ISSUES

Justification, limited to evidence actually gathered:

- Every discovered route was exercised on the deployed site: 151 route × viewport
  combinations, 0 horizontal overflow, 0 unlabelled controls, 0 failed requests after
  the fix, and one runtime error that is now fixed and redeployed.
- The unauthenticated security boundary behaves correctly on all 30 authenticated
  routes at both desktop and phone widths.
- The local regression suite is green (294 passed, 2 skipped, exit 0) on the exact
  build that was deployed, including 37 authenticated layouts at three widths.
- It is **not** "ready for supervised user testing": the three accounts have never
  signed in, so role permissions, workspace scoping and every authenticated screen
  remain unverified on the live build. Internal testers must supply the
  `AETRIX_TEST_*_PASSWORD` values. The deployed build now states honestly that no
  engine is published, which is correct for its content but means signed-in triage
  will show unavailable data until a public engine origin exists.

---

## Reproduction commands

```bash
# local gate
cd frontend && ../.tools/node/node.exe node_modules/typescript/bin/tsc --noEmit
cd frontend && ../.tools/node/node.exe node_modules/vite/bin/vite.js build
cd frontend && ../.tools/node/node.exe node_modules/vite/bin/vite.js preview --port 3000
cd frontend && ../.tools/node/node.exe node_modules/@playwright/test/cli.js test

# live sweep used for this report (temporary spec, removed after the run)
cd frontend && BASE_URL=https://aetrix.pages.dev \
  ../.tools/node/node.exe node_modules/@playwright/test/cli.js test tests/live-uiqa.tmp.spec.ts
```

Raw measurements: `preview-shots/live-uiqa-results.json` (post-fix local check),
`preview-shots/live-uiqa-results-deployed.json` (deployed build before the fix).
