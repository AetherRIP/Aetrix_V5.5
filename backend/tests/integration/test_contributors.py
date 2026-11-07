"""Multi-contributor key pool: attribution, revocation, quota and statistics.

The invariants under test are the ones the brief names:

* a key belongs to the person who lent it, and consent is recorded before use;
* withdrawal stops new leases immediately and never exposes or keeps a reusable
  secret;
* one contributor's failure (bad key, suspension, withdrawal) cannot stop the
  pipeline while another contributor still has an eligible key;
* capacity is counted per Google Cloud project, so contributors sharing a
  project never multiply its allowance;
* usage is attributable to contributor, key, project, model and job.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import SecretBox
from app.db.models import (
    CorrectionJob,
    ProviderContributor,
    ProviderCredential,
    ProviderUsage,
    Tenant,
    User,
)
from app.prompts.registry import PromptRegistry
from app.providers.base import LLMResponse, TokenUsage
from app.providers.errors import ProviderAuthenticationError
from app.services import contributors, provider_fleet
from app.services.provider_calls import ProviderCallService
from pydantic import SecretStr
from sqlalchemy import select

from tests.support import FakeProvider

CONSENT = "2026-11-01"


class KeyAwareProvider:
    """Fails for named keys and succeeds for the rest — one contributor's outage."""

    name = "fake"

    def __init__(self, bad_keys: set[str]) -> None:
        self.bad_keys = bad_keys
        self.keys: list[str] = []

    def generate(self, request, api_key) -> LLMResponse:
        raw = api_key.get_secret_value()
        self.keys.append(raw)
        if raw in self.bad_keys:
            raise ProviderAuthenticationError("key revoked upstream")
        return LLMResponse(
            text="{}",
            model=request.model,
            usage=TokenUsage(input_tokens=100, output_tokens=50, cached_tokens=0),
            finish_reason="STOP",
            provider_request_id="fake-request",
            latency_ms=1,
        )


def _settings(*, rpm: int = 100, rpd: int = 5000):
    base = get_settings()
    return base.model_copy(
        update={
            "quota": base.quota.model_copy(
                update={"requests_per_minute": rpm, "requests_per_day": rpd, "model_limits": {}}
            )
        }
    )


def _service(db_session, provider, settings) -> ProviderCallService:
    return ProviderCallService(
        db_session, settings, provider, PromptRegistry(settings.provider.prompt_root)
    )


def _call(service, identity, *, job_id: uuid.UUID | None = None):
    return service.call(
        tenant_id=identity.tenant_a.id,
        purpose="BLUEPRINT_EXTRACTION",
        prompt_id="blueprint_extraction",
        job_id=job_id,
    )


def _contributor(db_session, *, name="Ada", user=None) -> ProviderContributor:
    return contributors.create_contributor(
        db_session,
        display_name=name,
        consent_version=CONSENT,
        consent_reference=f"agreement-{name}",
        user_id=user.id if user is not None else None,
    )


def _key(db_session, settings, contributor, project_id: str, index: int) -> ProviderCredential:
    return contributors.register_key(
        db_session,
        settings,
        contributor,
        project_id=project_id,
        api_key=SecretStr(f"AIza-{contributor.display_name}-{project_id}-{index}"),
        label=f"{contributor.display_name}-{index}",
    )


def test_a_contribution_cannot_exist_without_recorded_consent(db_session) -> None:
    with pytest.raises(AppError) as error:
        contributors.create_contributor(
            db_session, display_name="Ada", consent_version="   "
        )
    assert error.value.code.value == "VALIDATION_ERROR"

    recorded = _contributor(db_session)
    assert recorded.consent_version == CONSENT
    assert recorded.consent_at is not None
    assert recorded.status == "ACTIVE"


def test_keys_carry_their_contributor_and_may_span_projects(db_session) -> None:
    settings = _settings()
    ada = _contributor(db_session, name="Ada")
    grace = _contributor(db_session, name="Grace")

    first = _key(db_session, settings, ada, "proj-one", 0)
    second = _key(db_session, settings, ada, "proj-two", 1)
    third = _key(db_session, settings, grace, "proj-one", 2)

    assert first.contributor_id == ada.id
    assert second.contributor_id == ada.id
    assert third.contributor_id == grace.id
    assert [key.project_id for key in contributors.contributor_keys(db_session, ada)] == [
        "proj-one",
        "proj-two",
    ]


def test_two_contributors_in_one_project_share_one_quota_pool(db_session, identity) -> None:
    settings = _settings(rpm=1)
    ada = _contributor(db_session, name="Ada")
    grace = _contributor(db_session, name="Grace")
    _key(db_session, settings, ada, "shared", 0)
    _key(db_session, settings, grace, "shared", 1)

    service = _service(db_session, FakeProvider("{}"), settings)
    _call(service, identity)

    # Two contributors, two keys, one project: the second request has no pool.
    with pytest.raises(AppError) as error:
        _call(service, identity)
    assert error.value.code.value == "PROVIDER_UNAVAILABLE"


def test_withdrawal_revokes_keys_and_stops_leasing_immediately(db_session, identity) -> None:
    settings = _settings()
    ada = _contributor(db_session, name="Ada")
    credential = _key(db_session, settings, ada, "ada-proj", 0)
    service = _service(db_session, FakeProvider("{}"), settings)
    _call(service, identity)

    revoked = contributors.withdraw_contributor(
        db_session, settings, ada, reason="Taking my key back"
    )

    assert revoked == 1
    db_session.refresh(credential)
    assert credential.revoked_at is not None
    assert credential.revoked_reason == "Taking my key back"
    assert credential.health == "DISABLED"
    box = SecretBox(settings.security.encryption_key.get_secret_value())
    assert box.decrypt(credential.encrypted_secret) == ""
    assert ada.status == "WITHDRAWN"
    assert ada.withdrawn_at is not None

    with pytest.raises(AppError) as error:
        _call(service, identity)
    assert error.value.code.value == "PROVIDER_UNAVAILABLE"


def test_a_revoked_key_cannot_be_re_enabled(db_session) -> None:
    settings = _settings()
    ada = _contributor(db_session)
    credential = _key(db_session, settings, ada, "proj", 0)
    contributors.revoke_credential(db_session, settings, credential, reason="done")

    with pytest.raises(AppError) as error:
        provider_fleet.set_enabled(db_session, credential, enabled=True)
    assert error.value.code.value == "CONFLICT"


def test_suspension_is_reversible_and_eligibility_follows_status(db_session, identity) -> None:
    settings = _settings()
    ada = _contributor(db_session, name="Ada")
    credential = _key(db_session, settings, ada, "ada-proj", 0)
    service = _service(db_session, FakeProvider("{}"), settings)
    _call(service, identity)

    contributors.suspend_contributor(db_session, ada, reason="Policy review")
    assert ada.status == "SUSPENDED"
    db_session.refresh(credential)
    assert credential.health == "DISABLED"
    # Suspension is reversible, so the ciphertext is kept.
    assert credential.encrypted_secret

    with pytest.raises(AppError):
        _call(service, identity)

    contributors.reinstate_contributor(db_session, ada)
    db_session.refresh(credential)
    assert ada.status == "ACTIVE"
    # A paused key must prove itself again rather than assume it still works.
    assert credential.health == "UNKNOWN"
    _call(service, identity)


def test_one_contributors_broken_keys_do_not_stop_another_contributor(
    db_session, identity
) -> None:
    settings = _settings(rpm=100)
    ada = _contributor(db_session, name="Ada")
    grace = _contributor(db_session, name="Grace")
    _key(db_session, settings, ada, "ada-proj", 0)
    _key(db_session, settings, grace, "grace-proj", 1)

    provider = KeyAwareProvider({"AIza-Ada-ada-proj-0"})
    result = _call(_service(db_session, provider, settings), identity)

    row = db_session.scalar(select(ProviderUsage).where(ProviderUsage.id == result.usage_id))
    assert row is not None
    assert row.project_id == "grace-proj"
    assert row.contributor_id == grace.id
    assert row.success is True


def test_unattributed_platform_keys_stay_eligible(db_session, identity) -> None:
    settings = _settings()
    credential = provider_fleet.add_credential(
        db_session, settings, project_id="platform-proj", api_key=SecretStr("AIza-platform")
    )
    assert credential.contributor_id is None

    result = _call(_service(db_session, FakeProvider("{}"), settings), identity)
    row = db_session.scalar(select(ProviderUsage).where(ProviderUsage.id == result.usage_id))
    assert row is not None and row.contributor_id is None


def test_usage_is_attributed_to_contributor_key_project_model_and_job(
    db_session, identity, paper
) -> None:
    settings = _settings()
    ada = _contributor(db_session, name="Ada")
    credential = _key(db_session, settings, ada, "ada-proj", 0)

    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state="CORRECTING",
        idempotency_key="contributor-attribution",
        request_hash="c" * 64,
    )
    db_session.add(job)
    db_session.commit()

    result = _call(_service(db_session, FakeProvider("{}"), settings), identity, job_id=job.id)
    row = db_session.scalar(select(ProviderUsage).where(ProviderUsage.id == result.usage_id))

    assert row is not None
    assert row.contributor_id == ada.id
    assert row.credential_id == credential.id
    assert row.project_id == "ada-proj"
    assert row.model == settings.provider.model_primary
    assert row.job_id == job.id


def test_summary_reports_aggregate_and_individual_statistics(db_session, identity) -> None:
    settings = _settings()
    ada = _contributor(db_session, name="Ada")
    grace = _contributor(db_session, name="Grace")
    _key(db_session, settings, ada, "shared", 0)
    _key(db_session, settings, ada, "ada-only", 1)
    _key(db_session, settings, grace, "shared", 2)
    provider_fleet.add_credential(
        db_session, settings, project_id="platform", api_key=SecretStr("AIza-platform-own")
    )

    _call(_service(db_session, FakeProvider("{}"), settings), identity)

    summary = contributors.contribution_summary(db_session, settings)
    aggregate = summary["aggregate"]
    assert aggregate["contributors_total"] == 2
    assert aggregate["contributors_by_status"]["ACTIVE"] == 2
    assert aggregate["keys_contributed"] == 3
    assert aggregate["platform_keys"] == 1
    assert aggregate["projects"] == 2
    assert aggregate["shared_projects"] == 1
    assert aggregate["requests_in_window"] == 1
    assert aggregate["requests_today"] == 1

    rows = {row["contributor"].display_name: row for row in summary["contributors"]}
    assert rows["Ada"]["keys_total"] == 2
    assert rows["Ada"]["projects"] == ["ada-only", "shared"]
    assert rows["Ada"]["window"]["requests"] == 1
    assert rows["Grace"]["window"]["requests"] == 0


def test_capacity_is_counted_per_project_not_per_key(db_session) -> None:
    settings = _settings(rpm=10, rpd=100)
    ada = _contributor(db_session, name="Ada")
    grace = _contributor(db_session, name="Grace")

    _key(db_session, settings, ada, "shared", 0)
    one_key = contributors.capacity(db_session, settings)

    for index in range(1, 6):
        _key(db_session, settings, grace, "shared", index)
    six_keys = contributors.capacity(db_session, settings)

    model = settings.provider.model_primary
    one_row = next(row for row in one_key["models"] if row["model"] == model)
    six_row = next(row for row in six_keys["models"] if row["model"] == model)

    assert one_row["totals"]["requests_per_minute_remaining"] == 10
    assert six_row["totals"]["requests_per_minute_remaining"] == 10
    assert six_row["projects"][0]["keys"] == 6
    assert six_row["projects"][0]["contributors"] == 2
    assert "Keys are never added up" in six_keys["note"]


def test_admin_can_manage_contributors_and_never_sees_key_material(
    client, db_session, auth_headers
) -> None:
    tenant = Tenant(name="Platform", slug="platform-contrib")
    db_session.add(tenant)
    db_session.flush()
    admin = User(tenant_id=tenant.id, subject="contrib-admin", role="ADMIN")
    db_session.add(admin)
    db_session.commit()
    headers = auth_headers(admin)

    created = client.post(
        "/api/v1/admin/providers/contributions",
        headers=headers,
        json={
            "display_name": "Ada Lovelace",
            "consent_version": CONSENT,
            "consent_reference": "email-2026-11-07",
        },
    )
    assert created.status_code == 201
    contributor_id = created.json()["id"]
    assert created.json()["status"] == "ACTIVE"

    secret = "AIza-contributed-secret-that-must-not-leak"
    key = client.post(
        f"/api/v1/admin/providers/contributions/{contributor_id}/keys",
        headers=headers,
        json={"project_id": "contrib-proj", "api_key": secret, "tier": "FREE"},
    )
    assert key.status_code == 201
    assert secret not in key.text
    credential_id = key.json()["id"]
    assert key.json()["contributor_id"] == contributor_id

    summary = client.get("/api/v1/admin/providers/contributions", headers=headers)
    assert summary.status_code == 200
    assert secret not in summary.text
    assert summary.json()["aggregate"]["keys_contributed"] == 1
    assert summary.json()["contributors"][0]["contributor"]["display_name"] == "Ada Lovelace"

    suspended = client.post(
        f"/api/v1/admin/providers/contributions/{contributor_id}/suspend",
        headers=headers,
        json={"reason": "Awaiting consent refresh"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "SUSPENDED"

    reinstated = client.post(
        f"/api/v1/admin/providers/contributions/{contributor_id}/reinstate",
        headers=headers,
    )
    assert reinstated.json()["status"] == "ACTIVE"

    revoked = client.delete(
        f"/api/v1/admin/providers/contributions/{contributor_id}/keys/{credential_id}",
        headers=headers,
    )
    assert revoked.status_code == 204

    withdrawn = client.post(
        f"/api/v1/admin/providers/contributions/{contributor_id}/withdraw",
        headers=headers,
        json={"reason": "Contributor left the programme"},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"



def test_workspace_owner_cannot_administer_contributions(
    client, identity, auth_headers
) -> None:
    response = client.get(
        "/api/v1/admin/providers/contributions", headers=auth_headers(identity.user_a)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_a_contributor_can_withdraw_their_own_keys(client, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    secret = "AIza-self-service-key-value"

    registered = client.post(
        "/api/v1/contributions/me/keys",
        headers=headers,
        json={
            "project_id": "self-proj",
            "api_key": secret,
            "display_name": "Teacher A",
            "consent_version": CONSENT,
        },
    )
    assert registered.status_code == 201
    body = registered.json()
    assert secret not in registered.text
    assert body["contributor"]["status"] == "ACTIVE"
    assert body["keys"][0]["project_id"] == "self-proj"
    assert "api_key" not in body["keys"][0]

    mine = client.get("/api/v1/contributions/me", headers=headers)
    assert mine.status_code == 200
    credential_id = mine.json()["keys"][0]["id"]

    revoked = client.delete(
        f"/api/v1/contributions/me/keys/{credential_id}", headers=headers
    )
    assert revoked.status_code == 204
    after = client.get("/api/v1/contributions/me", headers=headers).json()
    assert after["keys"][0]["revoked_at"] is not None

    withdrawn = client.post(
        "/api/v1/contributions/me/withdraw", headers=headers, json={"reason": "No longer able"}
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"

    again = client.post(
        "/api/v1/contributions/me/keys",
        headers=headers,
        json={
            "project_id": "self-proj",
            "api_key": "AIza-another-key-value",
            "display_name": "Teacher A",
            "consent_version": CONSENT,
        },
    )
    assert again.status_code == 409


def test_one_contributor_cannot_touch_anothers_key(
    client, identity, auth_headers, db_session
) -> None:
    other = User(tenant_id=identity.tenant_b.id, subject="teacher-c", role="OWNER")
    db_session.add(other)
    db_session.commit()

    registered = client.post(
        "/api/v1/contributions/me/keys",
        headers=auth_headers(other),
        json={
            "project_id": "other-proj",
            "api_key": "AIza-other-secret-value",
            "display_name": "Teacher C",
            "consent_version": CONSENT,
        },
    )
    assert registered.status_code == 201
    foreign_id = registered.json()["keys"][0]["id"]

    # The first account must have its own record for the ownership check to run.
    own = client.post(
        "/api/v1/contributions/me/keys",
        headers=auth_headers(identity.user_a),
        json={
            "project_id": "own-proj",
            "api_key": "AIza-own-secret-value",
            "display_name": "Teacher A",
            "consent_version": CONSENT,
        },
    )
    assert own.status_code == 201

    response = client.delete(
        f"/api/v1/contributions/me/keys/{foreign_id}", headers=auth_headers(identity.user_a)
    )
    # Another contributor's key is indistinguishable from a missing one.
    assert response.status_code == 404
    assert client.get(
        "/api/v1/contributions/me", headers=auth_headers(other)
    ).json()["keys"][0]["revoked_at"] is None
