from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import PromptVersion, ProviderCredential, ProviderUsage
from app.prompts.registry import PromptRegistry
from app.providers.errors import ProviderAuthenticationError
from app.services.provider_calls import ProviderCallService
from sqlalchemy import select

from tests.support import FakeProvider


def _service(db_session, provider, settings=None):
    settings = settings or get_settings()
    return ProviderCallService(
        db_session,
        settings,
        provider,
        PromptRegistry(settings.provider.prompt_root),
    )


def test_usage_records_tokens_cost_and_prompt_version(
    identity, provider_credential, db_session
) -> None:
    fake = FakeProvider('{"questions": []}')
    result = _service(db_session, fake).call(
        tenant_id=identity.tenant_a.id,
        purpose="BLUEPRINT_EXTRACTION",
        prompt_id="blueprint_extraction",
    )
    assert result.usage_id
    assert result.cost_usd is not None and result.cost_usd > 0
    usage = db_session.scalar(select(ProviderUsage).where(ProviderUsage.id == result.usage_id))
    assert usage is not None
    assert usage.prompt_version_id is not None
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.reported is True
    prompt = db_session.scalar(
        select(PromptVersion).where(PromptVersion.id == usage.prompt_version_id)
    )
    assert prompt is not None
    assert prompt.prompt_id == "blueprint_extraction"
    assert prompt.version == 1


def test_quota_reservation_blocks_a_second_call(identity, provider_credential, db_session) -> None:
    settings = get_settings().model_copy(
        update={"quota": get_settings().quota.model_copy(update={"requests_per_minute": 1})}
    )
    fake = FakeProvider("{}")
    service = _service(db_session, fake, settings)
    service.call(
        tenant_id=identity.tenant_a.id,
        purpose="BLUEPRINT_EXTRACTION",
        prompt_id="blueprint_extraction",
    )
    with pytest.raises(AppError) as error:
        service.call(
            tenant_id=identity.tenant_a.id,
            purpose="BLUEPRINT_EXTRACTION",
            prompt_id="blueprint_extraction",
        )
    assert error.value.code.value == "PROVIDER_UNAVAILABLE"


def test_authentication_failure_invalidates_the_credential(
    identity, provider_credential, db_session
) -> None:
    fake = FakeProvider(error=ProviderAuthenticationError("bad key"))
    with pytest.raises(AppError):
        _service(db_session, fake).call(
            tenant_id=identity.tenant_a.id,
            purpose="BLUEPRINT_EXTRACTION",
            prompt_id="blueprint_extraction",
        )
    db_session.expire_all()
    credential = db_session.get(ProviderCredential, provider_credential.id)
    assert credential is not None
    assert credential.health == "INVALID"
    failure = db_session.scalar(
        select(ProviderUsage).where(ProviderUsage.success.is_(False)).limit(1)
    )
    assert failure is not None
    assert failure.error_class == "ProviderAuthenticationError"
