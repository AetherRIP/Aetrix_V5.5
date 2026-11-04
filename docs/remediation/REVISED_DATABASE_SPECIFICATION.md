# Revised Database Specification

**Status:** RECOMMENDED — supersedes `architecture/DATABASE_DESIGN.md` where they differ. The original remains
unmodified and authoritative for anything not restated here.
**Target:** Cloudflare D1 (SQLite). Planning only: no database, binding or migration has been created.

---

## 1. What changed, and why

| # | Original | Revised | Reason |
|---|---|---|---|
| 1 | Hand-rolled `users`, `sessions`, `memberships`, `invitations` | Better Auth's `user`, `session`, `account`, `verification`, `organization`, `member`, `invitation`, `twoFactor`, `passkey` | The library validates its schema at runtime and rejects mismatches; two identity systems drift (DB-01) |
| 2 | Timestamps `TEXT` ISO-8601 | `INTEGER` epoch milliseconds, formatted at the API edge | Better Auth 1.7 requires date-typed timestamps; text breaks session `max_age` |
| 3 | Tenant consistency by convention | `BEFORE INSERT`/`BEFORE UPDATE OF` triggers on every child table | The only database-level control SQLite offers (SEC-05/DB-03) |
| 4 | `UNIQUE(ws, a, b)` including soft-deleted rows | Partial unique indexes | Re-upload and re-invite must work (DB-04) |
| 5 | `total_marks` written by handlers | Derived by trigger; handlers never write it | The number the product sells must not be able to disagree with its parts (DB-08) |
| 6 | `needs_review` boolean with `awarded = 0` | `awarded NULL` when `needs_review = 1`, enforced by `CHECK` | Makes "never a silent zero" a schema invariant |
| 7 | No `api_keys`, `job_outbox`, `exports`, `review_drafts`, `sample_reviews`, `notification_preferences`, `legal_holds`, `idempotency_records`, `platform_operators`, `maintenance_windows`, `rate_limit` | Added | Requirements with no storage (register §8) |
| 8 | Audit append-only "by convention" | `BEFORE UPDATE` abort; `DELETE` only inside a recorded maintenance window | Enforceable, and still purgeable (DB-11) |
| 9 | KV listed as a cache | Removed | Unused binding is an unowned permission (ARC-09) |

**DDL ownership.** The Better Auth baseline is generated **once** from the auth configuration, committed to
`migrations/`, and extended by hand. The generator is never run against production, and no auto-migration is a
deploy step. This is what prevents an upgrade from silently rewriting identity tables.

---

## 2. Identity schema (Better Auth, canonical)

Column names follow the library (**camelCase**) and are extended only through supported mechanisms.

```sql
-- Core, required by Better Auth
CREATE TABLE user (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  emailVerified INTEGER NOT NULL DEFAULT 0,
  image         TEXT,
  createdAt     INTEGER NOT NULL,
  updatedAt     INTEGER NOT NULL,
  -- product extensions (additionalFields)
  failedLoginCount INTEGER NOT NULL DEFAULT 0,
  lockedUntil      INTEGER,
  mfaRequired      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE session (
  id        TEXT PRIMARY KEY,
  userId    TEXT NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  token     TEXT NOT NULL UNIQUE,
  expiresAt INTEGER NOT NULL,
  ipAddress TEXT,
  userAgent TEXT,
  createdAt INTEGER NOT NULL,
  updatedAt INTEGER NOT NULL,
  activeOrganizationId TEXT,          -- organization plugin
  -- product extensions
  amr           TEXT,                 -- JSON array: ["pwd","totp"] | ["passkey"] | ["google"]
  mfaVerifiedAt INTEGER
);
CREATE INDEX idx_session_user ON session(userId);

CREATE TABLE account (
  id                    TEXT PRIMARY KEY,
  userId                TEXT NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  accountId             TEXT NOT NULL,
  providerId            TEXT NOT NULL,   -- 'credential' | 'google' | ...
  accessToken           TEXT,
  refreshToken          TEXT,
  accessTokenExpiresAt  INTEGER,
  refreshTokenExpiresAt INTEGER,
  scope                 TEXT,
  idToken               TEXT,
  password              TEXT,            -- scrypt hash for providerId='credential'
  createdAt             INTEGER NOT NULL,
  updatedAt             INTEGER NOT NULL
);
CREATE INDEX idx_account_user ON account(userId);

CREATE TABLE verification (
  id         TEXT PRIMARY KEY,
  identifier TEXT NOT NULL,
  value      TEXT NOT NULL,
  expiresAt  INTEGER NOT NULL,
  createdAt  INTEGER NOT NULL,
  updatedAt  INTEGER NOT NULL
);
CREATE INDEX idx_verification_identifier ON verification(identifier);
```

**Plugin tables** — `twoFactor(id, userId, secret, backupCodes, verified, failedVerificationCount,
lockedUntil)`, `passkey(id, name, publicKey, userId, credentialID, counter, deviceType, backedUp, transports,
createdAt, aaguid)`, `organization(id, name, slug, logo, metadata, createdAt)`,
`member(id, organizationId, userId, role, createdAt, + product fields)`,
`invitation(id, organizationId, email, role, status, expiresAt, inviterId, teamId)`, and
`rate_limit(id, key UNIQUE, count, lastRequest)`.

`twoFactor.failedVerificationCount` and `lockedUntil` already exist in the library — noted because the audit
assumed a custom lockout table would be needed for TOTP guessing; only the *password* lockout needs new columns.

### 2.1 Mapping table (normative)

| Product term | Canonical | Notes |
|---|---|---|
| Workspace | `organization` | `workspace_id` **is** `organization.id`; there is no separate table |
| Workspace member | `member` | `role` holds one of five role names; `status`/`invitedBy`/`joinedAt`/`removedAt` are additional fields |
| User | `user` | Never referenced as `users` in SQL; the code alias is `User` |
| Session | `session` | `activeOrganizationId` is a *hint*; the membership row is the fact |
| Invitation | `invitation` | Library `status` (`pending`/`accepted`/`rejected`/`canceled`) replaces the package's own column |
| Membership role | `member.role` | `owner` \| `admin` \| `supervisor` \| `assistant` \| `viewer` |
| Platform operator | `platform_operators` (new) | Deliberately **not** a membership; operators have no workspace row |

### 2.2 Roles and permissions in one definition

Five workspace roles, not six: `platform_operator` is a platform capability with no membership, so treating it
as a role was the source of `SEC-07`'s drift. Built-in `owner`/`admin` keep the library's own names so its
organization endpoints continue to work; `supervisor`, `assistant` and `viewer` are declared with
`createAccessControl` over the product's statement set, merged with `defaultStatements`, and the roles matrix is
**generated** from that object rather than transcribed.

A `CHECK (role IN ('owner','admin','supervisor','assistant','viewer'))` on `member.role` makes an unregistered
role impossible; multi-role comma strings are not used, and are rejected by the same constraint.

---

## 3. Workspace and academic tables

```sql
-- organization extensions (additionalFields; shown for reference, not created here)
--   plan TEXT CHECK (plan IN ('trial','pilot','standard'))
--   region TEXT, status TEXT CHECK (status IN ('active','suspended','pending_deletion','deleted'))
--   retentionDays INTEGER, quotaAiCallsMonth INTEGER, quotaStorageBytes INTEGER
--   brandingJson TEXT, academicDefaultsJson TEXT, correctionDefaultsJson TEXT
--   deletedAt INTEGER, purgeAfter INTEGER, createdBy TEXT REFERENCES user(id)

CREATE TABLE classes (
  id          TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  name        TEXT NOT NULL,
  subject     TEXT,
  year        TEXT,
  external_ref TEXT,
  archived_at INTEGER,
  created_at  INTEGER NOT NULL
);
CREATE INDEX idx_classes_ws ON classes(workspace_id, archived_at);

CREATE TABLE students (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  display_name  TEXT NOT NULL,          -- marker-facing; may be a nickname
  full_name     TEXT,                   -- PII, gated by student.pii.read
  external_ref  TEXT,                   -- Classroom user id or imported number
  notes         TEXT,
  anonymised_at INTEGER,                -- set by erasure (UX-07)
  deleted_at    INTEGER,
  created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_students_external
  ON students(workspace_id, external_ref)
  WHERE external_ref IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE enrollments (
  id         TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  class_id   TEXT NOT NULL REFERENCES classes(id),
  student_id TEXT NOT NULL REFERENCES students(id),
  created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_enrollments ON enrollments(workspace_id, class_id, student_id);
```

**Erasure semantics (UX-07).** Erasure sets `anonymised_at`, replaces `display_name` with
`"Removed student N"`, nulls `full_name`, `external_ref` and `notes`, and retains the numeric results so class
aggregates stay correct. It never rewrites a grade already published to Classroom without an explicit operator
action, and it never deletes a `results` row — deleting the row would silently change the class's mean.

### 3.1 Assignments and schemes

```sql
CREATE TABLE assignments (
  id          TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  class_id    TEXT NOT NULL REFERENCES classes(id),
  title       TEXT NOT NULL,
  lesson_code TEXT,                     -- full CH1L1, never a bare L1
  status      TEXT NOT NULL CHECK (status IN
                ('draft','scheme_review','ready','marking','review','published','archived')),
  due_at      INTEGER,
  created_by  TEXT NOT NULL REFERENCES user(id),
  version     INTEGER NOT NULL DEFAULT 1,
  archived_at INTEGER,
  created_at  INTEGER NOT NULL
);
CREATE INDEX idx_assignments_ws_status ON assignments(workspace_id, status, created_at DESC);

CREATE TABLE assignment_questions (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  assignment_id TEXT NOT NULL REFERENCES assignments(id),
  question_no   TEXT NOT NULL,          -- TEXT: "1a", "2b(ii)" are real
  max_marks     REAL NOT NULL CHECK (max_marks > 0),
  sort_order    INTEGER NOT NULL,
  created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_aq ON assignment_questions(workspace_id, assignment_id, question_no);

CREATE TABLE mark_schemes (
  id             TEXT PRIMARY KEY,
  workspace_id   TEXT NOT NULL REFERENCES organization(id),
  assignment_id  TEXT NOT NULL REFERENCES assignments(id),
  source_file_id TEXT,
  status         TEXT NOT NULL CHECK (status IN ('extracting','needs_review','locked','failed')),
  blueprint_json TEXT NOT NULL,
  version        INTEGER NOT NULL DEFAULT 1,   -- added (UX-04)
  locked_at      INTEGER,
  locked_by      TEXT REFERENCES user(id),
  created_at     INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_scheme_assignment ON mark_schemes(workspace_id, assignment_id);

CREATE TABLE scheme_decisions (
  id             TEXT PRIMARY KEY,
  workspace_id   TEXT NOT NULL REFERENCES organization(id),
  mark_scheme_id TEXT NOT NULL REFERENCES mark_schemes(id),
  question_no    TEXT,
  decision       TEXT NOT NULL,
  reason         TEXT,
  actor_id       TEXT NOT NULL REFERENCES user(id),
  created_at     INTEGER NOT NULL
);
```

`mark_schemes.version` is the concurrency control: question edits and lock/unlock require `If-Match`.
Last-write-wins here means marks validated against the wrong maximum, which is a mark-integrity bug, not a UX
inconvenience.

### 3.2 Submissions, results, review

```sql
CREATE TABLE submissions (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  assignment_id TEXT NOT NULL REFERENCES assignments(id),
  student_id    TEXT NOT NULL REFERENCES students(id),
  status        TEXT NOT NULL CHECK (status IN
                  ('pending','queued','marking','needs_review','approved','published','failed')),
  assignee_id   TEXT,                    -- references member(id); NULL = unassigned
  version       INTEGER NOT NULL DEFAULT 1,
  source        TEXT CHECK (source IN ('upload','classroom','import')),
  deleted_at    INTEGER,
  created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_submissions_active
  ON submissions(workspace_id, assignment_id, student_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_submissions_ws_assignee ON submissions(workspace_id, assignee_id, status);
CREATE INDEX idx_submissions_ws_assign  ON submissions(workspace_id, assignment_id, status);
CREATE INDEX idx_submissions_ws_student ON submissions(workspace_id, student_id);   -- added (DB-10)

CREATE TABLE submission_files (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  submission_id TEXT NOT NULL REFERENCES submissions(id),
  r2_key        TEXT NOT NULL,           -- ws/{ws}/submissions/{subId}/{fileId}
  kind          TEXT NOT NULL,
  bytes         INTEGER NOT NULL,
  sha256        TEXT NOT NULL,           -- written at upload; the integrity anchor
  page_count    INTEGER,
  uploaded_by   TEXT NOT NULL REFERENCES user(id),
  created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_files_key ON submission_files(workspace_id, r2_key);   -- was global (DB-06)
CREATE INDEX idx_files_submission ON submission_files(workspace_id, submission_id);  -- added (DB-10)

CREATE TABLE results (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  submission_id TEXT NOT NULL REFERENCES submissions(id),
  total_marks   REAL NOT NULL DEFAULT 0,   -- derived by trigger; never written by handlers
  max_marks     REAL NOT NULL,
  marked_questions INTEGER NOT NULL DEFAULT 0,
  total_questions  INTEGER NOT NULL DEFAULT 0,
  is_complete   INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL CHECK (status IN
                  ('provisional','needs_review','approved','overridden','published')),
  verified_at   INTEGER,
  version       INTEGER NOT NULL DEFAULT 1,
  created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_results_submission ON results(workspace_id, submission_id);  -- was global

CREATE TABLE question_results (
  id                     TEXT PRIMARY KEY,
  workspace_id           TEXT NOT NULL REFERENCES organization(id),
  result_id              TEXT NOT NULL REFERENCES results(id),
  assignment_question_id TEXT NOT NULL REFERENCES assignment_questions(id),   -- added (DB-08)
  question_no            TEXT NOT NULL,
  awarded                REAL,            -- NULL when needs_review
  max_marks              REAL NOT NULL,
  confidence             REAL,
  needs_review           INTEGER NOT NULL DEFAULT 0,
  explanation            TEXT,
  created_at             INTEGER NOT NULL,
  CHECK (awarded IS NULL OR (awarded >= 0 AND awarded <= max_marks)),
  CHECK (needs_review = 0 OR awarded IS NULL)
);
CREATE UNIQUE INDEX ux_qr ON question_results(workspace_id, result_id, question_no);
CREATE INDEX idx_qr_result ON question_results(workspace_id, result_id);

CREATE TABLE overrides (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  result_id    TEXT NOT NULL REFERENCES results(id),
  question_no  TEXT NOT NULL,
  from_marks   REAL,
  to_marks     REAL NOT NULL,
  reason       TEXT NOT NULL CHECK (length(reason) >= 10),
  actor_id     TEXT NOT NULL REFERENCES user(id),
  created_at   INTEGER NOT NULL,
  CHECK (to_marks >= 0)
);

CREATE TABLE approvals (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  result_id    TEXT NOT NULL REFERENCES results(id),
  actor_id     TEXT NOT NULL REFERENCES user(id),
  approved_at  INTEGER NOT NULL,
  note         TEXT
);
CREATE UNIQUE INDEX ux_approvals_result ON approvals(workspace_id, result_id);   -- one approval

CREATE TABLE comments (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  submission_id TEXT NOT NULL REFERENCES submissions(id),
  author_id     TEXT NOT NULL REFERENCES user(id),
  body          TEXT NOT NULL,
  visibility    TEXT NOT NULL CHECK (visibility IN ('staff','admins')),   -- vocabulary added
  created_at    INTEGER NOT NULL
);

CREATE TABLE review_drafts (              -- added (UX-01)
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  result_id    TEXT NOT NULL REFERENCES results(id),
  actor_id     TEXT NOT NULL REFERENCES user(id),
  body_json    TEXT NOT NULL,
  base_version INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_review_drafts ON review_drafts(workspace_id, result_id, actor_id);

CREATE TABLE sample_reviews (             -- added (UX-03)
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  assignment_id TEXT NOT NULL REFERENCES assignments(id),
  result_id     TEXT NOT NULL REFERENCES results(id),
  selected_by   TEXT NOT NULL REFERENCES user(id),
  selection_reason TEXT NOT NULL CHECK (selection_reason IN ('random','flagged','manual')),
  state         TEXT NOT NULL CHECK (state IN ('pending','reviewed','signed_off')),
  reviewer_id   TEXT REFERENCES user(id),
  reviewed_at   INTEGER,
  note          TEXT,
  created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_sample_reviews ON sample_reviews(workspace_id, assignment_id, result_id);
```

---

## 4. Jobs, operations and metering

```sql
CREATE TABLE jobs (
  id              TEXT PRIMARY KEY,
  workspace_id    TEXT NOT NULL REFERENCES organization(id),
  submission_id   TEXT NOT NULL REFERENCES submissions(id),
  kind            TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN
                    ('queued','running','parked','retrying','succeeded','failed','cancelled','needs_verification')),
  idempotency_key TEXT NOT NULL,
  attempts        INTEGER NOT NULL DEFAULT 0,
  max_attempts    INTEGER NOT NULL DEFAULT 3,
  model           TEXT,
  provider        TEXT,
  error_code      TEXT,
  error_detail    TEXT,
  lease_until     INTEGER,
  started_at      INTEGER,
  finished_at     INTEGER,
  created_at      INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_jobs_idem ON jobs(workspace_id, idempotency_key);
CREATE INDEX idx_jobs_ws_status ON jobs(workspace_id, status, created_at);
CREATE INDEX idx_jobs_ws_lease  ON jobs(workspace_id, lease_until) WHERE status IN ('queued','running','parked');

CREATE TABLE job_outbox (                 -- added (ARC-01)
  job_id           TEXT PRIMARY KEY REFERENCES jobs(id),
  workspace_id     TEXT NOT NULL REFERENCES organization(id),
  created_at       INTEGER NOT NULL,
  published_at     INTEGER,
  publish_attempts INTEGER NOT NULL DEFAULT 0,
  last_error       TEXT
);
CREATE INDEX idx_outbox_pending ON job_outbox(created_at) WHERE published_at IS NULL;

CREATE TABLE job_attempts (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  job_id       TEXT NOT NULL REFERENCES jobs(id),
  attempt_no   INTEGER NOT NULL,
  outcome      TEXT NOT NULL,
  error_class  TEXT,
  started_at   INTEGER NOT NULL,
  finished_at  INTEGER,
  duration_ms  INTEGER
);
CREATE UNIQUE INDEX ux_job_attempts ON job_attempts(workspace_id, job_id, attempt_no);

CREATE TABLE automation_operations (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  job_id       TEXT NOT NULL REFERENCES jobs(id),
  op_key       TEXT NOT NULL CHECK (op_key IN ('attach_report','publish_grade','return_assignment')),
  state        TEXT NOT NULL CHECK (state IN
                 ('pending','in_progress','succeeded','failed','needs_verification','cancelled')),
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT,
  resolved_at  INTEGER,
  created_at   INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_ops ON automation_operations(workspace_id, job_id, op_key);
```

### 4.1 Metering

```sql
CREATE TABLE usage_events (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  kind          TEXT NOT NULL,          -- 'ai_call','export','report','storage_snapshot'
  quantity      INTEGER NOT NULL,
  unit          TEXT NOT NULL,          -- 'call','bytes','token'
  job_id        TEXT REFERENCES jobs(id),
  attempt_no    INTEGER,
  source_key    TEXT,                   -- non-job idempotency: export id, report id
  occurred_at   INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_usage_job
  ON usage_events(workspace_id, job_id, attempt_no, kind) WHERE job_id IS NOT NULL;
CREATE UNIQUE INDEX ux_usage_source
  ON usage_events(workspace_id, source_key, kind) WHERE source_key IS NOT NULL;
CREATE INDEX idx_usage_ws_kind ON usage_events(workspace_id, kind, occurred_at);

CREATE TABLE usage_daily (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  day          TEXT NOT NULL,           -- 'YYYY-MM-DD', UTC
  kind         TEXT NOT NULL,
  quantity     INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_usage_daily ON usage_daily(workspace_id, day, kind);
```

**Rollup semantics, stated once (DOC-13).** Events are the source of truth. An hourly cron recomputes the
**last two days** from events with replace semantics:

```sql
INSERT INTO usage_daily (id, workspace_id, day, kind, quantity)
SELECT :id, workspace_id, strftime('%Y-%m-%d', occurred_at/1000, 'unixepoch'), kind, SUM(quantity)
FROM usage_events WHERE workspace_id = ? AND occurred_at >= :twoDaysAgo
GROUP BY workspace_id, 2, kind
ON CONFLICT(workspace_id, day, kind) DO UPDATE SET quantity = excluded.quantity;
```

Replace, never increment: an incrementing rollup double-counts on retry and erases on re-run. The two-day window
covers late-arriving events. Monthly figures are a view over `usage_daily`, not a third table.

**Jobs retention and `usage_events.job_id` (DB Part C item 5).** Jobs are pruned at 90 days after terminal;
`usage_events` are kept 24 months. `job_id` is therefore `ON DELETE SET NULL` with the `job_id`/`attempt_no`
uniqueness nulled at the same moment — the metering survives, the link does not. Jobs are never hard-deleted
while a `usage_events` row references them *and* the workspace is under an audit hold.

---

## 5. Security, access and platform tables

```sql
CREATE TABLE api_keys (                   -- added (DB-02)
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  label        TEXT NOT NULL,
  prefix       TEXT NOT NULL,
  key_hash     TEXT NOT NULL,
  scopes_json  TEXT NOT NULL,
  created_by   TEXT NOT NULL REFERENCES user(id),
  created_at   INTEGER NOT NULL,
  last_used_at INTEGER,
  expires_at   INTEGER,
  revoked_at   INTEGER
);
CREATE UNIQUE INDEX ux_api_keys_prefix ON api_keys(prefix);

CREATE TABLE support_grants (
  id               TEXT PRIMARY KEY,
  workspace_id     TEXT NOT NULL REFERENCES organization(id),
  operator_user_id TEXT NOT NULL REFERENCES user(id),
  scope_json       TEXT NOT NULL,         -- array of read-only permission keys
  reason           TEXT NOT NULL CHECK (length(reason) >= 20),
  created_by       TEXT NOT NULL REFERENCES user(id),
  created_at       INTEGER NOT NULL,
  expires_at       INTEGER NOT NULL,
  revoked_at       INTEGER,
  revoked_by       TEXT REFERENCES user(id),
  CHECK (expires_at > created_at AND expires_at <= created_at + 259200000)  -- ≤ 72 h
);
CREATE UNIQUE INDEX ux_support_active
  ON support_grants(workspace_id, operator_user_id) WHERE revoked_at IS NULL;

CREATE TABLE platform_operators (         -- added (M10)
  user_id    TEXT PRIMARY KEY REFERENCES user(id),
  status     TEXT NOT NULL CHECK (status IN ('active','suspended')),
  created_by TEXT REFERENCES user(id),
  created_at INTEGER NOT NULL,
  notes      TEXT
);

CREATE TABLE exports (                    -- added (API-02)
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  kind          TEXT NOT NULL CHECK (kind IN ('workspace','assignment','class')),
  target_id     TEXT,
  state         TEXT NOT NULL CHECK (state IN ('queued','running','succeeded','failed','expired')),
  r2_key        TEXT,
  bytes         INTEGER,
  sha256        TEXT,
  manifest_json TEXT,
  row_counts_json TEXT,
  requested_by  TEXT NOT NULL REFERENCES user(id),
  created_at    INTEGER NOT NULL,
  completed_at  INTEGER,
  expires_at    INTEGER,
  error_code    TEXT
);
CREATE INDEX idx_exports_ws ON exports(workspace_id, created_at DESC);

CREATE TABLE idempotency_records (        -- added (M12)
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES organization(id),
  key           TEXT NOT NULL,
  route         TEXT NOT NULL,
  request_hash  TEXT NOT NULL,
  response_json TEXT,
  status_code   INTEGER,
  created_at    INTEGER NOT NULL,
  expires_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX ux_idem ON idempotency_records(workspace_id, key);

CREATE TABLE notification_preferences (   -- added (API-03/DB-09)
  user_id      TEXT NOT NULL REFERENCES user(id),
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  kind         TEXT NOT NULL,
  channel      TEXT NOT NULL CHECK (channel IN ('in_app','email','both','none')),
  updated_at   INTEGER NOT NULL,
  PRIMARY KEY (user_id, workspace_id, kind)
);

CREATE TABLE notifications (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  user_id      TEXT NOT NULL REFERENCES user(id),
  kind         TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  read_at      INTEGER,
  failed_at    INTEGER,
  created_at   INTEGER NOT NULL
);
CREATE INDEX idx_notifications_ws_user ON notifications(workspace_id, user_id, read_at);

CREATE TABLE legal_holds (                -- added (M11)
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  reason       TEXT NOT NULL,
  created_by   TEXT NOT NULL REFERENCES user(id),
  created_at   INTEGER NOT NULL,
  released_at  INTEGER
);
CREATE UNIQUE INDEX ux_legal_hold_active ON legal_holds(workspace_id) WHERE released_at IS NULL;
```

### 5.1 Audit and maintenance

```sql
CREATE TABLE audit_log (
  id           TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  actor_id     TEXT,
  actor_kind   TEXT NOT NULL CHECK (actor_kind IN ('member','api_key','support','system')),
  action       TEXT NOT NULL,
  target_type  TEXT,
  target_id    TEXT,
  before_json  TEXT,
  after_json   TEXT,
  ip           TEXT,
  request_id   TEXT NOT NULL,
  created_at   INTEGER NOT NULL
);
CREATE INDEX idx_audit_ws_time ON audit_log(workspace_id, created_at DESC);

CREATE TABLE maintenance_windows (        -- added (M15)
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('audit_purge','retention_sweep','workspace_purge')),
  workspace_id TEXT NOT NULL REFERENCES organization(id),
  actor_id     TEXT,
  started_at   INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL
);

CREATE TABLE platform_audit (
  id           TEXT PRIMARY KEY,
  actor_id     TEXT,
  action       TEXT NOT NULL,
  workspace_id TEXT,
  target       TEXT,
  detail_json  TEXT,
  ip           TEXT,
  request_id   TEXT NOT NULL,
  created_at   INTEGER NOT NULL
);

CREATE TABLE workspace_tombstones (id_hash TEXT PRIMARY KEY, purged_at INTEGER NOT NULL);
CREATE TABLE schema_migrations    (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);

-- platform operations (defined in full in R2_BACKUP_AND_RECOVERY_DESIGN.md §4)
--   ops_backup_log, backup_objects, ops_cron_runs
```

---

## 6. Invariants enforced below the application

### 6.1 Tenant consistency

One `BEFORE INSERT` and one `BEFORE UPDATE OF` trigger per child table, asserting each tenant FK resolves to a
parent in the same workspace. The pattern:

```sql
CREATE TRIGGER trg_<table>_tenant_ins BEFORE INSERT ON <table> FOR EACH ROW
WHEN NOT EXISTS (SELECT 1 FROM <parent> p
                 WHERE p.id = NEW.<parent_fk> AND p.workspace_id = NEW.workspace_id)
BEGIN SELECT RAISE(ABORT, 'tenant_mismatch'); END;
```

Covered tables and parents: `enrollments`→classes,students · `assignments`→classes ·
`assignment_questions`→assignments · `mark_schemes`→assignments · `scheme_decisions`→mark_schemes ·
`submissions`→assignments,students · `submission_files`→submissions · `results`→submissions ·
`question_results`→results,assignment_questions · `overrides`→results · `approvals`→results ·
`comments`→submissions · `review_drafts`→results · `sample_reviews`→assignments,results ·
`jobs`→submissions · `job_outbox`→jobs · `job_attempts`→jobs · `automation_operations`→jobs ·
`classroom_links`→assignments · `exports`→workspace · `api_keys`→workspace · `support_grants`→workspace ·
`notifications`→workspace · `usage_events`→workspace · `audit_log`→workspace.

**Schema-enumeration test.** `T-DB-01` reads `sqlite_master`, finds every table with a `workspace_id` column, and
asserts at least one `trg_*_tenant_ins` trigger exists for it. This is what stops the control decaying when a
future table is added.

### 6.2 Mark integrity

- `question_results.awarded` NULL ⇒ `needs_review = 1`; non-null ⇒ within `[0, max_marks]`.
- `overrides` validated against `assignment_questions.max_marks` by trigger (`mark_exceeds_max`).
- `results.total_marks`, `marked_questions`, `total_questions`, `is_complete` maintained by `AFTER INSERT/UPDATE/
  DELETE` triggers on `question_results`; no handler writes them.
- A weekly `verify` job asserts `total_marks = SUM(awarded)` per result and reports drift to `platform_audit`.

### 6.3 Audit immutability

```sql
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_append_only'); END;

CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_log FOR EACH ROW
WHEN NOT EXISTS (
  SELECT 1 FROM maintenance_windows w
  WHERE w.workspace_id = OLD.workspace_id
    AND w.kind = 'audit_purge'
    AND w.expires_at > CAST(strftime('%s','now') AS INTEGER) * 1000)
BEGIN SELECT RAISE(ABORT, 'audit_append_only'); END;
```

The maintenance window is the documented escape: a sweep opens one, deletes one workspace's expired rows, closes
it, and the window itself is written to `platform_audit`. Without it, "append-only" and "12-month retention" are
contradictory requirements.

### 6.4 Status vocabularies

Closed sets are `CHECK`-constrained: `assignments.status`, `mark_schemes.status`, `submissions.status`,
`jobs.status`, `results.status` (**now includes `published`**, closing DB Part C item 4), `automation_operations.state`,
`comments.visibility`, `support_grants` and `exports.state`. `workspaces.status` (on `organization`) is
`active|suspended|pending_deletion|deleted`.

`pending_review` is removed from all copy: the only state is `needs_review`, which is what the schema, the
design tokens and the acceptance criteria already use.

---

## 7. Indexes

Retained from the original: `idx_assignments_ws_status`, `idx_submissions_ws_assignee`,
`idx_submissions_ws_assign`, `ux_jobs_idem`, `idx_jobs_ws_status`, `idx_jobs_ws_lease`, `idx_qr_result`,
`idx_audit_ws_time`, `idx_usage_ws_kind`, `idx_notifications_ws_user`, `ux_users_email` (now `user.email`),
`ux_sessions_token` (now `session.token`).

Added: `idx_submissions_ws_student`, `idx_files_submission`, `idx_outbox_pending`, `idx_exports_ws`,
`ux_api_keys_prefix`, `ux_support_active`, `ux_legal_hold_active`, `ux_idem`, `ux_usage_job`, `ux_usage_source`,
`ux_review_drafts`, `ux_sample_reviews`, `ux_approvals_result`, `idx_session_user`, `idx_account_user`,
`idx_verification_identifier`, `idx_classes_ws`.

Rule retained: **any index whose first column is not `workspace_id` needs a written justification.** The five
exceptions are `user.email`, `session.token`, `api_keys.prefix`, `idempotency_records.key` (composite with
workspace), and `ops_*` platform tables.

---

## 8. Transactions and batching

Unchanged in spirit, sharpened by what the remediation adds:

| Operation | One batch, one transaction |
|---|---|
| Create job | `jobs` insert + `job_outbox` insert |
| Claim job | single guarded `UPDATE` with `attempts = attempts + 1`, then `meta.changes` check |
| Publish outbox | `QUEUE.send` per row, then one `UPDATE … WHERE published_at IS NULL` per row |
| Approve | `results` update (guarded by `version`) + `approvals` insert + `audit_log` insert |
| Override | `question_results` update + `overrides` insert + `audit_log` insert |
| Publish | three `automation_operations` upserts + assignment status + audit |
| Support read | the data read + its `audit_log` row |
| Create workspace | `organization` insert + `member` insert (owner) + `audit_log` insert |

Rules: no batch spans two workspaces; a batch counts as **one** query against the 1,000-per-invocation budget
and must finish inside the 30 s query limit; read-modify-write across awaits always carries a `version` guard.

Reads are **primary-only** in the MVP (`ARC-08`). A single `readSession()` helper wraps every read so read
replication can be enabled later without touching call sites; the Sessions API bookmark, when enabled, is used
only for read-your-writes inside one request.

---

## 9. D1 constraints and how this schema respects them

| Constraint (verified) | Consequence for this schema |
|---|---|
| 10 GB per database, hard cap | Metadata only; scripts stay in R2. Revised arithmetic: 4.4–6.1 KB per submission ⇒ ~0.35–0.45 GB/month at 100 workspaces, ~3–4 years to the wall with the stated retention |
| 50 MB query result from 2026-11-04 | No endpoint selects a whole tenant; results list paginates; exports stream table by table |
| 100 KB statement, 100 bound params | Insert chunks ≤ 100 rows; bulk import and restore batch at 1,000 rows per statement with ≤ 100 params |
| 2 MB row, 100 columns | `blueprint_json` and `manifest_json` are small; `organization` carries ~12 extension columns, within the limit |
| Single-threaded per database | Writes are short; triggers are primary-key probes; no long work inside a request |
| 1,000 queries per invocation | Batches reuse one query; no N+1 on the three hot reads (guarded by `T-API-07`) |
| `db.batch()` = one transaction, counts as one query | Used for every multi-statement invariant (§8) |
| No interactive transactions | Nothing spans two awaits without a version guard or an outbox |
| Time Travel 30 days, destructive in-place | Restore is a last resort; exports in R2 are the backup (BKP-R) |
| `d1 export` blocks the database, no FTS5 | Export runs in a maintenance window against a bookmark; no FTS5 tables are used |

**Foreign keys.** D1 enforces `FOREIGN KEY` constraints; the schema does not rely on that for tenancy (triggers
do), but does rely on it for orphan prevention. `T-DB-01` asserts enforcement rather than assuming it.

---

## 10. Migration plan

1. **Baseline generation.** Generate Better Auth's DDL once from the committed auth config; commit as
   `migrations/0001_identity.sql`; review every column against §2.
2. **Extensions.** `0002_identity_extensions.sql` (additional fields, `CHECK(role)`), `0003_domain.sql`,
   `0004_constraints.sql` (CHECKs, partial uniques), `0005_triggers.sql`, `0006_indexes.sql`,
   `0007_platform.sql`.
3. **Expand → migrate → contract** for anything destructive, as already required by `DEPLOYMENT_PLAN.md` §3.
4. **Rehearsal.** Every migration runs against the latest export in staging with timing capture; abort if it
   exceeds 50 % of the 30 s query budget (`REL-09`).
5. **No down-migrations.** Rollback is a forward fix or a Time Travel restore, rehearsed at least once.
6. **Trigger installation is a separate migration** from table creation, so a failed trigger does not leave a
   half-migrated table and the schema-enumeration test can distinguish "missing trigger" from "missing table".

---

## 11. Verification

| Test | Asserts |
|---|---|
| `T-DB-01` | Every table with `workspace_id` has a tenant trigger; FKs are enforced |
| `T-DB-02` | Cross-tenant parent FK rejected on insert and on update, per table |
| `T-DB-03` | Library boots against the migrated schema; sign-up → session → org → invite → role change all work |
| `T-DB-04` | `db.batch()` atomicity: a failing second statement leaves no first statement applied |
| `T-DB-05` | Partial uniques: re-upload, re-invite, re-add anonymised student |
| `T-DB-06` | Mark bounds: check constraint, override trigger, unknown-question branch |
| `T-DB-07` | Totals derived: sum, completeness, `needs_review` contributes nothing |
| `T-DB-08` | Metering idempotency: duplicate job attempt and duplicate export produce one row |
| `T-DB-09` | `assignment_question_id` required; a mark for a question outside the blueprint is impossible |
| `T-DB-10` | Audit immutability: UPDATE aborts; DELETE aborts outside a window, succeeds inside |
| `T-DB-11` | Scheme `version` guard: stale `If-Match` → 409, no write |
| `T-DB-12` | Settings JSON validates; unknown keys rejected |

---

## 12. Deliberately unchanged

- **UUIDv7 text keys** — correct, and a sequential id plus one missing predicate is an IDOR.
- **`workspace_id` leading every index** — still the difference between a scoped lookup and a scan.
- **404-not-403** — unchanged, and cheaper to keep correct now that illegal rows cannot exist.
- **Metadata-only D1** — the shape is right; only the arithmetic was wrong.
- **`needs_verification` distinct from `failed`** — the best domain modelling in the package.
- **One shared schema, no database-per-tenant** — the 10 GB cap and the absence of dynamic bindings still decide
  it.
