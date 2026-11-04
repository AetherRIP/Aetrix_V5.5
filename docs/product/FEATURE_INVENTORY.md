# Feature Inventory — ground truth

**Status:** VERIFIED for V5 behaviour (read from the V5 repository); RECOMMENDED for classifications.
Evidence base: `README.md`, `docs/ARCHITECTURE.md`, `backend/app/schema.sql`, `backend/app/` module tree,
`frontend/src/`, `docs/ui-identity-v6.md`.

Classifications: **A = preserve as-is** · **B = keep behaviour, rebuild the surface** · **C = new in V5.5**
· **D = explicitly deferred** · **? = cannot verify**.

## 1. Marking and integrity (the core — protect it)

| Feature | V5 evidence | Class | Notes |
|---|---|---|---|
| Preserved marking core | `backend/app/engine/legacy_marking.py` | A | Port behind an adapter; do not rewrite prompts |
| Determinism | `temperature: 0` + fixed seed per call | A | Must survive the move to a job runner |
| Mark-scheme blueprint | `engine/blueprint.py` — question list + max marks fixed once per scheme | A | Becomes a persisted per-assignment artefact |
| Sub-question model | `engine/scheme_structure.py` — identities, accepted answers, M/A/B points | A | |
| Post-marking reconciliation | `engine/verify.py`, `question_inventory.py`, `mark_integrity.py` | A | Reports only; never rewrites a mark |
| Overwrite guard | `engine/result_guard.py` | A | A valid mark cannot be silently replaced |
| Missing question handling | `REVIEW` status, never a silent `0` | A | The single most important invariant |
| Review reasons | `engine/review_reasons.py` | B | Surface them as filters and badges |
| Re-mark / partial re-mark | `engine/remark.py`, `recover_missing.py` | B | Needs quota metering |
| Double-check pass | `engine/double_check.py` | D | Off by default; cost |
| Mark-scheme audit + decisions | `engine/scheme_audit.py`, `scheme_decisions.py`, `scheme_exclusions.py` | B | Becomes the scheme review screen |
| PDF inspection | `engine/pdf_inspect.py` — page counts, per-page question evidence | A | Deterministic, read-only |
| Large-PDF routing | `engine/pdf_optimize.py`, `batching.py` | A | |
| Model health + pinning | `engine/model_health_store.py` | B | Moves to D1 per provider/workspace |
| Benchmarking | `backend/app/benchmark/` | B | Keep; make workspace-scoped |

## 2. Jobs, providers, reliability

| Feature | V5 evidence | Class | Notes |
|---|---|---|---|
| Persistent job manager | `jobs/manager.py` — staged progress, duplicate prevention, cancel, retry, crash recovery | B | Rebuilt on Queues + Workflows; semantics preserved |
| Idempotency | Existing successful result re-attached instead of re-running | A | Becomes an explicit `idempotency_key` |
| Classified retry policy | `retry_policy.py` — park / one retry / never resend | A | Port table verbatim |
| Provider circuit breaker | `gemini/provider_health.py` | B | Per-workspace, per-provider |
| Multi-key rotation | `gemini/key_manager.py` — fingerprints, cooldowns, benching | B | Becomes credential rotation in D1 |
| Key-scoped file re-upload | Files are key-scoped; retry re-uploads under the new key | A | Provider-specific behaviour to preserve |
| Prepared input cache | `data/tmp/job-<id>/prepared.json` | B | R2-backed instead of local disk |
| SSE progress | Frontend `useAdaptivePoll`, event-driven updates | B | Realtime hub + polling fallback |
| Multi-account support | `multi_account.py` | B | One provider credential per workspace |

## 3. Google Classroom

| Feature | V5 evidence | Class | Notes |
|---|---|---|---|
| OAuth + token storage | `classroom/`, secrets in `data/secrets/` | B | Per-workspace encrypted credential |
| Course/coursework sync + cache | DB-cached with TTL, allow-list | B | Incremental sync |
| Submission retrieval | Drive download into prepared input | B | |
| Report attachment | `report_deliveries`, `report_upload_records`, `report_upload_locks` | B | Preserve the lock/idempotency semantics |
| Draft grade write + 403 fallback | `automation_operations` per `(job_id, op_key)` | A | Three ops: report, grade, return |
| Grading handoff state | `NEEDS_VERIFICATION` + read-only reconcile | A | Never guess after a timeout |
| Lesson identity | `CH1L1` parsing in `reporting/class_report.parse_assignment` | A | Chapter is never dropped |
| Classroom as system of record | Marks published to Classroom | A | Contract for the product |

## 4. Reporting and analytics

| Feature | V5 evidence | Class | Notes |
|---|---|---|---|
| Class report (PDF) | `reporting/`, ReportLab + PyMuPDF | A | Server-side generation, stored in R2 |
| Grade matrix | Grouping by full lesson code, keyed by `coursework_id` | A | |
| Student profile | `api/student_routes.py` + Students page | B | Becomes workspace-scoped records |
| Submission history | Local correction history per student | B | |
| Statistics | `api_stats.py`, `analytics_routes.py` | C | Expand: distributions, trends, workload |
| Exports | CSV/PDF present in places | C | Formal export pipeline + permissions |

## 5. Platform capabilities

| Feature | V5 evidence | Class | Notes |
|---|---|---|---|
| Workspaces / tenancy | **Absent** (`teams`/`team_members` tables exist but are not tenancy) | C | Central to V5.5 |
| Shared identity, login, sessions | Local auth gate + device tokens (`auth_gate.py`, `devices`, `device_credentials`) | C | Replaced by Better Auth |
| Roles and permissions | Not present | C | See `USER_ROLES_AND_PERMISSIONS.md` |
| Invitations | Not present | C | |
| Audit log | `audit_log` table exists | C | Expand to workspace + platform scope |
| API keys / provider credentials UI | API Keys page + `accounts`/`account_scope` | B | Per-workspace, encrypted, never returned |
| Usage accounting | Usage counters on the Usage page | C | Becomes metering + quotas |
| File storage | Local disk under `DATA_DIR` | B | R2 |
| Notifications | In-app attention items only | C | Email + in-app + preferences |
| Collaboration | None | C | Ownership, comments, review requests |
| Real-time presence | None | D | Deferred; job progress only in MVP |
| Public marketing site | None | C | |
| Help centre, status, release notes | Docs exist in repo, not in product | C | |
| Platform administration | None | C | Separate surface, audited support access |
| Billing / subscriptions | None | D | Metering now, billing later |
| SSO / SCIM | None | D | WorkOS bolt-on when a customer requires it |

## 6. Desktop client

The WPF client (`desktop/`) drives the same HTTP API and starts the Python backend itself. In V5.5 it
**cannot be supported as-is** (it shells out to a local backend that no longer exists). Options are in
[`../decisions/OPEN_QUESTIONS.md`](../decisions/OPEN_QUESTIONS.md) Q7: (a) retire it, (b) keep it as a thin
shell over the hosted API, (c) reimplement the review workflow in the web app only. Recommendation: **(c)
for MVP**, (b) only if offline marking is a real requirement.

## 7. Explicitly not verifiable from source

- Whether the current marking prompt is licensed or cleared for redistribution beyond this product.
- Real Classroom API quota behaviour at department scale (tests mock it).
- Actual AI cost per script — the V5 benchmark folder exists but its results are not a pricing input here.
- Legal basis for processing student names (school DPA vs individual consent) — see `security/DATA_PRIVACY.md`.
