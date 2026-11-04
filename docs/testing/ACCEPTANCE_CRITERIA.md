# Acceptance Criteria

**Status:** RECOMMENDED. A phase is done when **all** its criteria hold and are demonstrated, not asserted.
Each criterion is written so it can be checked by someone who did not build the feature.

## 1. Global (applies to every phase)

- [ ] Feature works with keyboard only, in a logical order.
- [ ] Every error state has a message naming the problem and the next action.
- [ ] Cross-tenant isolation suite green, including the new resource's row in `TENANT_ISOLATION_TESTS.md` §2.
- [ ] Every new route has a declared permission and a policy test.
- [ ] No secret, key, hash or token appears in any response, log line or client bundle.
- [ ] Migration is expand-only or has a documented backfill.
- [ ] Docs updated: the relevant file in `docs/` reflects what shipped.

## 2. Phase 1 — Correction parity spike

- [ ] ≥ 20 fixture scripts marked through the new runtime.
- [ ] Per-question marks match V5 output exactly for every script, or a documented, reviewed reason differs.
- [ ] A script with a missing question yields `needs_review`, **never** `0`.
- [ ] A mark above `max_marks` is impossible to persist (test proves rejection).
- [ ] Total = sum of question marks in every case.
- [ ] Repeat run of the same input produces identical output (determinism).
- [ ] The compute decision for PDF inspection/rendering is recorded as an ADR with a costed alternative.

## 3. Phase 2 — Tenancy, auth, workspace shell

- [ ] Two workspaces cannot see each other across all 16 resource rows (suite green in CI).
- [ ] Signup → verify → create workspace → invite → accept → switch workspace works end to end.
- [ ] A user in two workspaces sees different roles in each and the UI reflects the active one.
- [ ] Removing a member takes effect on the next request and closes their socket within 30 s.
- [ ] MFA enrolment and step-up work; owner and operator accounts cannot skip MFA.
- [ ] Session list shows devices; "sign out everywhere" revokes all.
- [ ] 404 (not 403) for cross-tenant ids, verified in the response body.

## 4. Phase 3 — Design system and shell

- [ ] Tokens exist in one source and generate the app theme; documentation matches code.
- [ ] Core components (button, input, table, chip, dialog, tabs, nav item, toast) exist with all states.
- [ ] axe: zero serious/critical on every implemented route.
- [ ] Keyboard: every interactive element reachable and operable; focus visible at all times.
- [ ] 200% zoom and 125% OS scaling usable on the three densest screens.
- [ ] Visual regression baselines exist for light and dark.

## 5. Phase 4 — Academic and assignments

- [ ] CSV import: dry-run shows per-row errors, commit imports only valid rows, no partial silent failure.
- [ ] A duplicate student (same external ref) is detected and reported, not silently duplicated.
- [ ] Scheme extraction produces a blueprint; locking is blocked while conflicts exist.
- [ ] Marking refuses to start on an unlocked scheme.
- [ ] `CH1L1`-style lesson identity preserved: chapter never dropped, ordering correct.
- [ ] Allocation, claim and reassignment are audited.

## 6. Phase 5 — Files and correction

- [ ] Upload of a 40 MB PDF succeeds, resumes after an interrupted connection, and is rejected if truncated.
- [ ] A non-PDF masquerading with a `.pdf` extension is rejected at registration.
- [ ] Job lifecycle: queued → running → succeeded, with live progress and a correct final state.
- [ ] Injected 429 parks the job without consuming attempts; injected 503 retries once; injected 401 fails
      immediately with an actionable code.
- [ ] Cancel mid-job ends `cancelled` with no partial result.
- [ ] Duplicate submit creates one job and one provider call.
- [ ] Override requires a reason, is version-guarded, and is audited.
- [ ] Approve is a separate permission and produces one approval row.
- [ ] Usage events recorded per job; quota blocks at the configured limit.

## 7. Phase 6 — Classroom

- [ ] OAuth connect/disconnect per workspace; tokens encrypted; disconnect clears them.
- [ ] Sync imports courses/coursework idempotently; re-sync creates no duplicates.
- [ ] Publish performs three independent operations with one row each.
- [ ] A simulated timeout leaves `needs_verification`; reconcile settles it read-only.
- [ ] A 403 on grade write surfaces a specific, actionable state (not a generic failure).
- [ ] Manual upload path remains fully functional with Classroom disconnected.

## 8. Phase 7 — Reporting

- [ ] Class report PDF renders all students, correct totals, correct lesson grouping.
- [ ] Report generation is reproducible for the same inputs (same bytes or documented variance).
- [ ] Grade matrix exports CSV matching the on-screen figures exactly.
- [ ] Print stylesheet produces a legible A4 page.

## 9. Phases 8–10

- [ ] Comments are append-only; mentions produce exactly one notification.
- [ ] Notification preferences respected (in-app vs email).
- [ ] Support grant: scope, expiry, banner, per-read audit, forced revoke.
- [ ] Platform admin sees aggregates only; attempting detail without a grant returns 404.
- [ ] Load test at 10× target: p95 < 400 ms, no queue backlog growth over 30 min.
- [ ] Restore drill: tenant slice restored into staging with matching row counts.
- [ ] Pen-test criticals/highs closed or explicitly accepted in `../security/THREAT_MODEL.md` §5.

## 10. MVP definition of done

A department can sign up, create a workspace, invite a colleague, add a class and students, create an
assignment, upload a mark scheme, lock the blueprint, upload scripts, mark them server-side, review and
override marks, approve, generate a report, and publish to Classroom — **without any cross-tenant exposure,
without a silent wrong mark, and with every failure state visible and actionable.**
