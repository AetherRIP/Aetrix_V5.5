"""Fleet registration, project-level quota, failure handling and admin gating.

The quota tests are the important ones: the defect this feature had to remove
was counting a credential as a quota pool.  Every shared-project test asserts
that adding a key does *not* add capacity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import ModelQuota, get_settings
from app.core.errors import AppError
from app.db.models import (
    ProviderCredential,
    ProviderProjectCooldown,
    ProviderUsage,
    Tenant,
    User,
)
from app.prompts.registry import PromptRegistry
from app.providers.errors import ProviderAuthenticationError, ProviderQuotaError
from app.services import provider_fleet
from app.services.provider_calls import ProviderCallService
from app.services.quota import QuotaEstimator, day_start, next_reset
from pydantic import SecretStr
from sqlalchemy import select

from tests.support import FakeProvider


def _settings(*, rpm: int = 100, rpd: int = 5000, limits: dict[str, ModelQuota] | None = None):
    base = get_settings()
    return base.model_copy(
        update={
            "quota": base.quota.model_copy(
                update={
                    "requests_per_minute": rpm,
                    "requests_per_day": rpd,
                    "model_limits": limits or {},
                }
            )
        }
    )


def _service(db_session, provider, settings):
    return ProviderCallService(
        db_session, settings, provider, PromptRegistry(settings.provider.prompt_root)
    )


def _call(service, identity):
    return service.call(
        tenant_id=identity.tenant_a.id,
        purpose="BLUEPRINT_EXTRACTION",
        prompt_id="blueprint_extraction",
    )


def _key(project_id: str, index: int) -> SecretStr:
    return SecretStr(f"AIza-test-{project_id}-{index:04d}")


def _register(db_session, settings, project_id: str, count: int) -> list[ProviderCredential]:
    return [
        provider_fleet.add_credential(
            db_session,
            settings,
            project_id=project_id,
            api_key=_key(project_id, index),
            label=f"{project_id}-{index}",
        )
        for index in range(count)
    ]


def test_fleet_registers_a_hundred_and_twenty_keys_across_projects(db_session, identity) -> None:
    settings = _settings()
    for project in ("alpha-proj", "beta-proj", "gamma-proj"):
        _register(db_session, settings, project, 40)

    rows, total = provider_fleet.CredentialRepository(db_session).fleet(limit=200)
    assert total == 120
    assert len({row.project_id for row in rows}) == 3
    assert len({row.key_fingerprint for row in rows}) == 120

    # The secret is encrypted at rest and the fingerprint is not the key.
    stored = rows[0]
    assert "AIza-test" not in stored.encrypted_secret
    assert "AIza-test" not in stored.key_fingerprint


def test_duplicate_credential_is_rejected_not_silently_registered(
    db_session, identity
) -> None:
    settings = _settings()
    key = SecretStr("AIza-duplicate-key-value")
    provider_fleet.add_credential(
        db_session, settings, project_id="alpha-proj", api_key=key, label="first"
    )
    with pytest.raises(AppError) as error:
        provider_fleet.add_credential(
            db_session, settings, project_id="beta-proj", api_key=key, label="second"
        )
    assert error.value.code.value == "CONFLICT"


def test_import_reports_duplicates_and_rejections_without_losing_good_rows(
    db_session, identity
) -> None:
    settings = _settings()
    provider_fleet.add_credential(
        db_session,
        settings,
        project_id="alpha-proj",
        api_key=SecretStr("AIza-already-there"),
    )
    outcomes = provider_fleet.import_credentials(
        db_session,
        settings,
        [
            {"project_id": "alpha-proj", "api_key": "AIza-already-there"},
            {"project_id": "alpha-proj", "api_key": "AIza-fresh-one"},
            {"project_id": "alpha-proj", "api_key": "AIza-fresh-one"},
            {"project_id": "", "api_key": "AIza-no-project"},
        ],
    )
    assert [outcome.outcome for outcome in outcomes] == [
        "duplicate",
        "added",
        "duplicate",
        "rejected",
    ]
    assert provider_fleet.CredentialRepository(db_session).fleet()[1] == 2


def test_project_quota_is_not_multiplied_by_keys(db_session, identity) -> None:
    settings = _settings(rpm=2)
    _register(db_session, settings, "shared-proj", 5)
    service = _service(db_session, FakeProvider('{"questions": []}'), settings)

    _call(service, identity)
    _call(service, identity)

    with pytest.raises(AppError) as error:
        _call(service, identity)
    assert error.value.code.value == "PROVIDER_UNAVAILABLE"
    assert "quota" in error.value.message.lower()

    # Five keys, one project, two requests: the second call consumed the pool.
    assert (
        provider_fleet.UsageRepository(db_session).window_stats(
            _now() - timedelta(minutes=5)
        )["requests"]
        == 2
    )


def test_a_second_project_has_its_own_allowance(db_session, identity) -> None:
    settings = _settings(rpm=1)
    _register(db_session, settings, "proj-a", 1)
    service = _service(db_session, FakeProvider('{"questions": []}'), settings)
    _call(service, identity)
    with pytest.raises(AppError):
        _call(service, identity)

    _register(db_session, settings, "proj-b", 1)
    result = _call(service, identity)
    row = db_session.scalar(
        select(ProviderUsage).where(ProviderUsage.id == result.usage_id)
    )
    assert row is not None and row.project_id == "proj-b"


def test_429_pauses_the_whole_project_not_only_the_key(db_session, identity) -> None:
    settings = _settings(rpm=100)
    keys = _register(db_session, settings, "hot-proj", 3)
    provider = FakeProvider(error=ProviderQuotaError("429 quota", status_code=429))
    service = _service(db_session, provider, settings)

    with pytest.raises(AppError):
        _call(service, identity)

    cooldown = db_session.scalar(
        select(ProviderProjectCooldown).where(
            ProviderProjectCooldown.project_id == "hot-proj"
        )
    )
    assert cooldown is not None
    assert cooldown.cooldown_until > _now()
    # Only the leased key carries a credential-level cooldown; the project row is
    # what stops a sibling key from producing the same 429.
    cooling = [key for key in keys if key.health == "COOLDOWN"]
    assert len(cooling) == 1
    assert len(provider.keys) == 1


def test_revoked_key_is_disabled_without_pausing_its_project(db_session, identity) -> None:
    settings = _settings(rpm=100)
    keys = _register(db_session, settings, "auth-proj", 2)
    service = _service(
        db_session, FakeProvider(error=ProviderAuthenticationError("bad key")), settings
    )
    with pytest.raises(AppError):
        _call(service, identity)

    assert any(key.health == "INVALID" for key in keys)
    assert (
        db_session.scalar(
            select(ProviderProjectCooldown).where(
                ProviderProjectCooldown.project_id == "auth-proj"
            )
        )
        is None
    )


def test_removing_a_used_key_retires_it_instead_of_breaking_the_ledger(
    db_session, identity
) -> None:
    """ADR-022: the usage ledger is append-only, so a used key is neutralised."""

    settings = _settings()
    _register(db_session, settings, "retire-proj", 1)
    service = _service(db_session, FakeProvider('{"questions": []}'), settings)
    _call(service, identity)

    credential = provider_fleet.CredentialRepository(db_session).all_credentials()[0]
    ciphertext = credential.encrypted_secret
    outcome = provider_fleet.remove_credential(db_session, settings, credential)

    assert outcome == "retired"
    retained = db_session.get(ProviderCredential, credential.id)
    assert retained is not None, "a used key must keep its row for provenance"
    assert retained.health == "DISABLED"
    assert retained.encrypted_secret != ciphertext
    assert (
        db_session.scalar(
            select(ProviderUsage).where(ProviderUsage.credential_id == retained.id)
        )
        is not None
    )


def test_removing_an_unused_key_deletes_its_row(db_session, identity) -> None:
    settings = _settings()
    _register(db_session, settings, "unused-proj", 1)
    credential = provider_fleet.CredentialRepository(db_session).all_credentials()[0]

    assert provider_fleet.remove_credential(db_session, settings, credential) == "deleted"
    assert db_session.get(ProviderCredential, credential.id) is None


def test_usage_ledger_records_project_tokens_and_purpose(db_session, identity) -> None:
    settings = _settings()
    _register(db_session, settings, "ledger-proj", 1)
    service = _service(db_session, FakeProvider('{"questions": []}'), settings)
    result = _call(service, identity)

    row = db_session.scalar(select(ProviderUsage).where(ProviderUsage.id == result.usage_id))
    assert row is not None
    assert row.project_id == "ledger-proj"
    assert row.input_tokens == 100 and row.output_tokens == 50
    assert row.retry_count == 0
    assert row.purpose == "BLUEPRINT_EXTRACTION"


def test_estimator_never_presents_a_policy_limit_as_google_confirmed(db_session) -> None:
    model = get_settings().provider.model_primary
    policy = QuotaEstimator(db_session, _settings()).estimate(
        project_id="none-proj", model=model
    )
    assert policy.confidence == "ESTIMATED"
    assert policy.requests_per_minute.confidence == "ESTIMATED"
    # No token limit is known, so no percentage is invented for it.
    assert policy.tokens_per_minute.confidence == "UNKNOWN"
    assert policy.tokens_per_minute.limit is None
    assert policy.tokens_per_minute.remaining is None

    confirmed = QuotaEstimator(
        db_session,
        _settings(
            limits={
                model: ModelQuota(
                    requests_per_minute=15,
                    requests_per_day=1500,
                    tokens_per_minute=1_000_000,
                    source="google",
                )
            }
        ),
    ).estimate(project_id="none-proj", model=model)
    assert confirmed.confidence == "CONFIRMED"
    assert confirmed.requests_per_day.remaining == 1500


def test_estimate_counts_reservations_per_project(db_session, identity) -> None:
    settings = _settings(rpm=10)
    keys = _register(db_session, settings, "count-proj", 4)
    service = _service(db_session, FakeProvider('{"questions": []}'), settings)
    for _ in range(3):
        _call(service, identity)

    model = get_settings().provider.model_primary
    estimate = QuotaEstimator(db_session, settings).estimate(
        project_id="count-proj", model=model
    )
    assert estimate.requests_per_minute.used == 3
    assert estimate.requests_per_minute.remaining == 7
    assert len(keys) == 4


def test_daily_window_resets_at_midnight_pacific() -> None:
    moment = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    assert day_start(moment, "America/Los_Angeles") == datetime(
        2026, 11, 7, 8, 0, tzinfo=UTC
    )
    assert next_reset(moment, "America/Los_Angeles") == datetime(
        2026, 11, 8, 8, 0, tzinfo=UTC
    )
    # A bad zone degrades to UTC instead of crashing the dashboard.
    assert next_reset(moment, "Not/AZone") == datetime(2026, 11, 8, 0, 0, tzinfo=UTC)


def test_overview_and_alerts_reflect_recorded_state(db_session, identity) -> None:
    settings = _settings()
    _register(db_session, settings, "view-proj", 3)
    keys = _register(db_session, settings, "dark-proj", 2)
    for key in keys:
        provider_fleet.set_enabled(db_session, key, enabled=False)

    overview = provider_fleet.fleet_overview(db_session, settings)
    assert overview["keys_total"] == 5
    assert overview["projects"] == 2
    assert overview["keys_by_health"]["DISABLED"] == 2

    alerts = provider_fleet.fleet_alerts(db_session, settings)
    assert any(alert["kind"] == "project_unusable" for alert in alerts)


def test_admin_api_is_closed_to_workspace_owners(client, identity, auth_headers) -> None:
    response = client.get(
        "/api/v1/admin/providers/overview", headers=auth_headers(identity.user_a)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_admin_api_never_returns_the_key(client, identity, auth_headers, db_session) -> None:
    tenant = Tenant(name="Platform", slug="platform")
    db_session.add(tenant)
    db_session.flush()
    admin = User(tenant_id=tenant.id, subject="platform-admin", role="ADMIN")
    db_session.add(admin)
    db_session.commit()

    headers = auth_headers(admin)
    created = client.post(
        "/api/v1/admin/providers/keys",
        headers=headers,
        json={
            "project_id": "api-proj",
            "api_key": "AIza-secret-value-that-must-not-leak",
            "label": "operator key",
            "tier": "UNKNOWN",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["key_fingerprint"]
    assert "api_key" not in body
    assert "AIza-secret-value-that-must-not-leak" not in created.text

    listing = client.get("/api/v1/admin/providers/keys", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert "AIza-secret-value-that-must-not-leak" not in listing.text

    overview = client.get("/api/v1/admin/providers/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["keys_total"] == 1

    disabled = client.post(
        f"/api/v1/admin/providers/keys/{body['id']}/enabled",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["health"] == "DISABLED"

    removed = client.delete(
        f"/api/v1/admin/providers/keys/{body['id']}", headers=headers
    )
    assert removed.status_code == 204
    assert client.get("/api/v1/admin/providers/keys", headers=headers).json()["total"] == 0


def test_validation_reports_provider_unavailable_when_not_configured(
    db_session, identity
) -> None:
    from app.providers.base import ProviderNotConfigured

    class Unconfigured:
        name = "unconfigured"

        def generate(self, request, api_key):
            raise ProviderNotConfigured("The live provider is disabled in this build.")

    settings = _settings()
    credential = provider_fleet.add_credential(
        db_session, settings, project_id="val-proj", api_key=_key("val-proj", 0)
    )
    with pytest.raises(AppError) as error:
        provider_fleet.validate_credential(db_session, settings, Unconfigured(), credential)
    assert error.value.code.value == "PROVIDER_UNAVAILABLE"


def test_validation_success_marks_key_healthy_and_logs_the_probe(
    db_session, identity
) -> None:
    settings = _settings()
    credential = provider_fleet.add_credential(
        db_session, settings, project_id="val-proj", api_key=_key("val-proj", 1)
    )
    assert credential.health == "UNKNOWN"

    result = provider_fleet.validate_credential(
        db_session, settings, FakeProvider("ok"), credential
    )
    assert result["valid"] is True
    assert credential.health == "HEALTHY"

    probe = db_session.scalar(
        select(ProviderUsage).where(ProviderUsage.purpose == "validate")
    )
    assert probe is not None and probe.project_id == "val-proj"


def _now() -> datetime:
    from app.core.ids import utcnow

    return utcnow()
