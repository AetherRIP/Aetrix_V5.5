# Database Design

**Status:** RECOMMENDED. Target: Cloudflare D1 (SQLite). SQLite dialect: no RLS, no JSONB operators.

## 1. Conventions

- `TEXT` UUIDv7 primary keys (`id`); `TEXT` ISO-8601 UTC timestamps (`created_at`, `updated_at`).
- Booleans as `INTEGER 0/1`. Usage counters as `INTEGER`. Marks as `REAL` (mark schemes award halves).
- Soft delete via `deleted_at` on user-facing entities; hard delete only by the purge workflow.
- `workspace_id` on every tenant table, leading every index (see `MULTI_TENANCY.md` §3).
- Optimistic concurrency: `version INTEGER NOT NULL DEFAULT 1` on `assignments`, `submissions`, `results`.
- Enumerations are `TEXT` with a `CHECK` constraint, so a typo fails at write time.

## 2. ERD (core)

```
users ─┬─< sessions
       ├─< memberships >─ workspaces ─┬─< invitations
       │                              ├─< classes ─< students ─< enrollments
       │                              ├─< assignments ─┬─< assignment_questions
       │                              │                ├─< mark_schemes ─< scheme_decisions
       │                              │                └─< submissions ─┬─< results ─< question_results
       │                              │                                ├─< submission_files
       │                              │                                ├─< overrides
       │                              │                                └─< comments
       │                              ├─< jobs ─< job_attempts
       │                              ├─< automation_operations
       │                              ├─< provider_credentials / provider_health
       │                              ├─< usage_events
       │                              ├─< notifications
       │                              └─< audit_log
platform: platform_audit · support_grants · workspace_tombstones
```

## 3. Table catalogue — identity, tenancy, academic

Compact form: `table(columns…)`; `ws` = `workspace_id`; `fk` = foreign key.

**Identity (global)**
`users(id, email UNIQUE, email_verified_at, name, password_hash, mfa_secret, mfa_enabled, created_at, disabled_at)`
`sessions(id, user_id fk, token_hash UNIQUE, expires_at, ip, user_agent, created_at, revoked_at)`

**Tenancy**
`workspaces(id, name, slug UNIQUE, owner_id fk, status, plan, region, retention_days, deleted_at, created_at)`
`memberships(id, ws, user_id, role, status, invited_by, joined_at, UNIQUE(ws,user_id))`
`invitations(id, ws, email, role, token_hash UNIQUE, expires_at, accepted_at, created_by)`
`support_grants(id, ws, operator_id, scope, reason, expires_at, revoked_at, created_at)`

**Academic**
`classes(id, ws, name, subject, year, external_ref, archived_at)`
`students(id, ws, display_name, full_name, external_ref, notes, created_at, deleted_at)`
`enrollments(id, ws, class_id fk, student_id fk, UNIQUE(ws,class_id,student_id))`

Notes: `display_name` is the marker-facing label (V5 had a local nickname concept); `full_name` is PII and
requires `student.pii.read`. `external_ref` carries the Classroom user id or an imported student number.

**Assignments and schemes**
`assignments(id, ws, class_id fk, title, lesson_code, status, due_at, created_by, version, archived_at)`
`assignment_questions(id, ws, assignment_id fk, question_no, max_marks, sort_order, UNIQUE(ws,assignment_id,question_no))`
`mark_schemes(id, ws, assignment_id fk, source_file_id, status, blueprint_json, locked_at, locked_by)`
`scheme_decisions(id, ws, mark_scheme_id fk, question_no, decision, reason, actor_id, created_at)`

`lesson_code` preserves V5's rule: the **full** chapter-and-lesson identifier (`CH1L1`), never a bare `L1`,
because lesson numbers restart inside every chapter. Rows are keyed by `coursework_id` where a mark must pair
with its own assignment. `blueprint_json` holds the extracted question list and official max marks; once
`locked_at` is set, marking reads it and never re-derives it.

## 4. Status vocabularies (closed sets)

| Entity | Values |
|---|---|
| `assignments.status` | `draft`, `scheme_review`, `ready`, `marking`, `review`, `published`, `archived` |
| `mark_schemes.status` | `extracting`, `needs_review`, `locked`, `failed` |
| `submissions.status` | `pending`, `queued`, `marking`, `needs_review`, `approved`, `published`, `failed` |
| `jobs.status` | `queued`, `running`, `parked`, `retrying`, `succeeded`, `failed`, `cancelled`, `needs_verification` |
| `results.status` | `provisional`, `needs_review`, `approved`, `overridden` |
| `automation_operations.state` | `pending`, `in_progress`, `succeeded`, `failed`, `needs_verification`, `cancelled` |

`needs_verification` is deliberately distinct from `failed`: it means an attempt was interrupted and the
remote state must be **read** before anything is retried (V5 preserved this and it must not be collapsed).

## 5. Table catalogue — submissions, results, jobs, operations

**Submissions and results**
`submissions(id, ws, assignment_id fk, student_id fk, status, assignee_id, version, source, created_at, UNIQUE(ws,assignment_id,student_id))`
`submission_files(id, ws, submission_id fk, r2_key UNIQUE, kind, bytes, sha256, page_count, uploaded_by, created_at)`
`results(id, ws, submission_id fk UNIQUE, total_marks, max_marks, status, verified_at, version, created_at)`
`question_results(id, ws, result_id fk, question_no, awarded, max_marks, confidence, needs_review, explanation, UNIQUE(ws,result_id,question_no))`
`overrides(id, ws, result_id fk, question_no, from_marks, to_marks, reason, actor_id, created_at)`
`approvals(id, ws, result_id fk, actor_id, approved_at, note)`
`comments(id, ws, submission_id fk, author_id, body, visibility, created_at)` — append-only, never updated

Notes: `submission_files.r2_key` is `ws/{workspaceId}/submissions/{submissionId}/{fileId}`; the key is
derived server-side and never accepted from a client. `question_results.needs_review` is the V5 `REVIEW`
invariant: a missing or unverifiable question is flagged, never stored as `0`.

**Jobs and integrations**
`jobs(id, ws, submission_id fk, kind, status, idempotency_key, attempts, max_attempts, model, provider, error_code, error_detail, lease_until, started_at, finished_at, created_at, UNIQUE(ws,idempotency_key))`
`job_attempts(id, ws, job_id fk, attempt_no, outcome, error_class, started_at, finished_at, duration_ms, UNIQUE(ws,job_id,attempt_no))`
`automation_operations(id, ws, job_id fk, op_key, state, attempts, last_error, resolved_at, UNIQUE(ws,job_id,op_key))`
`provider_credentials(id, ws, provider, label, key_fingerprint, ciphertext, status, cooldown_until, last_tested_at, created_at)`
`provider_health(id, ws, provider, state, consecutive_failures, opened_until, updated_at, UNIQUE(ws,provider))`
`classroom_links(id, ws, course_id, coursework_id, assignment_id fk, last_synced_at, sync_state, UNIQUE(ws,coursework_id))`

`automation_operations` models the three independent remote effects of publishing — `attach_report`,
`publish_grade`, `return_assignment` — one row each. `state='needs_verification'` means the call was
interrupted and the remote state must be **read** before retry; a retry reuses the same row so the operation is
never duplicated (V5 semantics, preserved exactly).

**Operations**
`usage_events(id, ws, kind, quantity, unit, job_id, occurred_at)` — append-only metering
`usage_daily(id, ws, day, kind, quantity, UNIQUE(ws,day,kind))` — rollup for dashboards and quotas
`notifications(id, ws, user_id, kind, payload_json, read_at, created_at)`
`audit_log(id, ws, actor_id, action, target_type, target_id, before_json, after_json, ip, request_id, created_at)`
`saved_views(id, ws, user_id, resource, name, query_json)`

**Global (no `workspace_id`)**
`platform_audit(id, actor_id, action, workspace_id, target, detail_json, ip, request_id, created_at)`
`workspace_tombstones(id_hash PK, purged_at)`
`schema_migrations(version PK, applied_at)`

## 6. Indexes

```sql
CREATE INDEX idx_assignments_ws_status  ON assignments(workspace_id, status, created_at DESC);
CREATE INDEX idx_submissions_ws_assignee ON submissions(workspace_id, assignee_id, status);
CREATE INDEX idx_submissions_ws_assign   ON submissions(workspace_id, assignment_id, status);
CREATE UNIQUE INDEX ux_jobs_idem         ON jobs(workspace_id, idempotency_key);
CREATE INDEX idx_jobs_ws_status          ON jobs(workspace_id, status, created_at);
CREATE INDEX idx_jobs_ws_lease           ON jobs(workspace_id, lease_until) WHERE status IN ('queued','running');
CREATE INDEX idx_qr_result               ON question_results(workspace_id, result_id);
CREATE INDEX idx_audit_ws_time           ON audit_log(workspace_id, created_at DESC);
CREATE INDEX idx_usage_ws_kind           ON usage_events(workspace_id, kind, occurred_at);
CREATE INDEX idx_notifications_ws_user   ON notifications(workspace_id, user_id, read_at);
CREATE UNIQUE INDEX ux_users_email       ON users(email);            -- global, justified
CREATE UNIQUE INDEX ux_sessions_token    ON sessions(token_hash);    -- global, justified
```

Any index whose first column is not `workspace_id` needs a written justification in review.

## 7. Transactions

- Use `db.batch()` for one logical operation so it is atomic. D1 has no interactive transactions across
  round trips, so never design a read-modify-write that spans two awaits without a `version` guard.
- **Approve** = update `results` (guarded by `WHERE version = ?`) + insert `approvals` + insert `audit_log`,
  in one batch.
- **Publish** = upsert three `automation_operations` rows + set assignment status, one batch.
- **Never mix `workspace_id` values in one batch** — a batch is one transaction and a cross-tenant write would
  be a leak in the audit trail.

## 8. V5 → V5.5 mapping

| V5 | V5.5 | Note |
|---|---|---|
| `accounts`, `account_scope`, `multi_account` | `provider_credentials` | encrypted, workspace-scoped |
| `auth_tokens`, `devices`, `device_*` | `sessions` (Better Auth) | device flow dropped |
| `schools`, `teams`, `team_members` | `workspaces`, `memberships` | `teams` was not tenancy; do not reuse semantics |
| `classes`, `courses` | `classes` + `classroom_links` | local class vs external course |
| `results`, `update_history` | `results` + `question_results` + `overrides` | sub-question granularity preserved |
| `scheme_question_decisions`, `scheme_decision_history`, `scheme_ignored_questions` | `scheme_decisions` | one append-only table |
| `report_deliveries`, `report_upload_records`, `report_upload_locks` | `automation_operations` | one row per (job, op) |
| `automation_*`, `job_stage_events` | `jobs` + `job_attempts` | staged progress becomes attempt history |
| `large_pdf_jobs`, `large_pdf_batches`, `bulk_upload_claims` | `jobs` + R2 multipart | |
| `audit_log` | `audit_log` | adds `workspace_id`, `request_id` |
| `sync_events` | `classroom_links.last_synced_at` + `audit_log` | |
| `error_reports` | platform error store | not tenant data |
| `update_*` | none | desktop updater retired |

Students were local-only in V5 (`student_identity.py`); in V5.5 they are workspace records gated by
`student.pii.read`. **No V5 data is migrated automatically** — V5 stays a local product; an importer is a
separate decision (`../decisions/OPEN_QUESTIONS.md` Q5).

## 9. D1 constraints that shaped this design (VERIFIED)

| Constraint | Consequence |
|---|---|
| 10 GB per database, hard cap, cannot be raised | metadata only; blobs in R2. ~1 KB/submission means 100k submissions ≈ 100 MB |
| 50 MB max query result (from 2026-11-04) | exports/reports paginate; never `SELECT` an entire tenant |
| 100 KB statement, 100 bound params | inserts chunk at ≤ 100 rows |
| 2 MB row, 100 columns | `payload_json` small; no denormalised blobs |
| Single-threaded per database | short write batches; no long work inside a request |
| 1,000 queries per Worker invocation (Paid) | batch reads, avoid N+1 |
| Time Travel 30 days, **destructive in-place restore** | restore is last resort; R2 exports are the real backup |
