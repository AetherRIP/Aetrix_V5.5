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

## Contributors (migration `0007_contributors`)

Keys are lent by people, so the fleet has a contributor record. `provider_contributors` holds
a display name, an optional `user_id` (an account that may exist before the person signs in,
unique when set), a status of `ACTIVE`, `SUSPENDED` or `WITHDRAWN`, the consent version and
timestamp, and the suspension/withdrawal timestamps.

`provider_credentials.contributor_id` is nullable on purpose: `NULL` means the platform owns
the key, which is not the same thing as a contribution with no owner. Legacy and operator
keys keep working, and `provider_usage.contributor_id` is backfilled only from credentials
that actually have an owner.

The chain is `Contributor → API Key → Google Cloud Project → Model Quota`. Nothing assumes
one contributor owns one project, and nothing assumes one project has one contributor: a
contributor may hold several keys across several projects, and a project may be served by
keys from several contributors.

Consent is a precondition, not metadata: `create_contributor` refuses a blank consent
version, so a row that can schedule calls always records which agreement allowed it.

### Lifecycle

- **Suspension** is reversible. Keys are set `DISABLED`, the ciphertext stays, and the
  contributor is excluded from new leases while suspended.
- **Reinstatement** sets previously withheld keys to `UNKNOWN`, so a key must prove itself
  again rather than inherit an old success.
- **Withdrawal** is irreversible. The ciphertext is replaced with an encrypted empty string
  (the ADR-022 treatment), `revoked_at`/`revoked_reason` are recorded, keys are `DISABLED`,
  and the rows stay so the append-only ledger keeps its provenance.
- A revoked key can never be re-enabled; `set_enabled` refuses it with `CONFLICT`.

Eligibility lives in one place: `CredentialRepository.claim_candidates` outer-joins the
contributor and requires `revoked_at IS NULL` and an `ACTIVE` contributor (or no contributor
at all, for platform keys). Withdrawal therefore takes effect before the next lease — no
scheduler restart, no cache to expire.

### Capacity and attribution

`app/services/contributors.py:capacity` groups eligible keys by project, sums remaining
allowance **per project** (never per key), and reports the windows it could not measure
separately from the ones it could. The note it returns says so in words, because a number
that silently multiplied by key count is the failure mode this work exists to avoid.

`contributor_window_stats` aggregates the append-only `provider_usage` ledger by
`contributor_id`, and every row also carries the credential, project, model and — when the
caller passes one — the correction job. `contribution_summary` returns the aggregate and the
per-contributor rows, including how many projects are shared by more than one contributor.

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

`/api/v1/admin/providers/contributions` adds the contributor records: summary and capacity,
create, detail, add key, revoke key, suspend, reinstate and withdraw. A key belonging to a
different contributor answers `404`, exactly like a missing one.

`/api/v1/contributions/me` is the self-service side for any authenticated user: register a key
(the first registration also records consent), list your own keys, revoke one, and withdraw
from the programme. The contributor is resolved from `principal.user_id`, never from the
request body, so a caller cannot act on somebody else's record. No response in either router
contains key material.

Removal honours ADR-022: an unused key's row is deleted, a used key is disabled and its
ciphertext replaced, because deleting it would make `provider_usage`'s `SET NULL` issue an
UPDATE the append-only trigger rejects.

## Dashboard

`/platform/gemini` (platform operator) has Overview, API keys, Contributors, Projects, Usage
and Alerts tabs. Contributors shows status, consent version, eligible/total key counts,
projects, per-contributor requests, independent-project capacity, registration, suspension,
reinstatement, withdrawal and per-key revocation. It renders real figures when the engine
answers and the shared `StatePanel` when it does not; it never substitutes zeros for a missing
deployment.

## Gaps

- No Google credential is configured, so Cloud Monitoring/quota synchronisation is not
  implemented and cannot be verified.
- `tier` is operator-supplied and recorded as `UNKNOWN` unless set; nothing verifies a
  free-tier claim.
- The background monitoring interval is configured but no scheduler loops it yet.
- Migrations `0006` and `0007` have not been applied to any database. They render in Alembic
  offline mode, but the migration and contributor integration tests could not run here: the
  machine has no PostgreSQL. They are written and collect; they are unexecuted evidence.
- Contributor statistics come from Aetrix's own ledger. Nothing reconciles them against
  Google's billing or quota surfaces.
- The self-service contributor routes exist, but no teacher-facing screen calls them yet;
  only the operator screen at `/platform/gemini` consumes the contributor API.
