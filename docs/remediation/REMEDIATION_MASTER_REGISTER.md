# Remediation Master Register

**Phase:** 2 — Architecture Remediation & Decision Closure · **Date:** 2026-11-03
**Scope:** planning and documentation only. No application code, no dependencies, no Cloudflare resources, no
deployment. The 32 planning documents and the 12 audit documents are **unmodified**; this directory is additive.

**Status vocabulary used throughout `docs/remediation/`:**

| Code | Meaning |
|---|---|
| `SPEC` | Closed by a specification change in this package. No owner input needed. |
| `DEC` | Closed by a specification change **and** an owner decision (see `OWNER_APPROVAL_DECISIONS.md`). |
| `DEF` | Deliberately out of MVP scope, with rationale and a re-entry condition. |
| `RISK` | No change; risk accepted and recorded. |
| `INFO` | Informational; no action required. |

The audit's own severity table was corrected during this phase (see §1.2). Findings are counted **once**, at
their primary location; `REL-01` is the reliability restatement of `ARC-01`.

---

## 1. Baseline

### 1.1 What was read

All 44 documents: `README.md`, 5 product, 6 design, 7 architecture, 3 security, 4 operations, 3 testing,
3 decisions, and 12 audit documents. This register does not restate them; it records what changed in response.

### 1.2 Baseline arithmetic, re-checked

| Check | Result |
|---|---|
| Unique finding identifiers across the audit | **94** (`ARC`10, `SEC`10, `DB`13, `API`10, `DOC`16, `UX`12, `REL`12, `COST`8, `ROAD`3) |
| Distinct findings after de-duplication | **93** — `REL-01` is `ARC-01` restated |
| Severity split | **1 CRITICAL · 26 HIGH · 52 MEDIUM · 14 LOW** |
| Gated recommendations | **40**, in five gates |
| ADRs requiring reconsideration | **15** (all of `ADR-001`…`ADR-015` reviewed; 13 amended, 2 deferred) |
| False or imprecise platform claims | **6** (§7) |
| Missing architectural requirements not captured as findings | **17** (§8) |

The audit summary originally printed 23 HIGH / 31 MEDIUM / 12 LOW. That was an under-count produced by
summarising rather than enumerating; the enumeration above is authoritative and matches the per-finding rows in
§2. This is recorded because a remediation register that miscounts its own inputs cannot be audited.

### 1.3 Independent validation stance

The audit was treated as a **proposal**, not as evidence. Eleven consequential recommendations were re-tested
against primary documentation or against the schema itself (§5). Result: **eight confirmed, two refined, one
mechanism corrected, none reversed.** The one reversal is not of a finding but of a *remedy*: the audit's
suggested upload fix (presign everything) is worse than a hybrid, for reasons in `ADR-006R`.

---

## 2. Finding register — all 93

`Docs` lists the original documents the finding touched (abbreviations: `BP` BACKGROUND_PROCESSING, `MT`
MULTI_TENANCY, `DB` DATABASE_DESIGN, `API` API_DESIGN, `CF` CLOUDFLARE_ARCHITECTURE, `SEC` SECURITY_REQUIREMENTS,
`ROLES` USER_ROLES_AND_PERMISSIONS, `BKP` BACKUP_AND_RECOVERY, `MON` MONITORING_AND_LOGGING, `ACC`
ACCEPTANCE_CRITERIA, `ISO` TENANT_ISOLATION_TESTS, `DP` DATA_PRIVACY, `J` USER_JOURNEYS, `S` SCREEN_INVENTORY,
`RM` PRODUCT_ROADMAP, `COST` COST_AND_SCALABILITY, `OQ` OPEN_QUESTIONS, `ADR` ARCHITECTURE_DECISIONS).
`Verify` cites the specification section and the test that proves the fix.

### 2.1 Architecture (`ARC`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| ARC-01 | **CRIT** | No atomic boundary between `jobs` row and queue message | Transactional outbox: `job_outbox` written in the same `db.batch()`; publisher cron publishes behind a `published_at` guard; age alert | BP §2, SA §4 | DB-R §4.9, BP-R §2.3, `T-JOB-01/02` | SPEC |
| ARC-02 | HIGH | No reaper for `running` jobs with expired leases | 2-minute reaper re-queues or fails expired leases; attempts increment only on a winning claim; `instanceId = jobId` makes a duplicate start impossible | BP §2/§4, MON §1 | BP-R §2.4, `T-JOB-03/04` | SPEC |
| ARC-03 | HIGH | Durable Object not justified by cited workload | `ADR-008` deferred; polling specified with a cadence ladder and an SSE-free design; numeric promotion thresholds | RT §2, ADR-008 | DO-DEFER §2–§5 | DEC |
| ARC-04 | HIGH | PDF compute deferred into the phase that needs it | `ADR-017` (new) with three costed options, a P1 measurement gate, and a DPA note | SA §7, RM P1/P7 | ADR-R §3.2, `T-OPS-05` | DEC |
| ARC-05 | MED | Upload path contradicts its own rationale | Hybrid: presigned `PUT` above 20 MB with a scoped token, Worker proxy at or below 20 MB; false presigning rationale deleted | CF §4, ADR-006 | ADR-R §1.6, `T-FILE-01/02` | SPEC |
| ARC-06 | MED | DLQ depends on consumer code the design never shows | Real `corrections-dlq` queue, DLQ consumer, mandatory outer try/catch, depth alarm | CF §5, BP §7 | BP-R §7, `T-JOB-05` | SPEC |
| ARC-07 | MED | Edge rate limits assume an unstated plan tier | Per-user limiting moved into the Worker with a D1 counter; one edge rule retained; tier recorded as a purchase decision | CF §7, SEC AB-1 | SEC-R §3.2, COST-R §4 | DEC |
| ARC-08 | MED | Read replication designed in for absent scale | Primary-only reads; a single `readSession()` seam so replication can be enabled without touching call sites | MT §4, CF §1 | MT-R §4 | SPEC |
| ARC-09 | LOW | KV in the topology with no stated use | KV removed from the MVP topology | SA §1/§6 | ADR-R §4 | SPEC |
| ARC-10 | MED | Performance first tested at release | p95 budgets moved into P5 exit criteria; N+1 guard on the three hot reads | DB §9, TS L8 | ACC-R §6, `T-API-07` | SPEC |

### 2.2 Multi-tenant security (`SEC`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| SEC-01 | HIGH | Support-grant path bypasses membership and is unspecified | First-class `SupportContext` variant, grant **id** on the request, re-read per request, per-permission scope check, audit row in the same batch, read-only | SEC §7, MT §2, API §4 | SEC-R §6, `T-AUTH-09/10` | DEC |
| SEC-02 | HIGH | MFA required by policy but unreachable by configuration | Application-level **assurance gate** independent of sign-in method; enrolment enforced for owner/operator; per-method test matrix | SEC AU-4, ROLES §5 | SEC-R §2.3, `T-AUTH-04…07` | DEC |
| SEC-03 | HIGH | Auth brute-force protection absent on Workers | Better Auth `rateLimit.storage = "database"`; per-account lockout with backoff in `user`; one edge rule; Worker counters for per-user API limits | SEC AU-8/AB-1, CF §7 | SEC-R §3.1, `T-AUTH-11/12` | SPEC |
| SEC-04 | HIGH | Three permission restrictions cannot be expressed | Resource-aware `can(ctx, key, resource?)` plus audience-derived response shapers (`full`/`masked`/`aggregate`) | ROLES §4 ²⁴⁶, API §7/§8 | SEC-R §4, `T-PERM-01…05` | DEC |
| SEC-05 | HIGH | Tenant consistency is a convention; the leak is invisible to the suite | `BEFORE INSERT`/`BEFORE UPDATE` triggers on every child table asserting parent `workspace_id`; write-path test per table | MT §3 rule 5, DB §5 | DB-R §6, `T-DB-01/02` | SPEC |
| SEC-06 | MED | Notification payloads look workspace-broadcast | Scoped by `user_id` at the query, not at the transport; badge counts only for others | RT §4, DB §5 | API-R §6, `T-API-05` | SPEC |
| SEC-07 | MED | Better Auth ships 3 org roles; the product defines 6 | Five workspace roles declared as Better Auth access-control roles; matrix, policy and tests generated from one definition; `platform_operator` moved out of membership | ROLES §2, ADR-005 | SEC-R §4.1, `T-PERM-06` | SPEC |
| SEC-08 | MED | Session lifetime and role staleness exceed policy | `cookieCache.maxAge ≤ 60s`, DB check on sensitive routes, 12 h idle / 7 day absolute, session regeneration on role change | SEC AU-6, ROLES §5.5 | SEC-R §2.4, `T-AUTH-08` | DEC |
| SEC-09 | MED | Export exists in a journey, not in the API | `POST/GET /exports` implemented only as the tenant-scoped Workflow; isolation row counts rows per workspace in the archive | J8, API §4 | API-R §7, `T-ISO-09` | SPEC |
| SEC-10 | LOW | No cache-header regression test | CI assertion that every authenticated route returns `private` and caches vary on cookie | API §10, DP-2 | SEC-R §8, `T-API-08` | SPEC |

### 2.3 Database (`DB`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| DB-01 | HIGH | Identity schema incompatible with Better Auth | Better Auth tables become canonical (`user`/`session`/`account`/`verification`/`organization`/`member`/`invitation`/`twoFactor`/`passkey`); product columns via `additionalFields`; `workspace_id = organization.id`; we own committed DDL | DB §3, ADR-005 | DB-R §2–§3, `T-DB-03` | DEC |
| DB-02 | HIGH | No `api_keys` table though scoped keys are required | `api_keys` with prefix, SHA-256 hash, scope array, expiry, revocation; hard deny-list for member/credential/delete/transfer | API §1, ROLES §5.6 | DB-R §4.7, `T-PERM-07` | DEC |
| DB-03 | HIGH | Tenant consistency unenforced at the data layer | Same mechanism as SEC-05; trigger per child table, both `INSERT` and `UPDATE OF` | MT §3.5 | DB-R §6 | SPEC |
| DB-04 | HIGH | Soft delete collides with workspace-scoped unique constraints | Partial unique indexes (`WHERE deleted_at IS NULL`, `WHERE status <> 'removed'`) | DB §1/§5, ADR-012 | DB-R §5.2, `T-DB-05` | SPEC |
| DB-05 | HIGH | Nothing prevents a mark above the maximum | `CHECK (awarded IS NULL OR awarded BETWEEN 0 AND max_marks)`; override trigger against the blueprint; totals maintained by trigger | DB §1, J4, ACC §2 | DB-R §5.3, `T-DB-06/07` | SPEC |
| DB-06 | MED | Two uniqueness constraints are global | `UNIQUE(workspace_id, submission_id)`, `UNIQUE(workspace_id, r2_key)` | DB §5 | DB-R §5.4 | SPEC |
| DB-07 | MED | Metering can double-count; rollup semantics undefined | `UNIQUE(ws, job_id, attempt_no, kind)` partial index; day rollup recomputed from events with replace semantics | DB §5, COST §5 | DB-R §5.5, `T-DB-08` | SPEC |
| DB-08 | MED | Question marks have no link to the blueprint | `assignment_question_id` FK; `max_marks` derived; totals and completeness computed by trigger; weekly integrity job | DB §3/§5 | DB-R §5.3, `T-DB-09` | SPEC |
| DB-09 | MED | Screens and settings have no storage | Settings as typed `additionalFields` on `organization`; `notification_preferences`; quota columns; unsupported tabs removed | S §45–47 | DB-R §3.3, §4.10 | DEC |
| DB-10 | MED | Missing indexes for the two hottest reads | `(workspace_id, student_id)` on submissions; `(workspace_id, submission_id)` on files | DB §6 | DB-R §7 | SPEC |
| DB-11 | MED | "Append-only audit" has no mechanism | `BEFORE UPDATE` abort trigger; `DELETE` permitted only inside a recorded maintenance window | DB §5, SEC LG-4 | DB-R §6.2, `T-DB-10` | SPEC |
| DB-12 | LOW | Lease index exists with no consumer | Now consumed by the reaper (ARC-02); index retained and documented | DB §6 | BP-R §2.4 | SPEC |
| DB-13 | LOW | `d1 export` limitations noted, not planned | Export runs in the maintenance window against a Time Travel bookmark; blocking behaviour recorded in the runbook | BKP §2, DB §9 | BKP-R §4.2 | SPEC |

### 2.4 API (`API`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| API-01 | HIGH | Grade matrix has no endpoint | `GET /assignments/{id}/results` (cursor, totals only) and `/results/summary` (aggregates, min group 5) | S §36, ACC §8 | API-R §5, `T-API-01` | SPEC |
| API-02 | HIGH | Workspace export endpoint missing | `POST/GET /exports` + `/download`, `workspace.export` permission, Workflow-only implementation | J8, MT §7 | API-R §7, `T-ISO-09` | DEC |
| API-03 | MED | Notifications have storage, event and screen but no endpoints | List, read, read-all, unread-count, per-workspace preferences | S §25/§45 | API-R §6 | SPEC |
| API-04 | MED | Publish tri-state invisible to the UI | `GET /assignments/{id}/operations`, `GET /submissions/{id}/operations` | S §27/§37 | API-R §8 | SPEC |
| API-05 | MED | One permission covers two distinct publish effects | Publish (grades/return) and attach-report split; combined request requires both | API §8 | API-R §8 | SPEC |
| API-06 | MED | Bulk correction unbounded | Cap 100 per request; whole-batch quota check (all-or-nothing); `Idempotency-Key` required | ACC §6 | API-R §5.3 | SPEC |
| API-07 | MED | `Idempotency-Key` on approvals contradicts C2 | Approvals use `If-Match`; idempotency keys only on create-type POSTs; C2 decided | API §1, ISO C2 | API-R §3.2 | SPEC |
| API-08 | MED | Quota maps to 402 | `429` with `code: quota_exceeded` and `Retry-After` omitted deliberately; 402 removed from the set | API §2 | API-R §4 | SPEC |
| API-09 | LOW | Caching assertions absent | Same test as SEC-10, extended to `Vary: Cookie` | API §10 | `T-API-08` | SPEC |
| API-10 | LOW | Invitation acceptance can leak invite existence | One generic response for unknown, expired and wrong-email tokens; timing equalised by a constant-time path | API §4 | API-R §3.4, `T-AUTH-13` | SPEC |

### 2.5 Document consistency (`DOC`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| DOC-01 | HIGH | Three documents disagree on V5 migration | `ADR-015` → **DEFERRED**; one normative statement ("no automatic migration; importer is a separate decision") | ADR-015, OQ Q5, DB §8 | ADR-R §1.15 | DEC |
| DOC-02 | HIGH | Permission matrix promises row-level restrictions | Resolved by SEC-04; footnotes rewritten as enforceable scope definitions | ROLES §4, API §7 | SEC-R §4 | DEC |
| DOC-03 | HIGH | Export in a journey, absent from the API | Resolved by API-02/SEC-09 | J8, API §4 | API-R §7 | SPEC |
| DOC-04 | HIGH | Screen 36 has no endpoint | Resolved by API-01 | S §36 | API-R §5 | SPEC |
| DOC-05 | MED | `PRODUCT_VISION` duplicates principle 5 | Duplicate deleted; the list is five promises, numbered five | VISION | PROD-R §2 | SPEC |
| DOC-06 | MED | Screen inventory miscounts itself | Count corrected to **54 screens + 7 unnumbered states** | S header | PROD-R §3 | SPEC |
| DOC-07 | MED | Roadmap diagram contradicts phase text | P3 drawn as a parallel branch off P2 with an explicit merge gate | RM §Phase detail | RM-R §2 | SPEC |
| DOC-08 | MED | "Workspace admin" is both in and out of MVP | Term split: *workspace settings* (P4/P5) vs *administration surface* (P9) | RM | RM-R §3 | SPEC |
| DOC-09 | MED | MFA mandatory, absent from onboarding | MFA enforced at first sensitive action, not at creation; onboarding step 7 added; 15-minute target unchanged | SEC AU-4, J1, S §22 | SEC-R §2.3, PROD-R §4 | DEC |
| DOC-10 | MED | Double marking deferred and available | `double_check` is **not built**; Q14 default becomes "not built"; feature inventory rules | FEATURES §1, OQ Q14 | PROD-R §5 | SPEC |
| DOC-11 | MED | Monitoring targets differ from vision targets | One SLO set; alert thresholds derived from it | MON §1, VISION | COST-R §6, MON-R §1 | SPEC |
| DOC-12 | MED | Edge limits assume an unselected plan | Tier named, costed and marked as a purchase decision; per-user limits moved in-Worker | CF §7, DEPLOY | COST-R §4, OWNER C8 | DEC |
| DOC-13 | LOW | `usage_daily` period ambiguous | Events → hourly job → day-grain `usage_daily` → monthly view, stated once | DB §5, BP §8, COST §7 | DB-R §5.5 | SPEC |
| DOC-14 | LOW | Unsourced D1 REST rate-limit figure | Figure dropped; the dynamic-binding argument stands without it | MT §1 | MT-R §1 | SPEC |
| DOC-15 | LOW | Two names for the project | Naming stated once: product **MathChecker**, package **UI_V5.5**, directory `UI_Webpage_V5.5` | README | PROD-R §6 | SPEC |
| DOC-16 | LOW | D6 "this is what V5 looks like" unsourced | Claim withdrawn; D6 retained on its own merits | DESIGN_DIRECTIONS | PROD-R §7 | SPEC |

### 2.6 UX and product (`UX`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| UX-01 | HIGH | Interrupted review loses work; the fix contradicts itself | Server-side draft row per (result, actor) with debounced autosave and `base_version`; local storage as cache only; conflict replayed as a diff | J5, RESPONSIVE §4, S §34 | PROD-R §4.1, `T-UX-01` | DEC |
| UX-02 | HIGH | Simultaneous approval left undecided in a blocking suite | Same actor → idempotent `202`; different actor → `409` naming the approver; screen state defined | ISO C2 | API-R §5.4, `T-API-03` | SPEC |
| UX-03 | MED | The supervisor's core job has no screen | Sampled review in the MVP: `sample_reviews` table, `correction.sample` permission, endpoints, coverage counter, sign-off | VISION, S | PROD-R §4.3, `T-UX-02` | DEC |
| UX-04 | MED | Two supervisors editing a blueprint have no concurrency control | `mark_schemes.version` + `If-Match` on scheme mutations | DB §3, J3 | DB-R §3.3, `T-DB-11` | SPEC |
| UX-05 | MED | Workspace switching mid-task undefined | Switch rules: drafts flushed or blocked, route preserved when permitted, progress views refetch | IA, S §20 | PROD-R §4.6 | SPEC |
| UX-06 | MED | Removing a member orphans work | Blocked removal with reassignment offer; `assignee_id` nulled, not deleted; inbox item | ROLES §6 | PROD-R §4.7, `T-UX-03` | SPEC |
| UX-07 | MED | No erasure path that respects published marks | Anonymise the student, retain numerics, annotate reports, never rewrite a published grade without an operator action | DP §5, J8 | PROD-R §4.8, `T-UX-04` | DEC |
| UX-08 | MED | Trial path assumes a credential onboarding never asks for | Checklist step after the first mark; quota in the top bar during trial | J1, S §22/§46, OQ Q3 | PROD-R §4.9 | SPEC |
| UX-09 | MED | Mobile "approve" contradicts the canvas rules | Approve restricted to `md+`; phone approval is read-only | RESPONSIVE §1/§3 | PROD-R §4.10 | SPEC |
| UX-10 | MED | Three accessibility specifics unresolved | Canvas focus model, 12 px micro-label floor with measured contrast, single summarised live region | A11Y §2/§3 | PROD-R §4.11 | SPEC |
| UX-11 | LOW | `⌘`-first shortcuts on Windows | Alt-first bindings (`Ctrl`/`⌘` pairs, `Alt` for canvas) and a Windows keyboard walkthrough | SHORTCUTS | PROD-R §4.12 | SPEC |
| UX-12 | MED | Scope that will not pay for itself in an MVP | Cuts: analytics hub beyond two charts, saved views, status page, changelog, teams, presence; viewer retained with aggregate scope | S, FEATURES | PROD-R §5 | DEC |

### 2.7 Reliability (`REL`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| REL-01 | **CRIT** | Job loss is silent and undetected | Duplicate of `ARC-01`; counted once there | BP §2, MON §1 | `T-JOB-01` | SPEC |
| REL-02 | HIGH | Monitoring cannot see a stuck job | Two paging signals (unpublished outbox age, expired-lease age) plus oldest-non-terminal-job gauge | MON §1 | MON-R §1, `T-OPS-01` | SPEC |
| REL-03 | HIGH | The file backup plan is not implementable | Explicit replication pipeline on native primitives: event notification → Queue → server-side `CopyObject` + reconciliation + bucket lock; native vs built distinguished | BKP §2/§3 | BKP-R §2–§5, `T-BKP-01…04` | DEC |
| REL-04 | HIGH | Recovery designed but never proven; no clone environment | Restore tooling specified as a P2 deliverable; monthly slice drill, quarterly full rebuild; measured RTO replaces promised RTO | BKP §6 | BKP-R §6–§7, `T-BKP-05…08` | SPEC |
| REL-05 | MED | Outage longer than the park budget has no recovery path | Recovery sweep on circuit close, bounded per workspace | BP §3, J6 | BP-R §3.3, `T-JOB-06` | SPEC |
| REL-06 | MED | D1 outage story assumes an unused replica | Hard-failure behaviour documented; static maintenance page served without D1; replica implication removed | CF §6 | MT-R §4.3, `T-OPS-02` | SPEC |
| REL-07 | MED | Redelivery can exhaust the attempt budget | Attempts increment only inside the guarded claim `UPDATE`, verified by affected-row count | BP §4 | BP-R §2.2, `T-JOB-04` | SPEC |
| REL-08 | MED | Cancellation discards a paid result silently | Cancel copy states the in-flight call may complete; spend is metered; "keep result, don't publish" option | BP §6 | BP-R §6, `T-JOB-07` | SPEC |
| REL-09 | MED | Migration rollback forward-only, unrehearsed | Every migration runs against the latest export in staging with timing capture; abort above 50 % of the query budget | DEPLOY §3 | BKP-R §4.3, `T-OPS-03` | SPEC |
| REL-10 | MED | DLQ is a table nobody watches | Real DLQ queue, depth alert, daily failed-by-class digest | CF §5 | BP-R §7, `T-JOB-05` | SPEC |
| REL-11 | MED | Log retention shorter than the investigations it serves | Incident-time log export to R2 is a documented step; 30-day limit disclosed in the privacy page | MON §3, DP §8 | MON-R §3 | SPEC |
| REL-12 | LOW | Cron sweeps unmonitored | `ops_cron_runs` heartbeat; alert at 2× period | CF §? | MON-R §2, `T-OPS-04` | SPEC |

### 2.8 Cost and scalability (`COST`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| COST-01 | HIGH | Cost model omits the component the architecture needs | PDF line costed inside `ADR-017`; cannot be approved without a measured per-report figure | COST §4, SA §7 | ADR-R §3.2 | DEC |
| COST-02 | MED | Storage under-counted ~4× | Arithmetic redone row by row: **4.4–6.1 KB/submission**; wall at 100 workspaces ≈ 3–4 years with stated retention | COST §3 | COST-R §2 | SPEC |
| COST-03 | MED | DO line derived from nothing | Line deleted with the component (§`ARC-03`) | COST §4 | COST-R §4 | SPEC |
| COST-04 | MED | Rate-limit/WAF tier unbudgeted | Per-user limits moved in-Worker; tier becomes a deliberate purchase decision, not an architectural assumption | CF §7, SEC AB-1 | COST-R §4, OWNER C8 | DEC |
| COST-05 | MED | Workflow steps closer to allowance than shown | Step budget in the scale table; alarm at 60 % of included steps | COST §4 | COST-R §5 | SPEC |
| COST-06 | MED | AI dominance left implicit | Stated plainly: at any C ≥ $0.01 AI exceeds infrastructure by an order of magnitude; trial spend is the operator's | COST §5 | COST-R §3 | SPEC |
| COST-07 | LOW | Queue op accounting invisible | Recorded in the revised cost model so it need not be re-derived | COST §4 | COST-R §6 | INFO |
| COST-08 | LOW | Email is the only vendor with no candidate | Decision deferred to P2 with a price envelope and an explicit "not selected" status; the notification-orchestration category was evaluated and rejected | COST §4 | COST-R §7, OWNER C16 | DEF |

### 2.9 Roadmap (`ROAD`)

| ID | Sev | Finding | Resolution | Docs | Verify | Status |
|---|---|---|---|---|---|---|
| ROAD-01 | HIGH | Support access ships after the first customer | Grant mechanism (not the whole admin surface) moved into **P5**, before the first external workspace | RM P9, SEC SA-1…6 | RM-R §4 | DEC |
| ROAD-02 | MED | P3 parallelism contradicted by the dependency graph | Dependency graph redrawn with a parallel branch and a merge gate | RM | RM-R §2 | SPEC |
| ROAD-03 | MED | Bulk import precedes upload but duplicates its logic | Duplicate detection extracted as a shared domain service in P4, reused by P5 | RM P4/P5 | RM-R §5 | SPEC |

---

## 3. Dependency order

Fixing findings in ID order would fail. The actual dependency graph is:

```
DB-01 (identity)  ─┬─▶ DB-02 (api keys reference user)
                    ├─▶ SEC-07 (roles live in member.role)
                    ├─▶ SEC-08, SEC-02/03 (session fields, lockout columns)
                    └─▶ DB-03/SEC-05 (triggers reference every child table)

ARC-01 (outbox) ──▶ ARC-02 (reaper re-reads outbox state) ──▶ REL-02 (signals) ──▶ REL-10 (DLQ alerts)
ARC-01 ──▶ DB-07 (metering keys off job attempt)

SEC-04 (resource-aware policy) ─┬─▶ SEC-01 (support scope is a policy scope)
                                ├─▶ API-02/SEC-09 (export authorization)
                                └─▶ UX-03 (sampling needs `correction.sample` semantics)

REL-03 (R2 pipeline) ──▶ REL-04 (drills restore from it) ──▶ COST-01? (no; independent)
DB-04 (partial uniques) ──▶ UX-06 (re-invite after removal), UX-07 (student re-add after anonymise)
API-01 (results) ──▶ API-09? (no), UX-03 (sampling reads results)
```

Consequences for sequencing: **identity first, then constraints, then the job pipeline, then the permission
model, then product surface.** The audit's Gate 1 bundles these; §6 re-cuts the gates by dependency rather than
by severity.

---

## 4. The 40 recommendations, re-dispositioned

| R | Recommendation | Disposition |
|---|---|---|
| 1 | Outbox | Adopted — `DB-R §4.9`, `BP-R §2.3` |
| 2 | Lease reaper | Adopted — `BP-R §2.4` |
| 3 | Identity reconciliation | Adopted with a different shape than proposed (see §5.1) — `DB-R §2` |
| 4 | Support-grant context | Adopted — `SEC-R §6` |
| 5 | Tenant triggers | Adopted — `DB-R §6.1` |
| 6 | Mark `CHECK` + override trigger | Adopted, extended to totals — `DB-R §5.3` |
| 7 | Correct false platform claims | Adopted — §7 |
| 8 | Replace the R2 backup story | Adopted as a pipeline, not as a disclaimer — `BKP-R` |
| 9 | Pin Better Auth ≥ 1.7.16 + auth-config ADR | Adopted — `ADR-016` new |
| 10 | MFA for every method | Adopted as an assurance gate (library hooks are insufficient) — `SEC-R §2.3` |
| 11 | Resource-aware policy | Adopted — `SEC-R §4` |
| 12 | `api_keys` table | Adopted — `DB-R §4.7` |
| 13 | Partial unique indexes | Adopted — `DB-R §5.2` |
| 14 | Roles declared in Better Auth | Adopted, five roles not six — `SEC-R §4.1` |
| 15 | Decide C2 | Adopted with `202` not `200` — `API-R §5.4` |
| 16 | Support access into P5 | Adopted — `RM-R §4` |
| 17 | Restore script in P2 + first drill | Adopted — `BKP-R §6` |
| 18 | Real DLQ | Adopted — `BP-R §7` |
| 19 | Attempts on successful claim | Adopted — `BP-R §2.2` |
| 20 | Provider recovery sweep | Adopted — `BP-R §3.3` |
| 21 | Decide upload path | Adopted as hybrid — `ADR-R §1.6` |
| 22 | Usage uniqueness + rollup | Adopted, extended with `source_key` — `DB-R §5.5` |
| 23 | `mark_schemes.version` | Adopted — `DB-R §3.3` |
| 24 | Review-draft story | Adopted server-side — `PROD-R §4.1` (owner C9) |
| 25 | Missing endpoints | Adopted, seven not six (API keys added) — `API-R §5–§9` |
| 26 | p95 in P5 exit criteria | Adopted — `ACC-R §6` |
| 27 | PDF host decision | Adopted as `ADR-017`, still open — `OWNER C7` |
| 28 | Correct storage arithmetic + missing cost lines | Adopted — `COST-R §2` |
| 29 | Name the plan tier | Adopted as a purchase decision — `OWNER C8` |
| 30 | Student erasure with published marks | Adopted — `PROD-R §4.8` (owner C11) |
| 31 | Seven missing journeys | Adopted — `PROD-R §4.13` |
| 32 | Six missing permission keys | Adopted, seven added — `SEC-R §4.2` |
| 33 | Audit triggers + cron heartbeat | Adopted — `DB-R §6.2`, `MON-R §2` |
| 34 | Two paging signals | Adopted — `MON-R §1` |
| 35 | Defer the Durable Object | Adopted — `DO-DEFER` |
| 36 | Cut or restrict `viewer` | **Modified**: kept, restricted to aggregates in the shaper — `SEC-R §4.4` |
| 37 | Defer analytics hub, saved views, status page, changelog | Adopted — `PROD-R §5` |
| 38 | Defer the V5 importer | Adopted — `ADR-R §1.15` |
| 39 | Defer `double_check` consistently | Adopted — `PROD-R §5` |
| 40 | Remove KV | Adopted — `ADR-R §4` |

Two recommendations were **not** adopted as written: #3's shape (§5.1) and #36 (viewer removal). Both changes are
recorded with reasoning rather than applied silently.

---

## 5. Independent validation of consequential claims

| # | Audit claim / recommendation | How it was validated | Outcome |
|---|---|---|---|
| 1 | Better Auth requires `account`/`verification`/`passkey`/`twoFactor` and stores the password on `account` | Read the schema sources for the current 1.7 line | **Confirmed**, and sharpened: columns are **camelCase** (`emailVerified`, `createdAt`), configurable via `fields`; `twoFactor.failedVerificationCount`/`lockedUntil` already exist — which the audit missed and which removes the need for a custom lockout table |
| 2 | Cookie cache has no per-session bust | Session-management docs | **Confirmed**; revocation deletes the row, so DB-backed checks are authoritative and only the cache is stale |
| 3 | R2 has no versioning or replication | S3 compatibility matrix + durability page | **Confirmed**; *also* found the primitives the audit did not name: server-side `CopyObject`/`UploadPartCopy` (Class A, no egress), bucket locks, `CRC64NVME` `FULL_OBJECT` |
| 4 | R2 event notifications can drive a copy pipeline | Event-notifications docs | **Confirmed**, with caveats the design must honour: two event types, `size`/`eTag` absent on delete, no documented ordering, one event per object per bucket |
| 5 | TanStack prerender/SPA are supported behind the plugin | Prior phase's verification | **Confirmed**; ADR-001 rationale rewritten |
| 6 | `db.batch()` counts as one query; no interactive transactions | D1 docs | **Confirmed**; batch must also fit the 30 s query budget |
| 7 | Queues deletes a message after `max_retries` (default 3) without a DLQ | Queues docs | **Confirmed** |
| 8 | 402 should become 429 | RFC 9457/HTTP semantics | **Confirmed** — and 429 must not carry a `Retry-After` for quota, because waiting does not restore quota |
| 9 | Redelivery increments attempts before the claim fails | Reading `BP §4` against D1 `meta.changes` semantics | **Mechanism corrected**: it only does so if attempts are incremented outside the guarded `UPDATE`. The risk is real; the spec now pins the single-statement form so it cannot be introduced |
| 10 | D1-backed Better Auth rate limiting solves brute force | Rate-limit docs + lockout requirement | **Refined**: it gives per-key windows, not per-account exponential backoff; both are specified |
| 11 | Presigning "requires credentials we won't hold" | R2 docs (presign lifetime 1 s–7 days) | **Confirmed false**; ADR-006 rewritten, and the remedy refined to hybrid because presigning every upload is *worse* for validation (§`ADR-R §1.6`) |

**Nothing in the audit was reversed.** One severity was raised in effect: `DB-01` is treated as blocking P2
entirely, because Better Auth's runtime schema validation fails closed — a mismatched schema does not degrade,
it rejects every request.

---

## 6. Re-cut gates (dependency-ordered, replaces the audit's severity gates)

| Gate | Contents | Blocks | Why this order |
|---|---|---|---|
| **G-A — Identity** | DB-01, SEC-07, DB-02, SEC-08, SEC-02/03 | P2 | Every other table and every session field hangs off it |
| **G-B — Constraints** | DB-03/SEC-05, DB-04, DB-05, DB-06, DB-08, DB-10, DB-11 | P2 exit | Cheap, structural, and impossible to add later without a backfill |
| **G-C — Durability** | ARC-01, ARC-02, ARC-06, REL-07, REL-10, REL-05, REL-12 | P5 | The product promise depends on it |
| **G-D — Authorization** | SEC-04, SEC-01, SEC-09/API-02, API-01, SEC-06 | P5/P7 | Needs the role model from G-A |
| **G-E — Recovery** | REL-03, REL-04, REL-09, DB-13 | Launch | Needs G-C's queue plumbing |
| **G-F — Decisions** | C1–C16 in `OWNER_APPROVAL_DECISIONS.md` | Approval | Owner input, not engineering |

---

## 7. Incorrect factual claims, corrected

| # | Claim (source) | Reality (verified) | Where corrected |
|---|---|---|---|
| 1 | SPA mode and prerendering are unsupported behind the Cloudflare plugin (ADR-001) | Both supported; prerender shipped 2025-12-19 | `ADR-R §1.1` |
| 2 | R2 presigning needs long-lived credentials (ADR-006, CF §4) | Presigned URLs exist, 1 s–7 days | `ADR-R §1.6` |
| 3 | R2 objects are versioned by key prefix and recoverable from a replication bucket (BKP §2 B4, §3) | Neither versioning nor replication exists | `BKP-R §1` |
| 4 | Cloudflare documents OpenNext as "maintenance mode" (ADR-001) | "use this guide to **maintain** an existing application" — softer | `ADR-R §1.1` |
| 5 | Server caches membership ≤ 60 s and busts it on role change (ROLES §5.5) | No per-session bust; staleness = `cookieCache.maxAge`, which was never set | `SEC-R §2.4` |
| 6 | Cross-tenant FKs are impossible by construction (MT §3.5) | A code convention; SQLite triggers can enforce it | `DB-R §6.1` |
| 7 | D1 REST API rate limit "1,200 requests / 5 min" (MT §1) — unsourced | Unverified; argument does not need it | `MT-R §1` |
| 8 | Screen inventory "48 screens" (S header) | 54 + 7 states | `PROD-R §3` |
| 9 | `PRODUCT_VISION` principle 5 listed twice (VISION) | Duplicated verbatim | `PROD-R §2` |
| 10 | `double_check` is deferred (FEATURES) and available (Q14) | Contradiction | `PROD-R §5` |

Items 1–4 are platform facts and are the reason the package's decision record needed rewriting: a record that is
wrong about a checkable fact cannot be trusted about an uncheckable one.

---

## 8. Missing architectural requirements (not captured as findings)

The audit found gaps; remediation found **requirements with no home at all**. All are specified in
`REVISED_DATABASE_SPECIFICATION.md` unless noted.

| # | Missing requirement | Why it is needed | Consequence if omitted |
|---|---|---|---|
| M1 | `rate_limit` table + `user.failed_login_count`/`locked_until` | AU-8 has no storage | Lockout silently unenforced (SEC-03) |
| M2 | `job_outbox` | ARC-01 | Silent job loss |
| M3 | `backup_objects` manifest + `ops_backup_log` | REL-03/04 | Backup has no verification record |
| M4 | `ops_cron_runs` | REL-12 | Dead cron invisible |
| M5 | `review_drafts` | UX-01 | Lost overrides |
| M6 | `sample_reviews` + coverage | UX-03 | Buyer's core job has no surface |
| M7 | `exports` | API-02 | Export built ad hoc |
| M8 | `notification_preferences` | API-03/DB-09 | Preferences screen cannot persist |
| M9 | Quota + settings columns | DB-09 | Usage screen reads nothing |
| M10 | `platform_operators` | ROLES: `platform_operator` has no table | Operator identity has no record, so grants have no grantor |
| M11 | `legal_holds` | J8 mentions legal hold; nothing stores it | Purge cannot be blocked |
| M12 | `idempotency_records` | API requires `Idempotency-Key` on uploads/publications with no store | Duplicate publishes |
| M13 | `students.anonymised_at` | UX-07 | Erasure destroys aggregates or leaks PII |
| M14 | `question_results.assignment_question_id` | DB-08 | Marks can reference non-existent questions |
| M15 | `maintenance_windows` | DB-11 | Either no immutability or no purge |
| M16 | `session.mfa_verified_at` + `amr` (additionalFields) | SEC-02 | MFA unenforceable across methods |
| M17 | `usage_events.source_key` | DB-07 | Non-job usage (exports, reports) cannot be idempotent |

---

## 9. Rollup

| Status | Count | Meaning |
|---|---|---|
| `SPEC` | 68 | Closed by specification; no owner input required |
| `DEC` | 23 | Closed by specification **and** an owner decision (C-list) |
| `DEF` | 1 | `COST-08` — email vendor selected at P2 |
| `INFO` | 1 | `COST-07` |
| **Open with no resolution** | **0** | — |

Counting the `REL-01` restatement of `ARC-01` as its own row gives 94 rows for 93 findings (68 + 23 + 1 + 1 =
93 distinct).

Of the 27 CRITICAL+HIGH findings: **13 are closed outright** and **14 are closed subject to an owner decision** —
every CRITICAL/HIGH row marked `DEC` in §2. None is left without a written resolution.

The next document, `CRITICAL_AND_HIGH_REMEDIATION.md`, gives each of the 27 the full treatment: problem,
resolution, evidence, residual risk, and the test that proves it.
