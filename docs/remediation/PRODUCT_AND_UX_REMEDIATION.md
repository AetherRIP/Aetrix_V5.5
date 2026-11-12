# Product and UX Remediation

**Status:** RECOMMENDED. Supersedes `product/` and `design/` documents only where restated here; all originals
are unmodified.

This document closes the product-level findings — `UX-01…12`, `DOC-05…11`, `DOC-13…16`, `ROAD-02/03` — and the
seven missing journeys. `UX-01` (review drafts) and `UX-02` (approval concurrency) are specified in
`CRITICAL_AND_HIGH_REMEDIATION.md` §§19–20 and are not repeated.

---

## 1. What changes, at a glance

| Area | Change | Finding |
|---|---|---|
| Sampled supervisor review | Becomes an MVP feature with schema, permission, endpoints and screen | UX-03 |
| Scheme concurrency | `version` + `If-Match`; two supervisors can no longer silently overwrite a blueprint | UX-04 |
| Workspace switching | Explicit rules for drafts, sockets, routes and progress | UX-05 |
| Member departure | Reassignment flow; nothing is orphaned or deleted | UX-06 |
| Student erasure | Anonymise, retain numerics, annotate reports | UX-07 |
| Trial credentials | Onboarding step after the first mark; quota in the header | UX-08 |
| Mobile approval | Restricted to `md+` | UX-09 |
| Accessibility | Canvas focus model, 12 px floor, one summarised live region | UX-10 |
| Keyboard | `Ctrl`/`⌘` pairs, `Alt` for canvas bindings, Windows walkthrough | UX-11 |
| Scope | Analytics hub trimmed, saved views / status page / changelog / teams cut | UX-12 |
| Product vision | Duplicate fifth principle removed | DOC-05 |
| Screen inventory | Count corrected to 54 + 7 states; four screens amended, one added | DOC-06 |
| Roadmap | P3 parallel branch; terminology split; shared duplicate detection | DOC-07/08, ROAD-02/03 |
| Double marking | Not built; Q14 default changed to match | DOC-10 |
| Monitoring targets | One SLO set | DOC-11 |
| Naming | Product / package / directory stated once | DOC-15 |

---

## 2. Product vision — the duplicated principle

`PRODUCT_VISION.md` lists principle 5 twice, verbatim and consecutively, so the document advertises six promises
in a list numbered to five. The duplicate is deleted. The five promises become the canonical set against which
`UPDATED_TRACEABILITY_MATRIX.md` traces R01–R10, and they are quoted there so the matrix and the vision cannot
drift apart again.

---

## 3. Screen inventory — corrected count and the four amendments

The header said **48 screens**; the tables enumerate **54** (13 public, 10 auth/onboarding, 21 core, 10
settings/admin) plus 7 unnumbered states. Corrected to **54 screens + 7 states**.

Amendments:

| # | Screen | Change | Why |
|---|---|---|---|
| 22 | Onboarding checklist | Six steps → **seven**, adding "add your provider key" after the first successful mark; MFA enrolment moved to first sensitive action, not creation | UX-08, DOC-09 |
| 34 | Review canvas | Draft banner, autosave indicator, conflict-diff route, restore-on-reopen | UX-01 |
| 36 | Results / grade matrix | Backed by two new endpoints; paginated; CSV via export | API-01 |
| 45 | Settings | Five tabs with storage (general, branding, academic, corrections, notifications); retention shown read-only where it is a policy | DB-09 |
| 49 | Danger zone | Export section with state, manifest and download | API-02 |
| **New** | **Sampled review** (assignment sub-view, not a new numbered screen) | Coverage counter, random-N selection, sign-off | UX-03 |
| 25 | Inbox | Backed by real endpoints; unread badge from the poll | API-03 |
| 47 | Usage & quotas | Reads `usage_daily` + quota columns for the first time | DB-09 |

No screen is added to the numbered set: sampled review is a view of the assignment, which keeps the count honest
and avoids a 55th screen that is really one filter.

---

## 4. UX findings

### 4.1 UX-03 — The supervisor's core job has no screen

The vision names "mark ≥ 10 % of scripts" as a success metric and the buyer persona is the supervisor whose job
is to know that marking is consistent. There is no sampling queue, coverage counter, action or permission.

**Resolution — sampled review ships in the MVP.**

- `sample_reviews` table (`DB-R §3.2`), unique per `(workspace, assignment, result)`.
- `correction.sample` permission, held by owner/admin/supervisor.
- `POST /assignments/{id}/sample-review { percent | count, strategy: 'random' }` selects without replacement
  from approved results, excluding already-sampled rows.
- `GET …/sample-review` returns coverage: `{ selected, reviewed, signedOff, coveragePct, target }`.
- `POST /sample-review/{itemId}/sign-off` records a review with an optional note and reopens the result if the
  reviewer disagrees (which is the point).
- The UI shows a progress meter against the 10 % target and a "sampled" chip on the results table.

**Design consequence:** the assignment overview (screen 27) gains a fifth state row — *quality* — alongside
progress, blockers, next action and status. Without it the buyer's job has no home.

**Why MVP rather than later.** The product's differentiation is "a human decides every mark that matters". A
supervisor who cannot demonstrate coverage has no answer to "how do you know the AI is right?" — which is the
first question a head of maths asks.

### 4.2 UX-04 — Two supervisors editing one blueprint

`mark_schemes` had `locked_at`/`locked_by` and no `version`, while it is edited by more than one supervisor and
fixes every max mark in the assignment. Last-write-wins here means marks validated against the wrong maximum.

**Resolution.** `version INTEGER NOT NULL DEFAULT 1`; question edits, exclusions and lock/unlock require
`If-Match`; a stale write returns `409 version_mismatch` with the changed questions listed. The lock is a
separate action from the edit, so a supervisor can hold the lock while reviewing without blocking a colleague
from *reading*.

### 4.3 UX-05 — Workspace switching mid-task

Users may belong to two departments; nothing said what happens to an open socket, a queue position, an unsaved
override, a running job's progress view, or a route the target workspace does not grant.

**Resolution — the switch is a full context reset with three guarantees:**

| State | Behaviour |
|---|---|
| Unsaved review draft | Autosave flush is awaited (≤ 2 s); if the flush fails, the switch is blocked with a dialog and a retry |
| Upload in progress | Switch allowed; upload continues server-side; a toast on return reports the outcome |
| Running jobs | Unaffected — they are server-side; the progress view refetches from the new workspace |
| Route | Equivalent route preserved if the target grants it; otherwise land on the workspace home with a one-line explanation |
| Socket | Closed before the switch and reopened after (relevant only if the DO is promoted) |
| Polling | All timers cancelled on switch; one in-flight request is abandoned via `AbortController` |

### 4.4 UX-06 — Removing a member orphans their work

`submissions.assignee_id` pointed at a membership that could be removed; the roles document covered the
last-owner case and socket closure but not forty in-progress scripts.

**Resolution.** `DELETE /members/{userId}` refuses with `409` when the member has non-terminal assigned work
unless the caller supplies `?reassignTo=<memberId>` or `?unassign=true`. Reassignment moves `assignee_id` in one
transaction and writes one audit row per submission (batched, capped at 500 with a continuation). Unassigned
submissions appear in the inbox as "12 scripts need an owner". **Nothing is deleted** — the historic record of
who marked what survives in `results`/`approvals`/`audit_log`, which is the part that matters for accountability.

### 4.5 UX-07 — Erasure with published marks

A student can be deleted while their marks exist in a published Classroom grade and a generated report in R2.
Cascading the row orphans results; deleting results corrupts class aggregates; neither is acceptable.

**Resolution — erasure is anonymisation, not deletion:**

1. `students.anonymised_at` set; `display_name` → `"Removed student N"` (N stable per workspace, from a counter,
   not the row id); `full_name`, `external_ref`, `notes` nulled.
2. `results` retained, including `question_results`, so aggregates and historical reports remain arithmetically
   correct.
3. Reports already generated are **annotated, not regenerated**: a small "contains anonymised records" note is
   applied at download time by the report route; regenerating would change the artefact the school may have
   already filed.
4. A grade already published to Classroom is **never** rewritten without an explicit operator action; the
   product records that the student was anonymised and leaves the remote grade alone.
5. The audit row records the actor, time and scope, and the workspace privacy page states the behaviour.

This is a privacy control with an arithmetic constraint, and the constraint is why "delete everything" is the
wrong answer.

### 4.6 UX-08 — The trial path assumes a credential onboarding never asks for

`OPEN_QUESTIONS` Q3 defaults to platform keys for trial, workspace keys for production. Onboarding had six steps
and none of them mentioned a provider key, so a department discovered the requirement when the trial quota ran
out.

**Resolution.** Checklist step 7 ("Add your provider key to keep marking") appears **after** the first successful
mark — at the moment the value is obvious, not before it. During trial the top bar shows "Trial: 84 of 200
marks left". At 80 % the step is highlighted; at 100 % marking is blocked with `429 quota_exceeded` and the
onboarding step is the only call to action.

### 4.7 UX-09 — Mobile approval

`RESPONSIVE_DESIGN.md` §1 says `xs` is "read, approve, notify"; §3 says `< md` is read-only with approve. A
supervisor approving on a phone cannot see the script and the per-question marks together, which is the entire
basis of the approval decision.

**Resolution.** Approve requires `md+`. Below `md`, the submission view is read-only with an explicit "Open on a
larger screen to approve" affordance that copies a link. The alternative — a phone-specific approval view with a
"reviewed 6 of 6" gate — is recorded as a future option if pilot data shows phone approval is genuinely needed;
it is not built speculatively.

### 4.8 UX-10 — Accessibility specifics

| Issue | Resolution |
|---|---|
| Canvas key bindings (`0–9`, `J/K`) collide with type-ahead and browser shortcuts | Roving tabindex over the question list; single tab stop per region; bindings active only when the mark grid has focus; `aria-keyshortcuts` declared; `Esc` releases |
| 11 px uppercase micro-labels carry table headers | Floor raised to **12 px**; contrast measured (not asserted) at ≥ 4.5:1 with a 1.02 minimum margin over the threshold; a token test enforces it |
| `aria-live` throttled to 1 per 2 s during a 200-job batch | One summarised live region per assignment: "34 of 200 complete", updated at most every 5 s; individual job changes are not announced |

The dark-theme status hues that were claimed to hold 4.5:1 "by shifting one step lighter" now carry actual
measured values in the token table (`ADR-010`).

### 4.9 UX-11 — Keyboard bindings on Windows

Eleven of fourteen bindings were written `⌘`-only. Rewritten as pairs (`Ctrl`/`⌘`), canvas bindings moved off
digits where they collide with type-ahead in a text field, and a Windows keyboard walkthrough is added to the
manual test list (`TEST_STRATEGY` §8).

### 4.10 UX-12 — Scope that will not pay for itself

| Item | Decision | Reason |
|---|---|---|
| Platform analytics hub beyond two charts | **Cut from MVP** | No decision it informs before there are customers |
| `saved_views` | **Cut** | The queue has four filters; a saved-view system is not one of them |
| Public status page, changelog | **Deferred to P9** | Valuable once there are customers, noise before |
| Teams / sub-organisations | **Not built** | The library supports them; the product has no need |
| Presence, live cursors | **Deferred** | `ADR-008` |
| `viewer` role | **Retained, restricted to aggregates** | The cover-staff persona is real; the shaper now enforces the restriction the matrix promised |
| Six roles | **Five** | `platform_operator` was never a workspace role |

---

## 5. Roadmap changes

### 5.1 P3 is a parallel branch (DOC-07, ROAD-02)

The dependency block said `P0 → P1 ─┬→ P2 → P3` (strictly sequential) while the phase text said P3 "runs partly
in parallel with P2 (different people)". Redrawn:

```
P0 → P1 ─┬→ P2 ─────────────┬→ P4 → P5 → P6
         │                  │
         └→ P3 (design) ────┘   merge gate: P3 components + P2 shell before P4 starts
```

The merge gate is explicit because parallel work with an implicit merge is how design and implementation drift.

### 5.2 Terminology split (DOC-08)

"Workspace admin" meant two things: the *settings* an owner uses (P4/P5) and the *administration surface* an
operator uses (P9). Split: **workspace settings** (P4/P5) and **platform administration** (P9). The MVP cut line
now reads unambiguously.

### 5.3 Shared duplicate detection (ROAD-03)

Bulk import (P4) validates student rows; upload (P5) validates files; both need duplicate detection, and the
acceptance criteria test them as two separate behaviours. Extracted as a domain service in P4 (`detectDuplicate`)
that P5 reuses, honouring `SYSTEM_ARCHITECTURE.md` §2's rule that domain services are shared between the request
and job paths. One rule, one test, two callers.

### 5.4 Phase-table changes

| Phase | Change |
|---|---|
| P2 | Isolation suite plus the trigger and shaper rows; identity reconciliation is a P2 precondition, not work inside it |
| P4 | Duplicate-detection service; scheme `version` |
| P5 | Outbox, reaper, DLQ, polling progress (no sockets), **support-grant mechanism**, review drafts, quota enforcement |
| P6 | Publish/attach split |
| P7 | Results/matrix endpoints, export pipeline, PDF host decision consumed |
| P9 | Platform administration, analytics hub, status page |

---

## 6. Naming, stated once (DOC-15)

| Term | Meaning |
|---|---|
| **Aetrix V5.5** | The product name, used in UI, docs and contracts |
| **UI_V5.5** | The package/phase name for this blueprint |
| `UI_Webpage_V5.5` | The directory on disk. It is **not** renamed; the brief forbids it |
| `TEMP` | The workspace label in `README.md`; historical, not a product name |
| V5 | The existing local application, unchanged and still the source of truth until P1 parity passes |

---

## 7. The seven missing journeys

Each is defined at the same fidelity as J1–J8: happy path, branches, and the state the user is left in.

### J9 — Sampled supervisor review
Supervisor opens the assignment → "Quality" row shows coverage 0 of 10 % → selects a random sample of 8 → reviews
each (accept or reopen) → signs off → coverage reaches 100 % → the assignment overview shows "Sampled: 8 of 8".
**Branches:** sample larger than the class (sample everything, say so); a reopened result returns to the queue and
lowers coverage until re-reviewed; sample already complete (action disabled, not hidden).

### J10 — MFA enrolment and recovery
Owner signs in → first sensitive action (invite, credential, delete) → `403 mfa_enrolment_required` → guided
enrolment (QR, verify code, download backup codes) → action resumes → later, device lost → "Use a backup code" →
re-enrol → old sessions offered for revocation. **Branches:** no backup codes saved (support path is re-verification
by email plus a 24 h delay, documented); operator without MFA cannot access `/admin` at all.

### J11 — Password recovery
Forgot → email → token (single use, 30 min) → new password → all other sessions revoked → sign-in.
**Branches:** token expired; token reused; the account's verified email changed since the request (request
refused, generic message); account locked (recovery also clears the lock, after the delay).

### J12 — Workspace switching mid-task
Covered by §4.3; the journey exists so the rules have a narrative home.

### J13 — Member departure
Owner removes an assistant → 409 with "14 scripts are assigned" → chooses reassign-to → confirmation shows the
counts → reassignment completes → inbox item for the new assignee → audit rows. **Branches:** last owner
(blocked, transfer first); member with a running job (job completes, attribution preserved); member re-invited
later (partial unique index allows it, history intact).

### J14 — Student erasure with published results
Owner (or operator acting on a controller instruction) requests erasure → typed confirmation names counts and
warns that published grades are not rewritten → anonymisation completes → reports annotated on download → audit
row → a later re-import of the same student creates a new row, not a resurrection. **Branches:** legal hold blocks
erasure and says so; the student has an in-flight job (cancelled first).

### J15 — Concurrent scheme edit
Two supervisors open the blueprint → A edits question 7 and saves (version 3 → 4) → B saves at version 3 →
`409` with the changed questions → B sees a diff, re-applies on top → both locked states visible → lock is
explicit and single-holder.

---

## 8. Acceptance criteria added

| Phase | New criterion |
|---|---|
| P2 | Identity schema match: sign-up, sign-in, org create, invite, role change against the canonical schema |
| P2 | Tenant trigger rejects a cross-tenant parent FK for every child table |
| P5 | A job whose message was never published reaches `running` within 90 s (outbox) |
| P5 | A killed Workflow reaches a terminal state within two lease periods (reaper) |
| P5 | A poison message lands in the DLQ and alerts |
| P5 | 5 redeliveries produce 1 attempt |
| P5 | An operator cannot read tenant data without an active grant; every granted read is audited |
| P5 | Review draft survives a tab kill and a device change; a concurrent save is never overwritten |
| P5 | Quota is checked once for a 100-script batch; nothing is enqueued when it fails |
| P6 | `reconcile` performs zero writes (row counts unchanged) |
| P7 | Sample review reaches 10 % coverage and sign-off |
| P7 | Export archive contains zero rows from any other workspace |
| P7 | Report reproducibility: identical bytes for totals, marks, names and lesson code, or the variance list is empty |
| P9 | Platform admin sees aggregates only; detail without a grant is 404 |
| P10 | Restore drill measured, recorded, and the measured RTO published |

---

## 9. What did not change

- **The exception leads; states are named, not implied.** The status vocabulary is closed and now enforced by
  `CHECK`.
- **The review canvas** — script left, marks right, explanation per question — is the right shape and is
  untouched.
- **`NEEDS_VERIFICATION` with a "Check status" action** remains the best failure UX in the package.
- **The keyboard model** for a 200-script session survives, amended for Windows and for the canvas focus model.
- **Refusing to claim compliance** and admitting handwriting is inherently inaccessible — unchanged, and still
  the correct posture.
- **The density stance** (a thousand marks on one screen) survives; the 12 px floor is the only concession.
