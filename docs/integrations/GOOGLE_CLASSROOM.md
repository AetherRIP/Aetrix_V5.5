# Google Classroom integration

Status: **code-complete, not live-verified.** Every Google call in this document goes
through an injectable transport that the test suite replaces. No OAuth client is
configured in this repository's environment, no consent screen has been visited and no
live Classroom course, roster, submission or grade has been read or written. Do not
describe this integration as working against Google until the procedure at the end of
this document has been carried out and recorded.

The correction engine is unchanged: `aetrix_v5_5` is still the only engine, and nothing
here marks a paper.

---

## 1. Architecture

```
                    ┌──────────────────────────────────────────┐
  Platform admin ──▶│  /api/v1/admin/classroom                 │
                    │  connection · oauth · sync · courses     │
                    └───────────────┬──────────────────────────┘
                                    │ one central Google account
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │ classroom_connections  (connection_key)   │
                    │ Fernet ciphertext, refresh, revocation    │
                    └───────────────┬──────────────────────────┘
                                    │  courses.list / rosters / coursework
                                    ▼                    / submissions / drive
                    ┌──────────────────────────────────────────┐
                    │ Google Classroom API  +  Google Drive     │
                    └───────────────┬──────────────────────────┘
                                    │
   classroom_classes ◀── discovery ─┘
          │
          │ classroom_allocations (ACTIVE = exactly one workspace)
          ▼
   Workspace teacher ──▶ /api/v1/workspaces/{id}/classroom/...
                          courses · roster · coursework · submissions · review · publish
                                    │
                                    ▼
                    Aetrix ingestion → correction job → review → approval → grade write
```

### Central account ownership

There is **one** Google authorisation for the whole platform, held in a single
`classroom_connections` row with `connection_key = 'platform'` and a NULL `tenant_id`.
Platform administration (`app_metadata.aetrix_role` = `ADMIN` or `PLATFORM_OWNER`)
is the only authority that can start, complete, refresh, sync or disconnect it. A
workspace owner is refused with `FORBIDDEN`: owning a tenant is not owning the
platform's Google account, and teachers never authorise a personal account.

The earlier per-workspace design is retired. Migration `0037_classroom_integration`
drops the per-tenant unique constraint, discards those grants' ciphertext and marks
them `RECONNECT_REQUIRED` with `last_error_code = CENTRAL_ACCOUNT_REQUIRED`. They are
kept as history; they were never the central grant.

### Layers

| Layer | Module |
|---|---|
| Google transport (only place that talks to Google) | `backend/app/services/classroom_google.py` |
| Central connection, state, refresh, discovery | `backend/app/services/classroom_oauth.py` |
| Shared authorisation and allocation guard | `backend/app/services/classroom_access.py` |
| Roster and student identity | `backend/app/services/classroom_roster.py` |
| Assignment ↔ coursework | `backend/app/services/classroom_assignments.py` |
| Submission retrieval and ingestion | `backend/app/services/classroom_submissions.py` |
| Review, approval, grade publication | `backend/app/services/classroom_grades.py` |
| HTTP contracts | `backend/app/api/v1/classroom_integration.py` |
| Platform screen | `frontend/src/routes/_app.platform.classroom.tsx` |
| Workspace screen | `frontend/src/routes/_app.classroom.tsx` |

---

## 2. OAuth setup

1. Google Cloud Console → **APIs & Services → Library**: enable **Google Classroom API**
   and **Google Drive API** on the project that owns the OAuth client.
2. **OAuth consent screen**: choose *Internal* for a Workspace-only deployment, otherwise
   *External* with the required verification. The scopes below are sensitive/restricted
   (`classroom.coursework.students`, `drive.readonly`), so an External app in *Testing*
   is limited to listed test users and cannot be used for real classes until verified.
3. **Credentials → Create credentials → OAuth client ID → Web application**.
   Authorised redirect URI must be exactly the configured `AETRIX_CLASSROOM__REDIRECT_URI`
   (for local use: `http://127.0.0.1:3000/auth/classroom`). It is never derived from a
   request `Host` header.
4. Copy the client id and secret into the backend environment (below). The secret stays
   server-side; no frontend bundle contains it.

### Environment variables

| Variable | Meaning |
|---|---|
| `AETRIX_CLASSROOM__CLIENT_ID` | OAuth client id |
| `AETRIX_CLASSROOM__CLIENT_SECRET` | OAuth client secret (SecretStr) |
| `AETRIX_CLASSROOM__REDIRECT_URI` | Exact registered redirect URI |
| `AETRIX_SECURITY__ENCRYPTION_KEY` | Fernet key used to encrypt both tokens at rest |
| `AETRIX_CLASSROOM__MAX_COURSES` | Optional discovery ceiling (default 2000) |
| `AETRIX_CLASSROOM__MAX_ROSTER_STUDENTS` | Optional per-course roster ceiling (default 5000) |
| `AETRIX_CLASSROOM__MAX_SUBMISSIONS` | Optional per-coursework ceiling (default 5000) |
| `AETRIX_CLASSROOM__MAX_ATTACHMENT_BYTES` | Largest Drive attachment fetched (default 25 MB) |
| `AETRIX_CLASSROOM__REQUEST_ATTEMPTS` | Retries for a 429/5xx (default 3) |
| `AETRIX_CLASSROOM__RETRY_BACKOFF_SECONDS` | Base backoff (default 0.5, honours `Retry-After`) |

If the client id, secret or redirect URI is absent, every Classroom route answers
`CLASSROOM_NOT_CONFIGURED` (503). Absence is a reported state, never a fake connection.

---

## 3. Scopes

Only these are requested. Each is load-bearing; none is speculative.

| Scope | Operations that need it |
|---|---|
| `classroom.courses.readonly` | `courses.list`, `courses.get` |
| `classroom.rosters.readonly` | `courses.students.list`, `courses.teachers.list` |
| `classroom.profile.emails` | `emailAddress` on a student or teacher profile |
| `classroom.coursework.students` | `courses.courseWork.create` / `.get` / `.list` / `.patch`, `courses.courseWork.studentSubmissions.list` / `.get` / `.patch`, `:return` |
| `drive.readonly` | `files.get?alt=media` for a submission attachment |
| `openid`, `userinfo.email` | `userinfo`, so an administrator can see which account is connected |

`classroom.courses.readonly` alone is not sufficient: it cannot read a roster, create
coursework or write a grade. Nothing outside this list is requested — in particular no
`classroom.courses` (write), no announcements, topics, guardians, Forms or Gmail scope.

**Missing scope handling.** On completion the granted scope string is compared against
the full required set. If any is missing the token is revoked immediately, the attempt
is recorded as a failed run with the missing scopes, and the request fails with
`CLASSROOM_SCOPE_MISSING` carrying `details.missing_scopes`. A connection whose grant
later loses a scope reports it in `GET /admin/classroom/connection.missing_scopes`.
Re-authorising (`access_type=offline`, `prompt=consent`, `include_granted_scopes=true`)
is the reconnect path; there is no partial-consent mode where an operation silently
succeeds with fewer permissions.

---

## 4. Database entities

All Classroom tables except the connection are tenant-scoped. Migration:
`backend/migrations/versions/0037_classroom_integration.py` (revises
`0036_verification_completeness`); RLS is enabled on every new table.

| Table | Purpose | Key constraints |
|---|---|---|
| `classroom_connections` | The single central grant | `UNIQUE(connection_key)`; `tenant_id` nullable; status `CONNECTED`/`RECONNECT_REQUIRED` |
| `classroom_classes` | Discovered courses (platform inventory) | `UNIQUE(course_id)`; `teacher_name` added |
| `classroom_allocations` | Course → workspace, append-only | partial `UNIQUE(classroom_class_id) WHERE status='ACTIVE'` |
| `classroom_roster_entries` | Google identity ↔ Aetrix student, per course | `UNIQUE(tenant_id, course_id, google_user_id)`, `UNIQUE(tenant_id, course_id, student_id)` |
| `classroom_coursework_links` | Aetrix assignment ↔ Classroom coursework | `UNIQUE(tenant_id, assignment_id)`, `UNIQUE(tenant_id, coursework_id)` |
| `classroom_submission_links` | External submission ↔ Aetrix submission/document | `UNIQUE(tenant_id, google_submission_id)`, `UNIQUE(tenant_id, coursework_link_id, google_user_id)` |
| `classroom_grade_publications` | Every publication attempt | state `SUCCEEDED`/`FAILED`/`UNKNOWN`/`CONFLICT` |
| `classroom_sync_runs` | Discovery, roster and submission history | `kind` `COURSES`/`ROSTER`/`SUBMISSIONS`, `status` `RUNNING`/`SUCCEEDED`/`PARTIAL`/`FAILED` |

Approval lives on `classroom_submission_links` (`approved_total`, `approved_max`,
`approved_by_subject`, `approved_by_role`, `approved_at`) plus `correction_job_id`, so a
result is traceable to its course, coursework, Google user, external submission,
workspace, assignment, internal submission, document, correction job and approval.

The migration is reversible, and both directions were executed on a throwaway
PostgreSQL 16.2 cluster: `alembic upgrade head` applies, `alembic downgrade
0036_verification_completeness` reverses, and `alembic check` reports no Classroom drift
against the models. Downgrade deletes the platform connection row (a workspace-scoped
schema has no place for it) and recreates the per-tenant constraints; it never deletes
roster, coursework, submission or publication history. If more than one retained history
row shares a workspace — only reachable by inserting rows by hand, since the application
never writes workspace-scoped connections any more — the downgrade refuses with the
conflicting workspace ids rather than letting PostgreSQL raise a duplicate-key error,
and the transaction leaves the schema at 0037.

RLS is enabled on every new table and privileges are revoked from `anon` and
`authenticated`, as 0017 and 0019 do for their tables. On the throwaway cluster a role
with `USAGE` on `public` still receives `permission denied for table
classroom_sync_runs`, and `has_table_privilege` is false for every Classroom table.

---

## 5. Course allocation

* A course becomes known by a successful central discovery (stored `VERIFIED`, source
  `google_classroom`) or by an operator recording it (`UNVERIFIED` until Google lists it).
* Platform administration allocates a known `ACTIVE` course to one active, non-demo
  workspace. The partial unique index is the database's guarantee that no two active
  allocations exist for one course, even under concurrent requests.
* Release keeps the row; reassignment releases the old row and creates a new one with
  `previous_allocation_id`. Every mutation writes a `platform_audit_events` row with
  actor, course, previous workspace, new workspace and reason.
* Reassignment never moves historical data: roster entries, coursework links, submission
  links and publications carry their own `tenant_id` and stay with the workspace that
  produced them. A new workspace receives the course and its future work.
* Teachers can neither allocate nor reassign. `require_allocation` filters on the
  verified tenant and answers `NOT_FOUND` for anything else, so an unallocated or
  cross-tenant course looks nonexistent rather than forbidden-with-detail.

---

## 6. Roster synchronization

`POST /api/v1/workspaces/{workspace_id}/classroom/courses/{course_id}/sync-roster`

* Reads `courses.students.list` with `pageSize=100`, following `nextPageToken` across
  pages up to `AETRIX_CLASSROOM__MAX_ROSTER_STUDENTS`; reaching the ceiling reports
  `truncated: true` instead of a partial list presented as complete.
* Identity is the Google user id, never the display name. Two students who share a name
  remain two students.
* Matching order, recorded in `match_source`:
  1. `EXTERNAL_ID` — an existing Aetrix student already uses the Google id as
     `student_ref`.
  2. `CREATED` — Aetrix created a student with `student_ref` = the Google id.
  3. `MANUAL` — a teacher resolved the identity through the link endpoint.
* Manual identity data is never overwritten: a sync fills a blank `display_name` and
  nothing else.
* A student absent from the latest listing is marked `REMOVED`; no roster row, student
  row, submission or result is deleted.
* Archived or deleted courses cannot be rostered (`CONFLICT`).
* Each person is upserted in a savepoint. A row that fails is counted and reported as a
  problem; the rest of the sync still commits, and the run is `PARTIAL`.

`POST .../roster/link` attaches a Google identity to an existing Aetrix student with a
stated reason. It refuses (`CONFLICT`) when the auto-created student already holds
submissions, because reassigning the identity would detach that work from its owner.
There is no UI control for this endpoint yet; it is API-only.

---

## 7. Assignment publishing

1. `POST /api/v1/workspaces/{id}/classroom/coursework` links an Aetrix assignment to an
   allocated course and stores a `DRAFT` row (title defaults to the assignment name).
2. `POST .../coursework/{link_id}/publish` creates `courses.courseWork` with
   `workType=ASSIGNMENT`, `state=PUBLISHED`, and stores the returned `coursework_id`.
3. Idempotency: a published link is returned unchanged; a link in `PUBLISHING` is refused
   with `CONFLICT`; a link in `FAILED` first lists existing coursework and adopts an
   unambiguous title match before creating anything, so a lost response cannot become a
   duplicate assignment. Ambiguous matches are refused for a person to resolve.
4. Due dates are converted from the stored instant into the course's IANA time zone
   (`courses.get.timeZone`); an unreadable zone falls back to UTC and the audit record
   says so.
5. `PATCH .../coursework/{link_id}` synchronises the supported fields only (title,
   description, due date/time, points) for a published link. Materials are not uploaded:
   Google coursework materials need Drive files and this integration does not create them.

---

## 8. Submission retrieval and ingestion

`POST .../coursework/{link_id}/submissions/sync` then, per submission,
`POST .../submissions/{link_id}/ingest` (also called inline during sync).

* Requires the coursework to be `PUBLISHED` and the roster to have been synchronised;
  otherwise `CLASSROOM_ASSIGNMENT_NOT_PUBLISHED` / `CLASSROOM_ROSTER_INCOMPLETE`.
* Deduplication is the external id: `UNIQUE(tenant_id, google_submission_id)`.
  Re-synchronising updates metadata and never re-ingests already-ingested work.
* Attachments: the first Drive file whose MIME type the ingestion pipeline accepts
  (`application/pdf`, `image/png`, `image/jpeg`) is downloaded through
  `files.get?alt=media` with a hard byte ceiling. Link, YouTube and Form attachments are
  recorded as kinds and refused with an actionable message — this integration never
  pretends to have read them.
* Ingestion calls the **existing** `DocumentService.ingest_for_submission`, so the same
  validation, page rendering, ordering and mapping apply, and the same
  `DOCUMENT_REJECTED` reasons come back. A rejection sets `INGEST_FAILED` with that
  reason and keeps the submission row.
* A student who reclaims work after it was corrected is marked `WITHDRAWN` (or, for a
  changed file, flagged that an explicit re-mark is required); nothing is silently
  overwritten.

## 9. Correction integration

`POST .../submissions/{link_id}/correct` creates a correction job through the existing
`JobService` with idempotency key `classroom:{tenant}:{google_submission_id}`. A repeat
returns the same job, so a retried synchronization or a double click cannot fan out. The
job requires the assignment's approved blueprint and mark scheme exactly as any other
job does. The job id is stored on the submission link for traceability.

Marking itself is untouched: the worker runs `aetrix_v5_5`; nothing in this integration
awards a mark. Uncertain decisions land in the existing review workflow.

> Limitation: `start_correction` uses one idempotency key per external submission, so a
> **second** marking run for the same Classroom submission is not exposed. A re-mark must
> be requested through the existing correction-job recovery path once that is extended to
> Classroom links.

---

## 10. Review, approval and grade publication

* `GET .../submissions/{link_id}/review` returns the decided total and maximum, the
  uncertain questions and whether the result is approvable. Approval requires a
  `COMPLETED` job with at least one result and no `REVIEW_REQUIRED`/`UNMARKED` or
  `review_required` question.
* `POST .../submissions/{link_id}/approve` (reviewer, administrator or platform owner
  only) records `approved_total`, `approved_max`, actor and time; the previous approval
  is preserved in the audit detail.
* `POST .../submissions/{link_id}/publish-grade` writes one field with an explicit
  confirmation, a stated reason and `updateMask`:
  * `assignedGrade` — the returned grade a student sees (default);
  * `draftGrade` — a provisional mark a teacher sees, which does not release anything.
  Optional `:return` after the write; a failed return is reported separately because the
  grade write already succeeded.
* Safeguards: an unapproved total is refused (`CLASSROOM_GRADE_NOT_APPROVED`); a total
  above `maxPoints` is refused before any request; an `assignedGrade` Google already holds
  that this integration did not write is never replaced without
  `allow_overwrite_external` (a `CONFLICT` row is recorded and nothing is written);
  publishing the same approved value twice returns the existing publication without a
  second write.
* A transient failure records `UNKNOWN` and the next attempt reads the submission from
  Google first; if Google already holds the value, that attempt is resolved as
  `SUCCEEDED` instead of writing again.
* Nothing publishes automatically, and no background job publishes grades.

Reports are associated with the right student and assignment on the Aetrix side
(assignment, submission, document, job, result). Google Classroom has no "attach a report
PDF to a returned submission" API for an app: `studentSubmissions` exposes grades, state
and attachments the student submitted. The closest supported workflow is the grade write
plus `:return`; attaching an Aetrix report file to Drive and linking it is **not**
implemented and is not claimed.

---

## 11. Error handling and quotas

| Condition | Classification | Effect on the connection |
|---|---|---|
| Token endpoint `invalid_grant` | `RECONNECT_REQUIRED` | Ciphertext discarded, status `RECONNECT_REQUIRED` |
| Token endpoint `invalid_client`/`unauthorized_client` | `CONFIGURATION` | Connection kept; `CLASSROOM_NOT_CONFIGURED` |
| 401 from an API | `RECONNECT_REQUIRED` | Ciphertext discarded |
| 403 mentioning scopes | `SCOPE_MISSING` | `CLASSROOM_SCOPE_MISSING`, reconnect |
| Other 403, 400, 404, 409, 412 | `PERMANENT` | Not retried |
| 429 or 5xx | `TRANSIENT` | Retried up to `REQUEST_ATTEMPTS`, honouring `Retry-After`, bounded by the request timeout |
| Timeout / connection error | `TRANSIENT` | Connection kept, retried later |

Every token-bearing log is avoided: logs carry identifiers, status codes and decisions,
never a token, client secret or Google response body containing one. API responses never
include a credential (a unit test asserts no Classroom contract has a `token` or `secret`
field).

Google's default Classroom quota is per-project, per-minute. With one central account
every workspace shares it: the retry policy is bounded, `pageSize=100` reduces request
counts, and a 429 parks the operation with a stated reason rather than looping. Discovery,
roster and submission syncs are all triggered explicitly, never on page load.

---

## 12. Security and tenant isolation

* Only `ADMIN`/`PLATFORM_OWNER` can read or change the connection (verified claim,
  resolved server-side).
* OAuth state is Fernet-encrypted and binds nonce, workspace, subject, platform role and
  expiry; the callback re-verifies all of them, so a state cannot be replayed, or attached
  to another account, tenant or a downgraded authority.
* Tokens are Fernet ciphertext at rest; decryption failure is treated as
  `RECONNECT_REQUIRED`, never as a usable token.
* Every workspace route resolves the tenant from the verified principal; a path workspace
  that is not the caller's is a 404.
* External ids are only ever used inside a tenant-scoped query; they never authorise.
* Publication requires a reviewer-or-higher role, explicit confirmation and a reason, and
  writes a tenant `audit_events` row plus a `classroom_grade_publications` row.
* File retrieval is a Drive download performed by the engine, bounded by size; the browser
  never receives a Drive token.

---

## 13. API summary

Platform (`platform.classroom.manage`), all under `/api/v1/admin/classroom`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/connection` | status, identity, scopes, missing scopes, last sync, recent runs |
| POST | `/oauth/start` | consent URL + expires |
| POST | `/oauth/complete` | exchange code + state |
| POST | `/sync` | discover courses |
| POST | `/disconnect` | revoke and discard |
| GET | `/courses` | discovered courses with their allocation (`q`, `limit`, `offset`) |
| GET | `/sync-runs` | course discovery history |

Workspace (`teaching` role for mutations, member for reads), under
`/api/v1/workspaces/{workspace_id}/classroom`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/courses` | allocated courses with student/coursework counts |
| GET | `/courses/{course_id}/roster` | synchronized roster |
| POST | `/courses/{course_id}/sync-roster` | roster synchronization |
| POST | `/courses/{course_id}/roster/link` | explicit identity resolution |
| GET/POST | `/coursework` | list / draft coursework |
| POST | `/coursework/{link_id}/publish` | publish to Classroom |
| PATCH | `/coursework/{link_id}` | update supported fields |
| GET | `/coursework/{link_id}/submissions` | stored submissions |
| POST | `/coursework/{link_id}/submissions/sync` | retrieve submissions |
| POST | `/submissions/{link_id}/ingest` | retry ingestion |
| POST | `/submissions/{link_id}/correct` | create the correction job |
| GET | `/submissions/{link_id}/review` | totals, uncertain questions, approvability |
| POST | `/submissions/{link_id}/approve` | approve the final result |
| GET | `/submissions/{link_id}/publication` | publication history |
| POST | `/submissions/{link_id}/publish-grade` | write the approved grade |

---

## 14. Manual live verification

Local tests prove the client's request shapes, pagination, classification, idempotency and
the approval gate. They are **not** evidence that Google accepts the configuration.
Perform the following in order, and record each result. Use a dedicated test Classroom
course and test student accounts; never real student data.

### Stage A — read-only

1. Create the OAuth client and enable both APIs (section 2). Set the three
   `AETRIX_CLASSROOM__*` values and a `AETRIX_SECURITY__ENCRYPTION_KEY`.
2. Sign in as a platform owner/administrator. Open **Platform → Google Classroom**.
   Expect `Not connected`, configured.
3. Press **Connect the central account**, complete Google's consent with every Classroom
   checkbox selected. Expect the callback to land on `/auth/classroom` and then
   `/platform/classroom` with `Connected` and the account's email.
4. Reload: the connection persists; `last_refresh_at` is set. Compare
   `granted_scopes` with the required list — `missing_scopes` must be empty.
5. Press **Synchronise courses**. Expect the real course count and names. If the account
   teaches more courses than one page holds, confirm the second page appears (check the
   count against Classroom itself).
6. Open **Platform → Allocation**, allocate the test course to a test workspace. Confirm
   it disappears from the available list and appears as allocated.
7. Sign in as a teacher in that workspace → **Google Classroom**: only this course is
   listed. Sign in to a second workspace: the course is not listed.
8. Confirm **Synchronisation history** shows the run with its actor and counts, and the
   platform audit log has `classroom.allocation_created`.

### Stage B — coursework and read-only submissions

9. As the teacher, create (or select) an Aetrix assignment with an approved blueprint and
   mark scheme, draft the coursework and publish it. Confirm exactly one coursework
   exists in Classroom.
10. Press Publish again: the same coursework id returns and no second assignment appears.
11. In Classroom, have one test student turn in a PDF. Retrieve submissions. Expect one
    row `INGESTED` with the document's page count.
12. Retrieve again: no duplicate submission link, no second document.
13. Start marking. Wait for the worker. Confirm the review screen reports the job state
    and any uncertain question.

### Stage C — grade publication (only after A–B are recorded, and only with explicit
authorisation)

14. Approve the result as a reviewer. Publish with a reason and `return_to_student`
    checked. Confirm the grade appears as the assigned grade in Classroom and the
    submission is returned.
15. Publish again: no second write occurs; the existing publication is returned.
16. Deliberately change the grade in Classroom, then publish again without
    `allow_overwrite_external`: expect `CLASSROOM_PUBLISH_CONFLICT` and no write.

---

## 15. Known limitations

* **Not live-verified.** No OAuth client exists in this environment; no Google request has
  been made from this repository.
* Grade publication is implemented but has never written a real grade here.
* A second marking run for the same Classroom submission is not exposed (see §9).
* Manual identity linking is API-only; there is no UI control for it.
* Ingestible attachments are PDF, PNG and JPEG only (the ingestion pipeline's formats).
  Google Docs/Sheets/Slides native files, Forms and YouTube attachments are recorded but
  refused with an explicit reason; converting a native Google Doc to PDF is not
  implemented.
* Coursework materials (Drive files, links, videos) are not created or attached.
* No Aetrix report file is uploaded to Google Classroom (no supported API for it).
* Roster sync does not create an Aetrix `classes` row: membership is expressed by the
  allocation plus `classroom_roster_entries`, so `students.class_id` stays NULL for
  Classroom-sourced students.
* Archived-course handling: discovery records `ARCHIVED` state and refuses to roster such
  a course. A course that disappears from Google entirely is left as recorded rather than
  guessed to be deleted.
* The integration stores no Google `courseWork` materials, rubric or Form data, because it
  never writes them.
