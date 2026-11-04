# Test Strategy

**Status:** RECOMMENDED. The pyramid is deliberately bottom-heavy because the expensive failures in this
product are *data* failures (a wrong mark, a leaked row), not UI regressions.

## 1. Layers

| Layer | Scope | Tool | Speed | Gate |
|---|---|---|---|---|
| L1 Unit | Pure functions: mark reconciliation, retry classification, permission policy, token mapping | vitest | < 5 s | Every commit |
| L2 Integration | Route → domain → D1 (local workerd), R2 stubs, fake provider | vitest + workerd | < 60 s | Every commit |
| L3 Contract | API shapes, error envelope, no-secret assertions | schema snapshot | < 20 s | Every commit |
| L4 E2E | Real browser flows on a seeded workspace | Playwright | < 8 min | PR + pre-deploy |
| L5 Isolation | Cross-tenant attacks (dedicated suite) | vitest + workerd | < 90 s | Every commit, **blocking** |
| L6 A11y | axe on every route + keyboard walkthrough | Playwright + axe-core | < 2 min | PR |
| L7 Visual | Screenshot diff of key screens (light/dark, dense) | Playwright snapshots | < 3 min | PR (advisory → blocking for design-system files) |
| L8 Performance | p95 budgets on hot routes; 200-job burst | k6 or scripted | < 10 min | Release |
| L9 Security | Authz matrix, upload abuse, log redaction, dependency audit | vitest + audit | < 3 min | Release |
| L10 Recovery | Restore drill, queue replay, crash mid-job | scripted | manual | Release |

## 2. What must be tested at unit level (highest value per line)

1. **Mark reconciliation**: missing question → `needs_review`, never `0`; awarded never exceeds max; totals
   recomputed; verification never mutates an award.
2. **Retry classification**: each error class maps to park / one-retry / never; budget exhaustion terminates.
3. **Permission policy**: every permission × role cell from the matrix, including the footnote restrictions.
4. **Tenant scoping helper**: an unscoped call must be impossible to express (type-level) and must throw at
   runtime if forced.
5. **Version guard**: stale version → `409`, not a silent overwrite.
6. **Status transitions**: illegal transitions rejected (e.g. `published → queued` without reopen).
7. **Crypto**: envelope encrypt/decrypt round-trip; ciphertext never equals plaintext; key rotation re-wraps.

## 3. Integration tests that earn their keep

- Upload → register → job → fake provider → result → approve, against local D1/R2.
- Publish with a fake Classroom: three operations, one fails with a timeout → `needs_verification`; reconcile
  re-reads and settles it.
- Duplicate POST with the same `Idempotency-Key` → one job.
- Queue message delivered twice → one execution (lease claim).
- Cancel mid-job → terminal `cancelled`, no partial result row.
- Retention sweep deletes only rows inside the target workspace.

## 4. Test data

- **Synthetic only.** Two seeded workspaces (`alpha`, `bravo`) with overlapping-looking ids, similar names and
  identical class names — deliberately confusable, so an isolation bug cannot pass by accident.
- Fixture scripts: 5 real-shaped PDFs (multi-page, faint handwriting, missing question, duplicated page).
- Fake provider with programmable behaviours: success, 429, 503, timeout, malformed JSON, "missing question 7".
- No production data, ever. A CI check fails if a fixture looks like real PII (names allowlisted).

## 5. Coverage gates

| Area | Line coverage | Note |
|---|---|---|
| `domain/` and `data/` | ≥ 85% | Where correctness lives |
| `api/` | ≥ 75% | Handlers are thin by design |
| Components | not gated | Behaviour is covered by E2E |
| Migration/SQL | every migration has an assertion test | |

Coverage is a floor, not a target: the isolation and reconciliation suites are judged by scenario coverage.

## 6. Flake policy

- A flaky test is quarantined within one working day, with an owner and an expiry (14 days).
- Quarantined tests do not count toward the gate, but the count is visible and must not grow.
- No `retry: 3` to hide nondeterminism; determinism bugs in job handling are real bugs.

## 7. CI wiring

`typecheck → lint → L1 → L5 → L2 → L3 → build → L4 (+L6, L7 on PR) → deploy dev → smoke`.
Release adds L8, L9; L10 is manual with a checklist. Any failure blocks; there is no "merge and fix".

## 8. Manual testing that cannot be automated (yet)

- Real Classroom OAuth with a real Google account (staging only).
- Real AI provider behaviour under rate limiting.
- Screen-reader pass with NVDA.
- Printed report fidelity (paper, not PDF viewer).
- 1366×768 laptop ergonomics with a real marker.

## 9. Definition of "tested" for a feature

A feature is tested when: unit coverage of its rules, an integration path through the API, one E2E journey,
its error states exercised, its permission enforced in the policy test, and (if it touches student data) an
isolation test. Anything less is "demoed", not "tested".
