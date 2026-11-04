# Tenant Isolation Tests

**Status:** RECOMMENDED and **blocking**. This suite ships with phase 2 and never regresses. It is the
executable form of `../architecture/MULTI_TENANCY.md`.

## 1. Harness

Two seeded workspaces, deliberately confusable:

| | Alpha | Bravo |
|---|---|---|
| Slug | `alpha` | `alpha-2` |
| Owner | `owner@alpha.test` | `owner@bravo.test` |
| Class name | "Year 10 Maths" | "Year 10 Maths" |
| Assignment title | "CH1L1 Homework" | "CH1L1 Homework" |
| Student display name | "A. Smith" | "A. Smith" |

Every test authenticates as a real member of one workspace and attempts to reach the other's resources by id,
slug, query parameter, header, body field and socket.

## 2. Cross-tenant access matrix (each row = one test)

For every resource, three requests: **read by id**, **list containing the id**, **mutate by id**.

| Resource | Alpha member tries Bravo's… | Expected |
|---|---|---|
| Workspace | `GET /w/alpha-2` | 404 |
| Member | `PATCH /w/alpha/members/{bravoUserId}` | 404 |
| Invitation | `DELETE /w/alpha/invitations/{bravoInviteId}` | 404 |
| Class | `GET /w/alpha/classes/{bravoClassId}` | 404 |
| Student | `GET /w/alpha/students/{bravoStudentId}` | 404 |
| Assignment | `GET /w/alpha/assignments/{bravoAssignmentId}` | 404 |
| Scheme | `GET /w/alpha/assignments/{bravoId}/scheme` | 404 |
| Submission | `GET /w/alpha/submissions/{bravoSubmissionId}` | 404 |
| Submission file | `GET /w/alpha/submissions/{bravoId}/file` | 404, no R2 key leak |
| Result | `GET /w/alpha/results/{bravoResultId}` | 404 |
| Job | `GET /w/alpha/jobs/{bravoJobId}` | 404 |
| Report | `GET /w/alpha/reports/{bravoReportId}/download` | 404 |
| Credential | `DELETE /w/alpha/credentials/{bravoCredId}` | 404 |
| Audit | `GET /w/alpha/activity?target={bravoId}` | 200 but zero rows from Bravo |
| Comment | `POST /w/alpha/submissions/{bravoId}/comments` | 404 |
| Support grant | `POST /w/alpha/support-grants` targeting Bravo | 404 / rejected |

**Assertion detail:** the response must be `404` with the standard problem body — *not* `403`, and not a
`500`. A `403` is a failure of this test because it confirms existence.

## 3. Forgery attempts (must all fail)

| Attempt | Expected |
|---|---|
| Path slug Alpha, body `workspaceId: bravo` | Body field ignored; operation scoped to Alpha |
| Header `X-Workspace-Id: bravo` | Ignored entirely (not a supported header) |
| `?workspace=bravo` on any list | Ignored; Alpha data only |
| JWT/claims edited client-side (role → owner) | Rejected; role read from membership row |
| Session cookie of a removed member | 401 within one request |
| API key scoped `submission:read` calling `POST /members` | 403 (member of Alpha, insufficient scope) |
| API key of Alpha used against `/w/alpha-2` | 404 |
| Support operator without a grant reading a result | 404 (no membership, no grant) |
| Support operator **with** a grant reading a result | 200 + audit row naming the operator |
| Socket ticket minted for Alpha used against Bravo's DO | Upgrade rejected |
| `page`/`cursor` from another tenant's list | Empty page, never Bravo rows |
| Batch write mixing Alpha and Bravo rows | Rejected before execution |

## 4. Concurrency tests (two assistants)

**C1 — simultaneous override of the same question.**
Both read result at `version=4`. A writes (→5). B writes with `version=4` → `409 version_mismatch`, response
carries current marks. Assert: exactly one `overrides` row for that attempt, audit shows both actors with one
rejection, no lost update.

**C2 — simultaneous approval.**
A and B both approve. Assert: exactly one `approvals` row, second gets `409` (already approved) or `200`
idempotent — **decided behaviour**, documented, and tested. Recommendation: idempotent `200` if the same actor,
`409` if different, so two people cannot both believe they approved.

**C3 — publish while a mark is overridden.**
Override in flight during publish. Assert: publish uses the version it read; if the override lands first, the
publish sees the new version (or fails with `409`); a published result cannot be silently changed.

**C4 — duplicate job creation.**
Two POSTs with the same `Idempotency-Key` → one job. Two POSTs with different keys for the same submission →
second returns the existing successful result (`200`), no second provider call.

**C5 — queue redelivery.**
Same message delivered 3×. Assert: one execution (lease), one `job_attempts` row per genuine attempt only.

## 5. Data-path leakage tests

| Check | Method |
|---|---|
| R2 keys are workspace-prefixed | Static assertion on every generated key |
| Signed URL is bound to the object and expires | Decode params, assert `exp` ≤ 5 min |
| Export contains only one workspace | Count rows per workspace in the zip |
| Aggregate analytics suppress small groups | Query with a 1-row group → suppressed |
| Logs contain no student names | Canary string in a student record must not appear in captured logs |
| Error messages do not echo ids | Cross-tenant 404 body has no target id |

## 6. Regression policy

- The suite runs on every commit; a failure blocks merge.
- Any new table or route **must** add its row to §2 in the same PR — the PR template enforces it.
- A quarterly "red team" pass attempts three novel bypasses (e.g. a new endpoint, a cached response, a
  background job) and files findings as tests.

## 7. What this suite does not prove

It cannot prove that a *future* endpoint will be scoped — only that the pattern and the review checklist hold.
The mitigation is structural: the tenant-bound repository has no unscoped method to call, so a new endpoint
that forgets scoping fails to compile rather than failing a test.
