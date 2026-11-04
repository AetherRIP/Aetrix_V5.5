# Updated Traceability Matrix

**Status:** RECOMMENDED — supersedes `audit/REQUIREMENT_TRACEABILITY.md` as the live view. The audit document
remains as the historical record of what was broken.

**Status key:** **T** traced end to end (statement → design → architecture → phase → proof) · **D** traced and
dependent on an owner decision · **F** deferred by decision (not a gap).

Score after remediation: **46 of 46 traced** — 43 fully, 3 dependent on a decision, 0 gaps, 0 contradictions.

---

## 1. Requirements

### 1.1 Product and integrity

| ID | Requirement | Design / screen | Architecture | Phase | Proof | Status |
|---|---|---|---|---|---|---|
| R01 | Missing question → `needs_review`, never `0` | S34 canvas | `question_results.awarded NULL` + `CHECK`; workflow step 6 | P1 | `T-DB-06`, ACC §2 | **T** |
| R02 | Marking deterministic (temp 0, fixed seed) | — | Workflow step 4 | P1 | ACC §2 "repeat run identical" | **T** |
| R03 | A mark can never exceed the question maximum | S34 | `CHECK` + override trigger + API `422` | P1/P5 | `T-DB-06` | **T** |
| R04 | Verification reports, never rewrites | S34 | `verify` step, read-only | P1 | `T-API-06` | **T** |
| R05 | Override requires reason + actor + time | S34 | `overrides` + `CHECK(length(reason) >= 10)` | P5 | ACC §6 | **T** |
| R06 | Approval is a separate permission | S34 | `correction.approve` + `approvals` unique | P5 | ACC §6, `T-API-03` | **T** |
| R07 | The browser never marks; no key reaches the client | — | Server-side jobs; shaper omits credentials | P5 | `T-AUTH-20` | **T** |
| R08 | Interrupted remote write → `NEEDS_VERIFICATION` | S27, S37 | `automation_operations.state` | P6 | ACC §7 | **T** |
| R09 | `CH1L1` identity preserved | S30, S37 | `assignments.lesson_code` | P4 | ACC §5 | **T** |
| R10 | Blueprint must be locked before marking | S30 | `mark_schemes.locked_at`; `409 scheme_unlocked` | P4 | ACC §5 | **T** |

### 1.2 Tenancy and access

| ID | Requirement | Design | Architecture | Phase | Proof | Status |
|---|---|---|---|---|---|---|
| R11 | One workspace cannot read another's data | — | 4 layers + triggers | P2 | `T-ISO-01…12` | **T** |
| R12 | Cross-tenant ids return 404, not 403 | permission-denied page | Route + repository + shaper | P2 | `T-ISO-03` | **T** |
| R13 | Cross-tenant child rows are impossible | — | 23 triggers + schema-enumeration test | P2 | `T-DB-01/02` | **T** |
| R14 | Roles are a closed bundle, enforced server-side | all gated screens | `can(ctx, key, resource?)`, generated matrix | P2 | `T-PERM-01…05` | **T** |
| R15 | Invitations single-use, 7-day, email-bound | S19 | `invitation` + partial unique | P2 | `T-AUTH-13` | **T** |
| R16 | MFA required for owner and operator | S18 | Assurance gate above the library | P2 | `T-AUTH-04…07` | **D** (`C3`) |
| R17 | Session revocation effective on next request | S23 | Row deleted; cache 60 s; DB check on sensitive routes | P2 | `T-AUTH-08` | **T** |
| R18 | Role change effective immediately | — | Membership re-read + cache invalidation | P2 | `T-AUTH-08` | **T** |
| R19 | Provider keys never returned or logged | S46 | Envelope encryption + shaper | P5 | `T-AUTH-20` | **T** |
| R20 | Scoped API keys cannot manage members/credentials/delete | — | `api_keys` + allow-list ∩ scope + deny-list | P5 | `T-PERM-07` | **T** |
| R21 | Support access consented, scoped, audited, expiring | S53 | `SupportContext` + grant re-read per request | **P5** | `T-AUTH-09/10` | **D** (`C14`) |

### 1.3 Files, jobs, integration

| ID | Requirement | Design | Architecture | Phase | Proof | Status |
|---|---|---|---|---|---|---|
| R22 | Uploads validated (type, size, magic bytes, page cap) | S32 | Upload route + validation step + quarantine | P5 | `T-FILE-06` | **T** |
| R23 | Every job reaches a terminal state | S33, job drawer | Outbox + reaper + DLQ | P5 | `T-JOB-01…05` | **T** |
| R24 | Duplicate submissions create one job and one call | — | `idempotency_key` + unique index | P5 | `T-JOB-02` | **T** |
| R25 | Rate limit parks without consuming attempts | job drawer | Retry classification | P5 | ACC §6 | **T** |
| R26 | 401/invalid → never resend | job drawer | Retry classification | P5 | ACC §6 | **T** |
| R27 | Cancel leaves no partial result | S33 | Cancel flag + discard | P5 | `T-JOB-07` | **T** |
| R28 | Progress visible without a socket | S33 | Polling ladder + ETag | P5 | `T-UX-05` | **T** |
| R29 | Classroom optional at every step | S48 | Integration layer | P6 | ACC §7 | **T** |
| R30 | Grade publish 403 has an actionable fallback | S27 | `automation_operations` state | P6 | ACC §7 | **T** |

### 1.4 Reporting, data, operations

| ID | Requirement | Design | Architecture | Phase | Proof | Status |
|---|---|---|---|---|---|---|
| R31 | Class report PDF, reproducible, printable | S37 | Host decided in `ADR-017` | P7 | `T-OPS-05` | **D** (`C7`) |
| R32 | Grade matrix on screen and as CSV | S36 | `GET /assignments/{id}/results` + export | P7 | `T-API-01` | **T** |
| R33 | Workspace export, tenant-scoped | S49 | `exports` + Workflow | P7 | `T-ISO-09` | **T** |
| R34 | Deletion: grace, purge, tombstone | S49 | Purge Workflow + `workspace_tombstones` | P9 | `T-OPS-09` | **T** |
| R35 | Audit append-only, 12 months | S43 | UPDATE abort trigger; DELETE windowed | P9 | `T-DB-10` | **T** |
| R36 | Usage metered per job, quota enforced | S47 | `usage_events` uniqueness + quota-in-batch | P5 | `T-DB-08`, `T-JOB-11` | **T** |
| R37 | Backups restorable, drills run | — | `BKP-R` pipeline + `ops_backup_log` | P10 | `T-BKP-05…08` | **T** |
| R38 | In-app + email notifications, preferences | S25, S45 | `notifications` + `notification_preferences` | P8 | `T-API-05` | **T** |
| R39 | Observability: SLOs, alerts, runbooks | S52 | Outbox/lease/DLQ/cron signals | P9 | `T-OPS-01` | **T** |

### 1.5 Experience

| ID | Requirement | Design | Phase | Proof | Status |
|---|---|---|---|---|---|
| R40 | WCAG 2.2 AA | tokens, components | P3 | axe + manual | **T** |
| R41 | Full keyboard operation, visible focus | shortcut model + canvas focus model | P3 | `T-UX-06` | **T** |
| R42 | Desktop-first, graceful reduction | breakpoints | P3 | manual | **T** |
| R43 | Design system: tokens, states, no one-offs | D1 | P3 | ACC §4 | **T** |
| R44 | Review work never lost on interruption | S34 draft | P5 | `T-UX-01` | **T** |
| R45 | Supervisor can audit marking quality | sampled review view | P5 | `T-UX-02` | **T** |
| R46 | Workspace switching is safe | S20 | P2 | `T-UX-07` | **T** |

### 1.6 Deferred by decision (previously "gaps")

| Requirement | Disposition |
|---|---|
| V5 data importer | **F** — `ADR-015` deferred, `C15` open |
| `double_check` | **F** — not built; removed from Q14's default |
| Presence / live cursors | **F** — `ADR-008` deferred |
| Billing | **F** — metering only, as designed |

---

## 2. Endpoint → screen → permission

Generated from the route manifest at build time; this table is the reviewed snapshot. The CI check
(`T-PERM-08`) fails if a route lacks a screen or a permission, or a screen references a non-existent route.

| Endpoint | Screen | Permission | Tenant scope | Audit event |
|---|---|---|---|---|
| `POST /auth/signup` | 14 | – | – | `auth.signup` |
| `POST /auth/login` | 15 | – | – | `auth.login` / `auth.login_failed` |
| `POST /auth/mfa/verify` | 18 | session | – | `auth.mfa` |
| `GET /auth/sessions` | 23 | session | – | – |
| `DELETE /auth/sessions/{id}` | 23 | session | – | `auth.session_revoked` |
| `POST /auth/invitations/{token}/accept` | 19 | – | – | `member.joined` |
| `GET/PATCH /me` | 45 | session | – | – |
| `POST /me/export` | 23 | session | – | `subject.export` |
| `GET /w/{slug}/members` | 44 | `workspace.read` | workspace | – |
| `POST /w/{slug}/invitations` | 44 | `workspace.member.invite` | workspace | `member.invited` |
| `PATCH /w/{slug}/members/{id}` | 44 | `workspace.member.role` | workspace | `member.role_changed` |
| `DELETE /w/{slug}/members/{id}` | 44 | `workspace.member.remove` | workspace | `member.removed` |
| `POST/GET /w/{slug}/support-grants` | 45 / 53 | `support.grant` | workspace | `support.grant_created` |
| `GET /w/{slug}/support-grants/active` | banner | `workspace.read` | workspace | – |
| `GET/POST /w/{slug}/classes` | 38 | `academic.read` / `.write` | workspace | `class.created` |
| `GET/POST /w/{slug}/students` | 39 | `academic.read` / `.write` + PII level | workspace | `student.created` |
| `POST /w/{slug}/students/import` | 41 | `academic.write` | workspace | `student.imported` |
| `GET /w/{slug}/students/{id}` | 40 | `academic.read` + `student.pii.read` scope | workspace | – |
| `GET/POST /w/{slug}/assignments` | 26, 28 | `assignment.read` / `.create` | workspace | `assignment.created` |
| `GET /w/{slug}/assignments/{id}` | 27 | `assignment.read` | workspace | – |
| `POST /w/{slug}/assignments/{id}/allocate` | 27 | `assignment.allocate` | workspace | `assignment.allocated` |
| `POST /w/{slug}/assignments/{id}/scheme` | 29 | `scheme.write` | workspace | `scheme.uploaded` |
| `PATCH /…/scheme/questions/{no}` | 30 | `scheme.write` + `If-Match` | workspace | `scheme.edited` |
| `POST /…/scheme/lock` | 30 | `scheme.approve` + `If-Match` | workspace | `scheme.locked` |
| `GET /w/{slug}/assignments/{id}/submissions` | 31 | `submission.read` + assignee scope | workspace | – |
| `POST /w/{slug}/submissions/upload-url` | 32 | `submission.upload` | workspace | – |
| `POST /w/{slug}/submissions` | 32 | `submission.upload` | workspace | `submission.created` |
| `GET /w/{slug}/submissions/{id}` | 35 | `submission.read` + scope | workspace | – |
| `GET /w/{slug}/submissions/{id}/file` | 34/35 | `submission.read` + scope | workspace | `file.read` |
| `POST /w/{slug}/corrections` | 33 | `correction.start` | workspace | `job.created` |
| `POST /w/{slug}/corrections/bulk` | 31 | `correction.start` (≤100) | workspace | `jobs.created` |
| `GET /w/{slug}/jobs/{id}` | 33, drawer | `job.read` | workspace | – |
| `POST /w/{slug}/jobs/{id}/cancel` | 33 | `correction.cancel` | workspace | `job.cancelled` |
| `GET /w/{slug}/results/{id}` | 34/35 | `correction.result.read` + PII level | workspace | – |
| `PATCH /w/{slug}/results/{id}/questions/{no}` | 34 | `correction.override` + `If-Match` | workspace | `result.overridden` |
| `POST /w/{slug}/results/{id}/approve` | 34 | `correction.approve` + `If-Match` | workspace | `result.approved` |
| `PUT/GET/DELETE /w/{slug}/results/{id}/draft` | 34 | `correction.override` | workspace | – |
| `GET /w/{slug}/assignments/{id}/results` | 36 | `correction.result.read` + level | workspace | – |
| `GET /w/{slug}/assignments/{id}/results/summary` | 36 | `report.read` | workspace | – |
| `POST/GET /…/sample-review` | 27 | `correction.sample` | workspace | `sample.created` |
| `POST /…/sample-review/{itemId}/sign-off` | 27 | `correction.sample` | workspace | `sample.signed_off` |
| `POST /w/{slug}/assignments/{id}/publish` | 27 | `correction.approve` | workspace | `assignment.published` |
| `POST /…/report/attach` | 37 | `report.generate` | workspace | `report.attached` |
| `GET /…/operations` | 27, 37 | `correction.approve` | workspace | – |
| `POST /w/{slug}/automation/{opId}/reconcile` | 27 | `correction.approve` | workspace | `op.reconciled` |
| `POST/GET /w/{slug}/exports` | 49 | `workspace.export` | workspace | `export.requested` |
| `GET /w/{slug}/exports/{id}/download` | 49 | `workspace.export` | workspace | `export.downloaded` |
| `GET /w/{slug}/notifications` | 25 | `notification.read` | own rows | – |
| `GET/PATCH /w/{slug}/notification-preferences` | 45 | `notification.preferences` | own rows | – |
| `GET/POST/DELETE /w/{slug}/api-keys` | 45 | `apiKey.read` / `.write` | workspace | `api_key.created` |
| `GET/POST /w/{slug}/credentials` | 46 | `credential.read` / `.write` | workspace | `credential.added` |
| `POST /w/{slug}/credentials/{id}/rotate` | 46 | `credential.rotate` | workspace | `credential.rotated` |
| `GET /w/{slug}/usage` | 47 | `workspace.usage.read` | workspace | – |
| `GET /w/{slug}/activity` | 43 | `audit.read` | workspace | – |
| `GET /admin/workspaces` | 51 | platform | aggregate only | `platform.read` |
| `GET /admin/queues` | 52 | platform | – | – |
| `GET /admin/support-grants` | 53 | platform | – | – |
| `GET /health`, `/health/ready` | 52 | – | – | – |

**Deleted from the manifest:** `/w/{slug}/events/ticket` and the socket upgrade (deferred with `ADR-008`).

---

## 3. Requirement → test

| Requirement group | Tests |
|---|---|
| R01–R06 integrity | `T-DB-06/07/09`, `T-API-06`, ACC §2/§6 |
| R07–R10 secrets/identity | `T-AUTH-19/20`, `T-DB-09` |
| R11–R14 isolation/authorisation | `T-ISO-01…12`, `T-PERM-01…05`, `T-DB-01/02` |
| R15–R21 identity lifecycle | `T-AUTH-04…13`, `T-PERM-07` |
| R22–R27 files/jobs | `T-FILE-01…06`, `T-JOB-01…07` |
| R28–R30 progress/integration | `T-UX-05`, `T-JOB-13`, ACC §7 |
| R31–R39 reporting/data/ops | `T-API-01`, `T-ISO-09`, `T-DB-08/10`, `T-BKP-05…08`, `T-OPS-01…04` |
| R40–R46 experience | `T-UX-01…07` |

---

## 4. Roadmap ordering (ROAD-01…03 resolved)

| Finding | Resolution |
|---|---|
| ROAD-01 | Support-grant mechanism moves to P5; the platform directory stays in P9 |
| ROAD-02 | P3 is a parallel branch with an explicit merge gate (`PROD-R §5.1`) |
| ROAD-03 | Duplicate detection extracted as a shared domain service in P4, reused in P5 |

Phase ordering otherwise stands: parity before design, tenancy before features, Classroom at P6, metering at P5,
administration at P9. The audit found the ordering sound; remediation changed three edges, not the spine.

---

## 5. Coverage delta

| Group | Before | After |
|---|---|---|
| Product / integrity | 8 T, 1 W, 1 G | **10 T** |
| Tenancy / identity | 5 T, 3 W, 3 G | **9 T, 2 D** |
| Files / jobs / integration | 7 T, 1 W, 1 G | **9 T** |
| Reporting / data / ops | 0 T, 4 W, 5 G | **8 T, 1 D** |
| Experience | 4 T, 1 W, 2 G | **7 T** |
| **Total** | **24 T (52 %), 10 W, 12 G** | **43 T (93 %), 3 D, 0 G, 0 W** |

The three **D** items are decisions, not gaps: they are blocked on the owner, have a written specification, and
become **T** the moment `C3`, `C7` and `C14` are answered.

---

## 6. What the matrix still cannot prove

It proves that every requirement has a design, an architecture, a phase and a test. It cannot prove that the
tests pass — the code does not exist. It also cannot prove that a future endpoint will be scoped; that rests on the
route manifest, the typed repository and the schema-enumeration test, which fail the build rather than the
customer. Both limits are stated in `REMEDIATION_READINESS_REPORT.md` §6.
