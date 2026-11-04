# Roles and Permissions

**Status:** RECOMMENDED · enforcement is server-side only.

## 1. Principle

A role is a **named bundle of permissions**, never a code path. Authorisation is evaluated from the
**membership row** resolved server-side on every request; the browser may *hide* a control, but hiding is
cosmetic. No workspace id, role or ownership claim from the client is ever trusted on its own.

## 2. Roles

| Role | Scope | Intent | Typical holder |
|---|---|---|---|
| `platform_operator` | Platform | Run the service; **no default access to workspace data** | You |
| `workspace_owner` | Workspace | Owns the account, members, credentials and deletion | Head of department |
| `workspace_admin` | Workspace | Runs the workspace day to day, except destruction/transfer | Department administrator |
| `supervisor` | Workspace | Owns marking quality: schemes, review, approval, reports | Senior marker / head of maths |
| `assistant` | Workspace | Marks assigned work and submits it for review | Teaching assistant |
| `viewer` | Workspace | Read-only: progress and reports, no marks, no PII by default | Observer / cover staff |

`platform_operator` is **not** a workspace role and does not imply membership. It grants platform
surfaces only; reading customer data additionally requires a time-boxed, audited **support grant**
(see `../security/SECURITY_REQUIREMENTS.md` §7).

## 3. Permission keys

Grouped by domain. Every key is checked by a policy function, and every key that touches tenant data also
requires a valid workspace membership.

| Key | Meaning |
|---|---|
| `workspace.read` | View workspace record and settings |
| `workspace.settings.write` | Rename, branding, defaults, retention settings |
| `workspace.member.invite` / `.remove` / `.role` | Membership management |
| `workspace.transfer` / `workspace.delete` | Ownership transfer, deletion (owner only) |
| `workspace.usage.read` | Storage, AI usage, quotas |
| `credential.read` / `.write` / `.rotate` | Provider API credentials (metadata only on read) |
| `integration.classroom.manage` | Connect/disconnect Classroom, choose courses |
| `academic.read` / `.write` | Terms, classes, subjects, students, bulk import/export |
| `student.pii.read` | Full student names and identifiers (separate from `academic.read`) |
| `assignment.read` / `.create` / `.edit` / `.delete` / `.archive` | Assignment lifecycle |
| `assignment.allocate` | Assign assistants, claim/reassign ownership |
| `scheme.read` / `.write` / `.approve` | Mark-scheme structure and decisions |
| `submission.read` / `.upload` / `.delete` | Submission lifecycle |
| `correction.start` / `.cancel` / `.remark` | Job control |
| `correction.result.read` | View marks, per-question breakdown, AI explanation |
| `correction.override` | Change a mark by hand (recorded) |
| `correction.approve` | Approve a corrected submission as final |
| `report.read` / `.generate` / `.export` | Reports and exports |
| `comment.write` | Comments, internal notes, mentions |
| `audit.read` | Workspace audit history |
| `support.grant` | Grant a platform operator temporary support access |

## 4. Matrix

`PO` = platform_operator (platform only), `WO` owner, `WA` admin, `SV` supervisor, `AS` assistant, `VW` viewer.

| Permission | PO | WO | WA | SV | AS | VW |
|---|---|---|---|---|---|---|
| `workspace.read` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `workspace.settings.write` | – | ✓ | ✓ | – | – | – |
| `workspace.member.invite` | – | ✓ | ✓ | – | – | – |
| `workspace.member.remove` | – | ✓ | ✓¹ | – | – | – |
| `workspace.member.role` | – | ✓ | ✓¹ | – | – | – |
| `workspace.transfer` | – | ✓ | – | – | – | – |
| `workspace.delete` | – | ✓ | – | – | – | – |
| `workspace.usage.read` | – | ✓ | ✓ | ✓ | – | – |
| `credential.read` | – | ✓ | ✓ | – | – | – |
| `credential.write` / `.rotate` | – | ✓ | ✓ | – | – | – |
| `integration.classroom.manage` | – | ✓ | ✓ | – | – | – |
| `academic.read` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `academic.write` | – | ✓ | ✓ | ✓ | – | – |
| `student.pii.read` | – | ✓ | ✓ | ✓ | ✓² | – |
| `assignment.read` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `assignment.create` / `.edit` | – | ✓ | ✓ | ✓ | – | – |
| `assignment.delete` / `.archive` | – | ✓ | ✓ | ✓ | – | – |
| `assignment.allocate` | – | ✓ | ✓ | ✓ | – | – |
| `scheme.read` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `scheme.write` | – | ✓ | ✓ | ✓ | – | – |
| `scheme.approve` | – | ✓ | ✓ | ✓ | – | – |
| `submission.read` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `submission.upload` | – | ✓ | ✓ | ✓ | ✓ | – |
| `submission.delete` | – | ✓ | ✓ | ✓ | – | – |
| `correction.start` / `.cancel` | – | ✓ | ✓ | ✓ | ✓³ | – |
| `correction.remark` | – | ✓ | ✓ | ✓ | – | – |
| `correction.result.read` | – | ✓ | ✓ | ✓ | ✓ | ✓⁴ |
| `correction.override` | – | ✓ | ✓ | ✓ | ✓⁵ | – |
| `correction.approve` | – | ✓ | ✓ | ✓ | – | – |
| `report.read` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `report.generate` | – | ✓ | ✓ | ✓ | – | – |
| `report.export` | – | ✓ | ✓ | ✓ | – | ✓⁶ |
| `comment.write` | – | ✓ | ✓ | ✓ | ✓ | – |
| `audit.read` | – | ✓ | ✓ | – | – | – |
| `support.grant` | – | ✓ | – | – | – | – |
| Platform surfaces | ✓ | – | – | – | – | – |

¹ cannot modify or remove an owner, or grant a role above their own. ² only students on their own
assignments. ³ only jobs they own or are allocated. ⁴ aggregates only, no per-student PII. ⁵ only before
approval, and recorded as an override. ⁶ only pre-aggregated exports, never raw PII.

## 5. Enforcement rules

1. **Resolve, then check.** Middleware resolves `userId` → active workspace membership → permission set.
   The route handler receives a `TenantContext`; it cannot be constructed from request input.
2. **Two checks per request:** *can this user do this action* (`permission`) **and** *in this workspace*
   (`workspace_id` on every row predicate).
3. **Deny by default.** Unlisted permission = denied. New endpoints fail closed until a policy is added.
4. **404, not 403,** for cross-tenant object access, so existence is not leaked.
5. **No permission caching in the browser.** Server caches membership for ≤ 60 s per session and busts it
   on role change, removal and invite acceptance.
6. **API keys are scoped, not role-bearing.** A workspace key carries explicit scopes (e.g.
   `submission:write`, `correction:start`) and is never able to manage members, credentials or delete.
7. **Audit every privileged action** — role change, credential rotation, deletion, support grant, override,
   approval — with actor, target, before/after, IP and request id.

## 6. Edge cases that must be decided in code, not by convention

| Case | Rule |
|---|---|
| Last owner tries to leave | Blocked; must transfer ownership first |
| Owner transfer | Owner-only, requires re-authentication, both parties notified |
| Admin promotes someone to owner | Not permitted |
| Role changed mid-session | Effective on next request; live socket is told and re-authorised |
| Removed member with an open socket | Connection closed on membership change within 30 s |
| Supervisor above owner | Not possible; supervisor cannot delete or transfer |
| Viewer with `correction.result.read` | Aggregates only; per-question marks hidden |
| Support operator without a grant | Sees metadata only; every attempt logged |
| Deactivated account with active membership | Sessions revoked; membership retained for audit |
