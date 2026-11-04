# Requirement Traceability

**Audit date:** 2026-11-03. Each requirement is traced from its statement to the design that expresses it, the
architecture that implements it, the phase that delivers it, and the test or criterion that proves it. The last
column records the audit verdict.

Status key: **T** traced end to end · **G** gap (a link is missing) · **W** weak (a link exists but does not
prove the requirement) · **X** contradiction (links disagree).

## 1. Product and integrity requirements

| ID | Requirement | Source | Design / screen | Architecture / data | Phase | Proof | Status |
|---|---|---|---|---|---|---|---|
| R01 | Missing question → `needs_review`, never `0` | Vision §promise 1 | S34 review canvas | `question_results.needs_review`; workflow step 6 | P1 | ACC §2 bullet 3; TS §2.1 | **T** |
| R02 | Marking is deterministic (temp 0, fixed seed) | Vision; V5 engine | — | Workflow step 4 params | P1 | ACC §2 "repeat run identical" | **T** |
| R03 | A mark can never exceed the question maximum | Vision; J4 | S34 | API 422; **no DB CHECK** | P1/P5 | ACC §2 bullet 4 | **W** — DB-05 |
| R04 | Verification reports, never rewrites | Vision | S34 explanation | `verify` step, read-only | P1 | TS §2.1 | **T** |
| R05 | Override requires reason + actor + time | J4 | S34 | `overrides` row | P5 | ACC §6 "override requires reason" | **T** |
| R06 | Approval is a separate permission | Roles §3 | S34 | `correction.approve`; `approvals` | P5 | ACC §6 | **T** |
| R07 | The browser never marks; no key reaches the client | Vision §promise 2 | — | Server-side jobs; SC-2 | P5 | Contract test asserting absence | **T** |
| R08 | Interrupted remote write → `NEEDS_VERIFICATION`, never a guess | Vision §promise 5 | S27, S37 | `automation_operations` | P6 | ACC §7 timeout case | **T** |
| R09 | `CH1L1` lesson identity preserved (chapter never dropped) | Feature inv. §3 | S30, S37 | `assignments.lesson_code` | P4 | ACC §5 | **T** |
| R10 | Blueprint lock required before marking | J3 | S30 | `mark_schemes.locked_at`; 409 | P4 | ACC §5 | **T** |

## 2. Tenancy, identity and access

| ID | Requirement | Source | Design | Architecture / data | Phase | Proof | Status |
|---|---|---|---|---|---|---|---|
| R11 | One workspace cannot read another's data | Vision §promise 3 | — | 4-layer `TenantContext` | P2 | Isolation suite (16 resources × 3) | **T** |
| R12 | Cross-tenant ids return 404, not 403 | Roles §5.4 | S"permission-denied" page | Route + repository | P2 | ACC §3; isolation §2 | **T** |
| R13 | Cross-tenant child rows are impossible | Multi-tenancy §3.5 | — | Application assertion only | P2 | none | **G** — DB-03 |
| R14 | Roles are a closed permission bundle, enforced server-side | Roles §1 | all gated screens | Policy function | P2 | Policy unit tests | **W** — parts unexpressible (SEC-04) |
| R15 | Invitations are single-use, 7-day, email-bound | J2; AU-10 | S19 | `invitations` | P2 | ACC §3 e2e | **T** |
| R16 | MFA required for owner and operator | AU-4 | S18 | Better Auth 2FA | P2 | "owner cannot skip MFA" | **G** — not achievable by config (SEC-02) |
| R17 | Session revocation takes effect on next request | Roles §5.5, §6 | S23 | DB sessions + cookie cache | P2 | "removed member 401" | **W** — cache window (SEC-08) |
| R18 | Role change is effective immediately | Roles §5.5 | — | membership lookup | P2 | not tested | **W** — documented claim is false for cookie cache |
| R19 | Provider keys never returned, never logged | SC-2 | S46 | `provider_credentials` encrypted | P5 | Contract "asserting absence" | **T** |
| R20 | Scoped API keys cannot manage members/credentials | Roles §5.6 | — | **no table defined** | P5 | — | **G** — DB-02 |
| R21 | Support access is consented, scoped, audited, expiring | J7; SA-1…6 | S53 | `support_grants` | **P9** | ACC §9 (expiry + banner) | **G** — mechanism unspecified (SEC-01), scoped tests absent, and **ships after MVP** (ROAD-01) |

## 3. Files, jobs and integration

| ID | Requirement | Source | Design | Architecture | Phase | Proof | Status |
|---|---|---|---|---|---|---|---|
| R22 | Uploads validated (type, size, magic bytes, page cap) | IN-3 | S32 | Upload route | P5 | ACC §6 truncated/masquerade | **T** |
| R23 | Every job reaches a terminal state | Vision metric ≥99%/24h | S33, job drawer | Queues + Workflows | P5 | ACC §6 lifecycle | **G** — ARC-01/02 |
| R24 | Duplicate submissions create one job and one provider call | J6; Feature inv. | — | `idempotency_key` | P5 | ACC §6 duplicate | **T** |
| R25 | Rate limit parks without consuming attempts | BP §3 | job drawer | retry classification | P5 | ACC §6 429 case | **T** |
| R26 | 401/invalid → never resend | BP §3 | job drawer | classification | P5 | ACC §6 401 case | **T** |
| R27 | Cancel leaves no partial result | BP §6 | S33 | cancel flag + discard | P5 | ACC §6 cancel | **T** |
| R28 | Progress visible without a browser tab open | J6 | S33 | DO or polling | P5 | — | **W** — DO deferred (ADR-008) |
| R29 | Classroom is optional at every step | J3; Feature inv. | S48 | integration layer | P6 | ACC §7 manual path | **T** |
| R30 | Grade publish 403 has an actionable fallback | J3 | S27 | `automation_operations` state | P6 | ACC §7 | **T** |

## 4. Reporting, data and operations

| ID | Requirement | Source | Design | Architecture | Phase | Proof | Status |
|---|---|---|---|---|---|---|---|
| R31 | Class report PDF, reproducible, printable | Feature inv. §4 | S37 | **host undecided** (containers) | P7 | ACC §8 (escape hatch on reproducibility) | **G** — ARC-04, COST-01 |
| R32 | Grade matrix on screen and as CSV | S36 | S36 | **no endpoint** | P7 | ACC §8 | **G** — API-01 |
| R33 | Workspace export, tenant-scoped | J8; DP-3 | S49 | Workflow | P9 | — | **G** — API-02, SEC-09 |
| R34 | Deletion: 14-day grace, purge, tombstone | J8; DP-4 | S49 | purge Workflow | P9 | Restore/deletion drill | **W** — no purge test in ACC |
| R35 | Audit log append-only, 12 months | LG-3/4/5 | S43 | `audit_log` | P9 | "code review + test" | **W** — no mechanism (DB-11) |
| R36 | Usage metered per job, quota enforced | ADR-009; AB-3 | S47 | `usage_events`, `usage_daily` | P5 | ACC §6 quota blocks | **W** — double-count risk (DB-07) |
| R37 | Backups restorable, drills run | BP §6 | — | exports to R2 | P10 | quarterly drill | **G** — files unrecoverable (REL-03); no script (REL-04) |
| R38 | In-app + email notifications, preferences | Feature inv. §5 | S25, S45 | `notifications` | P8 | ACC §9 | **G** — no endpoints (API-03), no prefs table (DB-09) |
| R39 | Observability: SLOs, alerts, runbooks | MON §1 | S52 | Workers Logs, Analytics Engine | P9 | Manual | **W** — blind to job loss (REL-02) |

## 5. Experience requirements

| ID | Requirement | Source | Design | Phase | Proof | Status |
|---|---|---|---|---|---|---|
| R40 | WCAG 2.2 AA across app and marketing | Accessibility §1 | tokens, components | P3 | axe + manual gates | **T** |
| R41 | Full keyboard operation, visible focus | Accessibility §2 | shortcut model | P3 | keyboard walkthrough | **W** — canvas focus model unspecified (UX-10) |
| R42 | Desktop-first with graceful reduction | Responsive §2 | breakpoints per screen | P3 | manual | **T** |
| R43 | Design system: tokens, states, no one-offs | Design system §8 | D1 | P3 | ACC §4 | **T** |
| R44 | Review work is never lost on interruption | implied by J5 | S34 | P5 | — | **G** — UX-01 |
| R45 | Supervisor can audit marking quality (sampling) | Vision metric ≥10% | **no screen** | — | — | **G** — UX-03 |
| R46 | Workspace switching is safe | IA `/workspaces` | S20 | P2 | — | **G** — UX-05 |

## 6. Features with no acceptance criterion anywhere

`double_check` (deferred but referenced), saved views, analytics hub beyond overview, docs/help centre, status page,
changelog, platform audit search, notification preferences, bulk reassignment on member removal, student erasure
with published marks, and the support-grant **scope** check (only expiry is tested).

## 7. Roadmap ordering review

The proposed order is broadly correct and challenges the brief for the right reasons. Two defects:

### ROAD-01 — HIGH — Support access ships after the first customer
**Documents:** `product/PRODUCT_ROADMAP.md` (P9 "Administration + observability", outside the MVP cut line) vs
`security/SECURITY_REQUIREMENTS.md` SA-1…SA-6 (no standing access) and `product/USER_JOURNEYS.md` J7.
The MVP deliberately excludes the platform admin surface and the consent-grant mechanism. But the MVP launches to
design-partner schools, and operators will immediately need to diagnose their data. The only available tool at that
point is raw D1 access — precisely what SA-1 forbids. The control therefore exists on paper and is violated in
practice from day one.
**Resolution:** move the support-grant mechanism (not the whole admin surface) into P5/P6, before the first external
workspace. It is a small feature: a table, one endpoint each side, a context variant, an audit row and a banner.

### ROAD-02 — MEDIUM — P3's parallelism is contradicted by the dependency graph
See DOC-07. Draw P3 as a parallel branch with an explicit merge, or make it sequential and accept the schedule.

### ROAD-03 — MEDIUM — Bulk import (P4) precedes file upload (P5) but depends on its validation rules
CSV import validates student rows; the upload path validates files. Both share the duplicate-detection logic that
the acceptance criteria test separately (ACC §5 "duplicate student detected" vs ACC §6 "duplicate submission").
No dependency is drawn between them, so the same rule will be implemented twice.
**Resolution:** extract duplicate detection as a domain service in P4 and require P5 to reuse it (this is exactly
the "domain services are shared" rule in `SYSTEM_ARCHITECTURE.md` §2 — the roadmap does not apply it).

## 8. Traceability scorecard

| Group | Requirements | Traced | Weak | Gap | Contradiction |
|---|---|---|---|---|---|
| Product / integrity | 10 | 8 | 1 | 1 | 0 |
| Tenancy / identity | 11 | 5 | 3 | 3 | 0 |
| Files / jobs / integration | 9 | 7 | 1 | 1 | 0 |
| Reporting / data / ops | 9 | 0 | 4 | 5 | 0 |
| Experience | 7 | 4 | 1 | 2 | 0 |
| **Total** | **46** | **24 (52 %)** | **10 (22 %)** | **12 (26 %)** | **0** |

The asymmetry is informative: **every** marking-integrity requirement is traced end to end, and **none** of the
data-lifecycle group is. The package's attention followed the product's pride, not its risk — which is why the
gaps cluster in export, deletion, backup and notification rather than in marking.
