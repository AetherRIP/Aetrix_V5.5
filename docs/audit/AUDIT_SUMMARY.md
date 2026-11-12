# Audit Summary

**Subject:** Aetrix V5.5 UI_V5.5 planning package — 32 documents, 213 KB, planning complete, no code written.
**Audit date:** 2026-11-03. **Auditor:** independent review; the auditor did not write the original plan.
**Constraint honoured:** no application code, no dependencies, no Cloudflare resources, no deployment, no change to
any of the 32 source documents, no rename, no modification of `MATH_CHECKER_V5` or `Engine_V5.5`.

## 1. What was done

- Read all 32 documents in full (`README.md`, 5 product, 6 design, 7 architecture, 3 security, 4 operations,
  3 testing, 3 decisions), plus `.agents/SKILLS_INDEX.md` for context.
- Re-verified every platform claim against current official documentation: TanStack Start, Cloudflare Workers /
  D1 / R2 / Queues / Workflows / Durable Objects, Better Auth, OWASP session guidance.
- Traced 46 requirements from statement → design → architecture → phase → test.
- Attempted cross-tenant access through every channel the design exposes, and checked whether each named control
  actually exists at the layer that would enforce it.
- Recomputed the cost model and the storage projection from stated assumptions.
- Produced 12 audit documents, none of which modifies the source package.

## 2. Headline assessment

This is a **strong planning package**. It is decision-oriented rather than descriptive, it documents alternatives,
it separates what is verified from what is assumed, and it makes one genuinely difficult call correctly — proving
marking parity before drawing a single screen. That is rare, and it is the right instinct for this product.

It is also **not ready to build from**. Three classes of problem recur:

1. **Durability gaps in the asynchronous path.** The pipeline that carries every mark has two silent failure modes,
   and the monitoring plan cannot see either. This is the most serious finding in the audit and it is fixable with
   two tables and two crons.
2. **Controls asserted at the wrong layer.** MFA that the library does not enforce for passkeys, permission
   restrictions the API cannot express, tenant consistency delegated to a code convention, session staleness
   assumed away by a cache that has no bust, an upload control that depends on a backup feature R2 does not have.
   Each is individually small; together they are the pattern that turns a secure design into a breached system.
3. **Documentation drift at the seams.** The large decisions agree with each other; the edges do not. Export exists
   in a journey and not in the API. A screen has no endpoint. V5 migration is both accepted and deferred. The
   permission matrix promises row-level scoping that the policy model cannot hold.

## 3. Findings by severity

**93 numbered findings** across eleven audit documents.

| Severity | Count | Findings |
|---|---|---|
| **CRITICAL** | **1** | ARC-01 — no atomic boundary between the job row and the queue message → silent, undetected job loss (restated as REL-01, counted once) |
| **HIGH** | **26** | ARC-02…04; SEC-01…05; DB-01…05; API-01, API-02; DOC-01…04; UX-01, UX-02; REL-02…04; COST-01; ROAD-01 |
| **MEDIUM** | **52** | ARC-05…08, ARC-10; SEC-06…09; DB-06…11; API-03…08; DOC-05…12; UX-03…10, UX-12; REL-05…11; COST-02…06; ROAD-02, ROAD-03 |
| **LOW** | **14** | ARC-09; SEC-10; DB-12, DB-13; API-09, API-10; DOC-13…16; UX-11; REL-12; COST-07, COST-08 |

Cross-listed issues are counted once at their primary location (REL-01 → ARC-01; DOC-02 → SEC-04; DOC-03 →
API-02/SEC-09; DOC-04 → API-01). Four further observations are unnumbered: the source Cloudflare docs disagree
with themselves on D1 databases per account (1,000,000 ceiling vs 100,000 included); the 50 MB D1 result cap takes
effect 2026-11-04, one day after this audit; D1's `BEGIN/COMMIT` limitation is documented indirectly rather than
declared; and Vinext's status is beta per docs but 1.0 "production-ready" per Cloudflare's own blog.

## 4. The three things that must change first

1. **Make the asynchronous path durable.** Outbox + reaper + DLQ. Without them the product's own promise
   (≥ 99 % of jobs terminal within 24 h) is not supportable, and no monitoring signal reveals the failure.
2. **Reconcile identity before P2.** Better Auth's required tables and the package's hand-rolled `users`/
   `sessions`/`memberships` are different systems. Choosing late means choosing under pressure, and the shortcut
   (duplicate identity rows) produces stale membership — a security bug.
3. **Fix the claims that are false.** TanStack SPA/prerender support, R2 presigning, R2 versioning/replication,
   the session-cache bust, and "cross-tenant FKs are impossible by construction". A decision document that is wrong
   about a verifiable fact cannot be trusted about the unverifiable ones.

## 5. What the package gets right

Worth stating plainly, because a red-team report that only lists faults is itself unreliable:

- **The tenancy model** is the correct answer for D1 and is better reasoned than most production SaaS designs.
- **Marking parity before design** (ADR-011) is the strongest judgement in the package and should survive
  unchanged.
- **`needs_verification` and `automation_operations`** are excellent domain modelling for a non-idempotent remote
  API, and the three-operation publish model is unusually careful.
- **The isolation test harness** — two workspaces with confusable names, 16 resources × 3 request shapes, asserting
  404 in the body — is genuinely good test design.
- **The design language** is specified to token level, refuses the current default aesthetic on stated grounds, and
  documents what it cannot fix (handwriting accessibility).
- **The honesty about compliance**: no SOC 2 claim, no "GDPR compliant" marketing, legal questions left open rather
  than asserted. That is the correct posture and it should not be softened later.

## 6. Verdict

**READY WITH REQUIRED CHANGES.**

The plan is good enough to keep, and not good enough to build from unmodified. Nothing found requires abandoning a
major decision: every CRITICAL and HIGH finding is closed by adding a table, a constraint, a cron, an endpoint, or
a configuration decision — not by re-architecting. The full reasoning, and the separation of what blocks design,
architecture, implementation and launch, is in `FINAL_READINESS_REPORT.md`.

## 7. Documents in this audit

| File | Contents |
|---|---|
| `AUDIT_SUMMARY.md` | This document |
| `DOCUMENT_CONSISTENCY_AUDIT.md` | 16 findings (10 direct contradictions), missing journeys, permissions, criteria, terminology |
| `ARCHITECTURE_RED_TEAM.md` | Platform reality check, ARC-01…ARC-10, subsystem verdicts |
| `ADR_REVIEW.md` | ADR-001…ADR-015: evidence for, evidence against, verdict, confidence, follow-up |
| `MULTI_TENANT_SECURITY_AUDIT.md` | SEC-01…SEC-10 attack scenarios and mitigations |
| `DATABASE_API_AUDIT.md` | DB-01…DB-13, API-01…API-10, cross-document mismatches |
| `UX_PRODUCT_GAP_ANALYSIS.md` | UX-01…UX-12, usability risks for the real buyer, scope to cut |
| `RELIABILITY_AUDIT.md` | REL-01…REL-12, failure matrix |
| `COST_SCALABILITY_AUDIT.md` | Recomputed workload and costs, COST-01…COST-08, tier verdicts |
| `REQUIREMENT_TRACEABILITY.md` | 46 requirements traced; roadmap ordering review (ROAD-01…03) |
| `RECOMMENDATIONS.md` | 40 gated recommendations with effort and approval flags |
| `FINAL_READINESS_REPORT.md` | Separate verdicts for design, architecture, implementation, launch |
