# API Design

**Status:** RECOMMENDED. REST over `/api/v1`, JSON only, workspace-scoped by construction.

## 1. Conventions

- Base path `/api/v1`; workspace context in the path: `/api/v1/w/{slug}/…`. The slug is a **hint** — the
  session decides (see `MULTI_TENANCY.md` §4).
- Auth: session cookie (Better Auth) for the app; `Authorization: Bearer mc_…` for scoped workspace keys.
- Idempotency: `Idempotency-Key` **required** on POSTs that create jobs, uploads or publications.
- Concurrency: `If-Match: <version>` on mark/approval writes; `409 version_mismatch` with the current version.
- Pagination: cursor only (`?cursor=&limit=`), default 50, max 200. Offset pagination is banned (D1 cost).
- Errors: `application/problem+json` (RFC 9457): `type`, `title`, `status`, `detail`, `code`, `requestId`.
- Timestamps ISO-8601 UTC. Marks are numbers. No endpoint returns a credential, hash, token or raw R2 key.
- API keys carry explicit scopes (`submission:write`, `correction:start`), never a role, and can never
  manage members, credentials or delete a workspace.

## 2. Error codes (closed set)

`unauthorized` 401 · `forbidden` 403 · `not_found` 404 · `conflict` 409 · `version_mismatch` 409 ·
`validation_failed` 422 · `rate_limited` 429 · `quota_exceeded` 402 · `provider_unavailable` 503 ·
`needs_verification` 409 · `internal` 500.

## 3. Auth and account

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/auth/signup` | Create account | – |
| POST | `/auth/login` | Password or passkey | – |
| POST | `/auth/logout` | End session | session |
| POST | `/auth/verify-email` | Confirm address | – |
| POST | `/auth/forgot` · `/auth/reset` | Recovery | – |
| POST | `/auth/mfa/verify` | Step up | session |
| GET | `/auth/sessions` | List devices | session |
| DELETE | `/auth/sessions/{id}` | Revoke one | session |
| GET · PATCH | `/me` | Profile, preferences | session |
| POST | `/me/export` | Data-subject export | session |
| DELETE | `/me` | Deactivate | session |

## 4. Workspaces and members

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/workspaces` | Create workspace | – |
| GET · PATCH | `/workspaces/{slug}` | Read / settings | `workspace.read` / `.settings.write` |
| POST | `/workspaces/{slug}/transfer` | Transfer ownership | `workspace.transfer` |
| DELETE | `/workspaces/{slug}` | Request deletion | `workspace.delete` |
| POST | `/workspaces/{slug}/cancel-deletion` | Cancel grace | `workspace.delete` |
| GET | `/w/{slug}/members` | List members | `workspace.read` |
| POST · GET | `/w/{slug}/invitations` | Invite / list | `workspace.member.invite` |
| DELETE | `/w/{slug}/invitations/{id}` | Revoke invite | `workspace.member.invite` |
| POST | `/auth/invitations/{token}/accept` | Accept | – |
| PATCH | `/w/{slug}/members/{userId}` | Change role | `workspace.member.role` |
| DELETE | `/w/{slug}/members/{userId}` | Remove member | `workspace.member.remove` |
| POST · DELETE | `/w/{slug}/support-grants` | Grant / revoke operator access | `support.grant` |

## 5. Academic

| Method | Path | Purpose | Permission |
|---|---|---|---|
| GET · POST | `/w/{slug}/classes` | List / create | `academic.read` / `.write` |
| PATCH · DELETE | `/w/{slug}/classes/{id}` | Update / archive | `academic.write` |
| GET · POST | `/w/{slug}/students` | List / create | `academic.read` / `.write` |
| PATCH · DELETE | `/w/{slug}/students/{id}` | Update / delete | `academic.write` |
| POST | `/w/{slug}/students/import` | CSV: dry-run → commit | `academic.write` |
| GET | `/w/{slug}/students/export` | CSV (PII-gated) | `student.pii.read` |

## 6. Assignments and schemes

| Method | Path | Purpose | Permission |
|---|---|---|---|
| GET · POST | `/w/{slug}/assignments` | List / create | `assignment.read` / `.create` |
| GET · PATCH · DELETE | `/w/{slug}/assignments/{id}` | Read / edit / delete | `.read` / `.edit` / `.delete` |
| POST | `/w/{slug}/assignments/{id}/archive` | Archive | `assignment.archive` |
| POST | `/w/{slug}/assignments/{id}/duplicate` | Duplicate as draft | `assignment.create` |
| POST | `/w/{slug}/assignments/{id}/allocate` | Assign assistants | `assignment.allocate` |
| POST | `/w/{slug}/assignments/{id}/scheme` | Upload mark scheme, start extraction | `scheme.write` |
| GET | `/w/{slug}/assignments/{id}/scheme` | Read blueprint | `scheme.read` |
| PATCH | `/w/{slug}/assignments/{id}/scheme/questions/{no}` | Adjust a question | `scheme.write` |
| POST | `/w/{slug}/assignments/{id}/scheme/lock` | Lock blueprint | `scheme.approve` |
| POST | `/w/{slug}/assignments/{id}/scheme/reconcile` | Re-run extraction | `scheme.write` |

Behaviour: `lock` fails with `409` if extraction conflicts are unresolved; marking refuses to start on an
unlocked scheme (`409 scheme_unlocked`) rather than guessing max marks.

## 7. Submissions, jobs and results

| Method | Path | Purpose | Permission |
|---|---|---|---|
| GET | `/w/{slug}/assignments/{id}/submissions` | List (cursor) | `submission.read` |
| POST | `/w/{slug}/submissions/upload-url` | Signed upload target | `submission.upload` |
| POST | `/w/{slug}/submissions` | Register uploaded file | `submission.upload` |
| GET | `/w/{slug}/submissions/{id}` | Detail + files | `submission.read` |
| GET | `/w/{slug}/submissions/{id}/file` | 5-min signed URL | `submission.read` |
| DELETE | `/w/{slug}/submissions/{id}` | Delete | `submission.delete` |
| POST | `/w/{slug}/corrections` | Start a job | `correction.start` |
| POST | `/w/{slug}/corrections/bulk` | Start many | `correction.start` |
| GET | `/w/{slug}/jobs` | List jobs | `submission.read` |
| GET | `/w/{slug}/jobs/{id}` | Job + attempts | `submission.read` |
| POST | `/w/{slug}/jobs/{id}/cancel` | Cancel | `correction.cancel` |
| POST | `/w/{slug}/jobs/{id}/retry` | Retry after failure | `correction.remark` |
| GET | `/w/{slug}/results/{id}` | Result + per-question | `correction.result.read` |
| PATCH | `/w/{slug}/results/{id}/questions/{no}` | Override one mark | `correction.override` |
| POST | `/w/{slug}/results/{id}/approve` | Approve | `correction.approve` |
| POST | `/w/{slug}/results/{id}/reopen` | Reopen | `correction.override` |
| GET · POST | `/w/{slug}/submissions/{id}/comments` | Comments (append-only) | `comment.write` |

`POST /corrections` returns `202 { jobId, status }`. If an identical successful result exists for the same
submission and model, it returns `200` with the existing result and creates no job.

Override request: `{ awarded, reason, version }`. Server rejects `awarded > max_marks` (`422`), rejects a
stale `version` (`409` with current marks), and writes an `overrides` row plus audit entry.

## 8. Publishing, reporting, credentials, integrations

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/w/{slug}/assignments/{id}/publish` | Attach report, publish grades, return | `correction.approve` |
| POST | `/w/{slug}/automation/{opId}/reconcile` | Re-read remote state (read-only) | `correction.approve` |
| GET | `/w/{slug}/reports/class/{assignmentId}` | Report record | `report.read` |
| POST | `/w/{slug}/reports/class/{assignmentId}` | Generate PDF | `report.generate` |
| GET | `/w/{slug}/reports/{id}/download` | Signed URL | `report.read` |
| GET | `/w/{slug}/analytics/overview` | Aggregates (min group 5) | `report.read` |
| GET | `/w/{slug}/activity` | Audit list | `audit.read` |
| GET | `/w/{slug}/usage` | Metering + quotas | `workspace.usage.read` |
| GET · POST | `/w/{slug}/credentials` | List / add provider key | `credential.read` / `.write` |
| POST | `/w/{slug}/credentials/{id}/test` | Validate against provider | `credential.write` |
| POST | `/w/{slug}/credentials/{id}/rotate` | Rotate | `credential.rotate` |
| DELETE | `/w/{slug}/credentials/{id}` | Delete | `credential.write` |
| GET | `/w/{slug}/integrations/classroom` | Status + health | `integration.classroom.manage` |
| POST | `/w/{slug}/integrations/classroom/connect` | Begin OAuth | `integration.classroom.manage` |
| GET | `/callback/google` | OAuth callback (state-bound) | – |
| POST | `/w/{slug}/integrations/classroom/sync` | Sync courses/coursework | `integration.classroom.manage` |

**Credential responses never include the secret.** List returns `{ id, provider, label, fingerprint, status,
lastTestedAt, cooldownUntil }`. There is no read-back endpoint at all — rotation replaces.

## 9. Realtime and platform

| Method | Path | Purpose | Permission |
|---|---|---|---|
| POST | `/w/{slug}/events/ticket` | Mint single-use socket ticket (30 s) | `workspace.read` |
| GET | `/admin/workspaces` | Operator directory (aggregates only) | platform |
| GET | `/admin/queues` | Queue + DLQ depth | platform |
| GET | `/admin/health` | Component health | platform |
| POST | `/admin/workspaces/{id}/suspend` | Suspend for abuse/safety | platform |
| GET | `/admin/audit` | Platform audit | platform |
| POST | `/admin/support-grants/{id}/revoke` | Force-revoke | platform |

## 10. Response shaping and caching

- Collections: `{ data: [...], nextCursor, total? }`; `total` only when it is an indexed count.
- Objects: `{ data: {...} }` — never a bare array at the top level.
- Every mutable object carries `version`; every list item carries `id` and `links`.
- Authenticated responses: `Cache-Control: private, no-store`, except explicitly cacheable tenant-keyed GETs
  (e.g. class list) which use `private, max-age=30` plus an ETag.
- Offsets, `fields=` mass-assignment and `include=` graphs are **not** supported; the client asks for the
  shapes we designed.

## 11. Versioning

- `/api/v1` is frozen at GA. Breaking changes go to `/api/v2`; additive fields are allowed in v1.
- Deprecation: `Sunset` and `Deprecation` headers, 90 days minimum, announced in `/changelog`.
- Workspace API keys are per-environment and revocable independently of user sessions.
