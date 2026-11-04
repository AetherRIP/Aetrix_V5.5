# Multi-Tenant Security Audit

**Audit date:** 2026-11-03 · **Priority:** highest · **Method:** attempt to read or write another workspace's
data through every channel the design exposes, then test whether the stated controls actually exist.

Nothing here asserts the system is insecure; it asserts that specific controls are **specified but not
implemented, not enforceable, or not where the document claims**. Original documents unchanged.

## 0. Verdict in one line

The isolation *model* is sound and unusually well thought through. The isolation *implementation surface* has
four gaps that will become real defects if built exactly as documented: the identity schema does not match the
library, the enforcement is application-only, one permission class cannot be expressed, and the support-access
path — the one deliberate cross-tenant door — is unspecified at the point where it matters.

## 1. Attack scenarios and findings

### SEC-01 — HIGH — The support-grant path bypasses membership and is never specified
**Documents:** `SECURITY_REQUIREMENTS.md` §7, `MULTI_TENANCY.md` §2, `API_DESIGN.md` §4.

**Problem.** `TenantContext` is minted only after a **membership** row resolves. A platform operator has no
membership by design (`platform_operator` "does not imply membership"). The documents never say how a granted
read therefore obtains a context: whether the grant replaces the membership check, whether the context is marked
`support: true`, how it is revoked mid-request, or how a granted 200 is distinguished from a leaked 200 in logs.

**Evidence.** `support_grants(id, ws, operator_id, scope, reason, expires_at, revoked_at, created_at)` exists in
the schema, and `SA-3` requires per-read auditing, but no route, middleware branch, or context variant appears in
`API_DESIGN.md` or `MULTI_TENANCY.md`.

**Consequence.** This is the highest-privilege path in the product and the one most likely to be implemented
under time pressure as a session flag (`isSupport: true`) that then applies to *all* workspaces. That single
shortcut converts a bounded feature into a standing cross-tenant read capability — the failure mode `SA-1`
exists to prevent.

**Resolution.** Specify it as a first-class context variant: `resolveTenant` accepts a grant **id** (not a flag),
the grant row is re-read on every request, the context carries `{ supportGrantId, scope[], expiresAt }`, scope is
checked per permission key (not per route), every read writes an audit row inside the same `db.batch()`, and a
grant can only be created by the workspace owner. Add a test: an operator with a grant scoped
`results:read` calling `GET /submissions/{id}/file` gets 404.

**Owner approval:** Required — this is a new architectural component.

### SEC-02 — HIGH — MFA is required by policy but not achievable by configuration
**Documents:** `SECURITY_REQUIREMENTS.md` AU-4, `USER_ROLES_AND_PERMISSIONS.md` §5.

**Problem.** `AU-4` requires TOTP MFA for `workspace_owner` and `platform_operator`. Better Auth's 2FA plugin
gates only `/sign-in/email`, `/sign-in/username` and `/sign-in/phone-number`; **passkey, OAuth/social, magic
link, email-OTP and anonymous sign-ins are not gated by default**. `AU-5` simultaneously encourages passkeys.

**Evidence.** Better Auth 2FA documentation (plugins/2fa, 2026): the challenge is wired to password sign-in
routes; other methods require custom hooks.

**Consequence.** A UI that offers "Sign in with Google" gives an attacker a complete bypass of the MFA
requirement for exactly the accounts that matter most, while the audit checklist reads "MFA enforced".

**Resolution.** Require `after`/`sendOTP` hooks for every enabled sign-in method, or disable social/passkey
sign-in for owner and operator roles. Add an E2E test per method: sign in with each enabled method and assert the
MFA challenge appears.

**Owner approval:** Not required (configuration + test).

### SEC-03 — HIGH — Authentication brute-force protection is absent by default on Workers
**Documents:** `SECURITY_REQUIREMENTS.md` AU-8, AB-1; `CLOUDFLARE_ARCHITECTURE.md` §7.

**Problem.** Better Auth's rate limiter is **on by default but in-memory**, which the library's own docs warn is
unsuitable for serverless. Workers isolates are per-colo and short-lived, so the counter is effectively
per-instance. The package's compensating control is an edge rule (`/auth/*` 10/min/IP), but Cloudflare allows
**one** rate-limiting rule on Free, two on Pro, five on Business — and counters are per-colo, so a distributed
credential-stuffing attempt gets N× the advertised limit.

**Consequence.** `AU-8` ("lockout after 10 consecutive failures per account with exponential backoff") is
described as a requirement with a "test" check, but nothing in the design stores per-account failure counts or
implements the backoff.

**Resolution.** Set Better Auth rate-limit `storage: "database"`; implement the per-account lockout in D1 (a
`login_failures` counter on `users`, reset on success) because a per-IP edge rule cannot express it; and state
the required Cloudflare plan tier or move per-user limiting into the Worker.

**Owner approval:** Not required (implementation), but the plan-tier statement is a purchasing decision.

### SEC-04 — HIGH — Three permission restrictions cannot be expressed by the API
**Documents:** `USER_ROLES_AND_PERMISSIONS.md` §4 footnotes ² ⁴ ⁶, `API_DESIGN.md` §7 §8.

**Problem.** The matrix promises finer control than the API can enforce:
- `student.pii.read` for `assistant` — "only students on their own assignments" (²).
- `correction.result.read` for `viewer` — "aggregates only, no per-student PII" (⁴).
- `report.export` for `viewer` — "only pre-aggregated exports, never raw PII" (⁶).

But `GET /w/{slug}/results/{id}` is protected by `correction.result.read` and returns per-question marks, and
`GET /w/{slug}/students` is protected by `academic.read` with PII masked "by default" — a presentation rule, not
an authorisation rule. There is no row-level scope concept in the policy layer at all.

**Evidence.** No endpoint in `API_DESIGN.md` carries an assignee or aggregate-only variant; the policy model is
`permission → role`, one-dimensional.

**Consequence.** Implemented literally, a `viewer` can fetch per-student marks — the exact confidentiality
control the matrix claims to provide for minors' data. This is a privacy defect with a written promise
contradicting it, which is worse than an unspecified gap.

**Resolution.** Add a second dimension to the policy function: `can(ctx, permission, resource?)` where resource
carries `{ ownerId, assigneeId, aggregate }`. Define three variants explicitly (`results:read:aggregate`,
`student:read:own-assignments`) or remove the footnotes and accept the weaker policy honestly.

**Owner approval:** Required — changes the permission model.

### SEC-05 — HIGH — Tenant consistency is not enforced by the database, and the leak runs the wrong way to be caught
**Documents:** `MULTI_TENANCY.md` §3 rule 5, `DATABASE_DESIGN.md` §5.

**Problem.** "Cross-tenant foreign keys are impossible by construction: child rows carry the parent's
`workspace_id`, and application code asserts equality on insert." That is a code convention, not a constraint.
Nothing prevents `INSERT INTO submissions (workspace_id=A, assignment_id=<belongs to B>)`. SQLite supports
`BEFORE INSERT` triggers that `RAISE(ABORT)`, and none are specified.

**Evidence.** The isolation suite tests reads and mutations **by id from the wrong workspace**, which this row
does not trigger: the row is written with `workspace_id = A`, so every scoped read in A finds it, and B never
looks for it. The suite would stay green.

**Consequence.** Silent data corruption that can surface later as a cross-tenant read the moment any query joins
without a `workspace_id` predicate (analytics, exports, reports).

**Resolution.** Add tenant-consistency triggers to every child table, plus a test that a mismatched parent FK is
rejected at write time. This is cheap and is the only database-level control available.

**Owner approval:** Not required (schema hardening).

### SEC-06 — MEDIUM — Notification payloads appear to be workspace-broadcast
**Documents:** `REALTIME_ARCHITECTURE.md` §4, `DATABASE_DESIGN.md` §5 (`notifications.user_id`).

**Problem.** Event types include `notification.created` and the DO fans out per workspace. The document filters
events by permission for job storms ("per-job events only for jobs the user can see"), but does not state that
notification content is filtered **per socket by `user_id`** before transmission.

**Consequence.** A notification such as "your access was reinstated" or a mention in a comment reaching every
connected member is a low-grade but genuine disclosure, and it is trivially prevented.

**Resolution.** Filter at the DO: only sockets whose ticket `userId` matches `notification.user_id` receive the
payload; everyone else receives at most a badge-count event.

**Owner approval:** Not required.

### SEC-07 — MEDIUM — Better Auth ships `owner`/`admin`/`member`; the product defines six roles
**Documents:** `USER_ROLES_AND_PERMISSIONS.md` §2, `ARCHITECTURE_DECISIONS.md` ADR-005.

**Problem.** The organization plugin's default roles do not include `supervisor`, `assistant` or `viewer`, and
its `hasPermission` model is separate from the product's 30-key permission list. The package never states that
custom roles must be declared in Better Auth configuration, nor that the matrix must be generated from a single
source with the policy code.

**Consequence.** Two role systems drift: the UI and API check the product policy, while Better Auth's org
endpoints (invite, remove, update-role) check its own. The first mismatch is a privilege-escalation bug.

**Resolution.** Declare the six roles as Better Auth dynamic access-control roles and generate both the matrix
table and the policy functions from one definition; add a test asserting the two agree.

**Owner approval:** Not required.

### SEC-08 — MEDIUM — Session lifetime and role-change staleness exceed the stated policy
**Documents:** `SECURITY_REQUIREMENTS.md` AU-6, `USER_ROLES_AND_PERMISSIONS.md` §5 rule 5.

**Problem.** AU-6 sets 7-day idle / 30-day absolute. OWASP's Session Management guidance recommends 2–5 minutes
idle for high-value applications and 15–30 minutes for low-risk ones, with a 4–8 hour absolute timeout for a
workday application, plus session-ID regeneration after any privilege change. Separately, the roles document
claims the server "caches membership for ≤ 60 s per session and busts it on role change" — Better Auth's cookie
cache has no per-session bust; the staleness window is `maxAge`, whatever it is set to, and the package never
sets it.

**Consequence.** A demoted or removed user retains cached role claims for the full cache window, and a stolen
session remains valid for a week of activity — for an application holding minors' marks.

**Resolution.** Set an explicit `cookieCache.maxAge` ≤ 60 s (or disable it), add an absolute lifetime enforced by
a custom session field, shorten `expiresIn`, and regenerate the session on role change. State the chosen numbers
in one place and test them.

**Owner approval:** Required (product decision on session length).

### SEC-09 — MEDIUM — The workspace export path exists in the journey but not in the API
**Documents:** `USER_JOURNEYS.md` J8, `API_DESIGN.md` §4 (only `/me/export` exists).

**Problem.** J8 promises an owner-triggered export producing a signed bundle; `MULTI_TENANCY.md` §7 describes the
Workflow. There is no endpoint, and `THREAT_MODEL.md` T17 correctly bans `d1 export --table`.

**Consequence.** The feature will be built under pressure by whoever needs it, and the ban exists precisely
because the obvious shortcut is table-wide. A rushed implementation is the most likely source of the first real
cross-tenant leak.

**Resolution.** Add `POST /w/{slug}/exports` + `GET /w/{slug}/exports/{id}` with a `report.export`-class
permission, implemented only as the documented tenant-scoped Workflow, and ship it with the isolation suite row
that counts rows per workspace in the produced archive.

**Owner approval:** Not required.

### SEC-10 — LOW — There is no cache-header regression test for tenant-private responses
**Documents:** `API_DESIGN.md` §10, `SECURITY_REQUIREMENTS.md` DP-2.

**Problem.** Authenticated responses use `private, no-store`, except tenant-keyed GETs at `private, max-age=30`
with an ETag. That is correct only if no CDN rule ever overrides it, and nothing tests it.

**Consequence.** A misconfigured "Cache Everything" rule or a missing `Vary` on a future endpoint turns a
workspace-private response into a shared cache entry — the classic multi-tenant cache poisoning incident.

**Resolution.** Add a CI assertion that every authenticated route returns `Cache-Control` containing `private`,
and that cached variants vary on `Cookie`. Include it in L3 contract tests.

**Owner approval:** Not required.

## 2. What the design gets right

- **404-not-403** is correctly chosen, correctly tested, and asserted in the response *body*, not just the status.
- **Branded `TenantContext`** is the right structural control; "it cannot be constructed from request input" is
  the correct invariant.
- **Single-use 30-second socket tickets** close the WebSocket handshake hole properly, and re-checking
  permissions per privileged message is better than most production systems.
- **The `TenantIsolationTests` harness** — two workspaces with deliberately confusable names, identical class
  names and look-alike slugs — is genuinely good test design, and the three-request pattern (read/list/mutate) is
  the right matrix.
- **Banning `d1 export --table` in the runbook** shows the author understood where the real leak risk sits.
- **Per-read auditing of support access** is the correct control; it only lacks the mechanism (SEC-01).

## 3. Residual risk after the recommended changes

| Risk | After fixes | Note |
|---|---|---|
| Application-enforced isolation | Medium | Acceptable at this scale, given triggers + type system + suite |
| Operator access | Low | Only with SEC-01 implemented as a scoped grant |
| Cache poisoning | Low | With SEC-10 test |
| Session theft | Medium | Bounded by SEC-08 changes |
| Auth library advisories | Medium | Pin ≥ 1.7.16 and track scoped packages |
