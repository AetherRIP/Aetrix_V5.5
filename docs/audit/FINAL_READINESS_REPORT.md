# Final Readiness Report

**Audit date:** 2026-11-03 · **Verdict: READY WITH REQUIRED CHANGES**

Four separate questions were asked, because they have different answers and different costs of being wrong.

| Question | Answer |
|---|---|
| Can UI design start? | **Yes**, with two caveats (permission scope, review-draft model) |
| Can the architecture be approved? | **No** — 8 required changes |
| Can implementation start? | **No** — and P2 cannot start until identity is reconciled |
| Can this launch to a customer? | **No** — 8 further changes, one of them expensive |

## 1. Issues that block UI design

Design work (P3) is the least blocked activity in the plan and should not wait for the architecture fixes.

| # | Issue | Why it blocks design | Fix |
|---|---|---|---|
| D1 | Permission footnotes ² ⁴ ⁶ cannot be enforced (SEC-04) | Screen states for a `viewer` or an assistant's PII scope cannot be drawn until the model is decided | Decide resource-aware policy, or delete the footnotes |
| D2 | Review-draft model undecided (UX-01) | The review canvas needs to know whether it autosaves to the server or holds a local draft — it changes the save affordance, the conflict UI and the session-expiry interstitial | Pick one; add to the canvas spec |

Neither is a design failure; both are upstream decisions that the design layer accurately exposes. Everything else
in the design package — tokens, density, keyboard model, responsive stances, accessibility gates — can proceed.

## 2. Issues that block architecture approval

These change the shape of the system. Approving the architecture without them approves a known defect.

| # | Issue | Finding |
|---|---|---|
| A1 | No atomic boundary between job row and queue message | ARC-01 / REL-01 (**CRITICAL**) |
| A2 | No reaper for jobs stuck `running` with an expired lease | ARC-02 |
| A3 | Identity schema incompatible with the chosen auth library | DB-01 |
| A4 | Tenant consistency enforced by convention, not constraint | DB-03 / SEC-05 |
| A5 | Support-access path (the only deliberate cross-tenant door) unspecified | SEC-01 |
| A6 | Mark integrity not enforced at the data layer | DB-05 |
| A7 | R2 has no versioning or replication; the file backup plan is not implementable | REL-03 |
| A8 | Four platform claims in the decision record are false | ADR-001/006, ARC platform table |

Total effort: roughly two tables, two crons, four constraints, one schema reconciliation, one context variant and
a documentation correction. No decision needs reversing.

## 3. Issues that block implementation

Everything in §2, plus:

| # | Issue | Finding |
|---|---|---|
| I1 | MFA cannot be enforced for passkey/OAuth sign-in as configured | SEC-02 |
| I2 | Auth rate limiting is in-memory by default on Workers | SEC-03 |
| I3 | Session lifetime and role-change staleness exceed the stated policy | SEC-08 |
| I4 | No `api_keys` table though the API and permission model require scoped keys | DB-02 |
| I5 | Soft delete collides with every workspace-scoped unique constraint | DB-04 |
| I6 | Six endpoints missing against advertised screens and journeys (results, exports, notifications, operations, bulk cap, preferences) | API-01…04, 06 |
| I7 | Dead-letter queue absent; `max_retries` defaults to 3 and then the message is deleted | ARC-06 / REL-10 |
| I8 | Support access ships in P9, after the first external customer exists | ROAD-01 |
| I9 | PDF render host undecided and uncosted | ARC-04 / COST-01 |
| I10 | Recovery procedure has no script and no rehearsal environment (D1 has no clone) | REL-04 |

## 4. Issues that can be deferred

Explicitly **not** blockers. Treating these as blockers would delay the product for no benefit.

| # | Item | Why it can wait |
|---|---|---|
| F1 | Durable Object realtime | Polling covers the only real need (progress); the DO design is sound and can be added later without rework |
| F2 | Presence, live cursors, collaborative editing | Correctly deferred already; versioning solves the actual conflict |
| F3 | Billing (Stripe) | Metering-first is the right sequencing; DB-07 makes the data trustworthy |
| F4 | SSO / SCIM | WorkOS bolt-on when a customer pays for it |
| F5 | Per-tenant databases (option C) | Designed for, not needed below ~250 workspaces |
| F6 | `saved_views`, analytics hub, status page, changelog | No MVP value |
| F7 | V5 data importer | Q5 is open; ADR-015 should be downgraded, not built |
| F8 | `double_check`, teams/sub-organisations, multi-LMS | Genuinely later |
| F9 | WPF client retirement mechanics | Already out of MVP scope |
| F10 | Dark-theme token measurement, micro-label floor | Design-phase polish, not a blocker |

## 5. Risk if the required changes are skipped

| Skipped item | Likely consequence, in order of appearance |
|---|---|
| Outbox / reaper | First "queued since Tuesday" support ticket within weeks of the first pilot; no diagnostic path; manual D1 surgery |
| Identity reconciliation | P2 slips by weeks, or ships with duplicate identity rows and a stale-membership bug |
| Tenant triggers | A cross-tenant row appears during P5 (bulk upload is the likely source); invisible until a report joins without a predicate |
| Support-grant specification | An operator reads customer data through a session flag; the first incident is also the first breach |
| R2 replication | A prefix deletion during cleanup is unrecoverable; the backup document has promised otherwise |
| PDF host decision | P7 blocks; the cheap option (browser print) contradicts the reproducibility requirement |
| Permission model | A `viewer` sees per-student marks; the matrix says they cannot — a privacy incident with a written contradiction attached |

## 6. Confidence in this audit

| Area | Confidence | Basis |
|---|---|---|
| Platform facts | **High** | Official documentation read on the audit date; each claim quoted with its URL |
| Multi-tenant security | **High** | Findings are structural and checkable against the documents themselves |
| Database and API gaps | **High** | Enumerated by comparing catalogues and route tables line by line |
| Cost estimates | **Medium** | Assumptions are explicit; unit prices verified; the AI variable remains genuinely unknown |
| UX judgements | **Medium** | Based on the stated personas and workflow, not on user testing |
| Scalability beyond 250 workspaces | **Low** | Not modelled; would need measurement, not analysis |

Where this audit could be wrong: the storage projection (COST-02) depends on the size of AI explanations, which
nobody has measured; the DO verdict (ARC-03) would flip if progress latency proves unacceptable to markers; and the
permission-model finding (SEC-04) is severe only if the footnotes were meant literally rather than aspirationally.

## 7. Recommended next actions, in order

1. Owner approves or rejects the eight Gate-1 changes (one working session; `RECOMMENDATIONS.md`).
2. Correct the four false platform claims in ADR-001/006 and the Cloudflare document — this is editing, and it
   restores the package's credibility as a decision record.
3. Reconcile the identity schema against Better Auth and record the mapping (blocks P2).
4. Run the P1 parity spike **including** the failure paths (429/503/401, missing question, overwrite guard) and
   settle the PDF host with measured cost.
5. Only then start P2, with the isolation suite and the two durability crons as exit criteria.

## 8. Closing assessment

The plan is worth building. That is the finding that matters, and it survives a hostile reading: the tenancy model,
the job semantics, the marking-integrity invariants and the design language are all better than what a team
typically starts from.

What it is not is **finished**. It reads like a plan written by someone who thought hard about the hard parts and
then, near the end, wrote the operational and data-lifecycle sections from memory. The result is a package where
the marking pipeline is specified to the retry class, and the backup strategy depends on a storage feature that does
not exist.

The distance between here and implementation is measured in days of focused work, not weeks — provided the eight
architecture items are treated as prerequisites rather than as backlog. The failure mode to avoid is the one this
audit was commissioned to catch: approving the package because it is impressive, and discovering ARC-01 in
production.
