# UX and Product Gap Analysis

**Audit date:** 2026-11-03. Reviewed as a product designer and technical PM for the actual users: a head of maths
buying, and a teaching assistant marking 200 scripts at speed, on a school laptop, in 40-minute gaps.

The design work is well above average for a planning package: 54 screens with states, a keyboard model, an
accessibility position that admits what it cannot fix, and a design language with real tokens. The gaps below are
about **what happens when the happy path breaks**, and about **scope that will not earn its keep in an MVP**.

## 1. Findings

### UX-01 — HIGH — An interrupted review loses work, and the fix contradicts itself
**Documents:** `product/USER_JOURNEYS.md` J5, `design/RESPONSIVE_DESIGN.md` §4 rule 6, `design/SCREEN_INVENTORY.md` §34 §"Session-expired interstitial".

**Problem.** The journey covers two reviewers colliding, but not one reviewer interrupted: a fire drill, a
laptop lid, a session expiry mid-override. `RESPONSIVE_DESIGN.md` says "the app must not lose a typed override:
drafts persist **locally** until saved" — but the write model is version-guarded on the server, so a local draft
that is later applied can silently overwrite a change made in between, or fail and lose the text. There is no
server-side draft, no autosave cadence, and no rule for what a local draft means after a version bump.

**Consequence.** The single most valuable keystroke in the product (a reasoned override) is the one most likely to
be lost, and the recovery path can itself cause a lost update — the exact hazard J5 was written to prevent.

**Resolution.** Choose one: (a) server-side draft row per `(result, actor)` with debounced autosave and no version
bump until "save"; or (b) local draft that is **replayed with a diff on reconnect**, never auto-applied. State the
cadence and the conflict rule; add an acceptance criterion ("kill the tab mid-override, reopen, the text is
recoverable, and a concurrent change is never overwritten").

### UX-02 — HIGH — Simultaneous approval is left undecided inside a blocking test suite
**Documents:** `testing/TENANT_ISOLATION_TESTS.md` C2.

C2 says "`409` (already approved) or `200` idempotent — **decided behaviour**, documented, and tested" but does not
decide it. For a product whose promise is "a human decides every mark that matters", the second approver must not
be told they approved something they did not. Recommended: `200` if the same actor re-submits, `409` with the
approver's name if a different actor does. Add the screen state: "Approved by J. Patel 2 minutes ago".

### UX-03 — MEDIUM — The supervisor's core job has no screen
**Documents:** `product/PRODUCT_VISION.md` (≥ 10 % sampled review coverage), `design/SCREEN_INVENTORY.md`.

The vision names sampled supervisor review as a success metric, and the buyer persona is the supervisor whose job
is "know that marking is consistent". There is no sampling queue, no coverage counter, no "review these 10 % at
random" action, no endpoint and no permission. The supervisor can only browse the submissions table and hope.

**Resolution.** Add a sampled-review view on the assignment (random N % selection, coverage progress, "sign off"),
`correction.sample` permission, and an endpoint. This is the feature that justifies the buyer's seat — it should
be in the MVP, not implied by it.

### UX-04 — MEDIUM — Two supervisors editing one blueprint have no concurrency control
**Documents:** `architecture/DATABASE_DESIGN.md` §3 (`mark_schemes` has `locked_at`, `locked_by`, no `version`),
`product/USER_JOURNEYS.md` J3.

`assignments`, `submissions` and `results` carry `version`; `mark_schemes` does not, although it is edited by
multiple supervisors and is the artefact that fixes every max mark in the assignment. Last-write-wins here means
marks silently validated against the wrong maximum.

**Resolution.** Add `version` to `mark_schemes` and guard the question-edit and lock endpoints with `If-Match`.

### UX-05 — MEDIUM — Switching workspace mid-task is undefined
**Documents:** `design/INFORMATION_ARCHITECTURE.md` (`/workspaces`, switcher), `design/SCREEN_INVENTORY.md` §20.

Users may belong to two departments. Nothing states what happens to: an open socket (one per workspace), a queue
position, an unsaved override, a running job's progress view, or the active route if the target workspace does not
grant it. The natural implementation (reload the shell) is fine — it just needs saying, because the socket
lifecycle and the draft story both depend on it.

**Resolution.** Specify: switching tears down the socket, flushes or blocks on unsaved drafts, preserves the
equivalent route when permitted, and lands on the workspace home otherwise. Add journey J12 (DOC consistency §2).

### UX-06 — MEDIUM — Removing a member orphans their work
**Documents:** `product/USER_ROLES_AND_PERMISSIONS.md` §6, `architecture/DATABASE_DESIGN.md` (`submissions.assignee_id`).

`submissions.assignee_id` points at a membership that can be removed. The roles document covers the last-owner edge
case and socket closure, but not: what happens to 40 in-progress submissions assigned to a departing assistant, who
can see them, and whether the queue offers "reassign everything". `assignment.allocate` exists as a permission with
no bulk-reassign behaviour.

**Resolution.** On removal, offer bulk reassignment (owner/admin), mark affected submissions unassigned rather than
deleting the link, and surface an inbox item "12 scripts need an owner".

### UX-07 — MEDIUM — There is no erasure path that respects published marks
**Documents:** `security/DATA_PRIVACY.md` §5 (erasure), `product/USER_JOURNEYS.md` J8 (workspace deletion only).

A student can be deleted individually (privacy §5 "Student delete (batched, cascading)") while their marks already
exist in a published Classroom grade and a generated report PDF in R2. Cascading the student row would either
orphan `results` or delete marks the school still needs; neither outcome is specified, and the report artefacts are
not covered at all.

**Resolution.** Define student erasure as: anonymise the student record (`display_name` → "Removed student N",
`full_name` null), retain the numeric results for the class's aggregate integrity, regenerate or annotate reports,
and never rewrite a grade already published to Classroom without an explicit operator action. This is a privacy
requirement, not a UX nicety.

### UX-08 — MEDIUM — The trial path assumes a credential the onboarding never asks for
**Documents:** `product/USER_JOURNEYS.md` J1, `design/SCREEN_INVENTORY.md` §22 §46, `decisions/OPEN_QUESTIONS.md` Q3.

Q3's default is "both: platform keys for trial, workspace keys for production". The onboarding checklist has six
steps and none of them is "connect an AI provider"; screen 46 exists in Settings. With platform keys the first
mark works, but nothing tells the user that production requires their own key, and nothing in the product surfaces
the transition. A department that reaches its trial quota discovers the requirement at the worst moment.

**Resolution.** Add a checklist step after the first successful mark ("Add your provider key to keep marking"), and
show quota remaining in the top bar during trial.

### UX-09 — MEDIUM — Mobile "approve" contradicts the review canvas rules
**Documents:** `design/RESPONSIVE_DESIGN.md` §1 ("`xs`: Read, approve, notify. No marking.") vs §3 ("`< md`:
read-only **with approve action**; overriding is disabled").

A supervisor approving on a phone cannot see the script page and the per-question marks together, which is the
entire basis of the approval decision the product is selling. Offering the button invites rubber-stamping — the
failure mode the sampled-review metric exists to prevent.

**Resolution.** Either restrict approve to `md+`, or design a phone-specific approval view: marks summary first,
tap-through to page images, and an explicit "reviewed 6 of 6 questions" gate before the action enables.

### UX-10 — MEDIUM — Accessibility intent is strong; three specifics are not resolved
**Documents:** `design/ACCESSIBILITY.md` §2 §3, `design/DESIGN_SYSTEM.md` §4.

1. The review canvas binds `0–9` to set a mark and `J/K` to move between questions. For screen-reader and
   switch users this collides with type-ahead and with browser shortcuts; the document specifies the keys but not
   the roving-tabindex/focus model that makes them safe.
2. 11 px uppercase micro-labels carry table headers — the densest, most-read text in the app at 125 % OS scaling.
3. `aria-live` announcements are throttled to one per 2 s, but a 200-job batch produces state changes faster than
   that; nothing says what is dropped or summarised.

**Resolution.** Specify the focus model for the canvas, raise the micro-label floor to 12 px with a 1.02 minimum
contrast margin, and make batch progress a single summarised live region ("34 of 200 complete") rather than
per-job announcements.

### UX-11 — LOW — `⌘`-first shortcuts on Windows
The shortcut table leads with `⌘K`/`Ctrl+K` and uses `⌘S`, `⌘Enter`, `⌘A`. Schools are overwhelmingly Windows. The
document does include `Ctrl`, but 11 of 14 bindings are written `⌘` only.

**Resolution.** Write bindings as `Ctrl`/`⌘` pairs consistently, and test the keyboard walkthrough on Windows.

### UX-12 — MEDIUM — Scope that will not pay for itself in an MVP
Named in the package but unlikely to earn its keep before product-market fit: the platform analytics hub (screen
42) beyond two charts; `saved_views`; the public status page and changelog (screen 11/12) before there are
customers; six roles (owner/admin/supervisor/assistant/viewer/operator) when four would carry the MVP and the
viewer role is the only one whose restrictions cannot even be enforced (SEC-04); the presence-ready DO (ARC-03);
`double_check`; teams/sub-organisations (Better Auth supports them; the product does not need them).

**Resolution.** Cut `viewer` (or ship it as "read-only admin" with no mark visibility), defer `saved_views` and the
analytics hub, and keep the four roles the journey actually uses.

## 2. What the product gets right

- **The exception leads** and "states are named, not implied" are the correct principles for this domain, and the
  status vocabulary is genuinely closed rather than aspirational.
- **The review canvas** (script left, per-question marks right, explanation per question) is the right shape for
  the work, and describing the PDF's accessible alternative as the mark table is the correct answer.
- **The keyboard model** for a 200-script session is specified, not assumed.
- **Failure states are treated as product surface** — `NEEDS_VERIFICATION` with a "Check status" action is better
  than most commercial products manage.
- **Refusing to claim compliance** and admitting "handwriting is inherently inaccessible" is exactly the honesty a
  red-team review looks for.

## 3. Usability risks for the actual buyer

| Risk | Evidence | Mitigation |
|---|---|---|
| 54 screens is a lot to learn | Screen inventory | Ship 20 in MVP; the rest are settings and marketing |
| A supervisor cannot do the one thing they were hired for | No sampling flow (UX-03) | Add sampled review to MVP |
| Density may be too high on 1366×768 | `RESPONSIVE_DESIGN.md` names the risk | Density toggle exists; test with 5 assistants before P4 |
| Trial-to-paid surprise | UX-08 | Onboarding step + quota in the header |
| Two-approver confusion | UX-02 | Decide C2, show the approver's name |
