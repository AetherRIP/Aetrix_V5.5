# Threat Model

**Status:** RECOMMENDED. Method: asset inventory → trust boundaries → threat enumeration (STRIDE-style) →
mitigation matrix → residual risk. Reviewed at phase 0 and re-run at phase 10.

## 1. Assets, ranked by damage if lost

| # | Asset | Impact of compromise |
|---|---|---|
| A1 | Cross-tenant data (student names, marks) | Catastrophic: trust, contract, regulatory |
| A2 | Provider API credentials (per workspace) | High: financial loss, abuse, key revocation |
| A3 | Student personal data (minors) | High: safeguarding, legal |
| A4 | Session tokens / password hashes | High: account takeover |
| A5 | Mark integrity (silent wrong marks) | High: product promise broken |
| A6 | Script files in R2 | High: content confidentiality, copyright of exam papers |
| A7 | Audit trail | Medium: accountability, incident response |
| A8 | Availability of correction pipeline | Medium: operational, not confidential |

## 2. Trust boundaries

```
Internet ──[edge: WAF/TLS]── Worker ──[binding]── D1 / R2 / Queues / DO
                                   └──[HTTPS]── AI provider
                                   └──[OAuth]── Google Classroom
Browser (untrusted) ──────────────▶ everything above
Platform operator ──[consent grant]▶ workspace data
```

Everything inside the browser is untrusted, including anything the UI displays about permissions.

## 3. Threat matrix

| # | Threat | Vector | L | I | Mitigation | Residual |
|---|---|---|---|---|---|---|
| T1 | **Cross-workspace read** | Forged `workspaceId` in path/body/query | M | Critical | `TenantContext` minted server-side only; `workspace_id` in every predicate; membership check before handler | Low |
| T2 | **IDOR on object id** | Guessing/enumerating UUIDs | M | Critical | UUIDv7; always `id AND workspace_id`; 404 not 403 | Low |
| T3 | Broken function-level authz | Missing permission check on a new route | H | High | Deny-by-default policy; route table test asserts every route has a policy | Medium |
| T4 | Privilege escalation via role change | Admin promotes self to owner | L | High | Owner-only transfer; cannot grant above own role | Low |
| T5 | Session theft | XSS, shared device | M | High | HttpOnly+Secure+SameSite=Lax cookies, short TTL, device list + revoke, step-up for sensitive acts | Medium |
| T6 | Password brute force | Credential stuffing | H | Medium | Rate limit, lockout with backoff, Turnstile, MFA available, breach-list check on set | Low |
| T7 | Credential leakage to client | API returning `ciphertext`, logs | M | Critical | Response shapers whitelist fields; secrets never in DTOs; lint rule; test asserts absence | Low |
| T8 | Provider key exfiltration | Read D1 dump or backups | L | Critical | Envelope encryption with a Workers Secret; keys never in R2 exports; rotation path | Low |
| T9 | Malicious PDF / zip bomb | Upload | M | High | MIME + magic-byte check, size/page caps, sandboxed parse, no server-side macro execution, quarantine state | Medium |
| T10 | Stored XSS via filenames/comments | Any user text | M | High | Escape on render, sanitise markdown subset, CSP without inline script | Low |
| T11 | CSRF on state-changing routes | Cross-site form post | M | High | SameSite cookies + Origin check + custom header requirement on mutations | Low |
| T12 | SQL injection | String-built SQL | L | Critical | Bound parameters only; no dynamic SQL from user input; lint ban on template literals in queries | Low |
| T13 | SSRF via URL ingestion | "Import from URL" feature | L | High | Feature not exposed; if added, allowlist scheme/host, no metadata endpoints | Low |
| T14 | Queue/job authorization | Crafted `jobId` in a message | L | High | Workers only enqueue; consumer re-reads job and asserts `workspace_id` | Low |
| T15 | Replay of a job message | At-least-once delivery | M | Medium | Idempotency key + lease claim + versioned persist | Low |
| T16 | WebSocket without auth | Direct DO connect | M | High | Single-use 30 s HMAC ticket; DO validates; per-message permission recheck | Low |
| T17 | Cross-tenant export | `d1 export --table` misuse | L | Critical | Export only via workflow with `WHERE workspace_id`; CLI export banned in runbook | Low |
| T18 | Support-access abuse | Operator reads customer data | M | High | Consent grant, scope, ≤72 h expiry, per-read audit, workspace-visible banner | Medium |
| T19 | Audit log tampering | Insider or bug | L | High | Append-only table, no UPDATE/DELETE grants in app code; platform audit separate | Low |
| T20 | Data resurrection after deletion | Late job recreates rows | M | Medium | Soft-delete → cancel jobs → purge → tombstone hash | Low |
| T21 | Log leaks PII | Debug logging | H | High | Structured logging with field allowlist; no bodies, no filenames, no tokens; redaction test | Medium |
| T22 | Backup exposure | Public R2 bucket | L | Critical | Private buckets; signed URLs only; no `r2.dev`; separate credentials | Low |
| T23 | Denial of wallet | Runaway AI jobs | M | High | Per-workspace quotas, per-job budget, metering, alerts, kill switch | Medium |
| T24 | Supply chain | Malicious dependency | M | High | Lockfile, provenance, minimal deps, no postinstall scripts in CI | Medium |
| T25 | Tenant enumeration | Signup/invite responses | M | Medium | Generic "check your email" responses; invite acceptance does not reveal workspace existence to non-recipients | Low |

L = likelihood, I = impact, both qualitative.

## 4. Threats specific to the marking domain

| Threat | Mitigation |
|---|---|
| **Silent wrong mark** (worse than an error) | Blueprint max marks enforced; missing question → `needs_review`; verification reports and never rewrites; override requires a reason; approval is a separate permission |
| **Grade published to wrong student** | Publication is per-submission, keyed by Classroom `coursework_id` + student id from the synced roster; a mismatch blocks publish (`409`) |
| **Re-mark used to hide an error** | Re-mark creates a new result revision; the previous one is retained and auditable |
| **Student data used for model training** | Provider terms must be verified; no training on customer data is a contractual requirement, not an assumption (see `DATA_PRIVACY.md` §6) |
| **Exam paper copyright** | Scripts stored privately per workspace; retention policy; export only to the workspace owner |

## 5. Residual risks we accept, with eyes open

1. **Shared-database isolation is application-enforced.** SQLite has no RLS. Compensating controls: typed
   context, lint, and a standing cross-tenant test suite. This is the strongest argument for revisiting
   Postgres if a customer demands database-enforced isolation.
2. **Malware scanning is not native to Cloudflare.** There is no first-party virus scanner for R2 objects.
   We validate type/size/structure and never execute content; a dedicated scanning service is an option, not
   an assumption.
3. **Platform operators with production access** can, in principle, reach data. Mitigated by consent grants
   and audit, not by pretending the capability does not exist.
4. **AI provider data handling** is outside our boundary; it is a contractual control, listed as an open
   question rather than asserted as compliant.

## 6. Verification of this model

- Phase 2: cross-tenant suite green (`../testing/TENANT_ISOLATION_TESTS.md`).
- Phase 5: upload abuse tests, job replay tests, credential-absence tests.
- Phase 10: external penetration test; every critical/high finding closed or explicitly accepted here.
