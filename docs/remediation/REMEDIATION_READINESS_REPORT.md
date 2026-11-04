# Remediation Readiness Report

**Date:** 2026-11-03 · **Phase:** 2 — Architecture Remediation & Decision Closure
**Deliverables:** 12 documents in `docs/remediation/` · **Original documents modified:** 0

---

## 1. Verdict

# REQUIRES OWNER DECISIONS

Not because a technical question is unresolved — none is — but because six decisions are the owner's to make and
this remediation was explicitly forbidden from inventing them.

| Block | Verdict | Detail |
|---|---|---|
| **UI design** | **READY** | Nothing blocks P3. Both prior blockers are closed: the permission model is specified (`SEC-04` → resource-aware + shapers) and the review-draft model is decided (`UX-01` → server-side, `C9` only ratifies). |
| **Architecture approval** | **READY, SUBJECT TO SIX DECISIONS** | All 27 CRITICAL/HIGH findings have written resolutions. Six product decisions (`C1`–`C5`, `C7`) must be answered before the architecture is binding. Answering them is a signature, not a design session. |
| **Implementation start** | **NOT YET** | P2 is blocked on `C1` (identity contract). Nothing else blocks, and P1 (the parity spike) can start immediately — it touches no tenancy, no auth and no schema this remediation changed. |
| **Launch** | **NOT YET** | `C7` (report host) and `C6` (backup retention) remain, plus the drills and the pen test that were always launch gates. |

Why not **READY FOR ARCHITECTURE APPROVAL**: because the six decisions are product decisions with real
trade-offs (session length, MFA friction, upload path, report processor), and marking them approved on the
owner's behalf would be exactly the failure the mission warned against.
Why not **REMEDIATION INCOMPLETE**: every one of the 93 findings has a disposition, 68 are closed outright, 23 await a signature, and
two are deferred or informational. Nothing is unaddressed.

---

## 2. Completion criteria

The mission's nine criteria, each with evidence rather than assertion.

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | Every CRITICAL and HIGH finding has a documented resolution or explicit owner decision | 27 findings: 17 `SPEC`, 10 `DEC`; each has a full entry in `CRITICAL_AND_HIGH_REMEDIATION.md` | **Met** |
| 2 | No critical security requirement relies solely on frontend enforcement or developer convention | `SECURITY_ENFORCEMENT_SPECIFICATION.md`: every requirement names a layer from `EDGE`/`ROUTE`/`POLICY`/`REPO`/`DB`/`SHAPE`. Six residual conventions are enumerated with their compensating controls (§10 there) | **Met** |
| 3 | The database and API specifications agree | Both written against one schema; the API's permission column, the matrix and the manifest agree; `T-PERM-08` fails the build on divergence | **Met** |
| 4 | Every major product workflow has a defined backend contract | 15 journeys → endpoints in `UPDATED_TRACEABILITY_MATRIX.md` §2; 7 previously missing journeys now defined; export, sampling, drafts, notifications, operations all have contracts | **Met** |
| 5 | The R2 recovery design is technically implementable | Built only on verified primitives (`CopyObject`, event notifications to Queues, bucket locks, lifecycle, checksums); the three things R2 does *not* have are stated and worked around, not assumed | **Met** |
| 6 | The Durable Object decision has been formally reconsidered | `ADR-008` → **DEFERRED**, with a costed design, numeric promotion thresholds and a migration path (`DURABLE_OBJECT_DEFERMENT_PLAN.md`) | **Met** |
| 7 | Remaining findings have explicit dispositions | The 66 MEDIUM/LOW findings: 55 `SPEC`, 9 `DEC`, 1 `DEF`, 1 `INFO`, 0 unresolved | **Met** |
| 8 | All document links resolve | Verified: every relative `.md` link in `docs/remediation/` resolves to an existing file | **Met** |
| 9 | All revised claims have current supporting evidence | Platform claims re-verified this phase against primary documentation; the six false claims are corrected in `REVISED_ARCHITECTURE_DECISIONS.md` §1 and register §7 | **Met** |

---

## 3. What changed, in numbers

| Quantity | Before | After |
|---|---|---|
| Distinct findings | 93 | 93 (0 added, 0 removed) |
| Closed outright (`SPEC`) | 0 | 68 |
| Closed pending signature (`DEC`) | 0 | 23 |
| Deferred with rationale (`DEF`) | — | 1 |
| Informational (`INFO`) | — | 1 |
| Unresolved | 93 | **0** |
| Requirements traced | 24 of 46 (52 %) | **46 of 46** (43 T, 3 decision-dependent) |
| ADRs amended or deferred | 0 | 13 amended, 2 deferred, 8 new |
| Tables added | — | 11 product/platform + 1 library (`rate_limit`) |
| Triggers specified | 0 | 23 tenant-consistency pairs + 3 integrity + 2 audit |
| False platform claims | 6 | 0 |
| Security requirements without an enforcement layer | 61 | 0 |

---

## 4. The six decisions that gate approval

| ID | Decision | Recommendation | Blocks |
|---|---|---|---|
| `C1` | Identity schema contract | Adopt Better Auth as canonical | **P2 entirely** |
| `C2` | Session lifetime / staleness | 12 h idle, 7 d absolute, 60 s cache | Auth config, acceptance criteria |
| `C3` | MFA enforcement vs convenience | Assurance gate over all methods | Onboarding, MFA tests |
| `C4` | Upload path | Hybrid (proxy ≤ 20 MB, presign above) | P5 upload surface |
| `C5` | Schema change bundle | Approve as one set | P2/P5 migrations |
| `C7` | Report rendering host | Containers if GA, else API with DPA | P5 report record, P7 |

Full options and consequences: `OWNER_APPROVAL_DECISIONS.md` §C.

---

## 5. Assumptions falsified or changed

`ASSUMPTIONS_AND_RISKS.md` is a living register; a remediation that falsifies an assumption must say so rather
than quietly dropping it. The original is unmodified, so the corrections are recorded here.

| # | Original assumption | Status | Evidence |
|---|---|---|---|
| A7 | "D1's 10 GB cap is far away for metadata-only storage" (High confidence, >10 years) | **Weakened** | Real arithmetic: 4.4–6.1 KB/submission → ~3–4 years at 100 workspaces with stated retention. Still far, but by a factor of three, not ten |
| A11 | "Durable Objects with hibernation are cost-effective at this scale" | **Falsified as stated** | Cost-effective *if built*, but never compared against the cost of not building anything. Polling is ~$0 and adds no stateful surface |
| A12 | "Better Auth covers organizations, MFA, passkeys adequately" | **Qualified** | Passkeys and orgs yes; MFA does not gate non-password sign-in without an application gate; rate limiting is in-memory by default; schema validation fails closed |
| A8 | "Queues/Workflows are sufficient for the correction pipeline" | **Qualified** | Sufficient *with* an outbox, a reaper and a DLQ. Without them the pipeline is lossy, which the original assumption did not distinguish |
| — | "Cross-tenant FKs are impossible by construction" (a claim, not an assumption) | **Falsified** | A code convention; now enforced by triggers |
| — | "R2 objects are versioned by key prefix" (BACKUP §3) | **Falsified** | No versioning exists |
| — | "R2 presigning needs long-lived credentials" (ADR-006) | **Falsified** | Presigned URLs exist, 1 s–7 days |
| — | "TanStack prerender/SPA unsupported behind the plugin" (ADR-001) | **Falsified** | Prerender shipped 2025-12-19 |

New risks introduced by this remediation, recorded so they are not surprises: a 60 s session-cache staleness
window (down from unbounded), ~60 s publisher latency, roughly 25 % additional storage for backups, and a copier
that is now a monitored component.

---

## 6. Limitations — what this package cannot prove

| Limitation | Consequence |
|---|---|
| **No code was written and no test was run.** Every `T-*` identifier is a *specification* of a test, not a result | The matrix proves traceability, not correctness. The first implementation sprint must produce these tests, and P2/P5 exit criteria depend on them passing |
| **Cost figures are derived, not measured.** Unit prices are verified; the workload and the AI cost `C` are not | `C` remains the dominant unknown; no pricing decision is safe before P1 measures it |
| **Better Auth's DDL was not generated.** Column lists came from the library's schema sources; the generated `CREATE TABLE` statements, index names and nullability were not verifiable without installing the package | The first migration is a generation step followed by review, not a transcription of `REVISED_DATABASE_SPECIFICATION.md` §2 |
| **The organization plugin's `member`/`invitation` column lists were not fully verified** (the schema section is rendered from components) | The partial unique index on `member` may collide with a library index; `T-DB-05` and the migration review both check it |
| **UX judgements rest on stated personas, not user testing** | Sampling in the MVP (`C10`) is a product bet, correctly labelled as one |
| **Nothing above 250 workspaces is modelled** | The scaling table ends there with "re-architecture"; that is honest, not predictive |
| **R2 lock semantics have no governance bypass** (documented absence) | The 90-day retention is a hard commitment; shortening it is not a config change |
| **No legal review** | `C11` (erasure) and `Q1–Q2` (controller/lawful basis) still need counsel |

---

## 7. Risks accepted deliberately

| Risk | Why accepted | Mitigation |
|---|---|---|
| Isolation remains application-enforced (plus triggers) | No RLS in SQLite, and Postgres costs ~50 ms/query plus a vendor | Triggers, typed repository, schema-enumeration test, shaper |
| 60 s role staleness | Zero cache means a D1 read per request | Sensitive routes bypass the cache; figure is published and tested |
| Backup copy lives in the same account | Off-provider copy adds a vendor for a scenario not yet required | Bucket lock + scoped tokens + documented next step |
| Presigned upload URL is a 15-minute bearer token | Proxying 200 MB through a Worker is worse | Single key, single use, post-upload validation, quarantine |
| Polling instead of realtime | No measured need; a stateful surface has ongoing cost | Numeric promotion thresholds |
| No malware scanner | No first-party scanner for R2 | Type/size/magic-byte/page caps, no execution, quarantine state |

---

## 8. Next actions, in order

1. **Answer `C1`, `C5`, `C2`, `C3`, `C4`, `C7`** (one working session; options and consequences are pre-written).
2. **Start P1 now.** The parity spike is independent of every remediation change: it needs the engine, the
   fixtures and the tier-0 measurement of AI cost `C`.
3. **Generate and review the identity DDL** against `REVISED_DATABASE_SPECIFICATION.md` §2; commit as migration
   `0001`. This is the first substantive implementation act.
4. **Author migrations `0002`–`0007`** (extensions, domain, constraints, triggers, indexes, platform) and run the
   schema-enumeration test before any feature code.
5. **Build the isolation suite additions** (`T-DB-01/02`, `T-PERM-01…05`) in P2 alongside the schema, not after.
6. **Do not start P5 without the outbox, reaper and DLQ.** They are cheap and they are the promise.
7. **Book the first restore drill before the first customer.** The backup is a rumour until it is restored.

---

## 9. Confidence

| Area | Confidence | Basis |
|---|---|---|
| Finding dispositions | **High** | Each is grounded in a document section and a mechanism; 68 closed by specification |
| Platform facts | **High** | Re-verified this phase against primary docs (Better Auth schema sources, R2 S3-compatibility and durability pages, event-notification docs, bucket-lock docs) |
| Database specification | **High for design, medium for DDL** | Logical schema is complete; the generated baseline must be reviewed (limitation §6) |
| Security enforcement | **High** | Every requirement names an enforcement layer and a failure behaviour; six residual conventions are disclosed |
| Backup design | **High** | Every primitive is documented and current; the three absent capabilities are stated and worked around |
| Cost | **Medium** | Unit prices verified; workload assumptions unchanged from the audit |
| UX | **Medium** | Persona-based, not tested |
| Schedule effect | **Medium** | ~6–8 days of design work already spent; the decisions unblock ~10 days of P2 |

---

## 10. Closing assessment

The package is now internally consistent, and the consistency is structural rather than textual: the schema
enforces what the documents promise, the API's permissions come from one definition, the matrix is generated, and
the seams that produced the original contradictions have tests that fail the build.

Three things are worth saying plainly, because a remediation that only congratulates itself is as unreliable as
an audit that only criticises.

**The original plan was right about the things that are expensive to get wrong.** Shared-schema tenancy, marking
parity first, ids-only messages, `needs_verification` as a real state, 404-not-403, metering before billing. None
of that changed. The 93 findings were almost entirely about the last mile of implementation detail and about
operational claims that had not been checked against the platform.

**The most serious finding was not a security hole.** It was a two-line gap between a database insert and a queue
send that would have produced "queued since Tuesday" tickets and no diagnostic path. That is what a plan written
from the inside tends to miss, and it is now two tables and two crons.

**The remaining work is decisions, not design.** Six answers, then P2 can begin. The distance from here to a
buildable specification is measured in a working session plus the DDL review, not in weeks.

The failure mode to avoid from here is the inverse of the one the audit caught: treating a consistent document
set as a working system, and discovering in P5 that a specified test was never written. Every `T-*` identifier in
this package is a promise that implementation must keep.
