"""Per-credential Aetrix pools, and why they are not Google projects.

The fleet is fifteen lent keys, each administered on its own: budget,
reservations, confirmed and unconfirmed usage, failure count, quarantine, last
success, last quota exhaustion and model access.  Google meters something else —
per Cloud project and model, with several keys possibly in one project — so these
tests pin both halves of the distinction:

* pools are independent Aetrix accounting and may each be spent;
* no pool count and no pool budget is treated as Google capacity, and a 429 is
  never answered by leasing another key.

Everything is scripted.  No provider is called and no Google number is asserted.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from app.core.config import ModelQuota, get_settings
from app.core.errors import AppError
from app.core.ids import utcnow
from app.core.security import SecretBox
from app.db.models import ProviderCredential, ProviderQuotaReservation
from app.providers.routing import FailureKind, RoutingAction, decide
from app.services import provider_calls as call_module
from app.services import quota as quota_module
from app.services.credential_pools import pool_id_for, quarantine_for

MODEL = "gemini-3.6-flash"
TENANT = uuid.uuid4()
UNVERIFIED = "PROJECT_IDENTITY_UNVERIFIED"
POOL_LABEL = "user-downloads-pool"
REVISION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0039_credential_pools.py"
)


def _settings(*, per_minute: int = 100, per_day: int = 20, pinned=None):
    base = get_settings()
    quota = base.quota.model_copy(
        update={
            "model_limits": {
                MODEL: ModelQuota(
                    requests_per_minute=per_minute,
                    tokens_per_minute=None,
                    requests_per_day=per_day,
                    source="operator",
                )
            }
        }
    )
    provider = base.provider.model_copy(update={"pinned_credential_id": pinned})
    return base.model_copy(update={"quota": quota, "provider": provider})


def _box():
    return SecretBox(_settings().security.encryption_key.get_secret_value())


def _credential(
    *,
    project_id: str = POOL_LABEL,
    identity: str = UNVERIFIED,
    health: str = "HEALTHY",
    cooldown_until=None,
    cooldown_kind=None,
):
    identifier = uuid.uuid4()
    return SimpleNamespace(
        id=identifier,
        pool_id=pool_id_for(identifier),
        tenant_id=None,
        project_id=project_id,
        project_identity=identity,
        revoked_at=None,
        health=health,
        cooldown_until=cooldown_until,
        cooldown_kind=cooldown_kind,
        last_error=None,
        last_success_at=None,
        last_quota_exhausted_at=None,
        last_quota_reason=None,
        consecutive_failures=0,
        model_access=[MODEL],
        encrypted_secret=_box().encrypt(f"key-{identifier}"),
        contributor_id=None,
    )


class _State:
    """Stands in for the SQLAlchemy session used by ``_finish``."""

    def __init__(self) -> None:
        self.credentials: dict[uuid.UUID, object] = {}
        self.reservations: dict[uuid.UUID, object] = {}

    def get(self, model, key):
        if model is ProviderCredential:
            return self.credentials.get(key)
        if model is ProviderQuotaReservation:
            return self.reservations.get(key)
        return None

    def commit(self) -> None:
        return None


class _Reservations:
    """Counts per credential.  ``inclusive`` includes UNCONFIRMED rows."""

    def __init__(self, state: _State, counts=None, unconfirmed=None) -> None:
        self.state = state
        self.counts = counts or {}
        self.unconfirmed = unconfirmed or {}

    def count_since_credential(
        self, credential_id, since, now, *, model=None, include_unconfirmed=False
    ) -> int:
        confirmed, inclusive = self.counts.get(credential_id, (0, 0))
        return inclusive if include_unconfirmed else confirmed

    def unconfirmed_count_credential(self, credential_id, since, *, model=None) -> int:
        return self.unconfirmed.get(credential_id, 0)

    def count_since_project(
        self, project_id, since, now, *, model=None, include_unconfirmed=False
    ) -> int:
        return 0

    def unconfirmed_count_project(self, project_id, since, *, model=None) -> int:
        return 0

    def credential_window_counts(
        self, credential_ids, *, minute_since, day_since, now, model=None
    ):
        """The batched seam the fleet reads: same counts, one call."""

        return {
            credential_id: {
                "minute": self.counts.get(credential_id, (0, 0))[1],
                "day": self.counts.get(credential_id, (0, 0))[0],
                "unconfirmed": self.unconfirmed.get(credential_id, 0),
            }
            for credential_id in credential_ids
        }

    def project_window_counts(
        self, project_ids, *, minute_since, day_since, now, model=None
    ):
        return {
            project_id: {"minute": 0, "day": 0, "unconfirmed": 0}
            for project_id in project_ids
        }

    def active_cooldowns_for(self, project_ids, now):
        return {}

    def project_cooldown(self, project_id):
        return None

    def reserve(self, **kwargs):
        row = SimpleNamespace(id=uuid.uuid4(), status="RESERVED")
        self.state.reservations[row.id] = row
        credential_id = kwargs["credential_id"]
        confirmed, inclusive = self.counts.get(credential_id, (0, 0))
        self.counts[credential_id] = (confirmed + 1, inclusive + 1)
        return row


class _Usage:
    def __init__(self, tokens: int = 0) -> None:
        self.tokens = tokens

    def validation_count_for_credential(self, credential_id, model, since) -> int:
        return 0

    def validation_count(self, project_id, model, since) -> int:
        return 0

    def tokens_since_credential(self, credential_id, model, since) -> int:
        return self.tokens

    def window_stats(self, since, *, project_id, model) -> dict:
        return {"input_tokens": 0, "output_tokens": 0, "failures": 0}

    def credential_pool_usage(
        self, credential_ids, *, model, minute_since, day_since
    ):
        """The batched seam the fleet reads: probes and tokens, one call."""

        return {
            credential_id: {
                "validations_minute": 0,
                "validations_day": 0,
                "tokens_minute": self.tokens,
            }
            for credential_id in credential_ids
        }

    def project_pool_usage(self, project_ids, *, model, minute_since, day_since):
        return {
            project_id: {
                "validations_minute": 0,
                "validations_day": 0,
                "tokens_minute": self.tokens,
            }
            for project_id in project_ids
        }


class _Credentials:
    def __init__(self, rows) -> None:
        self.rows = rows

    def claim_candidates(self, tenant_id, model, excluded):
        now = utcnow()
        return [
            row
            for row in self.rows
            if row.id not in excluded
            and row.revoked_at is None
            and row.health not in {"INVALID", "DISABLED"}
            and (row.cooldown_until is None or row.cooldown_until <= now)
            and (not row.model_access or model in row.model_access)
        ]

    def count_unknown_project_identity(self, model) -> int:
        return sum(
            1
            for row in self.rows
            if row.project_identity == UNVERIFIED
            and row.revoked_at is None
            and row.health not in {"INVALID", "DISABLED"}
        )


def _pool(monkeypatch, credentials, *, per_day=20, per_minute=100, counts=None, pinned=None):
    state = _State()
    for row in credentials:
        state.credentials[row.id] = row
    reservations = _Reservations(state, counts)
    monkeypatch.setattr(
        call_module, "CredentialRepository", lambda _s: _Credentials(credentials)
    )
    monkeypatch.setattr(
        call_module, "QuotaReservationRepository", lambda _s: reservations
    )
    monkeypatch.setattr(call_module, "UsageRepository", lambda _s: _Usage())
    pool = call_module.CredentialPool(
        state, _settings(per_minute=per_minute, per_day=per_day, pinned=pinned)
    )
    return pool, reservations, state


def _estimator(monkeypatch, *, counts=None, unconfirmed=None, per_day=20):
    reservations = _Reservations(_State(), counts, unconfirmed)
    monkeypatch.setattr(
        quota_module, "QuotaReservationRepository", lambda _s: reservations
    )
    monkeypatch.setattr(quota_module, "UsageRepository", lambda _s: _Usage())
    return quota_module.QuotaEstimator(None, _settings(per_day=per_day))


# -- 1. independent credential accounting ------------------------------------


def test_each_credential_has_its_own_budget(monkeypatch) -> None:
    first, second = _credential(), _credential()
    pool, reservations, _ = _pool(monkeypatch, [first, second], per_day=1)

    a = pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")
    b = pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    assert {a.credential_id, b.credential_id} == {first.id, second.id}
    assert reservations.counts[first.id] == (1, 1)
    assert reservations.counts[second.id] == (1, 1)
    with pytest.raises(AppError):
        pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")


def test_a_pool_records_its_own_confirmed_and_unconfirmed_usage(monkeypatch) -> None:
    credential = _credential()
    estimator = _estimator(
        monkeypatch, counts={credential.id: (2, 3)}, unconfirmed={credential.id: 1}
    )

    estimate = estimator.pool_estimate(credential, MODEL)

    assert estimate.requests_per_day.used == 2
    # Unconfirmed attempts stay inside the minute window so a retry storm cannot
    # exceed the burst limit while their outcome is still unknown; the daily
    # allowance counts confirmed requests only and reports the rest separately.
    assert estimate.requests_per_minute.used == 4
    assert estimate.unconfirmed_requests == 1
    assert estimate.pool_id == pool_id_for(credential.id)
    assert estimate.accounting == "AETRIX_POOL_RESERVATIONS_PLUS_VALIDATION"


# -- 2. several credentials may share one Google project ---------------------


def test_two_pools_may_share_one_google_project_and_are_still_separate_pools(
    monkeypatch,
) -> None:
    """Independent Aetrix budgets, but no claim of independent Google allowance."""

    first = _credential(project_id=POOL_LABEL)
    second = _credential(project_id=POOL_LABEL)
    pool, _, _ = _pool(monkeypatch, [first, second], per_day=1)

    assert pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")
    assert pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    estimator = _estimator(monkeypatch)
    for credential in (first, second):
        estimate = estimator.pool_estimate(credential, MODEL)
        assert estimate.google_quota_status == "UNKNOWN"
        assert estimate.project_identity == UNVERIFIED

    project = estimator.estimate(project_id=POOL_LABEL, model=MODEL)
    # The aggregate exists, but it is Aetrix's record for the label and says
    # nothing about Google's allowance.
    assert project.google_quota_status == "UNKNOWN"
    assert any("Google-level capacity is UNKNOWN" in note for note in project.notes)


# -- 3. unknown project identity ---------------------------------------------


def test_unknown_project_identity_labels_google_capacity_and_does_not_block(
    monkeypatch,
) -> None:
    credential = _credential(project_id=POOL_LABEL)
    pool, _, _ = _pool(monkeypatch, [credential], per_day=5)

    assert pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    estimate = _estimator(monkeypatch).pool_estimate(credential, MODEL)
    assert estimate.google_quota_status == "UNKNOWN"
    assert "Declare the project" in estimate.google_quota_note
    assert estimate.enabled is True
    assert estimate.quarantined is False


# -- 4. credential-specific exhaustion ---------------------------------------


def test_one_exhausted_pool_does_not_close_the_other(monkeypatch) -> None:
    spent = _credential()
    fresh = _credential()
    pool, _, _ = _pool(
        monkeypatch,
        [spent, fresh],
        per_day=1,
        counts={spent.id: (1, 1)},
    )

    lease = pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    assert lease.credential_id == fresh.id


def test_no_pool_is_leased_once_every_pool_is_spent(monkeypatch) -> None:
    first, second = _credential(), _credential()
    pool, _, _ = _pool(
        monkeypatch,
        [first, second],
        per_day=1,
        counts={first.id: (1, 1), second.id: (1, 1)},
    )

    with pytest.raises(AppError) as error:
        pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    message = error.value.message
    assert "no established Google" not in message.lower()
    assert "Google-level allowance is UNKNOWN" in message
    assert "No request was sent" in message


# -- 5. HTTP 429 handling ----------------------------------------------------


def test_a_429_records_quota_failure_quarantine_and_the_provider_reason(
    monkeypatch,
) -> None:
    credential = _credential()
    pool, _, state = _pool(monkeypatch, [credential], per_day=5)
    lease = pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")
    reason = (
        "RESOURCE_EXHAUSTED: Quota exceeded for "
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    )

    pool.failure(
        lease,
        error="ProviderQuotaError: 429",
        status_code=429,
        kind=FailureKind.QUOTA,
        provider_reason=reason,
        cooldown_seconds=600,
        reservation_status="CONSUMED",
    )

    stored = state.credentials[credential.id]
    assert stored.cooldown_kind == "QUOTA"
    assert stored.last_quota_exhausted_at is not None
    assert stored.last_quota_reason == reason
    assert stored.cooldown_until is not None
    assert stored.consecutive_failures == 1
    assert state.reservations[lease.reservation_id].status == "CONSUMED"

    estimate = _estimator(monkeypatch).pool_estimate(credential, MODEL)
    assert estimate.google_quota_status == "EXHAUSTED"
    assert estimate.quarantined is True
    assert estimate.quarantine_kind == "QUOTA"
    assert estimate.last_quota_reason == reason


def test_an_authentication_failure_marks_the_pool_unhealthy(monkeypatch) -> None:
    credential = _credential()
    pool, _, state = _pool(monkeypatch, [credential])
    lease = pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    pool.failure(
        lease,
        health="INVALID",
        error="ProviderAuthenticationError: 401",
        status_code=401,
        kind=FailureKind.AUTHENTICATION,
        cooldown_seconds=60,
        reservation_status="RELEASED",
    )

    stored = state.credentials[credential.id]
    assert stored.health == "INVALID"
    assert stored.cooldown_kind == "AUTH"
    # A refused key is not a quota exhaustion; the Google status must not claim
    # the project is spent.
    assert stored.last_quota_exhausted_at is None
    estimate = _estimator(monkeypatch).pool_estimate(credential, MODEL)
    assert estimate.google_quota_status == "UNKNOWN"
    assert estimate.enabled is False


# -- 6. quarantine and recovery ----------------------------------------------


def test_a_quarantined_pool_is_not_leased_until_its_window_lapses(monkeypatch) -> None:
    credential = _credential(
        cooldown_until=utcnow() + timedelta(minutes=10), cooldown_kind="QUOTA"
    )
    pool, _, _ = _pool(monkeypatch, [credential])

    with pytest.raises(AppError):
        pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    quarantine = quarantine_for(credential, utcnow())
    assert quarantine.active is True
    assert quarantine.kind == "QUOTA"

    # Once the recorded window has passed, the same pool is leaseable again.
    credential.cooldown_until = utcnow() - timedelta(seconds=1)
    assert pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")


def test_a_success_clears_the_quarantine_and_the_failure_count(monkeypatch) -> None:
    credential = _credential(
        cooldown_until=utcnow() - timedelta(seconds=1),
        cooldown_kind="QUOTA",
    )
    credential.consecutive_failures = 4
    pool, _, state = _pool(monkeypatch, [credential])
    lease = pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    pool.success(lease)

    stored = state.credentials[credential.id]
    assert stored.consecutive_failures == 0
    assert stored.cooldown_until is None
    assert stored.cooldown_kind is None
    assert stored.health == "HEALTHY"
    assert stored.last_success_at is not None


# -- 7. reservation concurrency ----------------------------------------------


def test_in_flight_reservations_close_the_pool_before_any_request_is_sent(
    monkeypatch,
) -> None:
    """RESERVED rows are the concurrency guard: two in flight exhaust a budget of 2."""

    credential = _credential()
    pool, reservations, _ = _pool(monkeypatch, [credential], per_day=2)

    assert pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")
    assert pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")
    assert reservations.counts[credential.id] == (2, 2)

    with pytest.raises(AppError):
        pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")


def test_the_minute_window_is_enforced_per_pool(monkeypatch) -> None:
    busy, idle = _credential(), _credential()
    pool, _, _ = _pool(
        monkeypatch,
        [busy, idle],
        per_day=100,
        per_minute=5,
        counts={busy.id: (0, 5)},
    )

    lease = pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")
    assert lease.credential_id == idle.id


# -- 8. no automatic quota-evasion rotation ----------------------------------


def test_a_quota_refusal_is_never_a_credential_rotation() -> None:
    action = decide(
        FailureKind.QUOTA,
        attempt_index=0,
        attempts_allowed=4,
        next_model_available=False,
        other_credential_available=True,
    )
    assert action is RoutingAction.STOP


def test_a_pinned_credential_is_never_silently_substituted(monkeypatch) -> None:
    authorised = _credential(
        cooldown_until=utcnow() + timedelta(minutes=5), cooldown_kind="QUOTA"
    )
    spare = _credential()
    pool, reservations, _ = _pool(
        monkeypatch, [authorised, spare], pinned=authorised.id
    )

    with pytest.raises(AppError) as error:
        pool.acquire(tenant_id=TENANT, model=MODEL, purpose="marking")

    assert "pinned" in error.value.message
    assert error.value.details["pinned_credential_id"] == str(authorised.id)
    # The spare key was not leased to fill the gap.
    assert reservations.counts.get(spare.id) is None


# -- 9. historical ledger preservation ---------------------------------------


def test_pool_accounting_is_new_state_and_never_a_rewrite_of_history() -> None:
    source = REVISION.read_text(encoding="utf-8")
    updates = [
        line
        for line in source.splitlines()
        if "UPDATE " in line.upper() and not line.strip().startswith("#")
    ]
    assert updates, "the revision is expected to backfill its own columns"
    # Every data statement in the revision targets provider_credentials (the
    # backfill of pool_id and the reason text).  No ledger row is touched.
    for line in updates:
        assert "{_TABLE}" in line, line
    assert "provider_usage" in source  # named only to say it is untouched
    assert "DELETE FROM" not in source.upper()
