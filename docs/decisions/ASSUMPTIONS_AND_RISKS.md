# Assumptions and Risks

**Status:** living register. Assumptions are things we believe without proof; risks are things that could hurt
us whether or not we believe them. Each has an owner and a way to be falsified.

**Labels.** Every row in §1 is an **ASSUMPTION** — the Confidence column rates how strongly we hold it, it is
not a label. The platform facts those assumptions rest on are **VERIFIED** against official documentation (D1's
10 GB cap, the Queues 128 KB message cap, Workers Paid CPU limits — cited in
`../operations/COST_AND_SCALABILITY.md`); the assumptions are about *our* workload, which no document can
verify. Risk likelihood and impact in §2 are **ASSUMPTION**-grade estimates until telemetry exists. Two items
are explicitly **UNKNOWN** rather than assumed: R11 (whether pricing/legal clears before launch) and A15
(whether exam-paper copyright is ours to carry).

## 1. Assumption register

| # | Assumption | Confidence | How to falsify | Consequence if wrong |
|---|---|---|---|---|
| A1 | 5–10 assistants per workspace is representative | Medium | First 5 pilot workspaces | Seat-based UI limits, invite flows, pagination |
| A2 | One workspace ≈ one school department | Medium | Pilot interviews | Nested orgs / sub-workspaces needed |
| A3 | ~300 submissions/workspace/month | Low | Pilot telemetry | Cost model, queue concurrency |
| A4 | Marking is the bottleneck, not assignment setup | Medium | Time-on-task study | Roadmap priority shifts to setup |
| A5 | Teachers will accept AI marks with human review | Medium | Pilot trust survey | Product premise fails |
| A6 | Classroom is optional, not the system of record for everyone | Medium | Pilot mix | Phase 6 becomes mandatory and blocking |
| A7 | D1's 10 GB cap is far away for metadata-only storage | High | Storage telemetry at 50 workspaces | Tiering to per-tenant DBs (option C) |
| A8 | Queues/Workflows are sufficient for the correction pipeline | High | Phase 1 spike | Containers or an external orchestrator |
| A9 | Python PDF tooling cannot run in Workers | High | Phase 1 spike | If false, drop the container (simplification) |
| A10 | TanStack Start is production-ready for this app | Medium | Phase 1–3 | Switch to React Router v8 (ADR-001) |
| A11 | Durable Objects with hibernation are cost-effective at this scale | Medium | 1 month of real traffic | Polling-only realtime |
| A12 | Better Auth covers organizations, MFA, passkeys adequately | High | Phase 2 build | Add WorkOS/Clerk (ADR-005) |
| A13 | A single region is acceptable to customers | Medium | Sales conversations | Multi-region or data-residency work |
| A14 | Report PDFs must be server-generated | Medium | Customer interviews | Client-side print only (simplifies hosting) |
| A15 | Exam-paper copyright is the school's responsibility | Low | Legal review | Licence agreements, storage restrictions |

**Unvalidated assumptions are the cheapest thing to test and the most expensive thing to build on.** A1, A3,
A5 are the three that change the product shape, and all three are answerable with five pilot conversations.

## 2. Risk register

| # | Risk | L | I | Score | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R1 | Cross-tenant data leak | L | Critical | **High** | ADR-004 layering; isolation suite blocking; pen test | Eng |
| R2 | Silent wrong mark erodes trust | M | Critical | **High** | Blueprint enforcement; `needs_review`; verification never rewrites; sampled supervisor review | Product + Eng |
| R3 | AI cost exceeds willingness to pay | H | High | **High** | Measure C in phase 1; quotas; fewer calls per submission; per-workspace keys | Product |
| R4 | PDF tooling cannot be hosted as planned | M | High | **High** | Phase 1 spike before any UI work | Eng |
| R5 | Google OAuth verification delay | M | Medium | Medium | Manual path first; start verification early | Product |
| R6 | Small team, large scope | H | High | **High** | MVP cut line enforced; phases gated; no billing/SSO/presence | Product |
| R7 | Design churn | M | Medium | Medium | Direction frozen at P0; component budget; density as a tunable | Design |
| R8 | D1 single-writer throughput at burst | M | Medium | Medium | Small writes; status churn batched; sharding path documented | Eng |
| R9 | Malware in uploads | L | High | Medium | Type/size/page caps; no execution; sandboxed parse; scanning service as an option | Eng |
| R10 | Support access misuse | L | High | Medium | Consent grants + per-read audit (ADR-013) | Ops |
| R11 | Pricing/legal blocked at launch | M | High | **High** | Q1–Q4 answered early; no compliance claims until confirmed | Founder |
| R12 | Vendor lock-in to Cloudflare | M | Medium | Medium | No heavy ORM; SQL-first schema; export tooling; the exit is painful but possible | Eng |
| R13 | Key-person dependency | H | High | **High** | Documentation (this package), ADRs, runbooks, pair on critical paths | Founder |
| R14 | Scope creep from "modern SaaS" expectations | H | Medium | **High** | This document's non-goals; roadmap cut line; say no in writing | Product |

## 3. What would make us change course

Written in advance so the decision is not made in a panic:

| Trigger | Response |
|---|---|
| Phase 1 parity < 95% on fixture scripts | Stop feature work; fix or re-scope the engine before anything else |
| A customer requires database-level isolation | Implement option C (per-tenant DB) for that tier only; do not migrate everyone |
| Measured AI cost > $0.10 per script | Re-architect the prompt/pre-pass, or price per script; do not absorb it |
| TanStack Start instability in phases 2–3 | Switch to React Router v8 (ADR-001); the app code is portable |
| Two consecutive isolation escapes | Pause releases; structural review; consider Postgres |
| Pilot shows < 3 workspaces after 3 months | Re-examine A4/A5 before building phases 7–9 |

## 4. Risks we are choosing to accept

1. **Shared-DB isolation is application-enforced.** Cheapest to run, requires discipline forever.
2. **No malware scanner in MVP.** Documented, with compensating validation.
3. **No offline support.** Schools with poor connectivity will have a worse experience; the review canvas is
   online-only.
4. **Single region.** Latency outside the primary region is worse; residency requests will need work.
5. **No billing in MVP.** We cannot charge on day one, deliberately.

## 5. Review cadence

- Assumptions A1–A5 re-checked after each pilot cohort.
- Risk register reviewed at every phase gate; scores change only with evidence.
- Any assumption that becomes *false* triggers an ADR update in the same week — otherwise the docs drift and
  stop being trusted.
