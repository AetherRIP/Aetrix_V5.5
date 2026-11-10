# Google Cloud quota and usage synchronisation

**Status: implemented, not live-verified.** No Google Cloud credential was
available while this was built, so every API response path is covered by mocked
tests only. No API was enabled, no IAM role was granted, and no quota, billing,
key or project configuration was changed.

This integration is read-only. It reads project identity, quota definitions,
consumer-quota usage and enabled services. It has no code path that increases a
quota, enables billing or an API, creates or deletes a key, or edits IAM.

## What it is not

- A Gemini API key is **not** a Google Cloud IAM credential. The parser accepts
  only `"type": "service_account"` and rejects authorised-user/external-account
  documents. No Gemini key is read by this integration.
- It does not replace Aetrix's own quota estimator. The Overview tab still shows
  Aetrix policy limits and Aetrix-recorded usage. Google-reported values live on
  the new **Google quota** tab and never silently become Aetrix limits.
- It does not claim a Gemini key belongs to a project. Resource Manager verifies
  that the declared project id exists and is readable; the key-to-project
  association remains operator-declared.
- It does not read AI Studio usage. Google publishes no public endpoint for the
  AI Studio rate-limit table or usage; the dashboard says so.

## APIs used

| API | Request | Permission | Purpose |
|---|---|---|---|
| Cloud Resource Manager v1 | `GET /v1/projects/{projectId}` | `resourcemanager.projects.get` | Confirm the declared id and read project number, display name and lifecycle state. |
| Cloud Quotas v1 | `GET /v1/projects/{project}/locations/global/services/{service}/quotaInfos` | `cloudquotas.quotas.get` | Quota ids, metrics, units, refresh interval, dimensions and per-dimension limits. |
| Cloud Monitoring v3 | `GET /v3/projects/{project}/timeSeries` | `monitoring.timeSeries.list` | Consumer-quota usage and exceeded counters. |
| Service Usage v1 | `GET /v1/projects/{project}/services?filter=state:ENABLED` | `serviceusage.services.list` | Whether the required APIs are enabled (diagnostic; failure does not fail the sync). |

The default service is `generativelanguage.googleapis.com`. It is configurable,
but the metric matching assumes Cloud Quotas metrics and Monitoring
`quota_metric` labels share the same metric id, which is how Google exposes
consumer quotas.

### OAuth scopes

The service-account assertion requests:

- `https://www.googleapis.com/auth/monitoring.read`
- `https://www.googleapis.com/auth/cloud-platform` (Cloud Quotas only accepts
  this scope)

Least privilege is enforced by IAM roles, not by the scope string. The integration
never uses the token for a write.

### Required IAM roles

Grant these on each monitored project (or at the smallest folder that contains
them). Do **not** grant Owner or Editor.

| Role | Supplies |
|---|---|
| `roles/browser` | `resourcemanager.projects.get` |
| `roles/cloudquotas.viewer` | `cloudquotas.quotas.get` |
| `roles/monitoring.viewer` | `monitoring.timeSeries.list` |
| `roles/serviceusage.serviceUsageViewer` | `serviceusage.services.list` |

## Credential configuration

Supported mechanisms, in order:

1. **Service-account JSON file** — recommended. Keep it outside the repository,
   mode `0600`, in a mounted secret directory.
2. **Inline JSON** via `AETRIX_GOOGLE_CLOUD__SERVICE_ACCOUNT_JSON` — for a secret
   manager that injects the document without writing it to disk. Prefer the file.
3. **Metadata server** — `AETRIX_GOOGLE_CLOUD__USE_METADATA=true` on GCE/Cloud
   Run with a workload identity that has the roles. No key file is needed.

`GOOGLE_APPLICATION_CREDENTIALS` is honoured as a file fallback when no explicit
path is set, but an explicit `AETRIX_GOOGLE_CLOUD__SERVICE_ACCOUNT_FILE` is
clearer.

```dotenv
AETRIX_GOOGLE_CLOUD__SERVICE_ACCOUNT_FILE=/run/secrets/aetrix-google-quota.json
AETRIX_GOOGLE_CLOUD__ENABLED=true
```

Rotation: replace the mounted file or secret. A new token provider is built on
every scheduled/manual sync, so the next sync uses the new key; revoke the old
key afterwards. The access token is cached in process memory only until shortly
before expiry. No token or private key is logged or returned by an API.

### Operator setup (not executed by Aetrix)

Run only after explicit approval. These commands are illustrative and must be
adapted to the real project and secret store.

```bash
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  cloudquotas.googleapis.com \
  monitoring.googleapis.com \
  serviceusage.googleapis.com \
  generativelanguage.googleapis.com \
  --project=PROJECT_ID

gcloud iam service-accounts create aetrix-quota-reader \
  --display-name="Aetrix quota reader" --project=PROJECT_ID

for ROLE in roles/browser roles/cloudquotas.viewer roles/monitoring.viewer roles/serviceusage.serviceUsageViewer; do
  gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:aetrix-quota-reader@PROJECT_ID.iam.gserviceaccount.com" \
    --role="$ROLE"
done

gcloud iam service-accounts keys create /secure/outside/repo/google-quota.json \
  --iam-account=aetrix-quota-reader@PROJECT_ID.iam.gserviceaccount.com
```

Then mount the file, set the environment variable, run `alembic upgrade head`
(0021 is the head for this change), restart the API and worker, and press
**Sync now** on the Google quota tab. The sync itself performs no setup.

## What is synchronised

### Per project

- Verification status (`VERIFIED`, `NOT_FOUND`, `PERMISSION_DENIED`, `ERROR`,
  `UNVERIFIABLE`, `UNVERIFIED`) from Resource Manager.
- Google project number, display name and lifecycle state.
- Last attempt, last verification, last successful quota read and last error.
- Enabled state of the required APIs, when Service Usage is readable.
- Staleness against `AETRIX_GOOGLE_CLOUD__STALE_AFTER_SECONDS`.

### Per quota observation

- `quotaId`, metric, display names, unit, refresh interval and container type.
- Declared dimensions and the concrete values (for example `model=gemini-2.5-pro`).
- Limit from `dimensionsInfos[].details.quotaValue` (or the top-level quota
  value); source `CLOUD_QUOTAS`. `-1` is preserved and displayed as unlimited.
- Fallback limit from Monitoring `serviceruntime.googleapis.com/quota/limit`
  only when Cloud Quotas returned none; source `CLOUD_MONITORING`.
- Usage from `quota/allocation/usage` or `quota/rate/net_usage`, matched on
  `quota_metric` and all known dimensions; source `CLOUD_MONITORING`.
- `quota/exceeded` latest counter, when present.
- `resetTime` exactly as Google returned it (often absent).
- Limit observation time and usage observation time, separately.

### Supported consumer-quota metrics

- `serviceruntime.googleapis.com/quota/allocation/usage`
- `serviceruntime.googleapis.com/quota/rate/net_usage`
- `serviceruntime.googleapis.com/quota/limit`
- `serviceruntime.googleapis.com/quota/exceeded`

The query uses `resource.type="consumer_quota"` and
`resource.label.service="generativelanguage.googleapis.com"`, a 15-minute
interval and per-series `ALIGN_MAX` (usage/limit) or `ALIGN_SUM` (exceeded).

## What remains unavailable

- **AI Studio usage and active rate limits.** Google documents that these are
  viewed in AI Studio; there is no public API. The dashboard states this and
  links to Google's documentation. It is a manually verified external value.
- **Per-model RPM/RPD/TPM** when Google does not emit a consumer-quota time
  series. Limits are still shown from Cloud Quotas, but usage is
  `NOT_EXPOSED`, never zero.
- **Spend-based limits** (rolling 10-minute spend) — not exposed here.
- **Quota increase or reset actions** — intentionally absent; read-only.
- **Reset/replenishment instants** — shown only when Google includes
  `resetTime`; Aetrix never derives one from the daily Pacific reset.

## Synchronisation behaviour

- **Cached read** — `GET /api/v1/admin/providers/google-quota` returns stored
  observations, their timestamps, per-project staleness and the last five runs.
- **Manual sync** — `POST /api/v1/admin/providers/google-quota/sync` with an
  optional `project_id`, platform administrator only. A project id must already
  be declared by a registered key; arbitrary ids are refused with 404.
- **Scheduled sync** — the worker starts a dedicated thread when the integration
  is configured and enabled. A PostgreSQL advisory lock prevents two worker
  processes sweeping at once. It never runs inside, or delays, a correction job.
  An API-only deployment has no scheduler; the manual endpoint still works.
- **Retry** — 429, 5xx, timeouts and network errors retry with exponential
  backoff up to `MAX_ATTEMPTS`. 401/403/404/400 are final and produce an
  actionable permission/identity error.
- **Partial failure** — each project runs in its own transaction. One project's
  failure does not roll back another. If Cloud Quotas succeeds but Monitoring
  fails, the run is `PARTIAL`, limits are refreshed, and the previous usage is
  carried forward with its original `usage_observed_at`. A failed sync otherwise
  keeps the previous snapshot rather than deleting it; the project is then stale.
- **No fabricated values** — a missing limit or usage is `null` and renders as
  "Unavailable"/"No limit returned"; stats never substitute zero.

## Security properties

- No secret is returned by any route; the report includes only the credential
  *source* enum.
- Error messages are Google's status text, truncated, and never include the
  assertion, token, private key or full JSON document.
- The service account needs four read roles. No Owner/Editor, no automatic
  grant, no API enablement.
- Manual sync is platform-admin only, restricted to declared projects.
- Only GET requests are implemented against Google.

## Tests

`backend/tests/unit/test_google_cloud_quota.py` mocks every HTTP response and
covers: signed assertion/scopes, token caching, missing and invalid credentials,
inline JSON rejection, project identity and mismatch, 403 without retry,
429/backoff, timeouts, quota pagination/dimensions/reset time, timezone
conversion, naive timestamps, usage matching per model, conflicting labels,
unlimited `-1`, exceeded counters, staleness, synthetic pool ids, unconfigured
client and explicit AI Studio unavailability.

The integration suite was not run: it refuses a non-loopback database because it
truncates every table.

## Files

- `backend/app/core/config.py` — `GoogleCloudSettings`.
- `backend/app/db/models.py` — project, snapshot and run tables.
- `backend/migrations/versions/0020_google_cloud_quota.py` — tables.
- `backend/migrations/versions/0021_google_quota_reset_time.py` — reset time.
- `backend/app/services/google_cloud.py` — auth, read-only clients, parsers.
- `backend/app/services/google_quota.py` — per-project sync and report.
- `backend/app/schemas/google_quota.py` — API contracts.
- `backend/app/schemas/provider_admin.py` — fleet verification fields.
- `backend/app/api/v1/admin_providers.py` — cached read and manual sync routes.
- `backend/app/services/provider_fleet.py` — verification joins the overview.
- `backend/app/worker.py` — scheduled sync thread with advisory lock.
- `backend/tests/unit/test_google_cloud_quota.py` — mocked tests.
- `backend/.env.example` — configuration template.
- `frontend/src/lib/api/gemini.ts` — report types and calls.
- `frontend/src/routes/_app.platform.gemini.tsx` — Google quota tab.
- `frontend/src/styles/hub.css` — quota table and run list.
- `frontend/tests/google-quota.spec.ts` — source labels, AI Studio unavailable, manual sync.
- `docs/architecture/GOOGLE_CLOUD_QUOTA.md` — this document.
