# Provider fleet: Gemini keys, project quota and selection

This note describes what the repository actually implements for managing many Gemini
credentials. It is a description of code, not a promise: no engine is deployed, the live
provider is `UNVERIFIED`, and nothing here has been exercised against Google.

## The rule that shapes everything

**Quota is a property of a Google Cloud project, not of a key.** Ten keys in one project
share one free-tier allowance, per model. Counting per credential was the defect this work
removed: it let rotation multiply a limit that Google does not multiply, so the fleet would
report capacity it did not have and meet 429s instead.

Every quota query therefore goes through
`QuotaReservationRepository.count_since_project(project_id, since, now)`, and
`CredentialPool._within_quota` receives a `project_id`, never a credential id.

## Schema (migration `0006_provider_fleet`)

- `provider_credentials` gains `project_id`, `auth_type`, `tier`, `last_failure_at`,
  `last_failure_status`, `last_validated_at`, plus check constraints and project indexes.
- `provider_usage` gains `project_id` (backfilled from the credential, `unattributed` when
  there is none) and `retry_count`, plus project/model indexes. The ledger stays
  append-only.
- `provider_project_cooldowns` is new: one row per paused project, RLS enabled and grants
  revoked, matching revision `0005_rls_lockdown`.

Legacy keys are backfilled to `legacy-<fingerprint>`, one pool each. That is deliberately
conservative: a guessed shared project would understate capacity, and inferring that two
legacy keys share a project is not verifiable from the data.

## Confidence, not optimism

`app/services/quota.py` reports each dimension (RPM, TPM, RPD) as:

- `CONFIRMED` — the limit was recorded with `source="google"`, i.e. someone read it from an
  authoritative Google surface. The *consumption* is still Aetrix's own ledger.
- `ESTIMATED` — the limit is Aetrix policy or a platform default.
- `UNKNOWN` — no limit is known. No percentage is computed, `remaining` is `null`.

The model-level `confidence` is the weakest of its windows, so a project with a confirmed
RPM and an unknown TPM never reports `CONFIRMED`. Daily windows reset at midnight Pacific
(`AETRIX_QUOTA__DAILY_RESET_TIMEZONE`); an unreadable zone degrades to UTC rather than
crashing a dashboard.

Google exposes no endpoint for "remaining free-tier quota". Nothing here pretends it does,
and Cloud Monitoring polling is not implemented — see the gaps below.

## Selection

`CredentialPool.acquire` walks candidates and skips, per project: a project in cooldown, a
project with no RPM or RPD left, and then leases a key, writing an atomic reservation row
before the network call and committing so the row lock is released. A second worker sees
that reservation through `count_since_project`; it does not assume the same capacity.

## Failure handling

| Failure | Credential | Project |
|---|---|---|
| 401 / 403 (`ProviderAuthenticationError`) | `INVALID`, no longer leased | untouched |
| 429 (`ProviderQuotaError`) | `COOLDOWN` until `retry-after` | cooldown row for every key in the project |
| 5xx / transport (`ProviderTransientError`) | `UNKNOWN`, retried within `max_attempts` | untouched |
| 400 (`ProviderRequestError`) | failure recorded | untouched, no retry |

A successful call clears the project cooldown, because success is evidence the project works
again. Every attempt is written to `provider_usage` with `retry_count`, `project_id`,
`purpose`, HTTP status and error class.

## Administration API

`/api/v1/admin/providers` — overview, keys (list/add/import/validate/enable/disable/delete),
projects, usage, alerts. Every route requires the engine's `ADMIN` role, resolved from the
verified token and the database; a workspace `OWNER` receives 403. Responses carry a
fingerprint, never a key. Validation performs one small real request and records it with
`purpose='validate'`.

Removal honours ADR-022: an unused key's row is deleted, a used key is disabled and its
ciphertext replaced, because deleting it would make `provider_usage`'s `SET NULL` issue an
UPDATE the append-only trigger rejects.

## Dashboard

`/platform/gemini` (platform operator) has Overview, API keys, Projects, Usage and Alerts
tabs. It renders real figures when the engine answers and the shared `StatePanel` when it
does not; it never substitutes zeros for a missing deployment.

## Gaps

- No Google credential is configured, so Cloud Monitoring/quota synchronisation is not
  implemented and cannot be verified.
- `tier` is operator-supplied and recorded as `UNKNOWN` unless set; nothing verifies a
  free-tier claim.
- The background monitoring interval is configured but no scheduler loops it yet.
- Migration `0006` has not been applied to the development database; it compiles in Alembic
  offline mode but the migration tests could not run (no PostgreSQL available locally).
