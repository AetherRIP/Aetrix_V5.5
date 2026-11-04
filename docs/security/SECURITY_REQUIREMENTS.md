# Security Requirements

**Status:** RECOMMENDED. Each requirement is testable; the check column names how it is verified.

## 1. Authentication

| ID | Requirement | Check |
|---|---|---|
| AU-1 | Passwords hashed with scrypt (Better Auth default) or Argon2id; never PBKDF2-SHA256 alone at low iterations | Unit + config review |
| AU-2 | Minimum 12 characters, breach-list checked, no forced composition rules, no periodic rotation | Test |
| AU-3 | Email verification required before sending invitations or API keys | E2E |
| AU-4 | MFA (TOTP) optional for all, **required** for `workspace_owner` and `platform_operator` | E2E |
| AU-5 | Passkeys supported and encouraged; at least two auth methods recommended before device loss | E2E |
| AU-6 | Sessions: 7-day idle / 30-day absolute; revocable per device; "sign out everywhere" | Test |
| AU-7 | Step-up re-authentication for: password change, MFA change, owner transfer, credential rotation, workspace deletion, support grant | E2E |
| AU-8 | Lockout after 10 consecutive failures per account with exponential backoff; per-IP rate limit | Test |
| AU-9 | Login history with IP + user agent, visible to the user | E2E |
| AU-10 | Invitations bound to the invited email; single use; 7-day expiry; revocable | Test |

## 2. Session and transport

| ID | Requirement | Check |
|---|---|---|
| SE-1 | Cookies `HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` prefix where possible | Header test |
| SE-2 | No session token in `localStorage` or any JS-readable store | Code scan |
| SE-3 | HSTS ≥ 6 months, no mixed content, TLS 1.2+ | Edge config test |
| SE-4 | CSP: no `unsafe-inline` script; `connect-src` limited to self + realtime origin; `frame-ancestors 'none'` | Header test |
| SE-5 | Mutations require same-origin or a custom header; `Origin` checked when present | Test |
| SE-6 | WebSocket upgrade requires a single-use 30 s ticket; DO validates and re-checks permissions per message | Integration test |

## 3. Authorisation

| ID | Requirement | Check |
|---|---|---|
| AZ-1 | Every route declares a permission; the policy layer denies by default | Route-table test |
| AZ-2 | `TenantContext` can only be minted from a verified session + membership | Type-level + unit |
| AZ-3 | Every object query includes `workspace_id`; 404 for cross-tenant ids | Isolation suite |
| AZ-4 | Ownership check is part of the write predicate, not a prior read | Concurrency test |
| AZ-5 | Role changes revoke affected live sockets within 30 s | Integration test |
| AZ-6 | API keys are scoped and cannot perform membership, credential or deletion actions | Test |
| AZ-7 | Platform operators cannot read tenant data without an active grant | Test |

## 4. Secrets and credentials

| ID | Requirement | Check |
|---|---|---|
| SC-1 | Provider keys encrypted with AES-GCM envelope encryption; master key in Workers Secrets only | Code review + test |
| SC-2 | Keys never returned by any endpoint, never logged, never in error messages | Contract test asserting absence |
| SC-3 | Key rotation supported without re-marking history; fingerprint recorded for display | E2E |
| SC-4 | No long-lived cloud credentials in the repo or CI output; deploy via short-lived tokens | CI review |
| SC-5 | `.env` files git-ignored; secret scanning in CI | CI job |

## 5. Input, files and output

| ID | Requirement | Check |
|---|---|---|
| IN-1 | All request bodies validated with a shared schema (zod); unknown keys rejected | Fuzz/contract tests |
| IN-2 | SQL uses bound parameters exclusively | Lint rule + review |
| IN-3 | Uploads: max 50 MB single / 200 MB multipart, allowed MIME allowlist, magic-byte check, page cap | Test |
| IN-4 | Uploaded content is never executed or rendered as HTML; PDFs served with `Content-Disposition: attachment` unless the viewer route | Header test |
| IN-5 | User text escaped; markdown restricted to a safe subset | XSS suite |
| IN-6 | Filenames sanitised; no path traversal in R2 keys (keys are server-derived) | Test |

## 6. Logging and audit

| ID | Requirement | Check |
|---|---|---|
| LG-1 | Structured logs with a field allowlist; no bodies, tokens, filenames or student names | Log-redaction test |
| LG-2 | `requestId` propagated to responses and logs | Test |
| LG-3 | Audit entries for: auth events, role changes, invitations, credential ops, overrides, approvals, publishes, deletions, support grants | Audit test |
| LG-4 | Audit log append-only; no application path can update or delete a row | Code review + test |
| LG-5 | Audit retention 12 months (configurable), exported to R2 monthly | Ops check |

## 7. Platform / support access

| ID | Requirement | Check |
|---|---|---|
| SA-1 | No standing access to customer data for operators | Design review |
| SA-2 | Support grant requires customer owner action, names scope and reason, expires ≤ 72 h | E2E |
| SA-3 | Each read under a grant is individually audited with the operator identity | Test |
| SA-4 | An active grant shows a banner inside the workspace | E2E |
| SA-5 | Operators can suspend a workspace for abuse/safety without reading its contents | Test |
| SA-6 | Operator accounts require MFA and are IP-restricted to the corporate range where feasible | Config check |

## 8. Data protection

| ID | Requirement | Check |
|---|---|---|
| DP-1 | Encryption in transit everywhere; at rest by the platform (D1/R2) | Config attestation |
| DP-2 | R2 buckets private; no `r2.dev`; signed URLs ≤ 5 min | Test |
| DP-3 | Tenant export scoped by `workspace_id`; never a table-wide dump | Test |
| DP-4 | Deletion: 14-day grace, then batched purge + R2 prefix delete + tombstone | Drill |
| DP-5 | No production data in dev/staging; synthetic seeds only | Review |
| DP-6 | Student PII gated by `student.pii.read`; masked in lists by default | E2E |

## 9. Availability and abuse

| ID | Requirement | Check |
|---|---|---|
| AB-1 | Rate limits: auth 10/min/IP, upload-url 60/min/user, API 600/min/user | Load test |
| AB-2 | Turnstile on signup, contact, password reset | E2E |
| AB-3 | Per-workspace AI quota with a hard stop and an alert at 80% | Test |
| AB-4 | Global kill switch for outbound provider calls | Drill |
| AB-5 | Degraded-mode banner when D1 or the provider is unhealthy | Manual |

## 10. Explicit non-claims

We do **not** claim SOC 2, ISO 27001, GDPR certification or penetration-tested status until those are
actually obtained. `DATA_PRIVACY.md` distinguishes legal requirements from our engineering intent.
