# Security Model — Aetrix V5.5 (Checkpoints 1-2)

## 1. Objectives

1. A tenant can never read or mutate another tenant's rows.
2. A provider credential is never stored in plaintext, logged, or returned by an
   API.
3. A mark, once produced, is explainable from immutable evidence and an
   append-only audit trail.
4. A misconfigured production deployment fails at boot rather than running with
   development authentication or a default key.
5. Model output is untrusted input until deterministic checks accept it.

Checkpoints 1-2 implement 1, 2, 3, 4 and upload validation. A live Gemini
adapter exists; its bounded post-change probe was rejected at authentication, so
live structured output remains unverified. Rate limiting, malware scanning and
full prompt-injection defenses remain gaps.

---

## 2. Assets and trust boundaries

| Asset | Where it lives | Protection |
|---|---|---|
| Student answers and marked results | PostgreSQL | TLS, tenant scoping, audit; encryption at rest from Supabase |
| Blueprint and scheme content | PostgreSQL | Versioning, approval, immutable approved versions |
| Supabase JWT | Client → API | TLS; short-lived; verified signature/audience/expiry |
| Provider API keys | Encrypted column; V5 key file read-only for one smoke | Fernet; key from environment/secret store; never copied or logged |
| Database password | Untracked `.env` / secret store | Never in git or logs |
| Audit trail | PostgreSQL | Append-only trigger; content hashes |
| Benchmark references | `benchmark/` | Frozen; no production imports |

Trust boundaries:

- **Browser/client → API.** Untrusted. The API verifies a Supabase-issued JWT and
  resolves the tenant from claims or the user record.
- **API/worker → database.** Trusted service role, but every query is still
  tenant-scoped in code. RLS is not relied upon because the connection is direct.
- **Engine → provider.** Untrusted response. Provider output is parsed into a
  strict schema and validated; it never becomes a mark unchecked.
- **Operator → secrets.** Out of band. Secrets are read from the environment or
  a secret store, not from the repository.

---

## 3. Authentication

- Supabase Auth issues JWTs. The engine verifies them; it does not issue them.
- Preferred verification is JWKS (`AETRIX_AUTH__JWKS_URL`) with RS256/ES256.
  The legacy HS256 shared secret is supported only when configured, with
  `algorithms=["HS256"]`.
- `exp` and `sub` are required. Audience is checked
  (`AETRIX_AUTH__JWT_AUDIENCE`, default `authenticated`). Issuer is checked when
  configured.
- A missing or malformed `Authorization` header is 401. An invalid token is 401.
- Development mode (`AETRIX_AUTH__DEV_MODE=true`) accepts a configured
  development principal **only** when the environment is not production, and it
  requires both a dev tenant id and a dev user id. Production validation rejects
  it.
- The API never accepts a tenant id from the request body.

### Roles

| Role | Can manage exams/blueprints | Can review | Read tenant data |
|---|---:|---:|---:|
| OWNER | Yes | Yes | Yes |
| ADMIN | Yes | Yes | Yes |
| TEACHER | Yes | Yes | Yes |
| REVIEWER | No | Yes | Yes |
| VIEWER | No | No | Yes |

Roles are read from the `users` row, not trusted from a token claim. A token can
identify a subject; the database decides the role.

---

## 4. Tenant isolation

- `tenant_id` is a non-null foreign key on every tenant-owned table.
- Repositories take the tenant id explicitly and filter on it.
- A cross-tenant row looks nonexistent: 404, not 403.
- A user who exists in another tenant is rejected at principal resolution (403).
- Tests cover service-level and API-level isolation, including list endpoints.
- Supabase RLS is not the primary control. It may be added as defence in depth
  for direct PostgREST clients, but the engine's direct SQLAlchemy connection
  would not be protected by it.

**Review rule:** a new repository method that fetches by id must also require a
tenant id or be explicitly documented as a platform-level lookup.

---

## 5. Secrets and credentials

### Provider credentials

- `provider_credentials.encrypted_secret` holds a Fernet token.
- `key_fingerprint` is a truncated SHA-256; it identifies a key without
  revealing it.
- The API returns only label, fingerprint and health. It never returns the
  encrypted or decrypted value.
- Key rotation is a later phase; changing the encryption key requires a
  re-encryption procedure.

### Database and application secrets

- `backend/.env` is git-ignored. `.env.example` contains no real values.
- Production requires `AETRIX_SECURITY__ENCRYPTION_KEY` and refuses the
  development key.
- Logs redact bearer tokens, Google-style keys (`AIza...`), JWTs, long hex
  strings and keys named `password`, `secret`, `token`, `api_key`, etc.
- The API never logs request bodies, prompts or model responses.

### V5 key file

`MATH_CHECKER_V5/API_KEYS.txt` was read **read-only** for the CP2 bounded
provider probe. It must not be copied into this repository, printed, logged or
committed. The probe script prints only key count/status and token metadata; it
never prints the key. The file remains outside this repository.

---

## 6. Data protection

- Transport: TLS to Supabase and to the provider. The deployment must terminate
  TLS at the edge and reject plaintext database connections.
- At rest: Supabase encrypts the database volume; provider secrets have an
  additional application-level encryption layer.
- Backups: Supabase-managed; a restore drill is a deployment responsibility.
- Deletion: tenant deletion cascades. Audit/usage deletion remains possible for
  retention, but updates are blocked. A retention policy is not implemented in
  Phase 1.
- PII: `student_ref` is an opaque reference, not a name. Do not put student
  names or email addresses in it.

---

## 7. Audit and immutability

`audit_events`, `job_events` and `provider_usage` have `BEFORE UPDATE` triggers
that raise. Application code does not update them.

Each audit event records:

- tenant, actor type/id, action, entity type/id;
- before/after content hashes (not full content);
- a JSON detail payload with identifiers and decisions;
- request id for correlation.

Approved blueprint versions are immutable by service rule **and** by a database
trigger. The trigger rejects structural changes, approval-field changes and an
`APPROVED -> DRAFT` status regression. A new version supersedes the old one; the
old row remains readable.

**Gap:** deletion is still possible. Retention and legal-hold policy are later
phases.

---

## 8. Logging and error handling

- JSON logs include `request_id`, `tenant_id` and `job_id` when in context.
- The redaction layer is a safety net, not permission to log sensitive content.
- API errors use a closed code vocabulary and safe messages. Database exception
  text is logged server-side and never returned.
- Validation errors return locations and messages, not the submitted values.

---

## 9. Input validation and upload security

- Pydantic validates every request shape; blueprint validation is stricter than
  parsing (unique ids, sub-question sums, declared total, exclusion reasons).
- Job ids and tenant ids are UUIDs; invalid UUIDs are rejected before any query.
- Idempotency keys are length-bounded and tenant-scoped.
- The upload path checks file signature, extension, declared MIME type, byte
  size, PDF structure/encryption/page count, image decode and image pixel count.
  The signature wins over the declared type. Rejections are persisted as typed
  `REJECTED` documents, not dropped.
- Uploads are stored through the `Storage` protocol. The current adapter is the
  local filesystem, rooted under the configured storage directory; the path is
  tenant- and document-scoped.
- Still missing: malware scanning, a decompression-bomb execution sandbox,
  per-tenant upload quotas, rate limiting and content-disarm. Do not expose the
  upload endpoints publicly until those are addressed.

---

## 10. Model output is untrusted

Implemented for extraction and mapping:

- Provider responses are parsed as JSON and validated against the canonical
  `BlueprintStructure` or the approved question-id set.
- Invalid JSON or an invalid structure produces `EXTRACTION_INVALID` and creates
  no blueprint version. The usage row remains for audit.
- Page mappings cannot introduce an identifier outside the approved blueprint.
- The model cannot approve a blueprint; extraction is draft-only.

Still planned for marking (Phase 6+):

- Strict JSON schema for marking output; reject unknown or missing fields.
- Evidence must reference a page/region and a quote; a mark without evidence is
  rejected.
- A deterministic validator runs on every result: totals, criterion consistency,
  mark bounds and duplicate awards.
- SymPy verification returns EQUIVALENT, DIFFERENT or UNKNOWN. UNKNOWN triggers
  review; it never becomes DIFFERENT automatically.
- Prompt injection in a student page or scheme is treated as data. The prompt
  must delimit it, and the validator must not trust instructions found inside it.
- The engine never executes model-provided code or `eval`.

---

## 11. Rate limiting and abuse (deferred)

Phase 1 has no rate limiter. Before exposure:

- per-tenant request limits at the edge and in the API;
- per-correction provider budget and quota checks;
- upload size/concurrency limits;
- a circuit breaker for provider outages;
- alerting on repeated 401/403/409 and cross-tenant probes.

---

## 12. Incident response

1. **Suspected credential exposure:** revoke/rotate the provider key, rotate the
   database password, invalidate sessions, inspect audit and provider usage.
2. **Cross-tenant report:** preserve logs and audit rows, identify the query path,
   add a regression test, and do not delete evidence.
3. **Provider compromise or malicious output:** disable the credential, park
   affected jobs, re-run verification, and review any result that used the
   affected model version.
4. **Database corruption:** restore from a verified backup; do not attempt to
   "repair" append-only evidence by updating it.

---

## 13. Known gaps

- No malware scanning or content-disarm.
- No rate limiting or WAF configuration.
- No RLS policies (by design; direct connection).
- No key rotation/re-encryption procedure.
- No Supabase Storage adapter; only the local filesystem adapter is wired.
- No metrics/tracing/alerting.
- No retention/legal-hold tooling.
- No penetration test.
- No frontend authentication flow (frontend not built).
- No live extraction-quality claim: the post-change probe returned 503/403 and
  no draft was created.
- A credential referenced by append-only `provider_usage` cannot be deleted; it
  is disabled and its ciphertext replaced with an encrypted empty value.

---

## 14. Deployment checklist

- [ ] `AETRIX_ENV=production`
- [ ] `AETRIX_DEBUG=false`
- [ ] `AETRIX_AUTH__DEV_MODE=false`
- [ ] `AETRIX_AUTH__JWKS_URL` set (preferred) or a rotated HS256 secret
- [ ] `AETRIX_SECURITY__ENCRYPTION_KEY` set from a secret store, not the dev key
- [ ] `AETRIX_DATABASE__URL` uses TLS and a least-privilege role where possible
- [ ] CORS restricted to the frontend origin; wildcard refused
- [ ] `AETRIX_STORAGE__ROOT` points at a durable, access-controlled volume
- [ ] `AETRIX_FEATURES__LIVE_PROVIDER=true` only after credentials are provisioned
- [ ] Prompt assets are deployed with the pinned manifest and hashes
- [ ] `/ready` checked by the orchestrator; `/health` used for liveness
- [ ] API and worker run as separate processes with separate restart policies
- [ ] Logs shipped to a restricted store; no request bodies
- [ ] Backups and a restore drill verified
- [ ] Provider keys stored encrypted; fingerprints recorded
- [ ] Benchmark digests still validate in CI
