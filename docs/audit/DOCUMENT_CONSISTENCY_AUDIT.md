# Document Consistency Audit

**Audit date:** 2026-11-03. Every document was read in full and cross-checked against the others. Findings are
limited to real contradictions, missing links and unsupported figures — not stylistic preferences.

## 1. Contradictions

### DOC-01 — HIGH — Three documents disagree on whether V5 data is migrated
**Documents:** `decisions/ARCHITECTURE_DECISIONS.md` ADR-015 (status: Accepted) vs
`decisions/OPEN_QUESTIONS.md` Q5 (default: "**No automatic migration**") vs `architecture/DATABASE_DESIGN.md` §8
("**No V5 data is migrated automatically** — an importer is a separate decision").
**Problem.** ADR-015 is written as an accepted decision describing a migration that "reads V5 SQLite exports and
writes through the public API path". Two other documents state the opposite as the default position. An accepted
ADR outranks an open question's default, so a reader implementing P1 could reasonably start building an importer.
**Resolution.** Downgrade ADR-015 to "shape if Q5 answers yes", or answer Q5. One statement, three files.

### DOC-02 — HIGH — The permission matrix promises row-level restrictions the API cannot express
**Documents:** `product/USER_ROLES_AND_PERMISSIONS.md` §4 footnotes ² ⁴ ⁶ vs `architecture/API_DESIGN.md` §7–§8.
Detailed in `MULTI_TENANT_SECURITY_AUDIT.md` SEC-04. Recorded here because it is first a documentation
inconsistency: two normative documents describe different systems.

### DOC-03 — HIGH — The workspace export exists in a journey and not in the API
**Documents:** `product/USER_JOURNEYS.md` J8 vs `architecture/API_DESIGN.md` §4 (only `/me/export`).
`MULTI_TENANCY.md` §7 describes the Workflow; `SECURITY_REQUIREMENTS.md` DP-3 requires it; no endpoint exists.
See SEC-09 / API-02.

### DOC-04 — HIGH — Screen 36 (grade matrix) has no endpoint
**Documents:** `design/SCREEN_INVENTORY.md` §36 vs `architecture/API_DESIGN.md`.
See API-01.

### DOC-05 — MEDIUM — `PRODUCT_VISION.md` contains a duplicated paragraph
**Document:** `product/PRODUCT_VISION.md`, "Product promise" list. Principle 5 ("The supervisor can always answer
…") appears **twice**, verbatim, consecutively. The document therefore advertises six promises in a list numbered
to five.
**Resolution.** Delete the duplicate. Low effort, but a decision document with a copy-paste artefact invites doubt
about the rest of its editing.

### DOC-06 — MEDIUM — The screen inventory miscounts itself
**Document:** `design/SCREEN_INVENTORY.md`, header says "**48 screens**". The tables enumerate **54** numbered
screens (13 public + 10 auth/onboarding + 21 core + 10 settings/admin), plus 7 unnumbered additions described in
the closing section.
**Resolution.** Correct the count to 54 (+7 states), or number the additions.

### DOC-07 — MEDIUM — The roadmap's dependency diagram contradicts its own phase text
**Document:** `product/PRODUCT_ROADMAP.md` §"Phase detail" says P3 "runs partly in parallel with P2 (different
people)", while the dependency block states `P0 → P1 ─┬→ P2 → P3` — strictly sequential with P1 conditional.
Two readers get two plans.
**Resolution.** Draw P3 as a parallel branch off P1/P2 with an explicit merge point.

### DOC-08 — MEDIUM — "Workspace admin" is both in the MVP and in P9
**Document:** `product/PRODUCT_ROADMAP.md`. The MVP cut line lists "workspace admin only" as **in** MVP, while
P9's objective is "Administration + observability … **workspace admin complete**", and P9 is outside the MVP cut.
**Resolution.** Split the term: "workspace settings (P4/P5)" vs "workspace administration surface (P9)".

### DOC-09 — MEDIUM — MFA is mandatory in one document and absent from the onboarding journey in another
**Documents:** `security/SECURITY_REQUIREMENTS.md` AU-4 (MFA **required** for `workspace_owner`) vs
`product/USER_JOURNEYS.md` J1 (signup → workspace → first marked script in < 15 min, no MFA step) and
`design/SCREEN_INVENTORY.md` §22 (onboarding checklist of six steps, no MFA).
The workspace creator is the owner, so the mandatory control applies to every new customer at the moment of
highest friction.
**Resolution.** Either enforce MFA at first sensitive action rather than at creation, or add the step to J1 and
the checklist and revise the 15-minute target honestly.

### DOC-10 — MEDIUM — Double marking is both deferred and available
**Documents:** `product/FEATURE_INVENTORY.md` §1 (`double_check.py` classified **D = explicitly deferred**) vs
`decisions/OPEN_QUESTIONS.md` Q14 (default: "Off by default; **available per assignment**").
**Resolution.** Pick one; if deferred, Q14's default should be "not built".

### DOC-11 — MEDIUM — Targets in the monitoring document differ from the targets in the vision
**Documents:** `operations/MONITORING_AND_LOGGING.md` §1 ("correction success < 98 % over 1 h → page"; "p95
time-to-terminal > 6 min → investigate") vs `product/PRODUCT_VISION.md` ("≥ 99 % within 24 h"; "median end-to-end
≤ 90 s").
98 % over 1 h and 99 % over 24 h can both be true, but nothing states the relationship, and the two documents
will be read as competing promises by whoever sets alerts.
**Resolution.** Define one primary SLO set (e.g. 99 % terminal in 24 h, p95 ≤ 10 min) and derive the hourly
alert thresholds from it.

### DOC-12 — MEDIUM — Edge rate limits assume a plan tier the deployment plan never selects
**Documents:** `architecture/CLOUDFLARE_ARCHITECTURE.md` §7, `security/SECURITY_REQUIREMENTS.md` AB-1 vs
`operations/DEPLOYMENT_PLAN.md` (no Cloudflare plan named; cost doc budgets Workers Paid only).
Cloudflare's rate-limiting rules are 1/2/5/100 by plan; the design lists four rules plus WAF managed rules, which
require Pro or above. The cost document omits the plan tier entirely (COST-06).
**Resolution.** Name the required plan in the deployment plan and its cost in the budget.

### DOC-13 — LOW — `usage_daily` is hourly in one document and monthly in another
`DATABASE_DESIGN.md` §5 defines `usage_daily` as a day rollup, `BACKGROUND_PROCESSING.md` §8 runs the rollup
hourly, and `COST_AND_SCALABILITY.md` §7 refers to monthly figures. Not wrong, but three different periods are
implied without a stated relationship.
**Resolution.** State: events → hourly job → `usage_daily` (day grain) → monthly view.

### DOC-14 — LOW — Unsupported figure: the D1 REST API rate limit
`architecture/MULTI_TENANCY.md` §1 cites "account API rate limits (1,200 requests / 5 min default)" with no
source. It is used to argue against database-per-tenant — an argument that does not need the number, since the
missing dynamic bindings are decisive on their own.
**Resolution.** Cite it or drop it.

### DOC-15 — LOW — Two names for the project
`README.md` says "**Workspace:** `TEMP` (future `UI_V5.5`)", documents use `UI_V5.5`, `V5.5` and
`UI_Webpage_V5.5`, and the folder is `UI_Webpage_V5.5`. Since the brief forbids renaming and the docs are the
contract, state once which is the product name and which is the directory.

### DOC-16 — LOW — `D6` is asserted to be the look of V5 without evidence
`design/DESIGN_DIRECTIONS.md` D6 claims "**This is what V5 already looks like**" and quotes a V6 audit. The V6
document is cited, but the audit package itself is the first place a reader meets the claim, and no V5 screenshot
or token list supports it. Harmless, but it is the kind of unverified assertion the package elsewhere forbids.

## 2. Missing user journeys

The eight journeys cover the happy paths well and the failure branches unusually well. Missing:

| # | Missing journey | Why it matters | Where it leaks |
|---|---|---|---|
| J9 | **Sampled supervisor review** ("mark ≥ 10 % of scripts") | It is a headline success metric with no walkthrough, screen, endpoint or permission of its own | Vision metrics vs screens |
| J10 | **MFA enrolment and recovery** | AU-4 mandates it; screens 18/23 exist; no journey covers losing a device | Security vs journeys |
| J11 | **Password recovery** | Screen 17 exists; no journey covers the "verified email changed" branch | Screens vs journeys |
| J12 | **Workspace switching mid-task** | Multi-membership is core to the tenancy model; no journey covers what happens to unsaved work | IA vs journeys |
| J13 | **Member departure** | Removing an assistant orphans their assigned submissions; no reassignment journey | Roles vs journeys |
| J14 | **Student erasure with published results** | Privacy rights require it; publish path has already sent marks to Classroom | Privacy vs journeys |
| J15 | **Concurrent scheme edit** | Two supervisors lock/edit a blueprint; only `locked_at`/`locked_by` exist | DB vs journeys |

## 3. Missing permissions

The 30-key vocabulary is disciplined, but the screens imply keys it does not define:

| Implied by | Missing key |
|---|---|
| Screen 25 (Inbox), notification preferences | `notification.read`, `notification.preferences` |
| `MULTI_TENANCY.md` §7 export workflow | `workspace.export` (currently only `report.export` exists, which is not the same thing) |
| `saved_views` table | `view.read` / `view.write` |
| Screen 43 (Activity) export | `audit.export` (only `audit.read` exists) |
| Screen 47 (Usage) quota edit | `workspace.quota.write` (quota changes are a financial control) |
| Job detail drawer | `job.read` (currently reuses `submission.read`, which conflates "see the script" with "see the pipeline") |

## 4. Missing acceptance criteria

`ACCEPTANCE_CRITERIA.md` is unusually good. Gaps where a phase claims an outcome that is not demonstrated:

| Phase | Claim without a criterion |
|---|---|
| P2 | "Role changes take effect on the next request" — tested for removal, not for demotion or promotion |
| P2 | Session-cache staleness bound is not tested at all (SEC-08) |
| P5 | No criterion for the outbox / stuck-job recovery (ARC-01, ARC-02) |
| P5 | No criterion for the DLQ path (ARC-06) |
| P5 | Metering accuracy (events = rollup) is not asserted, though billing depends on it |
| P6 | "Reconcile settles it read-only" — no criterion that reconcile performs *no* writes |
| P7 | Report reproducibility is "same bytes **or documented variance**" — a criterion with an escape hatch is not a criterion |
| P9 | Support-grant **scope** enforcement (SEC-01) is untested; only expiry and banner are |

## 5. Terminology used inconsistently

| Term | Variants found | Recommendation |
|---|---|---|
| Submission vs script | "script" (product), "submission" (schema) | Keep both, define once: a submission is the record, the script is the file |
| Review vs approval | `needs_review`, `pending_review`, `approved` | `pending_review` appears in J3 but is not in the closed status set (`needs_review` is) |
| Workspace vs organisation | `workspaces` (schema) vs `organization` (Better Auth) | Document the mapping explicitly (DB-01) |
| Parked vs waiting | `parked` (schema), "Waiting" (UI word) | Fine — but state that they are the same thing |
| Quota vs limit | "quota", "limit", "budget" | Three different concepts: quota = per-workspace allowance, budget = per-job attempt cap, limit = platform rate limit |

`pending_review` is the one genuine defect: J3 and `results.status` use different vocabularies, and the design
system's closed status list uses a third spelling. Add it to `submissions.status` or remove it from J3.

## 6. Summary

| Class | Count | Highest severity |
|---|---|---|
| Direct contradictions | 10 | HIGH (DOC-01…DOC-04) |
| Miscounts / duplicated text | 2 | MEDIUM |
| Unsupported figures or claims | 2 | LOW |
| Missing journeys | 7 | MEDIUM |
| Missing permission keys | 6 | MEDIUM |
| Missing acceptance criteria | 8 | HIGH (job durability, support scope) |

The package is internally coherent on its **large** decisions (tenancy, jobs, files, auth, design) and
inconsistent on its **edges** — permission granularity, export, notifications, and the vocabulary at the seams
between product and schema. All findings are fixable by editing; none requires re-architecting.
