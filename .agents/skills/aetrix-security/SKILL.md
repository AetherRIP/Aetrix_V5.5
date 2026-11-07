---
name: aetrix-security
description: Security model and review checklist for Aetrix. Use when touching authentication, JWT verification, tenant isolation, RLS grants, provider credentials, file uploads, error responses, logging, secrets or frontend auth state — and whenever reviewing a change for injection, IDOR, XSS, SSRF, privilege escalation or data leakage.
license: Proprietary (Aetrix project skill)
metadata:
  author: Aetrix
  version: '1.0.0'
---

# Aetrix security

Multi-tenant school data plus an LLM boundary. Assume every request is hostile and every
document is untrusted.

## Trust boundaries

```
Browser ──Supabase Auth (PKCE, JWKS-verified JWT)──► FastAPI ──► PostgreSQL (Supabase)
                                                        └──────► Gemini REST (untrusted output)
```

- The browser holds the publishable Supabase key (public by design) and a short-lived
  access token. The service-role key never enters the frontend bundle, repo, logs or a
  prompt.
- The API resolves the tenant from the **verified claim**, then looks up the user by
  `(tenant, subject)`. A missing membership is a 403 with no workspace detail.

## Checklist for any change

**Tenancy / IDOR**
- [ ] Every query filters by `tenant_id` taken from the principal, not from input.
- [ ] A row belonging to another tenant behaves as nonexistent (404-equivalent), not
      "forbidden, owned by X".
- [ ] IDs are `uuid.UUID`, parsed and validated; no string concatenation into SQL.

**Auth**
- [ ] JWT signature, issuer, audience and expiry verified (`app/core/security.py`); no
      `verify_signature=False`, no unverified decode, no trusting `sub` from the body.
- [ ] Dev mode (`AETRIX_AUTH__DEV_MODE`) stays `false` outside explicit local testing and
      is never enabled by a path that ships.
- [ ] Frontend: `getSupabase() === null` means auth unavailable; never fabricate a session.

**Database**
- [ ] RLS/grants: `tests/integration/test_rls_guard.py` must stay green — the public schema
      is closed to `anon` and `authenticated` Data API roles.
- [ ] Append-only tables reject update/delete at the database layer.
- [ ] Migrations add constraints and grants together; no permissive default grant.

**Secrets and logging**
- [ ] Provider credentials encrypted at rest; only fingerprints and health leave the service.
- [ ] Tokens, keys, document text and student names never appear in logs, errors, prompts,
      test fixtures or commit messages.
- [ ] `.env*`, `cloudflare.env` stay untracked; only `.env.example` placeholders are committed.

**Uploads and parsing**
- [ ] Content type and magic bytes checked, size capped, PDFs parsed in a bounded way;
      a page that fails validation is persisted with its reason, not silently dropped.
- [ ] No path traversal in stored filenames; no server-side request to a caller-supplied URL.

**Provider output**
- [ ] Model output is parsed and schema-validated before use; malformed output creates no
      blueprint and leaks no upstream payload to the client.
- [ ] Prompt assets are versioned; no secrets interpolated into prompts.

**Frontend**
- [ ] No `dangerouslySetInnerHTML` on user or model content; no `eval`; no token in a URL.
- [ ] Auth callback validates the redirect target (no open redirect) and clears the auth
      fragment after exchange.
- [ ] Mutations are same-origin and CSRF-safe by construction (bearer token, no cookies).

## Review method

For a diff, run `find-bugs` and `security-review`, then `supabase-postgres-best-practices`
if SQL changed. Report findings as `file:line — class (severity) — evidence — fix`. Never
report a theoretical issue without the code path that reaches it, and never downgrade a
real finding to keep a change shippable.

## Known, accepted gaps (do not present as fixed)

Rate limiting, malware scanning, Supabase Storage, and any production deployment are
unimplemented. Say so; do not invent mitigation that is not in the code.
