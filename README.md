# MathChecker V5.5

**This repository is part of MathChecker V5.5 — the hosted, multi-tenant rebuild of MathChecker — and it is a
work in progress.**

It contains the **planning, audit and remediation documentation** for the rebuild, and now the **public
marketing website** built from it: the TanStack Start frontend in `src/`, with its record in
[`docs/implementation/MARKETING_LANDING_IMPLEMENTATION.md`](docs/implementation/MARKETING_LANDING_IMPLEMENTATION.md).
The authenticated workspace is not built, and no Cloudflare resource, database or deployment has been created.
That is deliberate: the rebuild is being specified to the point where implementation cannot invent its own answers.

| | |
|---|---|
| **Product** | MathChecker — AI-assisted marking for Edexcel IGCSE 4MA1 |
| **This package** | `UI_V5.5` — the blueprint for the hosted rebuild |
| **Status** | Planning complete · independently audited · remediation complete · **awaiting six owner decisions** before phase 2 |
| **Code** | Public marketing site only (TanStack Start 1.0 on Workers). No authenticated app, no data layer |
| **Predecessor** | MathChecker V5 (`C:\Projects\MATH_CHECKER_V5`) — a local FastAPI + React + SQLite application, untouched by this repository |

## Where the build stands

The plan was audited by an independent red-team pass (93 findings: 1 critical, 26 high) and then remediated.
The critical finding — a job can be lost silently between the database write and the queue message — is closed
by a transactional outbox and a lease reaper. All 27 critical and high findings have written resolutions.

Six product decisions remain with the owner (identity schema, session lifetime, MFA friction, upload path,
schema bundle, report rendering host). Phase 1 — the marking-parity spike — does not depend on any of them and
can start immediately.

- Full status and verdicts: [`docs/remediation/REMEDIATION_READINESS_REPORT.md`](docs/remediation/REMEDIATION_READINESS_REPORT.md)
- The decisions awaiting sign-off: [`docs/remediation/OWNER_APPROVAL_DECISIONS.md`](docs/remediation/OWNER_APPROVAL_DECISIONS.md)

## What is in here

```
docs/
├── README.md              the blueprint's own front door and reading order
├── implementation/         what was actually built from the blueprint, with rendered evidence
├── product/                vision, feature inventory, roles, journeys, roadmap
├── design/                 design directions, system, IA, screens, responsive, accessibility
├── architecture/           system, multi-tenancy, database, API, Cloudflare, jobs, realtime
├── security/               threat model, security requirements, data privacy
├── operations/             deployment, monitoring, backup, cost
├── testing/                strategy, tenant-isolation suite, acceptance criteria
├── decisions/              ADRs, open questions, assumptions and risks
├── audit/                  independent red-team review (12 documents, 93 findings)
└── remediation/            the response to that review (12 documents)
```

**Three document sets, read in this order:**

1. **`docs/` — the blueprint (32 documents).** Decision-oriented: every major choice states its alternatives and
   what would force a revisit. Start at [`docs/README.md`](docs/README.md).
2. **`docs/audit/` — the independent review (12 documents).** Written by a reviewer who did not write the plan.
   Start at [`docs/audit/AUDIT_SUMMARY.md`](docs/audit/AUDIT_SUMMARY.md).
3. **`docs/remediation/` — the response (12 documents).** Revised specifications that supersede the blueprint
   where they differ, plus the register of every finding and its disposition. Start at
   [`docs/remediation/REMEDIATION_MASTER_REGISTER.md`](docs/remediation/REMEDIATION_MASTER_REGISTER.md).

**Where the documents disagree, the remediation wins**, and the blueprint stays as the historical record of what
was decided first and why. The audit is never edited to look prescient.

## The shape of the rebuild, in ten lines

- **Frontend:** TanStack Start 1.0 (SSR React) on Cloudflare Workers.
- **Database:** one D1 database, shared schema, `workspace_id` on every tenant table, enforced by a typed
  repository *and* by database triggers — not by convention.
- **Auth:** Better Auth on D1, whose schema is canonical; five workspace roles declared once and generated into
  both the policy code and the permission matrix.
- **Files:** R2, workspace-prefixed keys derived server-side, proxied downloads, presigned uploads only above
  20 MB.
- **Jobs:** Queues + Workflows, ids-only messages, a transactional outbox, a lease reaper and a real dead-letter
  queue.
- **Progress:** polling, not a Durable Object — deferred with numeric promotion thresholds rather than built on
  a hunch.
- **Backups:** a copy pipeline built on R2's actual primitives (server-side copy, bucket locks, checksums),
  because R2 has no versioning and no replication.
- **Marking integrity:** a mark can never exceed its question's maximum, and a missing question is `needs_review`
  — both enforced in the database, not only in a handler.
- **Billing:** out of the MVP; usage is metered from the first job so pricing can be added without a migration.
- **Non-claims:** no SOC 2, ISO 27001 or "GDPR compliant" claim appears anywhere until one is actually obtained.

## Ground rules for this repository

1. **V5 is the source of truth until marking parity is proven.** The engine, prompts and lesson identity
   (`CH1L1`) carry over; the surface is rebuilt.
2. **Planning documents are contracts.** Changing a decision means a new numbered record that names the one it
   replaces — not editing an accepted decision in place.
3. **Nothing in the docs is a claim about a running system.** Cost figures are estimates with stated
   assumptions; platform limits are cited and dated; anything unverified is labelled as such.
4. **No student data in this repository.** Fixtures and examples are synthetic; real scripts, names and marks
   stay in the product's private storage.

## Next steps

1. Owner answers the six blocking decisions (`C1`–`C5`, `C7`).
2. Phase 1: port the marking engine and prove parity on ≥ 20 fixtures, including the failure paths.
3. Generate and review the identity DDL, then the constraint and trigger migrations.
4. Build the tenant-isolation suite alongside the schema — it is a shipping gate, not a chore.
