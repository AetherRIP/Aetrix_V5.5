# Owner Approval Decisions

**Status:** all decisions below are **PENDING**. Nothing in this document has been approved, assumed or
pre-filled. Each row states the question, the options with their consequences, a recommendation, and what becomes
possible once it is answered.

**No approval is invented here.** Where a remediation document refers to `C1`…`C16`, this is the authoritative
list.

---

## 0. How the decisions are separated

| Category | Meaning | Count | Who decides |
|---|---|---|---|
| **A** | Technical corrections that do not change intended behaviour | 14 | Engineering (recorded, no sign-off needed) |
| **B** | Architectural changes that materially affect implementation | 9 | Engineering + owner awareness |
| **C** | Product decisions requiring owner approval | **16** | **Owner** |
| **D** | Features deliberately deferred | 8 | Owner informs, engineering executes |

Only **C** blocks approval. **A** and **B** are listed so the owner can see what changed without signing 39
separate items.

---

## A. Technical corrections (no behaviour change)

These fix something that was wrong or absent without changing what the product does. Listed for transparency;
none requires a decision.

| # | Correction | Finding |
|---|---|---|
| A1 | Outbox table + publisher cron | ARC-01 |
| A2 | Lease reaper + attempts-on-claim | ARC-02, REL-07 |
| A3 | Real DLQ + consumer + alerts | ARC-06, REL-10 |
| A4 | 23 tenant triggers + schema-enumeration test | SEC-05, DB-03 |
| A5 | Partial unique indexes | DB-04 |
| A6 | Mark `CHECK`, override trigger, derived totals | DB-05, DB-08 |
| A7 | Composite uniques, two missing indexes | DB-06, DB-10 |
| A8 | Usage uniqueness + replace-semantics rollup | DB-07 |
| A9 | Audit immutability triggers + maintenance window | DB-11 |
| A10 | Cron heartbeat table | REL-12 |
| A11 | Provider-recovery sweep on circuit close | REL-05 |
| A12 | Cache-header CI assertions | SEC-10, API-09 |
| A13 | Generic invitation-acceptance response | API-10 |
| A14 | Corrected false platform claims (6) | register §7 |

---

## B. Architectural changes that materially affect implementation

Each changes what gets built, not what the product promises. The owner should know; engineering decides.

| # | Change | Effect on implementation | Reversible? |
|---|---|---|---|
| B1 | Better Auth schema is canonical; `workspace_id = organization.id` | Every migration, repository and test touches this shape | Costly after P2; free now |
| B2 | Timestamps become `INTEGER` epoch ms | Every DTO formats at the edge | Cheap now, painful later |
| B3 | Support access is a context variant, not a session flag | One table, one principal type, three endpoints | Cheap |
| B4 | MFA enforced by an assurance gate above the library | Middleware + session fields + per-method tests | Cheap |
| B5 | Downloads proxied; uploads hybrid (presign > 20 MB) | Two upload paths; no signed downloads | Cheap |
| B6 | Permission model gains a resource dimension + shapers | Every result/student serialization goes through two functions | Moderate |
| B7 | Realtime deferred to polling | Polling ladder + ETag; no socket surface | Cheap both ways |
| B8 | Backup pipeline built on `CopyObject` + bucket lock | New Queue, copier, manifest, reconciliation | Cheap |
| B9 | D1 primary-only reads; replication behind one helper | No bookmark logic in call sites | Cheap |

---

## C. Product decisions requiring owner approval

### The six that block architecture approval

| ID | Decision | Blocks |
|---|---|---|
| **C1** | Identity schema contract (Better Auth canonical) | P2 entirely |
| **C2** | Session lifetime and staleness bound | Auth config, acceptance criteria |
| **C3** | MFA enforcement versus convenience | Onboarding, auth UX |
| **C4** | Upload path (hybrid presign) | P5 upload surface |
| **C5** | Schema change bundle (API keys, outbox, new tables) | P2/P5 migrations |
| **C7** | Report rendering host | P5 (report record), P7 |

`C6`, `C8`–`C16` matter before the phase they touch and do not block architecture approval.

---

### C1 — Identity schema contract

**Question.** Adopt Better Auth's tables as canonical, with product fields added through supported extension
points, and `workspace_id = organization.id`?

**Options.**
1. **Adopt (recommended).** One identity system. `organization` carries product columns via `additionalFields`;
   `member` carries `status`/`joinedAt`; every tenant FK points at `organization(id)`.
2. Keep the product's `users`/`sessions`/`memberships` and do not use the library's org plugin. Requires a
   hand-rolled auth implementation, discarding `ADR-005`.
3. Run both and synchronise. **Rejected**: two writers to one concept always drift, and a stale membership row
   is a security bug.

**Consequences of option 1.** The schema document's `workspaces` table is superseded by `organization`; timestamps
become integers; DDL is generated once and committed; library version is pinned `>= 1.7.16`.
**Recommendation.** Option 1. **Status: PENDING.**

### C2 — Session lifetime and staleness

**Question.** How long may a session live, and how stale may a role claim be?

**Options.**

| Option | Idle | Absolute | Cache staleness | Consequence |
|---|---|---|---|---|
| **1 (recommended)** | 12 h | 7 d | 60 s | A marker re-authenticates once a day; a stolen session is bounded to 12 h of activity |
| 2 | 4 h | 24 h | 30 s | Tighter; a long marking session is interrupted |
| 3 (current) | 7 d | 30 d | unset (effectively minutes) | Convenient; far outside OWASP guidance for minors' data |

**Consequences.** Option 1 costs one sign-in per working day and closes the "demoted user keeps their role"
window to 60 s. Option 3 is cheapest for users and worst for a data-protection review.
**Recommendation.** Option 1. **Status: PENDING.**

### C3 — MFA enforcement versus convenience

**Question.** `AU-4` requires MFA for owners. The library does not gate passkey/OAuth sign-in. How is that
resolved?

**Options.**
1. **Assurance gate (recommended).** Any owner without a second factor cannot perform mutations; sign-in works,
   but enrolment is required before the first write. All methods are covered.
2. Disable passkey/Google for owner and operator roles. Simple, but removes the phishing-resistant method from
   the accounts that need it most.
3. Enforce at sign-in only for password, accept the gap for passkey/OAuth. **Rejected**: it is a documented
   bypass.
4. MFA at workspace creation. Maximum friction at the moment of highest abandonment; also contradicts J1's
   15-minute promise.

**Consequences.** Option 1 adds a step at first sensitive action and keeps the 15-minute target intact.
**Recommendation.** Option 1. **Status: PENDING.**

### C4 — Upload path

**Question.** Presign all uploads, proxy all uploads, or hybrid?

**Options.**
1. **Hybrid (recommended).** ≤ 20 MB proxied (validation and simplicity for the common scan); > 20 MB presigned
   `PUT` with a scoped token, 15-minute expiry, one key.
2. Presign everything. Best throughput; worst validation story and a bearer URL for every small scan.
3. Proxy everything. Simplest authorisation; 200 MB through a Worker, no resumability.

**Consequences.** The 20 MB threshold is revisited after measuring a real 40 MB upload (P1). Downloads are
proxied in all options (authorisation stays revocable).
**Recommendation.** Option 1. **Status: PENDING.**

### C5 — Schema change bundle

**Question.** Approve the additive schema changes as one migration set?

**Contents.** `job_outbox`, `api_keys`, `exports`, `review_drafts`, `sample_reviews`, `notification_preferences`,
`legal_holds`, `idempotency_records`, `platform_operators`, `maintenance_windows`, `rate_limit`, plus
`assignment_question_id`, `mark_schemes.version`, `students.anonymised_at`, `usage_events.source_key`.

**Consequences.** P2 and P5 cannot start without the identity and constraint parts; the product parts (exports,
sampling, drafts) can land later but are cheaper now, while the schema is being written once.
**Recommendation.** Approve as one set. **Status: PENDING.**

### C6 — Backup retention and cost

**Question.** How long are file backups retained, and is the ~$10/month (at 100 workspaces) accepted?

**Options.**
1. **90 days, bucket-locked (recommended).** Recovers a mistaken prefix deletion; ~25 % storage overhead rather
   than 100 %.
2. 30 days. Cheaper; a discovery on day 40 is unrecoverable.
3. 1 year. Safest; lock has no governance bypass, so a year is a hard commitment.

**Consequences.** The lock is the retention control and cannot be bypassed; lifecycle alone can be shortened by
anyone with bucket-admin rights.
**Recommendation.** Option 1. **Status: PENDING.**

### C7 — Report rendering host

**Question.** Which option renders the authoritative report PDF?

**Options.**

| Option | Reproducible | New processor | Cost shape | Risk |
|---|---|---|---|---|
| A. Workers Containers + existing Python | Yes | No | memory × wall-time per render | GA status must be confirmed |
| B. Managed render API | Yes | **Yes — student data** | per document | DPA + sub-processor listing |
| C. Client print-to-PDF | No | No | zero | Cannot attach without a browser |

**Consequences.** The budget cannot be approved with this blank; P5 needs the report record shape, which depends
on it.
**Recommendation.** A if GA and within the measured envelope, else B with a DPA. **Status: PENDING.**

### C8 — Cloudflare plan tier

**Question.** Buy Pro (WAF managed rules, 2 rate-limit rules, ~$25/month) or run on Free/Paid with per-user limits
in the Worker?

**Options.**
1. **Free/Paid + in-Worker limits (recommended for MVP).** One edge rule, D1-backed per-user counters. Saves
   ~$25/month, which at pilot scale exceeds total infrastructure spend.
2. Pro. Managed WAF rules and a second rule; a real security uplift for a public auth surface.
3. Pro later, triggered by the first public signup campaign or the first attack.

**Consequences.** Option 1 is a deliberate acceptance of a thinner edge posture; option 2 is an order of
magnitude more than the rest of the bill at 2–10 workspaces.
**Recommendation.** Option 1 for pilot, revisit at public launch. **Status: PENDING.**

### C9 — Review draft model

**Question.** Server-side drafts, local drafts, or both?

**Options.**
1. **Server-side with local cache (recommended).** Survives device change; diffable against the current version.
2. Local only. No server write per keystroke; lost on device change; cannot be diffed.
3. No drafts. Cheapest; loses the most valuable keystroke in the product.

**Consequences.** Option 1 adds a table and an autosave cadence (2 s debounce); drafts expire at 30 days.
**Recommendation.** Option 1. **Status: PENDING.**

### C10 — Sampled review in the MVP

**Question.** Build sampled supervisor review now, or in P9?

**Options.**
1. **MVP (recommended).** ~4 days: table, permission, three endpoints, a view on the assignment.
2. P9. The buyer's core job has no surface for the whole pilot.
3. Never. Then the "≥ 10 % sampled" success metric should be removed from the vision, not silently unmet.

**Consequences.** Option 1 removes ~4 days from P7/P9 scope elsewhere; option 3 requires editing the vision.
**Recommendation.** Option 1. **Status: PENDING.**

### C11 — Student erasure policy

**Question.** What does "delete this student" mean once marks are published?

**Options.**
1. **Anonymise, retain numerics (recommended).** Aggregates stay correct; PII removed; published grades
   untouched; reports annotated.
2. Delete the row and cascade. Aggregates change silently; published grades orphaned.
3. Refuse erasure once published. Defensible only if disclosed before purchase.

**Consequences.** Option 1 is the only option that satisfies erasure *and* arithmetic integrity; it requires a
privacy-page sentence explaining that published grades are not rewritten without an operator action.
**Recommendation.** Option 1. **Status: PENDING.**

### C12 — Permission model and the `viewer` role

**Question.** Implement resource-aware permissions, or remove the restrictions the API cannot express?

**Options.**
1. **Resource-aware + shapers (recommended).** Keeps the cover-staff persona; the matrix becomes true.
2. Delete footnotes ²⁴⁶; drop `viewer` to a plain read role with no marks at all. Simpler; loses a persona.
3. Remove `viewer` entirely. Simplest; a real buyer request goes unmet.

**Consequences.** Option 1 adds one parameter and two serializer functions, and makes `T-PERM-01` possible.
**Recommendation.** Option 1. **Status: PENDING.**

### C13 — Durable Object deferral

**Question.** Ratify deferring realtime to polling?

**Options.**
1. **Ratify (recommended).** Polling + ETag; promotion thresholds defined; DO design preserved.
2. Build now (~$3–30/month, 8–12 days, plus a stateful surface and a security review).
3. Defer with a hard review date (e.g. end of P6) regardless of thresholds.

**Consequences.** Option 1 costs 2 s progress granularity and no presence. Option 2 costs a component nobody has
asked for yet.
**Recommendation.** Option 1. **Status: PENDING.**

### C14 — Support access timing

**Question.** Does the support-grant mechanism ship in P5 or P9?

**Options.**
1. **P5 (recommended).** It exists before the first external workspace, which is the point of `SA-1`.
2. P9. Operators use raw database access in the interim — the control exists on paper and is violated in
   practice.
3. P5 but read-only metadata only. Then diagnosing a marking bug is impossible.

**Consequences.** Option 1 adds ~3 days to P5 and removes the "we only have break-glass" problem.
**Recommendation.** Option 1. **Status: PENDING.**

### C15 — V5 data migration

**Question.** `OPEN_QUESTIONS` Q5. Does any V5 data move into V5.5?

**Options.**
1. **No automatic migration (recommended default).** Document a manual path; no importer work.
2. One-off importer writing through the API. Real work; must not run concurrently with marking.
3. Per-workspace import tool. Most flexible; largest scope.

**Consequences.** Option 1 means V5 users start fresh; `ADR-015` stays deferred.
**Recommendation.** Option 1 until a pilot customer asks. **Status: PENDING.**

### C16 — Transactional email vendor

**Question.** Which provider sends invitations, resets and notification digests?

**Options.**
1. **Select at P2 (recommended).** $10–$40/month at pilot volume. A notification-orchestration layer
   (free tier, ~10 k messages) was evaluated and rejected: it does not send email itself and would add a second
   vendor above a sender we still have to choose.
2. Choose now. Removes a P2 task; commits before requirements are firm.
3. Use the AI provider's email (none). Not applicable.

**Consequences.** The vendor choice is a P2 item with a price envelope already in the cost model; no architectural
impact.
**Recommendation.** Option 1. **Status: PENDING.**

---

## D. Deferred features (owner informed, not blocking)

| # | Feature | Deferred to | Re-entry condition |
|---|---|---|---|
| D1 | Durable Object realtime | Post-MVP | Any threshold in `DO-DEFERMENT §4` |
| D2 | Presence, live cursors, collaborative editing | Post-MVP | Simultaneous review in ≥ 10 % of sessions |
| D3 | Billing (Stripe) | Post-MVP | Pricing decided; metering data exists |
| D4 | SSO / SCIM | Enterprise tier | A customer pays for it (WorkOS bolt-on) |
| D5 | Per-tenant databases (option C) | Enterprise tier | A contract requires database-level isolation |
| D6 | `saved_views`, analytics hub, status page, changelog | P9 | Customers exist |
| D7 | V5 importer | On Q5 = yes | `C15` answered yes |
| D8 | `double_check`, teams, multi-LMS, mobile app, WPF client | Post-MVP | Explicit request |

---

## E. What each blocking decision unblocks

| Decision | Once answered | Effect |
|---|---|---|
| C1 | P2 can start | Identity, sessions, roles, invitations, API keys, tenant triggers |
| C2 | Auth config frozen | Acceptance criteria for session and role-change timing |
| C3 | Onboarding flow finalised | MFA tests, checklist step |
| C4 | P5 upload surface designed | File tests, multipart path |
| C5 | Migrations authored | Every new table lands in one migration set |
| C7 | Report record shape fixed | P5 report hooks, P7 rendering, budget line |

Everything else (C6, C8–C16) can be answered during the phase it touches, but answering `C8`, `C9` and `C12`
before P5 avoids rework in the review canvas.

---

## F. Recommendation summary

If the owner answers only six things, answer these, in this order: **C1, C5, C2, C3, C4, C7.**

The recommended option is marked in every case; adopting all sixteen recommendations leaves no open product
question in this package. That is not the same as saying they are approved — they are not.
