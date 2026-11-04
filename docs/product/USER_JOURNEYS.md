# User Journeys

**Status:** RECOMMENDED. Each journey lists the happy path, the branches that must not be forgotten, and
the state the user is left in when something fails. Failure states are product surface, not error logs.

## J1 — Signup to first marked script (the adoption gate)

1. Visitor lands on `/` → `Pricing` → `Start free` → `/signup`.
2. Email + password (or Google). Email verification sent; account created **unverified**.
3. Verify link → session issued → `/onboarding/workspace`.
4. Name the workspace (school/department) and choose a slug. Workspace created with creator as `owner`.
5. Onboarding checklist, resumable: *connect Classroom (optional)* → *add a class* → *add students* →
   *create an assignment* → *upload a mark scheme* → *mark one script*.
6. First script: upload PDF (or pick a Classroom submission), confirm scheme blueprint, start job.
7. Job runs server-side; user sees staged progress, then a result with per-question marks and `REVIEW`
   items highlighted.

**Branches:** email never verified (workspace exists, invitation sending blocked, banner every session);
Classroom declined (manual upload path fully usable — **must not dead-end**); no scheme yet (demo scheme
offered, clearly labelled synthetic, never a real mark); upload fails mid-way (resumable, nothing partial
is markable).

## J2 — Invitation and acceptance

1. Admin → Members → Invite → email + role (`assistant`).
2. Invite row created with single-use token, 7-day expiry, bound to the email.
3. Recipient opens link → if new, signup with that email only; if existing, matches by verified email.
4. Acceptance creates membership; redirect to workspace dashboard.
5. Admin sees the member appear; audit entry recorded.

**Branches:** invite to an existing member (idempotent, no duplicate row); expired (resend offered);
already accepted (safe landing, not an error page); different email signs in (refused, explains why);
workspace suspended (clear message, no acceptance).

## J3 — Assignment from Classroom to published grades

1. Sync courses → choose course → choose coursework → assignment draft created.
2. Attach mark scheme PDF → system extracts question inventory → supervisor reviews the blueprint
   (question list, max marks, M/A/B points) and **locks it**.
3. Allocate assistants; submissions appear as they are discovered.
4. Assistants mark; each result lands in `pending_review` or `approved`.
5. Supervisor samples, overrides where needed, approves.
6. Publish: report attached, draft grades written, assignment returned — three independent operations.

**Branches:** scheme extraction disagrees with the PDF (blocked until a human resolves; never guessed);
student not on the allow-list (skipped and listed, not silently dropped); grade write 403 (fallback path,
state `blocked_permission`, actionable); timeout mid-write (`NEEDS_VERIFICATION`, reconcile re-reads
Classroom read-only before anything is retried).

## J4 — Reviewing and overriding a mark

1. Queue → filter `REVIEW` → open submission.
2. Split view: script pages left, per-question marks right, AI explanation per question.
3. Reviewer changes a mark → reason required (free text or preset) → saved as an override with actor/time.
4. Approve → submission leaves the queue; totals recomputed; audit entry written.

**Branches:** two reviewers open the same submission (optimistic version check; second save is rejected
with a diff, not silently overwritten); override after approval (requires `correction.override` and
re-opens the submission, logged); mark exceeds question max (refused client- and server-side).

## J5 — Two assistants, same script (concurrency)

1. Both open submission S. Neither is told the other exists (presence is deferred).
2. A saves an override at version 4. B saves at version 4.
3. Server accepts A (version → 5). B's write fails the version predicate.
4. B is shown *what changed* and offered: reload, or re-apply their edit on top.

**Rule:** last-write-wins is forbidden for marks. Marks and approvals are version-checked; comments are
append-only and never conflict. See `../testing/TENANT_ISOLATION_TESTS.md` §4.

## J6 — Failure and recovery of a correction job

1. Job parks on rate limit (attempts preserved) rather than burning its budget.
2. Progress shows `parked`, with the resume time — not a spinner.
3. Provider circuit opens on sustained 5xx → all jobs for that workspace pause and say so.
4. After the window, the queue resumes; prepared input is reused (no second download/upload).
5. If the budget is exhausted, the job ends `failed` with a classified reason and one clear action
   (`Retry`, `Change model`, `Mark manually`).

**Rule:** no infinite loops; the V5 retry budget (15 min park) is preserved.

## J7 — Platform operator helping a customer

1. Operator sees workspace metadata (plan, usage, status) — no student data.
2. Customer owner grants support access: scope, duration (≤ 72 h), reason.
3. Grant recorded; operator's reads are audited individually; a banner is visible to the workspace.
4. Grant expires automatically; operator's access reverts to metadata.

**Refusal:** there is no break-glass that bypasses consent. If a customer is unreachable, the operator may
suspend a workspace for abuse/safety but still cannot read its contents.

## J8 — Export and deletion

1. Owner requests export → asynchronous job → signed bundle (CSV/JSON + files manifest) valid 24 h.
2. Owner requests deletion → typed confirmation naming counts (students, submissions, files, jobs).
3. 14-day grace period with cancel; workspace soft-deleted immediately (members lose access).
4. After grace: rows purged in batches, R2 objects removed, provider credentials destroyed, tombstone kept
   (id + hash) so late jobs cannot resurrect data.

**Branches:** active jobs at deletion (cancelled first, then purge); legal hold (blocks purge, says so);
platform-level retention of billing/audit records (metadata only, stated in the privacy doc).
