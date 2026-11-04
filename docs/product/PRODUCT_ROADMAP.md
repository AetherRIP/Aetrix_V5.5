# Product Roadmap

**Status:** RECOMMENDED. Phases are ordered by **risk retired per unit of work**, not by feature appeal.
The proposed order in the brief is challenged in §4.

## Phase table

| Phase | Objective | Exit criteria (all must hold) |
|---|---|---|
| 0 | Discovery and decisions | Open questions answered; ADRs signed; tenancy + auth decisions frozen |
| 1 | **Correction parity spike** | One real V5 script marked through the new runtime with identical totals and `REVIEW` behaviour |
| 2 | Tenancy, auth, workspace shell | Two workspaces cannot see each other; invites, roles, sessions proven by tests |
| 3 | Design system + app shell | Tokens, core components, navigation, keyboard model; a11y baseline passes |
| 4 | Academic + assignment management | Classes, students, assignments, scheme blueprint review, allocation |
| 5 | Files + correction pipeline | R2 upload, job lifecycle on Queues/Workflows, review + override + approve |
| 6 | Classroom integration + publishing | Report attach, grade publish, return, `NEEDS_VERIFICATION` reconcile |
| 7 | Reporting and analytics | Class report PDF, distributions, trends, workload, exports |
| 8 | Collaboration + notifications | Ownership, comments, review requests, in-app + email notifications |
| 9 | Administration + observability | Workspace admin complete; platform admin with consent-based support access |
| 10 | Hardening, launch, commercial | Security review, load test, runbooks, restore drill; billing designed (not necessarily built) |

## Phase detail (compressed)

**P0 Discovery.** Answer `../decisions/OPEN_QUESTIONS.md`. Outputs: ADRs, threat model reviewed, data
classification, retention defaults, pricing thesis. *Risk retired:* building the wrong tenancy.

**P1 Correction parity spike.** Highest technical risk is not Cloudflare — it is whether the marking engine
survives the move (`temperature: 0`, seeding, file re-upload semantics, PDF tooling in Workers).
Deliberately ugly: a single Worker endpoint, a hard-coded workspace, no UI. Compare per-question marks
against V5 output for a fixture set of ≥ 20 scripts. *If this fails, everything downstream changes.*
Note: ReportLab + PyMuPDF are Python-native; **PDF generation and heavy PDF inspection cannot run in
Workers**. P1 must therefore settle the compute question (containers vs external service vs client-side
inspection) before P5.

**P2 Tenancy + auth.** D1 schema, tenant-scoped data layer, Better Auth with organizations, roles,
invitations, session management. Ship the isolation test suite here, not later.

**P3 Design system.** Tokens → components → shell. Runs partly in parallel with P2 (different people).
Direction from `../design/DESIGN_DIRECTIONS.md`; specs in `../design/DESIGN_SYSTEM.md`.

**P4 Academic + assignments.** Bulk CSV import, duplicate detection, scheme blueprint review (the V5
`scheme_decisions` concept), allocation and claiming.

**P5 Files + correction.** Presigned upload, multipart, job orchestration, review/override/approve, live
progress. This is the largest phase; split into 5a (pipeline) and 5b (review surface).

**P6 Classroom.** OAuth per workspace, incremental sync, report attach, grade publish with the three
independent operations and `NEEDS_VERIFICATION` reconciliation. Must be **optional** at every step.

**P7 Reporting.** Server-side PDF (see P1 compute decision), grade matrix, distributions, trends.

**P8 Collaboration.** Comments, mentions, review requests, notification preferences. Presence deferred.

**P9 Administration.** Workspace admin, platform admin, consent-based support access, audit search.

**P10 Hardening.** Pen-test fixes, load test at 10× expected, restore drill, runbooks, on-call.

## MVP cut line

**In MVP:** P0–P6, plus the report PDF (P7 partial), in-app notifications only, workspace admin only,
single region, no billing, no SSO, no presence, no public API for customers.

**Out of MVP:** platform admin polish, email digests, analytics trends, SCIM/SSO, billing, mobile app,
WPF client, custom domains per workspace, data residency options.

## 4. Where this order challenges the brief

1. **Correction parity comes before the design system.** The brief puts design first. Design is the
   visible risk; marking parity is the existential one, and it is cheap to test early. If PyMuPDF-class
   PDF work cannot run on the target platform, the architecture changes — better to know in week 2.
2. **Tenancy before features.** Every later table inherits `workspace_id`; retrofitting it is the classic
   multi-tenant rewrite. The isolation test suite is a P2 deliverable, not a P9 chore.
3. **Classroom is phase 6, not phase 4.** It is an integration with an external system of record and its
   own failure modes; the product must be demonstrably useful with manual uploads first. This also
   de-risks the OAuth verification/allow-list dependency.
4. **Billing stays out, metering stays in.** Usage counters ship in P5 so that pricing can be added
   without a schema migration.
5. **Platform admin is late on purpose.** Tempting to build early; it is the highest-privilege surface and
   benefits from a mature audit model.

## Dependencies and critical path

```
P0 → P1 ─┬→ P2 → P3 ─┬→ P4 → P5 → P6
         └────────────┴→ P7 → P8 → P9 → P10
```

- P1 blocks P5 (compute decision) and P7 (PDF generation).
- P2 blocks everything data-bearing.
- P3 blocks P4+ (screens need components, not the reverse).
- P6 depends on P5 and on Google OAuth verification lead time (weeks, external).

## Risks by phase

| Phase | Dominant risk | Mitigation |
|---|---|---|
| P1 | PDF/AI tooling not portable to Workers | Spike; containers or external render service as fallback |
| P2 | Isolation bug | Typed data layer + standing cross-tenant test suite |
| P3 | Design churn | Freeze direction at P0; component budget capped |
| P5 | Job orchestration edge cases | Port V5 retry table verbatim; chaos tests for park/timeout/cancel |
| P6 | Google API policy/quota | Manual path always available; graceful degradation |
| P10 | Cost surprise | Metering from P5; budget alerts at 50/80/100% |
