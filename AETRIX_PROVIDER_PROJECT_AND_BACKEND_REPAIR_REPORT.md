# Aetrix Provider Project Distribution and Backend Connection Repair

**Date:** 9 November 2026  
**Repository:** `C:\Projects\Aetrix\Aetrix_V5.5-main`  
**Production frontend:** <https://aetrix.pages.dev>  
**Engine origin:** <https://arthur-rip-zn02.tail06bb75.ts.net>  
**Scope:** audit the 15 production Gemini keys, correct project/model capacity presentation, repair key removal, test provider management in isolation, deploy and verify.

No API key, secret, account credential or private account information is reproduced in this report.

---

## 1. Executive result

Two distinct defects were found and repaired:

1. **Key removal was not a network failure.** The engine correctly returned `204 No Content`; the browser client then called `response.json()` on the empty body. The resulting parse exception was caught by the generic network handler and displayed as “The engine could not be reached.” The client now treats `204`/`205` and an empty successful body as success, and reports a malformed successful body as a response error rather than a network error.
2. **The displayed capacity was not additive.** Aetrix applied the same project-wide usage count to every model estimate and the dashboard added the per-model remaining values into one total. The backend estimator now counts recorded usage per **project + model**, and the dashboard shows each project-model pool separately and labels the figure non-additive.

The production key inventory is unchanged: **15 rows, 15 distinct fingerprints, 15 stored `HEALTHY`, no revocations.** A read-only Google models call succeeded for **15/15** keys.

The actual Google Cloud project distribution is **UNKNOWN**, not “1 verified project.” The stored value `user-downloads-pool` is an operator-supplied grouping label. Google’s documented project lookup requires OAuth credentials with API-key-viewing permission on each owning project; no such Google Cloud identity or integration was available for keys collected from 15 different accounts.

### Overall status

| Area | Status | Meaning |
|---|---|---|
| Live key access check | **PASS** | 15/15 returned HTTP 200 from the read-only Gemini models endpoint |
| Duplicate-key check | **PASS** | 15 distinct fingerprints |
| Verified Google project identity | **BLOCKED** | No OAuth/API-keys lookup permission for the owning projects; actual identity remains `UNKNOWN` |
| Capacity grouping | **PASS** | Grouped by stored project and model; keys in one stored project do not add capacity |
| Capacity “confirmed” semantics | **PASS** | Current limits are `ESTIMATED`; no figure is labelled Google-reported |
| Removal root cause | **PASS** | Reproduced as a client-side empty-204 parse failure |
| Removal repair | **PASS** | Browser regression returns “Removal succeeded” on 204 |
| Isolated provider-management workflow | **PASS** | Full API workflow and audit records tested on disposable PostgreSQL |
| Production deployment | **PASS** | New bundle deployed and canonical origin serves it |
| Production authenticated fleet data | **PARTIAL** | Page/auth gate and engine boundary verified; no production admin session was used to read live fleet data |
| Infrastructure after work | **PASS** | `STATUS_AETRIX.bat` returned `STATUS: CONNECTED` |

---

## 2. Part A — the 15 keys

### 2.1 Stored inventory

Read-only database query, excluding ciphertext and all secret fields:

| Stored project identifier | Registered keys | Distinct fingerprints | Stored healthy | Revoked | Stored model association |
|---|---:|---:|---:|---:|---|
| `user-downloads-pool` | 15 | 15 | 15 | 0 | `gemini-3.6-flash` |

- Total credential rows: **15**
- Distinct key fingerprints: **15**
- Duplicate key rows: **none detected**
- Authentication type: **15 API keys**
- Tier: **15 `UNKNOWN`**
- Contributor-linked keys: **0**
- Disabled or invalid: **0**
- Revoked: **0**

The 15 keys are all assigned the same operator-supplied project label. That is a **stored grouping**, not a verified Google Cloud project identity.

### 2.2 Live Gemini access and models

Each stored key was decrypted only inside a local script and sent to the read-only Gemini `GET /models` endpoint. No key was printed, logged or returned in a response. No content was generated.

| Check | Result |
|---|---|
| Keys tested | 15 |
| HTTP 200 | 15 |
| Keys exposing `gemini-3.6-flash` | 15 |
| Keys exposing `gemini-3.1-pro-preview` | 15 |
| Models returned per key | 50 |
| Generation calls | 0 |
| Charges incurred | none (read-only model listing) |

A successful model listing proves that each key is accepted by Gemini and can see the configured models. It does **not** prove that two keys bill to independent projects or have independent quota. A key is an identifier for a Google Cloud project, not for an account, and separate Google accounts do not imply separate projects.

### 2.3 Actual project distribution

Google documents project lookup through:

```text
GET https://apikeys.googleapis.com/v2/keys:lookupKey?keyString=...
```

with an OAuth bearer token that has permission to view API keys in the owning project. No Google Cloud OAuth session, `gcloud` installation, or Google Cloud integration was available. The same limitation applies per key because the keys came from separate accounts.

| Project identifier | Registered keys | Healthy keys | Models | Independent quota pool |
|---|---:|---:|---|---|
| **UNKNOWN** — stored label `user-downloads-pool` | 15 | 15 | `gemini-3.6-flash`; `gemini-3.1-pro-preview` (live list) | **UNKNOWN** — not verifiable without project lookup |

**Verified unique Google Cloud projects: 0.** The system has one operator-declared pool, but the actual number could be one project, several projects, or fifteen projects. The evidence does not distinguish those cases.

Therefore the dashboard must not say “1 Google Cloud project” as though that were a verified Google fact. The presentation now says “declared project pool” and adds an explicit note that project IDs are operator-declared, not verified with Google.

---

## 3. Part B — capacity calculation

### 3.1 Original calculation

Before repair, the dashboard reported:

```text
Estimated available capacity: 374 requests
across 2 project-model combinations
```

The 374 was the sum of:

```text
gemini-3.6-flash       200 - 13 = 187
gemini-3.1-pro-preview 200 - 13 = 187
                                   ---
                                   374
```

Two problems were present:

1. **Model usage was not separated.** The request counter was project-wide and carried no model dimension, so the same 13 recorded requests were subtracted from both model pools.
2. **The models were added together in the UI.** Requests for `gemini-3.6-flash` are not interchangeable with requests for `gemini-3.1-pro-preview`. Summing them into one “available capacity” figure overstates what can be spent on either model.

The 374 figure was **not** multiplied by 15 keys. The per-project grouping was already preventing key-count multiplication. The defect was shared usage being applied to both models and the UI adding model pools.

### 3.2 Repair

Backend:

- `UsageRepository.window_stats()` now accepts an optional `model` filter.
- `QuotaEstimator.estimate()` now counts both minute and daily requests from the Aetrix usage ledger scoped to `project_id` **and** `model`.
- A flash request no longer consumes the review model’s daily pool, and vice versa.

Frontend:

- `capacityNote()` no longer sums remaining values.
- It renders each project-model pool separately and labels the result “per project-model, not additive.”
- The “1 Google Cloud projects” wording was changed to “declared project pool.”
- A footnote states that project IDs are operator-declared and unverified, and that keys assigned to the same project share one allowance.

### 3.3 Corrected live values

Read directly from the production database with the repaired estimator:

| Project label | Model | Used today | Limit | Remaining | Confidence |
|---|---|---:|---:|---:|---|
| `user-downloads-pool` | `gemini-3.6-flash` | 13 | 200 | 187 | `ESTIMATED` |
| `user-downloads-pool` | `gemini-3.1-pro-preview` | 0 | 200 | 200 | `ESTIMATED` |

The correct dashboard statement is now per model, for example:

```text
user-downloads-pool / gemini-3.6-flash: 187 left today;
user-downloads-pool / gemini-3.1-pro-preview: 200 left today
(estimated; per project-model, not additive)
```

The limits are Aetrix operator policy. They are **not** Google-reported values. Google Cloud console remains authoritative.

If the 15 keys actually belong to multiple projects, this calculation understates capacity because the stored label collapses them into one pool. It does not overstate capacity under the current data. Correctly separating them requires verified project identities, which are `UNKNOWN`.

---

## 4. Part C — the original removal failure

### 4.1 Request path

| Layer | Location/behaviour |
|---|---|
| UI action | `KeysTab` in `frontend/src/routes/_app.platform.gemini.tsx` |
| Client function | `removeKey()` in `frontend/src/lib/api/gemini.ts` |
| HTTP request | `DELETE /api/v1/admin/providers/keys/{credential_id}` |
| Authentication | `Authorization: Bearer <Supabase access token>` |
| Backend route | `delete_key()` in `backend/app/api/v1/admin_providers.py` |
| Authorization | `require_fleet_admin`; `ADMIN` or `PLATFORM_OWNER` only |
| Service | `remove_credential()` in `backend/app/services/provider_fleet.py` |
| Success response | `204 No Content` with an empty body |
| Audit | `provider.key.removed`, outcome `deleted` or `retired` |

### 4.2 Root cause

The engine and network were healthy:

- `http://127.0.0.1:8000/health` → 200
- `http://127.0.0.1:8000/ready` → 200
- public Funnel `/health` and `/ready` → 200
- CORS preflight for `DELETE` from `https://aetrix.pages.dev` → 200 with the correct allow-origin
- unauthenticated `DELETE` → 401 `UNAUTHORIZED`, proving the route is registered and protected

The failure was in `apiRequest()`:

```ts
if (!response.ok) return failure(response)
return { status: 'ok', data: (await response.json()) as T }
```

A successful delete returns no body. `response.json()` throws on the empty body. That exception was caught by the surrounding `catch`, which returned the generic message:

```text
The engine could not be reached. Check the deployment and network.
```

So the UI displayed a network-connectivity diagnosis for a successful server response. No production key was removed during this investigation.

---

## 5. Part D — repair

### 5.1 Client repair

`frontend/src/lib/api/client.ts` now:

- returns success immediately for `204` and `205`;
- treats any other successful response with an empty body as success;
- parses a non-empty successful body explicitly;
- returns “The engine returned a response that could not be read.” if a successful response is malformed, instead of claiming the engine was unreachable.

The generic network message is now reserved for actual fetch failures.

### 5.2 Security preserved

- JWT validation was not changed.
- `require_fleet_admin` authorization was not changed.
- Encrypted credential storage was not changed.
- Contributor permissions and project isolation were not changed.
- Audit logging remains on every add, validate, enable/disable and remove path.
- Backend remains bound to `127.0.0.1:8000`; PostgreSQL test access remained loopback-only.
- No API key or secret was added to logs, browser responses or source files.

---

## 6. Part E — provider-management tests

### 6.1 Test environment

Destructive tests ran against a disposable local PostgreSQL database on `127.0.0.1:55432`, with `AETRIX_TEST_DATABASE_URL` and `AETRIX_DATABASE__URL` explicitly set. The production Supabase database was never truncated or used for destructive provider tests.

No production credential was added, disabled, re-enabled or removed.

### 6.2 Workflow covered by the isolated API test

| Step | Result |
|---|---|
| Load provider overview | PASS — 200 |
| Load API keys | PASS — 200 |
| Load contributors/contributions | PASS — 200 |
| Load projects | PASS — 200 |
| Load usage | PASS — 200 |
| Load alerts | PASS — 200 |
| Add a disposable key | PASS — 201, secret absent from response |
| Disable the disposable key | PASS — `DISABLED` |
| Re-enable the disposable key | PASS — returns to `UNKNOWN` |
| Remove the disposable key | PASS — 204 with empty body |
| Verify removal from list | PASS — total returns to 0 |
| Verify audit actions | PASS — added, disabled, enabled, removed all recorded |
| Verify key never returned | PASS — key string absent from API responses |

### 6.3 Browser regression

A Playwright test intercepts the provider API with controlled data, returns `204` to the removal request, and confirms:

- the dashboard shows “Removal succeeded.”;
- the capacity copy contains the non-additive per-project-model warning;
- two model pools are not added into one figure.

The test passed locally and against the deployed canonical site.

---

## 7. Part F — security and data protection

| Requirement | Status | Evidence |
|---|---|---|
| No keys printed or logged | PASS | Scripts emitted only status, counts and model names |
| No keys in browser responses | PASS | API test asserts key string absent; existing `KeyRead` has fingerprint only |
| No credentials committed | PASS | No secret added; report contains no key |
| Encrypted storage preserved | PASS | `SecretBox` path unchanged |
| Contributor permissions preserved | PASS | No authorization code changed |
| Project isolation preserved | PASS | No tenant/project resolution changed |
| Audit logs preserved | PASS | Workflow test asserts four audit action records |
| No broad database truncation on production | PASS | Destructive tests used disposable loopback PostgreSQL only |
| No production key changes | PASS | 15 rows, 15 fingerprints, 0 revoked before and after |

---

## 8. Part G — infrastructure

`STATUS_AETRIX.bat` was executed and returned:

```text
Aetrix stack status
  mode    : tailscale
  public  : https://arthur-rip-zn02.tail06bb75.ts.net
  backend PID 14268: running
  tunnel  Tailscale Funnel: running
  worker  PID 2688: running
  monitor PID 13364: running
  [PASS] worker process
  [PASS] local /health
  [PASS] local /ready (database)
  [PASS] public /health
  [PASS] public /ready (database)
  [PASS] CORS + protected-route origin
  [PASS] deployed frontend

STATUS: CONNECTED
```

The engine was restarted through `scripts/aetrix-stack.ps1 restart` (the same script wrapped by `RESTART_AETRIX.bat`). The backend was not bound to `0.0.0.0`, no database port was exposed, and the local preview server used for Playwright was stopped afterward.

---

## 9. Part H — verification evidence

| Check | Command / observation | Result |
|---|---|---|
| Ruff | `python -m ruff check app tests` | PASS, exit 0 |
| Provider backend tests | `pytest -q tests/integration/test_provider_fleet.py` on disposable DB | **19 passed** |
| TypeScript | `tsc --noEmit` | PASS, exit 0 |
| Production build | `vite build` | PASS, exit 0 |
| Local browser regression | Playwright 204-removal test | **1 passed** |
| Deployed browser suite | `BASE_URL=https://aetrix.pages.dev` `roles.spec.ts` | **25 passed** |
| CORS preflight | `OPTIONS` DELETE from `https://aetrix.pages.dev` | 200, correct `Access-Control-Allow-Origin` |
| Unauthenticated DELETE | public Funnel | 401 `UNAUTHORIZED` |
| Local health/readiness | `127.0.0.1:8000` | 200 / 200 |
| Public health/readiness | Funnel | 200 / 200 |
| Canonical bundle | `https://aetrix.pages.dev` | `/assets/index-DOaNIrQq.js` |
| Deployment URL | Wrangler | `https://b00ced1e.aetrix.pages.dev` |
| Infrastructure | `STATUS_AETRIX.bat` | `STATUS: CONNECTED` |

The deployed canonical site and the new deployment both serve the same rebuilt bundle.

---

## 10. Changes made

- `frontend/src/lib/api/client.ts` — handle empty `204`/`205` success bodies; distinguish malformed success from network failure.
- `frontend/src/routes/_app.platform.gemini.tsx` — per-project-model capacity presentation; no summing across models; declared-project wording and unverified-project note.
- `backend/app/db/repositories.py` — optional model filter on usage aggregation.
- `backend/app/services/quota.py` — count requests per project and model using the usage ledger.
- `backend/tests/integration/test_provider_fleet.py` — regression for model-separated capacity and full provider-management API workflow.
- `frontend/tests/roles.spec.ts` — browser regression for `204` removal and non-additive capacity copy.

---

## 11. Remaining limitations

1. **Actual Google Cloud project IDs remain `UNKNOWN`.** The stored `project_id` is operator-entered. Google’s `lookupKey` route requires OAuth credentials with API-key-viewing permission on each owning project, and no such Google Cloud identity was available. No tool call can close this gap without that authorization.
2. **Project verification is not implemented in the product.** The dashboard now discloses this instead of presenting the stored label as a Google fact. A future verified-project workflow would need an authenticated Google Cloud lookup and a persisted verification result.
3. **Limits are estimates.** The 200 requests/day values are operator policy, not Google-reported quota. The UI labels them `ESTIMATED`.
4. **Model listing is not quota independence.** All 15 keys can list both models, but that does not establish whether any two keys share a Google project or quota pool.
5. **Production authenticated fleet data was not exercised.** The deployed page, role gate, engine boundary, CORS and unauthenticated rejection were verified, but no production administrator session was used to read the live fleet. The full add/disable/re-enable/remove workflow was tested against isolated state.
6. **No production key was touched.** Removal was verified with a disposable fixture; the 15 production rows remain intact by design.

---

## 12. Final statement

The backend connection was not down. The removal failure was a successful `204 No Content` being parsed as JSON and then misreported as a network error. That client path is repaired and covered by a browser regression.

The capacity display no longer multiplies capacity by key count, no longer applies one model’s usage to another model’s pool, and no longer sums non-interchangeable model allowances into a single figure. It also no longer presents the operator’s project label as a verified Google Cloud project.

The 15 production keys remain unchanged and all 15 passed a read-only Gemini access check. The true Google project distribution cannot be certified from the available credentials and is therefore reported as `UNKNOWN`, not as one verified project.
