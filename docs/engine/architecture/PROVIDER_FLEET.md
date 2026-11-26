# Provider fleet: Gemini credentials, per-key pools and Google project evidence

This note describes what the repository actually implements for managing many Gemini
credentials. It is a description of code, not a promise: no engine is deployed, the live
provider is `UNVERIFIED`, and nothing here has been exercised against Google.

## The rule that shapes everything

Two facts are kept apart, in code and in wording:

1. **Aetrix administers one pool per credential**, `gemini-key-{credential_id}`. The pool owns
   the reservations, the confirmed and unconfirmed usage, the failure counter, the quarantine
   window, the last success, the last quota exhaustion and the configured model access.
   Keys are lent by different people and must be observable and enable-able separately.
2. **Google meters per Cloud project and model, and several keys may share one project.** A
   pool is not evidence of a separate project allowance. Project identity is therefore a
   separate, evidence-only field: `VERIFIED` (Resource Manager), `DECLARED` (audited
   administrator assertion) or `PROJECT_IDENTITY_UNVERIFIED`.

Pool budgets go through `QuotaReservationRepository.count_since_credential(credential_id, …)`
and `CredentialPool._within_quota` receives a credential id. Project-level aggregates still
exist for reporting (`count_since_project`) but are labelled Aetrix records for a declared
label, and their Google quota status is `UNKNOWN` unless the project is established.

A 429 quarantines the credential that received it and is **never** answered by leasing a
sibling key. Two keys in one pool-shaped fleet may bill one project; no response Aetrix can
observe establishes otherwise.

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

`app/services/contributors.py:capacity` reports every eligible credential as its own pool:
pool id, declared project label, quarantine, Google quota status, and the pool's own
configured minute/day budget. Model totals are named `aetrix_requests_*_remaining` and carry
how many pools have a known versus unknown Google status. The note it returns says, in words,
that these are Aetrix budgets and never Google capacity — summing pools into a capacity
figure is the failure mode this design exists to avoid.

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

## Three states that must not be conflated

An operator reading a refusal needs to know which of these happened, because only one
of them says anything about Google.

| State | Evidence | What Aetrix does | What it may claim |
|---|---|---|---|
| **Aetrix pool budget exhausted** | The pool's own reservation/usage count reached the configured minute or day limit. No provider response is involved. | Skips that pool for this model. Another enabled pool may serve the request (scheduling, recorded against that credential). If the deployment is pinned, the operation stops and names the pin. | Only that this key spent its recorded budget. Nothing about Google. |
| **Google project quota exhausted** | Google answered HTTP 429 / `RESOURCE_EXHAUSTED`. The exact code and message are stored. | Quarantines that credential (`QUOTA`, `retry-after` or configured cooldown), marks Google status `EXHAUSTED`, and **stops the operation**. No other key is leased — not even one carrying the same project label — and marking has a one-entry model chain, so there is no model fallback. | That Google refused this request. Not that the project is out of quota for the day, and not that a sibling key would work. |
| **Google project identity unknown** | No Resource Manager verification and no administrator declaration. Every existing row is `PROJECT_IDENTITY_UNVERIFIED`. | Does not block the pool: its Aetrix budget, quarantine and enable switch still apply normally. | Google status `UNKNOWN`, and never a summed fleet capacity figure. |

The first is Aetrix's own accounting. The second is Google's answer. The third is an
absence of evidence. A 429 is the only one that stops the operation outright, and it
never triggers credential substitution.

### Pilot policy

The initial pilot is a **single pinned credential**, `gemini-3.6-flash` only:
`AETRIX_PROVIDER__PINNED_CREDENTIAL_ID` is set to one healthy key and nothing is
substituted. Enabling more keys is an explicit administrative act for a later phase;
it must never be used to raise capacity during the pilot, because the pins that keep the
pilot attributable would then be bypassed. Pooling is not capacity: if the pinned key's
Google project is shared or exhausted, the pilot stops with a 429 rather than continuing
on another key.

## Selection

`CredentialPool.acquire` walks eligible pools and skips a pool that is quarantined or has no
RPM/RPD left in its own Aetrix budget, then leases it, writing an atomic reservation row
before the network call and committing so the row lock is released. A second worker sees that
reservation through `count_since_credential`; it does not assume the same budget.

An administrator can pin the whole deployment to one credential with
`AETRIX_PROVIDER__PINNED_CREDENTIAL_ID`. When set, no other key is substituted — not after a
failure, and never to get around a quota — and the refusal names the setting.

## Failure handling

The unit is the credential pool.

| Failure | Pool | Google status |
|---|---|---|
| 401 / 403 (`ProviderAuthenticationError`) | `health=INVALID`, `cooldown_kind=AUTH`, not leased | unchanged (this is not a quota refusal) |
| 429 (`ProviderQuotaError`) | `cooldown_kind=QUOTA`, `cooldown_until` from `retry-after`, `last_quota_exhausted_at`, Google's own reason in `last_quota_reason` | `EXHAUSTED` while the window is active |
| 5xx / transport | one bounded retry on the same model, reservation `UNCONFIRMED` | unchanged |
| 400 / 404 | failure recorded, no retry, no model substitution for marking | unchanged |

No 429 leases another credential. `routing.decide` returns `STOP` for a quota failure unless
the chain has a genuinely different model, and production marking has a one-entry chain. A
successful call clears that pool's cooldown and resets its consecutive-failure count; it says
nothing about any other key. Every attempt is written to `provider_usage` with `retry_count`,
`project_id`, `purpose`, HTTP status and error class, and the reservation keeps its own
`CONSUMED` / `RELEASED` / `UNCONFIRMED` state.

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
and Alerts tabs. Each key row shows its pool id, enable state, Aetrix budget left today,
reservation and validation counts, Google quota status (`KNOWN` / `EXHAUSTED` / `UNKNOWN`),
project identity, quarantine window, consecutive failures and last error. Contributors shows
status, consent version, eligible/total key counts, per-contributor requests, pool budgets and
per-key revocation. Every pool field is Aetrix accounting; Google's own numbers are never
invented. The screen renders real figures when the engine answers and the shared `StatePanel`
when it does not; it never substitutes zeros for a missing deployment.

## Gaps

- No Google credential is configured, so Cloud Monitoring/quota synchronisation is not
  implemented and cannot be verified.
- `tier` is operator-supplied and recorded as `UNKNOWN` unless set; nothing verifies a
  free-tier claim.
- The background monitoring interval is configured but no scheduler loops it yet.
- **Upgrade/downgrade rehearsal has not been run.** This build machine has no PostgreSQL
  server, no `psql`/`pg_ctl`/`initdb` and no Docker, and the shared Supabase project must not
  be used for a rehearsal. The migration's DDL, backfill, constraints and inverse drops were
  inspected against the live `0038` schema and the SQLAlchemy models, but none of it has been
  executed. A disposable loopback database (`AETRIX_TEST_DATABASE_URL`) is the remaining
  requirement before applying it.
- Migration `0039_credential_pools` (per-pool state plus project-identity evidence) has not
  been applied to the live database. `alembic heads` reports it as the single head, but the
  chain cannot be rendered in offline mode here: revision `0008` queries `pg_constraint` while
  building, so `--sql` fails before reaching `0039`. The pool and routing unit suites run; the
  integration suite cannot, because the machine has no PostgreSQL. The DDL is unexecuted
  evidence until an operator applies it.
- No Google Cloud project identity is established for the registered keys, so every pool
  reports Google quota `UNKNOWN`. The fleet must not present the sum of pool budgets as Google
  capacity; declaring a real project id per key is what changes that label.
- Contributor statistics come from Aetrix's own ledger. Nothing reconciles them against
  Google's billing or quota surfaces.
- The self-service contributor routes exist, but no teacher-facing screen calls them yet;
  only the operator screen at `/platform/gemini` consumes the contributor API.
