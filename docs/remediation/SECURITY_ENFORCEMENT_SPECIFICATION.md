# Security Enforcement Specification

**Status:** RECOMMENDED — supersedes `security/SECURITY_REQUIREMENTS.md` where they differ; the original is
unchanged and remains the requirement source. Nothing here is implemented; every row names the layer that will
enforce it.

**The rule this document exists to satisfy:** no security requirement may be enforced by a frontend, a
convention, or a document. Each row below names an **enforcement layer**, a **responsible component**, the
**data** it needs, its **failure behaviour**, and the **test** that proves it.

**Layer vocabulary**

| Layer | Meaning | Can it be bypassed by a request? |
|---|---|---|
`EDGE` | Cloudflare WAF / rate rules / headers | No, for edge-reachable traffic |
`ROUTE` | route manifest + middleware (authn, tenant resolution, assurance) | No |
`POLICY` | `can(ctx, key, resource?)` in the domain layer | No, if every route calls it |
`REPO` | tenant-bound repository (the only SQL entry point) | No, it fails to compile |
`DB` | `CHECK`, partial unique index, FK, trigger | No — this is the backstop |
`SHAPE` | response shaper with audience-derived `PiiLevel` | No, if it is the only serializer |
`CRON` | scheduled sweep | Not applicable — it is the actor |
`OPS` | runbook / configuration / process | Yes — therefore never used alone |

---

## 1. Authentication

| ID | Requirement | Layer | Component | Data | Failure behaviour | Verification | Test |
|---|---|---|---|---|---|---|---|
| AU-1 | Password hashing with scrypt (or Argon2id) | `REPO` | Better Auth `account.password` | hash params | sign-in fails closed | config review + measured CPU | `T-AUTH-01` |
| AU-2 | Min 12 chars, breach-list checked, no composition rules | `ROUTE` | sign-up validator | password | `422 weak_password` | unit + e2e | `T-AUTH-02` |
| AU-3 | Email verification before invitations or API keys | `POLICY` | `requireVerified` | `user.emailVerified` | `403 verify_email_first` | e2e | `T-AUTH-03` |
| AU-4 | MFA required for `owner`/`admin`/operator | `ROUTE` | assurance middleware (§2) | `session.amr`, `session.mfaVerifiedAt`, `user.twoFactorEnabled` | `403 mfa_enrolment_required` | per-method matrix | `T-AUTH-04…07` |
| AU-5 | Passkeys supported and encouraged | `ROUTE` | auth config | `passkey` rows | passkey sign-in unavailable, password still works | e2e | `T-AUTH-05` |
| AU-6 | Sessions: 12 h idle / 7 d absolute, revocable per device | `ROUTE` | session config + absolute check | `session.expiresAt`, `session.createdAt` | `401`, re-auth | header + time-travel test | `T-AUTH-08` |
| AU-7 | Step-up re-auth for destructive acts | `ROUTE` | `requireAssurance('stepup')` | `freshAge` + `mfaVerifiedAt` | `403 stepup_required` | e2e | `T-AUTH-14` |
| AU-8 | 10-failure lockout, exponential backoff, per-IP limit | `DB` + `ROUTE` + `EDGE` | `rate_limit` table, `user.lockedUntil`, one edge rule | counters | account locked, `429` at the edge | injected failures | `T-AUTH-11/12` |
| AU-9 | Login history (IP + UA) visible to the user | `REPO` | `session` rows | `ipAddress`, `userAgent` | history unavailable, sign-in unaffected | e2e | `T-AUTH-15` |
| AU-10 | Invitations bound to email, single-use, 7-day, revocable | `DB` | `invitation` + partial index | `email`, `status`, `expiresAt` | `410`/generic refusal | e2e | `T-AUTH-13` |

### 1.1 Explicit note on AU-4

The library's 2FA plugin gates password sign-in only. `AU-4` is therefore enforced **above** the library, by the
assurance middleware, and the library's 2FA remains the second-factor *mechanism*. This division is deliberate:
mechanism in the library, policy in our code, so a new sign-in method cannot silently escape the requirement.

---

## 2. Session, assurance and transport

| ID | Requirement | Layer | Component | Data | Failure behaviour | Verification | Test |
|---|---|---|---|---|---|---|---|
| SE-1 | `HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` prefix | `EDGE` | cookie config | cookie attributes | browser rejects cookie; sign-in loop is loud | header assertion | `T-AUTH-16` |
| SE-2 | No session token in JS-readable storage | `SHAPE` | client session store (ids only) | — | — | bundle scan | `T-AUTH-17` |
| SE-3 | HSTS ≥ 6 months, TLS 1.2+, no mixed content | `EDGE` | zone config | — | browser warning | header test | `T-OPS-06` |
| SE-4 | CSP without `unsafe-inline`; `frame-ancestors 'none'` | `EDGE` | response headers | — | page fails closed (blocked script) | header + e2e | `T-OPS-06` |
| SE-5 | Mutations require same-origin or a custom header; `Origin` checked | `ROUTE` | CSRF middleware | `Origin`, `Sec-Fetch-Site` | `403 cross_origin` | e2e | `T-AUTH-18` |
| SE-6 | Socket upgrade requires a single-use ticket (deferred with the DO) | — | — | — | not applicable while `ADR-008` is deferred | see `DO-DEFER` | — |

### 2.1 Assurance levels (the mechanism behind AU-4/AU-7)

```ts
type Assurance = 'standard' | 'mfa' | 'stepup';

// standard: a valid session
// mfa:      role not in {owner, admin, operator} OR mfaVerifiedAt within 30 min
// stepup:   session fresh (freshAge ≤ 15 min) AND TOTP re-prompted at the action
```

Applied by the route manifest, not by handler discretion: every mutating route declares its level, and a route
without a declared level does not build.

### 2.2 Session invalidation — the full matrix

| Event | Mechanism | Effective |
|---|---|---|
| Sign-out | session row deleted | immediately (DB read) |
| Revoke one device | row deleted | immediately |
| "Sign out everywhere" | all rows for the user deleted | immediately |
| Role demoted | `member.role` updated + cached-session `expiresAt` shortened + `membership.changed` event | sensitive routes immediately (cache disabled there), all routes ≤ 60 s |
| Member removed | membership `status='removed'` + session rows for that user/workspace invalidated | next request (membership re-read) |
| Password changed | all other sessions deleted | immediately |
| Account locked | `user.lockedUntil` checked at sign-in and on privilege escalation | next request |
| Workspace suspended | `organization.status` checked in tenant resolution | next request |

The 60-second figure is the **published** staleness bound (`cookieCache.maxAge`), and it is the only window in
which a stale role claim can be used. Before this remediation the bound was unset and the claim ("busts on role
change") was false.

### 2.3 Distributed authentication rate limiting

Two independent controls, because they fail differently:

1. **Library windows in D1** — `rateLimit.storage = "database"` with the `rate_limit` table. Global across
   isolates because D1 is a single writer. Protects against a distributed spray against one route.
2. **Per-account lockout in the application** — `user.failedLoginCount` / `user.lockedUntil`, exponential delay
   `min(2^n × 1 s, 15 min)`, lock at 10 consecutive failures, reset on success, owner notified. Protects one
   account against a slow, address-rotating attack that no per-IP rule can see.
3. **One edge rule** — `/auth/*` 10/min/IP. A shield, not the control; counters are per-colo, which is exactly
   why it is not relied upon.

Failure behaviour: if the D1 write for the counter fails, the request is **allowed** (auth must not fail closed
into a lockout of all users) but a `platform_audit` row records the degradation and an alert fires. This is the
one place a control degrades open, and the reason is stated rather than hidden.

---

## 3. Authorisation

| ID | Requirement | Layer | Component | Data | Failure behaviour | Verification | Test |
|---|---|---|---|---|---|---|---|
| AZ-1 | Every route declares a permission; deny by default | `ROUTE` | route manifest + policy | manifest | route not built (no declaration ⇒ no publish) | manifest test | `T-PERM-08` |
| AZ-2 | `TenantContext` minted only from verified session/API key/grant | `REPO` | `resolveTenant` | session, membership, grant, key | no context ⇒ `401`/`404` | type + unit | `T-PERM-09` |
| AZ-3 | Every object query is workspace-scoped; 404 cross-tenant | `REPO` + `DB` | repository + triggers | `workspace_id` | `404` | isolation suite | `T-ISO-01…12` |
| AZ-4 | Ownership check is inside the write predicate | `REPO` | guarded `UPDATE … WHERE id=? AND workspace_id=? AND version=?` | version | `409`/`404`, no write | concurrency test | `T-API-03` |
| AZ-5 | Role change affects live clients within 30 s | `ROUTE` | cache invalidation + polling | membership | ≤ 60 s on read routes, immediate on sensitive | integration | `T-AUTH-08` |
| AZ-6 | API keys are scoped and cannot manage members/credentials/delete | `POLICY` + `DB` | allow-list ∩ scope, deny-list after | `api_keys.scopes_json` | `403` | matrix test | `T-PERM-07` |
| AZ-7 | Operators cannot read tenant data without an active grant | `ROUTE` + `POLICY` | support context | `support_grants` | `404` | e2e | `T-AUTH-09` |

### 3.1 Field-level and record-level authorisation (the SEC-04 mechanism)

Authorisation is two-dimensional: **what** (permission key) and **which rows/fields** (scope).

| Scope kind | Semantics | Declared for | Enforcement point |
|---|---|---|---|
| `workspace` | any row in the context workspace | default | repository predicate |
| `assignee` | rows where `assignee_id` = caller's membership | `student.pii.read`, `submission.read` for `assistant` | repository predicate + list filter |
| `aggregate` | no per-row identity, no per-question detail, groups < 5 suppressed | `correction.result.read`, `report.export` for `viewer` | `SHAPE` |
| `owner` | owner-only | transfer, delete, support grant, quota write | `POLICY` |
| `self` | the caller's own rows only | `review_drafts`, `notification_preferences` | repository predicate |

`PiiLevel` is derived once per request:

```
owner | admin | supervisor  → full
assistant (assignee scope)   → masked     (display name only; full name and external ref omitted)
viewer (aggregate scope)     → aggregate  (no identifiers; totals and bands only)
api key                      → level from its scopes, never above masked
support grant                → level from grant scope, never above masked
```

`shapeResult()` and `shapeStudent()` are the **only** serializers of these entities. A handler cannot return a
raw row: the repository returns entities, the shaper returns DTOs, and the route returns DTOs.

### 3.2 Principal types and what each may do

| Principal | May read | May write | May not |
|---|---|---|---|
| `member` | per role + scope | per role + scope | nothing outside its workspace |
| `apiKey` | per scopes | per scopes | members, credentials, deletion, transfer, support, quota, keys |
| `support` | per grant scope | **nothing** | any write, any socket, any export |
| `system` (cron/queue) | any, via explicit workspace param | yes, with `actor_kind='system'` audit | must never be reachable from a request |

---

## 4. Background-job authorisation

A job is not a user, but it acts on a user's data. Rules:

1. A job carries `workspaceId` and `submissionId` from creation; the consumer **re-reads** the job row and
   asserts both, rather than trusting the message.
2. Every Workflow step re-derives the workspace from the row (`BY id AND workspace_id`), so a message tampered
   with in the queue cannot redirect a write.
3. The job's effective permission set is the **intersection** of the requesting member's permissions at creation
   time and the workspace's current feature state. A removed member's job fails with `forbidden` rather than
   continuing to spend money.
4. Provider credentials are decrypted only inside the step that calls the provider, never stored in a step's
   return value (Workflow step outputs are durable and replayable).
5. Progress events and notifications are filtered per recipient, never broadcast.

Test: `T-JOB-08` (tampered message → `404`-equivalent failure, no cross-tenant write), `T-JOB-09` (removed
member's queued job fails closed), `T-JOB-10` (a step output contains no secret).

---

## 5. Files

| ID | Requirement | Layer | Component | Data | Failure behaviour | Verification | Test |
|---|---|---|---|---|---|---|---|
| FILE-1 | Keys are server-derived `ws/{ws}/submissions/{sub}/{file}` | `REPO` | key builder | context + ids | cannot construct a foreign key | static + test | `T-FILE-03` |
| FILE-2 | Download requires `submission.read` **and** record-level scope | `POLICY` | file route | `submission_files` row | `404` | e2e | `T-FILE-04` |
| FILE-3 | Downloads are proxied with `Range`; no bearer URLs | `ROUTE` | streaming route | — | `404` | header + range test | `T-FILE-05` |
| FILE-4 | Uploads ≤ 20 MB proxied; > 20 MB presigned `PUT` with a scoped token, 15 min, single key | `ROUTE` | upload route | upload session row | `403`/`410` | e2e | `T-FILE-01/02` |
| FILE-5 | Type, size, magic bytes and page cap validated before a job can start | `ROUTE` + `CRON` | register + validation step | `submission_files` | `422`, file quarantined | e2e | `T-FILE-06` |
| FILE-6 | No `r2.dev`, no public bucket, bucket lock on the backup prefix | `OPS` + `DB` | bucket config | lock rules | object not deletable | config test | `T-BKP-03` |

**Why downloads are proxied rather than signed.** A signed URL is a bearer token: once issued, it cannot be
revoked, it works from any client, and it appears in browser history and logs. Proxying costs one Worker request
per file (egress is free, and a streamed body consumes negligible CPU) and keeps authorisation on the request
path, where revocation, role change and audit already work. Presigning is used only for large uploads, where the
alternative is buffering 200 MB through a Worker.

**Residual:** a presigned upload URL is valid for 15 minutes for one key; an attacker who obtains it can write
that one object. Mitigated by the key being single-use, the object being validated after upload, and the fact
that an unvalidated object cannot start a job.

---

## 6. Support access (the deliberate cross-tenant door)

The ten rules are specified in `CRITICAL_AND_HIGH_REMEDIATION.md` §5. Summarised as enforcement:

| Property | Mechanism | Failure behaviour |
|---|---|---|
| Consent | grant created by workspace owner | no grant ⇒ `404` |
| Identity | operator must be in `platform_operators(status='active')` | `404` |
| Scope | per-permission check against `grant.scope_json` | out of scope ⇒ `404` |
| Expiry | `expires_at ≤ created_at + 72 h`, checked per request | expired ⇒ `404` |
| Revocation | row updated; re-read per request | revoked ⇒ `404`, same request |
| Read-only | context type has no write methods | write impossible to compile |
| Audit | one `audit_log` row per read, same batch | audit write fails ⇒ read fails |
| Visibility | banner endpoint + notification above 50 rows | banner absent ⇒ grant cannot be created |
| Separation | `platform_audit` for grant lifecycle, `audit_log` for reads | both required |
| No break-glass | none exists; suspension does not grant read | — |

---

## 7. Secrets and provider credentials

| ID | Requirement | Layer | Component | Data | Failure behaviour | Test |
|---|---|---|---|---|---|---|
| SC-1 | AES-GCM envelope encryption; master key in Workers Secrets | `REPO` | credential service | `ciphertext` | decrypt fails ⇒ job fails closed, no fallback to plaintext | `T-AUTH-19` |
| SC-2 | Keys never returned, logged or echoed | `SHAPE` | credential DTO | fingerprint only | field absent by construction | `T-AUTH-20` |
| SC-3 | Rotation without re-marking history | `REPO` | rotate endpoint | fingerprint | old rows keep working (they reference results, not keys) | `T-AUTH-21` |
| SC-4 | No long-lived cloud credentials in repo/CI | `OPS` | deploy config | — | deploy fails | `T-OPS-07` |
| SC-5 | `.env` ignored; secret scanning in CI | `OPS` | CI | — | build fails | `T-OPS-07` |

---

## 8. Output, caching and logging

| ID | Requirement | Layer | Component | Failure behaviour | Test |
|---|---|---|---|---|---|
| OUT-1 | Every authenticated response `Cache-Control: private, no-store` unless explicitly cacheable | `ROUTE` | response middleware | CI fails the build | `T-API-08` |
| OUT-2 | Cacheable tenant GETs use `private, max-age=30` **and** `Vary: Cookie` | `ROUTE` | response middleware | CI fails the build | `T-API-08` |
| OUT-3 | No CDN rule may override `private` | `EDGE` | zone config + test | deployment check fails | `T-API-08` |
| LG-1 | Structured logs with a field allowlist; no bodies, names, filenames, tokens | `SHAPE` | logger | log line dropped, request continues | `T-OPS-08` |
| LG-2 | `requestId` propagated to response and every log line | `ROUTE` | request context | request fails | `T-OPS-08` |
| LG-3 | Audit entries for the eleven privileged action classes | `REPO` | audit writer | **action fails** if audit cannot be written | `T-DB-10` |
| LG-4 | Audit append-only | `DB` | triggers | `ABORT` | `T-DB-10` |
| LG-5 | Audit retained 12 months, exported monthly to R2 | `CRON` | retention sweep with maintenance window | alert on sweep failure | `T-OPS-04` |

`OUT-1`/`OUT-2` are in this document because a missing `Vary` header is a cross-tenant cache leak, not a caching
optimisation.

---

## 9. Data protection and availability

| ID | Requirement | Layer | Component | Failure behaviour | Test |
|---|---|---|---|---|---|
| DP-1 | Encryption in transit; at rest by platform | `EDGE` | zone config | connection refused | `T-OPS-06` |
| DP-2 | Private buckets, no `r2.dev`, short-lived access | `OPS` | bucket config | upload/download `403` | `T-FILE-05` |
| DP-3 | Export scoped by `workspace_id`, never a table dump | `REPO` + `CRON` | export Workflow | export fails, no partial artefact | `T-ISO-09` |
| DP-4 | Deletion: 14-day grace, batched purge, R2 prefix, tombstone | `CRON` | purge Workflow | purge halts and alerts; data retained rather than half-deleted | `T-OPS-09` |
| DP-5 | No production data in dev/staging | `OPS` | environment config | seed check fails the deploy | `T-OPS-10` |
| DP-6 | Student PII gated by `student.pii.read`; masked in lists | `SHAPE` | `shapeStudent` | field absent, not blanked | `T-PERM-02` |
| AB-1 | Rate limits (in-Worker per user; one edge rule) | `ROUTE` + `EDGE` | limiter | `429` with `Retry-After` | `T-AUTH-12` |
| AB-2 | Turnstile on signup, contact, reset | `EDGE` | widget + verify | form refuses, message explains | `T-AUTH-22` |
| AB-3 | Per-workspace AI quota with a hard stop and 80 % alert | `POLICY` | quota check inside the job-creation batch | `429 quota_exceeded`, no job created | `T-JOB-11` |
| AB-4 | Global kill switch for provider calls | `OPS` | flag in `organization`/platform config | jobs park, banner shown | `T-JOB-12` |
| AB-5 | Degraded-mode behaviour when D1 or provider is unhealthy | `ROUTE` | health + banner | static maintenance page (no D1 dependency) | `T-OPS-02` |

**Quota fail-closed, precisely.** The quota check and the job insert are in the same `db.batch()`, with the check
expressed as a conditional insert (`INSERT … SELECT … WHERE (SELECT quota_used) < quota_limit`). If the check
cannot run, the batch fails and no job is created — failing closed without a second read that could race.

---

## 10. What is still enforced by convention — and the compensating control

| Convention (unavoidable) | Why it cannot be a hard control | Compensating control |
|---|---|---|
| Application-level tenancy | SQLite has no RLS | Triggers (DB) + typed repository + isolation suite + shaper |
| New routes calling the policy | The route exists before the check does | Route manifest: no permission declaration ⇒ route not built; `T-PERM-08` |
| New tables carrying `workspace_id` | Schema evolution | Schema-enumeration test `T-DB-01` |
| Log field discipline | Strings are strings | Logger redaction + canary test `T-OPS-08` |
| Operator good faith within a grant | Personnel, not code | Scope, expiry, read-only, per-read audit, banner |
| Presigned upload URL holder | Bearer by design | 15 min, one key, post-upload validation, quarantine |

This table exists so that "enforced" is not overclaimed: six things rest on structure, and each names the test
that catches its failure.

---

## 11. Verification summary

| Family | Count | Runs |
|---|---|---|
| `T-AUTH-01…22` | 22 | Every commit (L5) + release |
| `T-PERM-01…09` | 9 | Every commit |
| `T-ISO-01…12` | 12 | Every commit, **blocking** |
| `T-FILE-01…06` | 6 | Every commit |
| `T-JOB-08…12` | 5 | Every commit |
| `T-DB-01…12` | 12 | Every commit |
| `T-OPS-02…10` | 9 | Release + drill |
| `T-API-08` | 1 | Every commit (header assertions) |

A security requirement in this document without a test id does not exist. That is the closing rule.
