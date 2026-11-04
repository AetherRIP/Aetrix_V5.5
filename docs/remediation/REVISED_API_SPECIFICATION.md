# Revised API Specification

**Status:** RECOMMENDED — supersedes `architecture/API_DESIGN.md` where they differ. Unchanged sections are
restated only where an amendment touches them.

---

## 1. What changed

| # | Original | Revised | Finding |
|---|---|---|---|
| 1 | No results collection | `GET /assignments/{id}/results` + `/summary`, `GET /classes/{id}/results` | API-01 |
| 2 | No export endpoints | `POST/GET /exports`, `/{id}`, `/{id}/download`, `DELETE` | API-02 |
| 3 | No notification endpoints | list, read, read-all, unread-count, preferences | API-03 |
| 4 | No operations read | `GET /assignments/{id}/operations`, `GET /submissions/{id}/operations` | API-04 |
| 5 | Publish bundles report attach | split into `publish` and `report/attach`; combined requires both | API-05 |
| 6 | Unbounded bulk | cap 100, whole-batch quota check | API-06 |
| 7 | `Idempotency-Key` on approvals | approvals use `If-Match`; idempotency only on create-type POSTs | API-07 |
| 8 | `quota_exceeded` = 402 | `429`, no `Retry-After` | API-08 |
| 9 | Signed download URLs | proxied `Range` downloads | FILE-3 |
| 10 | No API-key management | `GET/POST/DELETE /api-keys` | DB-02 |
| 11 | No sampling surface | `POST/GET /assignments/{id}/sample-review`, sign-off | UX-03 |
| 12 | No draft surface | `PUT/GET/DELETE /results/{id}/draft` | UX-01 |
| 13 | No job revalidation | `ETag` + `Retry-After` on job reads | DO-DEFER |

---

## 2. Conventions (retained, with three amendments)

- Base `/api/v1`; workspace in path `/api/v1/w/{slug}/…`; the slug is a **hint**, the session is the fact.
- Auth: session cookie; `Authorization: Bearer mc_live_…` for scoped keys; `X-Support-Grant: <grantId>` for
  support reads (never alone).
- **Amended:** `Idempotency-Key` is required on exactly these POSTs — `/corrections`, `/corrections/bulk`,
  `/submissions/upload-url`, `/submissions`, `/exports`, `/assignments/{id}/publish`,
  `/assignments/{id}/report/attach`. It is **not** accepted on approvals, overrides or role changes; those are
  `If-Match` operations.
- Concurrency: `If-Match: <version>` on `results`, `submissions`, `mark_schemes`, `assignments`, `classes`.
- Pagination: cursor only, default 50, max 200.
- Errors: `application/problem+json` (`type`, `title`, `status`, `detail`, `code`, `requestId`).
- No endpoint returns a credential, hash, token, raw R2 key, or `full_name` outside `full` PII level.

### 2.1 Response shape and levels

Collections `{ data, nextCursor, total? }`; objects `{ data }`. Every mutable object carries `version`.

The same route returns different **fields** by audience — this is the SEC-04 mechanism, not a variant endpoint:

| Audience | `GET /results/{id}` contains |
|---|---|
| owner/admin/supervisor | per-question marks, explanations, overrides, student identity |
| assistant (assignee) | per-question marks, explanations, display name only |
| viewer (aggregate) | totals, max, band, completion counts — **no** `questionResults`, no `explanation`, no student id |
| API key | per its scopes, never above masked |
| support grant | per grant scope, never above masked |

Documented here because a client author must know that a field can be absent by policy, and must not treat absence
as an error.

---

## 3. Errors

| Code | HTTP | When |
|---|---|---|
`unauthorized` | 401 | no/expired session |
`forbidden` | 403 | member, insufficient permission or assurance |
`not_found` | 404 | absent **or** cross-tenant **or** out of support scope |
`conflict` | 409 | state conflict |
`version_mismatch` | 409 | stale `If-Match`, body carries current version |
`already_approved` | 409 | different actor approved (body names approver) |
`incomplete_result` | 409 | approval with `needs_review` rows |
`scheme_unlocked` | 409 | marking started on an unlocked scheme |
`export_not_ready` | 409 | download before `state='succeeded'` |
`validation_failed` | 422 | schema/field error |
`mfa_enrolment_required` | 403 | role requires MFA, not enrolled |
`stepup_required` | 403 | destructive action without fresh step-up |
`rate_limited` | 429 | limiter, `Retry-After` present |
`quota_exceeded` | 429 | workspace quota, **no** `Retry-After` (waiting does not restore quota) |
`provider_unavailable` | 503 | circuit open |
`needs_verification` | 409 | remote state unknown |
`internal` | 500 | anything else, `requestId` only |

`402` is removed: there is no billing, and a workspace over its AI quota has not been asked to pay.

### 3.1 Version and idempotency semantics

| Operation | Guard | Duplicate behaviour |
|---|---|---|
| Override a mark | `If-Match` on result | second write with stale version → `409` + current marks |
| Approve | `If-Match` | same actor → `202` idempotent; different actor → `409 already_approved` |
| Publish | `If-Match` + `Idempotency-Key` | same key → same response, no second operation |
| Attach report | `Idempotency-Key` | same key → same `automation_operations` row reused |
| Create job | `Idempotency-Key` (+ job unique) | same key → `202` with the existing job id |
| Create export | `Idempotency-Key` | same key → existing export |

`202` rather than `200` for the idempotent approval replay because approval is asynchronous in effect (it queues
notifications and may trigger publish-readiness checks); the client already treats both as success.

---

## 4. Auth and account (retained; additions marked)

| Method | Path | Purpose | Permission | Assurance |
|---|---|---|---|---|
| POST | `/auth/signup` | Create account | – | – |
| POST | `/auth/login` | Password / passkey / Google | – | – |
| POST | `/auth/mfa/verify` | Second factor | session | – |
| POST | `/auth/logout` | End session | session | standard |
| POST | `/auth/verify-email` · `/auth/forgot` · `/auth/reset` | Email flows | – | – |
| GET | `/auth/sessions` | Devices + last IP/UA | session | standard |
| DELETE | `/auth/sessions/{id}` | Revoke one | session | mfa |
| POST | `/auth/sessions/revoke-all` | Sign out everywhere | session | stepup |
| GET · PATCH | `/me` | Profile | session | standard |
| POST | `/me/export` | Subject export | session | mfa |
| DELETE | `/me` | Deactivate | session | stepup |
| **POST** | **`/auth/invitations/{token}/accept`** | Accept invitation | – | – |

`/auth/invitations/{token}/accept` returns **one** generic failure for unknown, expired, revoked and
wrong-email tokens (`404 invitation_unavailable`), and the same for a signed-in user with a different verified
email. It succeeds only when the token is valid *and* the session's verified email matches.

---

## 5. Results, matrix and review

| Method | Path | Purpose | Permission |
|---|---|---|---|
| GET | `/w/{slug}/results/{id}` | One result; fields per audience (§2.1) | `correction.result.read` |
| PATCH | `/w/{slug}/results/{id}/questions/{no}` | Override one mark (`If-Match`) | `correction.override` |
| POST | `/w/{slug}/results/{id}/approve` | Approve (`If-Match`) | `correction.approve` |
| POST | `/w/{slug}/results/{id}/reopen` | Reopen | `correction.override` |
| **GET** | **`/w/{slug}/assignments/{id}/results`** | Totals per student, cursor | `correction.result.read` |
| **GET** | **`/w/{slug}/assignments/{id}/results/summary`** | Aggregates, distribution, outliers | `report.read` |
| **GET** | **`/w/{slug}/classes/{id}/results?assignmentId=`** | Cross-assignment totals | `report.read` |
| **PUT** | **`/w/{slug}/results/{id}/draft`** | Autosave review draft | `correction.override` |
| **GET · DELETE** | **`/w/{slug}/results/{id}/draft`** | Restore / discard draft | `correction.override` |
| **POST** | **`/w/{slug}/assignments/{id}/sample-review`** | Select a sample | `correction.sample` |
| **GET** | **`/w/{slug}/assignments/{id}/sample-review`** | Coverage + items | `correction.sample` |
| **POST** | **`/w/{slug}/sample-review/{itemId}/sign-off`** | Record a review | `correction.sample` |

### 5.1 Results list contract

```json
{ "data": [{ "submissionId": "...", "student": { "id": "...", "displayName": "A. Smith" },
             "totalMarks": 34, "maxMarks": 40, "band": "B",
             "status": "approved", "isComplete": true,
             "markedQuestions": 12, "totalQuestions": 12 }],
  "nextCursor": "..." }
```

Totals only — no per-question payload. `student` is omitted for `aggregate` level and reduced to
`{ displayName }` for `masked`. Page size is enforced server-side; a `limit` above 200 is `422`, not clamped
silently.

### 5.2 Summary contract

`count`, `mean`, `median`, `distribution` (bands), `outliers` (results more than 2σ from the mean),
`suppressedGroups` (count of groups below 5 that were suppressed). Every aggregate respects the minimum group
size; a single-student "group" is impossible to request.

### 5.3 Bulk correction

`POST /w/{slug}/corrections/bulk` accepts at most **100** `submissionId`s. The quota check runs **once** for the
whole batch, before any job is created, and the batch is all-or-nothing: if the workspace cannot afford 100
calls, nothing is enqueued and the response is `429 quota_exceeded` with `required`/`available`. This closes the
partial-batch budget hole (API-06).

### 5.4 Approval decision (C2)

| Case | Response |
|---|---|
| Same actor, same result | `202` + existing approval, no new row |
| Different actor | `409 already_approved` + `{ approvedBy: { name }, approvedAt }` |
| `needs_review` rows present | `409 incomplete_result` + review row ids |
| Stale `If-Match` | `409 version_mismatch` + current marks |

The UI state "Approved by J. Patel, 2 minutes ago" is the point of the distinction; without it, two people
believe they signed off.

---

## 6. Notifications

| Method | Path | Purpose | Permission |
|---|---|---|---|
| GET | `/w/{slug}/notifications?cursor=&unreadOnly=` | Inbox, own rows only | `notification.read` |
| POST | `/w/{slug}/notifications/{id}/read` | Mark one | `notification.read` |
| POST | `/w/{slug}/notifications/read-all` | Mark all (own) | `notification.read` |
| GET | `/w/{slug}/notifications/unread-count` | Badge; cacheable 10 s | `notification.read` |
| GET · PATCH | `/w/{slug}/notification-preferences` | Per-kind channel | `notification.preferences` |

Every query is `WHERE workspace_id = ? AND user_id = ?` — the filter is in the SQL, not in a transport layer
(SEC-06). There is no workspace-broadcast notification endpoint, and no response ever contains another user's
notification payload.

Preferences are `(kind, channel)` with `channel ∈ in_app|email|both|none`; security notifications (password
changed, new device, grant created) are not suppressible and are excluded from the preference model.

---

## 7. Exports

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/w/{slug}/exports` | Request export | `workspace.export` |
| GET | `/w/{slug}/exports?cursor=` | List, own workspace | `workspace.export` |
| GET | `/w/{slug}/exports/{id}` | State, manifest, row counts, expiry | `workspace.export` |
| GET | `/w/{slug}/exports/{id}/download` | `302` to a 5-minute signed URL | `workspace.export` |
| DELETE | `/w/{slug}/exports/{id}` | Revoke early | `workspace.export` |

Request body `{ kind: 'workspace'|'assignment'|'class', targetId? }`. Response `202 { exportId, state }`.

Rules: implemented only as the Workflow described in `MULTI_TENANCY.md` §7 as amended; the Workflow takes
`(workspaceId, exportId)` and each step re-asserts the workspace from the row; the archive contains a
`manifest.json` with per-table row counts and per-file SHA-256; the download URL is single-use, 5 minutes, and
each issue writes an audit row. `viewer` cannot call these (it may request an **aggregate** export through
`report.export`, which produces a summary CSV with no identifiers).

---

## 8. Publishing and Classroom

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/w/{slug}/assignments/{id}/publish` | Publish grades + return | `correction.approve` |
| POST | `/w/{slug}/assignments/{id}/report/attach` | Attach report to Classroom | `report.generate` |
| GET | `/w/{slug}/assignments/{id}/operations` | Op states for the assignment | `correction.approve` |
| GET | `/w/{slug}/submissions/{id}/operations` | Op states for one script | `submission.read` |
| POST | `/w/{slug}/automation/{opId}/reconcile` | Read remote state (no writes) | `correction.approve` |

`publish` and `report/attach` are separate because they have different effects and different permissions. A
client wanting the old combined behaviour sends both requests under one `Idempotency-Key` group; the UI's
"Publish with report" action requires both permissions and shows which one is missing.

`reconcile` is **read-only by contract**: its response is the observed remote state, and the acceptance criterion
is that it performs no write (`T-API-06` asserts zero rows changed).

---

## 9. Jobs and progress (post-DO-deferral)

| Method | Path | Purpose | Permission |
|---|---|---|---|
| GET | `/w/{slug}/jobs?cursor=&status=` | List, own scope | `job.read` |
| GET | `/w/{slug}/jobs/{id}` | Job + attempts + next action | `job.read` |
| POST | `/w/{slug}/jobs/{id}/cancel` | Cancel | `correction.cancel` |
| POST | `/w/{slug}/jobs/{id}/retry` | Retry after failure | `correction.remark` |

`GET /jobs/{id}` carries `ETag` (hash of `status`, `attempts`, `step`, `updatedAt`) and
`Cache-Control: private, max-age=0, must-revalidate`. A `304` costs one cheap conditional read. When the job is
non-terminal the response includes `retryAfterMs` (the client's suggested next poll: 2 s while running, 10 s
while parked, 30 s while queued behind a backlog).

Clients poll on a ladder (2 s → 5 s → 10 s), pause when the tab is hidden, and refetch once on visibility regain.
That is the whole progress transport while `ADR-008` is deferred; the socket design is preserved in
`DURABLE_OBJECT_DEFERMENT_PLAN.md`.

`job.read` is a **new** permission: previously the job drawer reused `submission.read`, conflating "may see the
script" with "may see the pipeline". Splitting them lets a supervisor watch throughput without seeing scripts.

---

## 10. API keys

| Method | Path | Purpose | Permission |
|---|---|---|---|
| GET | `/w/{slug}/api-keys` | List (prefix, label, scopes, last used) | `apiKey.read` |
| POST | `/w/{slug}/api-keys` | Create; secret returned **once** | `apiKey.write` |
| DELETE | `/w/{slug}/api-keys/{id}` | Revoke | `apiKey.write` |

Both permissions are owner/admin-only, session-only, and `mfa` assurance. An API key can never call these
routes. Scopes are validated against the API-eligible subset at creation.

---

## 11. Support access

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/w/{slug}/support-grants` | Create a grant | `support.grant` (owner, step-up) |
| GET | `/w/{slug}/support-grants` | List grants (active + history) | `support.grant` |
| GET | `/w/{slug}/support-grants/active` | Banner state | `workspace.read` |
| DELETE | `/w/{slug}/support-grants/{id}` | Revoke | `support.grant` |

Operators read through the **same** tenant routes with `X-Support-Grant`, never through `/admin/*`. `/admin/*`
returns aggregates and metadata only.

---

## 12. Retained endpoints (unchanged)

Auth (§3 original), workspaces and members, academic, assignments and schemes, submissions and files, reports
and analytics, credentials and integrations, `/admin/*` (aggregates only). Two amendments:

- `PATCH /w/{slug}/assignments/{id}/scheme/questions/{no}` and `/scheme/lock` require `If-Match` on
  `mark_schemes.version` (`UX-04`).
- `DELETE /w/{slug}/members/{userId}` accepts `?reassignTo=<memberId>` and refuses (409) when the member has
  active assignments unless either `reassignTo` or `?unassign=true` is supplied (`UX-06`).

---

## 13. Caching, versioning, deprecation

Retained: `private, no-store` by default; tenant GETs (`/classes`, `/members`) may use `private, max-age=30` with
`ETag` **and** `Vary: Cookie`; no CDN rule may override either. `/api/v1` frozen at GA; breaking changes in
`/api/v2`; `Sunset`/`Deprecation` headers with 90 days minimum.

Added: the CI assertion (`T-API-08`) fails the build if any authenticated route omits `private` or if a
cacheable route omits `Vary`. This is the control that prevents a misconfigured "Cache Everything" rule from
turning a workspace response into a shared entry.

---

## 14. Endpoint → screen → permission

The full generated matrix lives in `UPDATED_TRACEABILITY_MATRIX.md` §2 and is a CI artefact, not a hand-written
table. The rule it enforces: **every route declares a screen and a permission; every screen in the inventory
references only routes that exist.** The three documentation contradictions this remediation closed (permission
footnotes, export, grade matrix) all existed because nothing checked that seam; now the build fails if it opens
again.

---

## 15. Not built

| Endpoint | Why not |
|---|---|
| `/w/{slug}/events/ticket`, socket upgrade | Deferred with `ADR-008`; polling covers progress |
| `POST /saved-views`, `/analytics/*` beyond overview | Cut from MVP (`UX-12`) |
| `POST /double-check` | Not built (`DOC-10`) |
| `/admin/impersonate` | Deliberately never exists — support access is the only path |
| Anything returning a credential or a raw R2 key | Never exists, at any version |
