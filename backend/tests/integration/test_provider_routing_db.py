"""Provider routing against a real PostgreSQL database.

The unit suite proves the routing *decision*.  This suite proves that the
production service — real credential rows, real reservations, the real
append-only usage ledger — actually acts on it.  Budgets and quarantine are
properties of a credential pool, while a 429 is answered by advancing the model
chain, never by leasing a sibling key that may share the same Google project.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from app.core.config import ModelChainEntry, get_settings
from app.core.errors import AppError
from app.core.ids import utcnow
from app.core.security import SecretBox, fingerprint
from app.db.models import CorrectionJob, ProviderCredential, ProviderUsage
from app.db.repositories import JobRepository
from app.jobs.states import JobState
from app.providers.base import LLMResponse, TokenUsage
from app.providers.errors import ProviderQuotaError, ProviderServerError
from app.services.provider_calls import ProviderCallService
from sqlalchemy import select

MODEL_A = "gemini-3.6-flash"
MODEL_B = "gemini-2.5-flash"
#: The verified blind-transcription checker.
TRANSCRIPTION_CHECKER = "gemini-3.1-flash-lite"


class _Registry:
    def load(self, prompt_id: str, version: int | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            prompt_id=prompt_id,
            version=version or 1,
            content="prompt body",
            content_hash="0" * 64,
            path=f"{prompt_id}/v1.md",
            model_role="primary",
        )


class _Provider:
    """A provider whose replies are scripted; nothing leaves this machine."""

    name = "scripted"

    def __init__(self, script: dict[str, list[object]]) -> None:
        self.script = {model: list(replies) for model, replies in script.items()}
        self.calls: list[str] = []

    def generate(self, request, api_key):
        self.calls.append(request.model)
        replies = self.script.get(request.model) or ["{}"]
        reply = replies.pop(0) if replies else "{}"
        if isinstance(reply, BaseException):
            raise reply
        return LLMResponse(
            text=str(reply),
            model=request.model,
            usage=TokenUsage(input_tokens=10, output_tokens=5, cached_tokens=0),
            finish_reason="STOP",
            provider_request_id=f"req-{len(self.calls)}",
            latency_ms=3,
        )


def _credential(
    db_session,
    identity,
    project_id: str,
    model_access: list[str],
    *,
    last_success_at=None,
) -> ProviderCredential:
    box = SecretBox(get_settings().security.encryption_key.get_secret_value())
    key = f"key-{uuid.uuid4()}"
    identifier = uuid.uuid4()
    row = ProviderCredential(
        id=identifier,
        pool_id=f"gemini-key-{identifier}",
        tenant_id=identity.tenant_a.id,
        project_id=project_id,
        account_label=f"label-{uuid.uuid4().hex[:8]}",
        key_fingerprint=fingerprint(key),
        encrypted_secret=box.encrypt(key),
        model_access=list(model_access),
        health="HEALTHY",
        last_success_at=last_success_at,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _settings(*, max_attempts: int = 2, chain: list[str] | None = None):
    """A chain that starts exactly where the test expects.

    ``model_primary`` is pinned to the first chain model so the operator's saved
    selection, which the service prepends, de-duplicates against it instead of
    inserting an unrelated model at position 0.
    """

    models = chain or [MODEL_A, MODEL_B]
    base = get_settings()
    provider = base.provider.model_copy(
        update={
            "model_primary": models[0],
            "model_chains": {
                "primary": [ModelChainEntry(model=model) for model in models],
                "review": [ModelChainEntry(model="gemini-3.1-pro-preview")],
                # The blind transcription is performed by the transcription
                # checker; a marking model is only reserved for that role.
                "lightweight": [ModelChainEntry(model=TRANSCRIPTION_CHECKER)],
            },
            "max_attempts": max_attempts,
            "retry_backoff_seconds": 0.0,
        }
    )
    return base.model_copy(update={"provider": provider})


def _service(db_session, provider, settings) -> ProviderCallService:
    return ProviderCallService(db_session, settings, provider, _Registry())


def _rows(db_session) -> list[ProviderUsage]:
    return list(
        db_session.scalars(select(ProviderUsage).order_by(ProviderUsage.created_at))
    )


def test_a_429_is_not_answered_by_leasing_a_sibling_key(db_session, identity):
    """A quota refusal quarantines the pool that saw it and stops there.

    There are three spare keys, including one that names another project.  None
    is leased: Aetrix cannot establish that a spare key has a Google allowance
    of its own, so spending it would be quota evasion rather than recovery.
    """

    now = utcnow()
    first = _credential(
        db_session, identity, "project-one", [MODEL_A, MODEL_B], last_success_at=now
    )
    _credential(
        db_session,
        identity,
        "project-one",
        [MODEL_A, MODEL_B],
        last_success_at=now - timedelta(minutes=1),
    )
    _credential(db_session, identity, "project-two", [MODEL_A, MODEL_B])

    provider = _Provider({MODEL_A: [ProviderQuotaError("quota", status_code=429)]})
    service = _service(db_session, provider, _settings(chain=[MODEL_A]))

    with pytest.raises(AppError):
        service.call(
            tenant_id=identity.tenant_a.id,
            purpose="marking",
            prompt_id="aetrix_v5_5_marking",
        )

    rows = _rows(db_session)
    assert [row.project_id for row in rows] == ["project-one"]
    assert [row.routing_decision for row in rows] == ["STOP"]
    assert len(provider.calls) == 1
    db_session.refresh(first)
    assert first.cooldown_kind == "QUOTA"
    assert first.last_quota_exhausted_at is not None
    assert first.cooldown_until is not None


def test_a_429_never_reaches_a_model_that_may_not_mark(db_session, identity):
    """A chain entry the permission table forbids is not a fallback.

    The configured chain names the review model after the marking model.  Only
    ``gemini-3.6-flash`` may mark, so the routing boundary filters the chain to
    one entry: a 429 stops the operation and the review model is never asked to
    mark a paper.  A genuine second marking model would be a separate allowance;
    a model that is not permitted to mark is not one at all.
    """

    now = utcnow()
    _credential(db_session, identity, "project-one", [MODEL_A, MODEL_B], last_success_at=now)
    _credential(
        db_session,
        identity,
        "project-one",
        [MODEL_A, MODEL_B],
        last_success_at=now - timedelta(minutes=1),
    )

    provider = _Provider(
        {
            MODEL_A: [ProviderQuotaError("quota", status_code=429)],
            MODEL_B: ["{}"],
        }
    )
    service = _service(db_session, provider, _settings())

    with pytest.raises(AppError) as error:
        service.call(
            tenant_id=identity.tenant_a.id, purpose="marking", prompt_id="aetrix_v5_5_marking"
        )

    rows = _rows(db_session)
    assert [row.model for row in rows] == [MODEL_A]
    assert [row.routing_decision for row in rows] == ["STOP"]
    assert [row.model_chain_position for row in rows] == [0]
    assert {row.project_id for row in rows} == {"project-one"}
    # Neither the unpermitted model nor the sibling key was ever called.
    assert provider.calls == [MODEL_A]
    assert error.value.code.value == "PROVIDER_UNAVAILABLE"


def test_the_ledger_labels_an_unpriced_model_instead_of_pricing_it_at_zero(
    db_session, identity
):
    _credential(db_session, identity, "project-one", [TRANSCRIPTION_CHECKER])
    provider = _Provider({TRANSCRIPTION_CHECKER: ["{}"]})
    base = _settings()
    unpriced = base.model_copy(
        update={
            "provider": base.provider.model_copy(update={"model_rates": {}}),
        }
    )
    service = _service(db_session, provider, unpriced)

    # The review model may not mark, so this call states the purpose that
    # actually routes it: an unpriced model still has to be *permitted* for the
    # work before its cost can be labelled.
    result = service.call(
        tenant_id=identity.tenant_a.id,
        purpose="transcription",
        prompt_id="aetrix_v5_5_transcription",
    )

    row = db_session.scalars(select(ProviderUsage)).one()
    assert result.cost_usd is None
    assert row.cost_usd is None
    assert row.cost_status == "COST_UNKNOWN"
    # The tokens are still real: an unknown price is not unknown usage.
    assert (row.input_tokens, row.output_tokens) == (10, 5)


def test_a_priced_model_records_a_known_cost(db_session, identity):
    _credential(db_session, identity, "project-one", [MODEL_A])
    provider = _Provider({MODEL_A: ["{}"]})
    service = _service(db_session, provider, _settings())

    service.call(
        tenant_id=identity.tenant_a.id, purpose="marking", prompt_id="aetrix_v5_5_marking"
    )

    row = db_session.scalars(select(ProviderUsage)).one()
    assert row.cost_status == "KNOWN"
    assert row.cost_usd is not None and row.cost_usd > 0


def test_a_failed_attempt_is_labelled_rather_than_recorded_as_a_free_call(
    db_session, identity
):
    _credential(db_session, identity, "project-one", [MODEL_A])
    provider = _Provider({MODEL_A: [ProviderServerError("down", status_code=503)]})
    service = _service(
        db_session, provider, _settings(max_attempts=1, chain=[MODEL_A])
    )

    with pytest.raises(AppError):
        service.call(
            tenant_id=identity.tenant_a.id,
            purpose="marking",
            prompt_id="aetrix_v5_5_marking",
        )

    row = db_session.scalars(select(ProviderUsage)).one()
    assert row.success is False
    assert row.cost_usd is None
    assert row.cost_status == "COST_UNKNOWN"
    # A provider status enum is not a finish reason; the failure carries it in
    # provider_code and the response had no finish reason at all.
    assert row.finish_reason is None
    assert row.routing_decision == "STOP"
    assert row.error_category == "provider_server"


def test_the_token_allowance_is_enforced_per_credential_pool(db_session, identity):
    """RPM alone is not the ceiling: one large call can spend the whole TPM."""

    from app.core.config import ModelQuota
    from app.db.models import ProviderUsage as Usage
    from app.services.provider_calls import CredentialPool

    base = get_settings()
    settings = base.model_copy(
        update={
            "quota": base.quota.model_copy(
                update={
                    "model_limits": {
                        MODEL_A: ModelQuota(
                            requests_per_minute=100,
                            requests_per_day=100,
                            tokens_per_minute=1_000,
                        )
                    }
                }
            )
        }
    )
    credential = _credential(db_session, identity, "project-one", [MODEL_A])
    pool = CredentialPool(db_session, settings)

    pool.acquire(tenant_id=identity.tenant_a.id, model=MODEL_A, purpose="marking")

    db_session.add(
        Usage(
            tenant_id=identity.tenant_a.id,
            credential_id=credential.id,
            project_id="project-one",
            provider="scripted",
            model=MODEL_A,
            purpose="marking",
            success=True,
            input_tokens=1_200,
            output_tokens=300,
        )
    )
    db_session.commit()

    with pytest.raises(AppError):
        pool.acquire(tenant_id=identity.tenant_a.id, model=MODEL_A, purpose="marking")


def test_a_refused_run_records_when_it_stopped(db_session, identity, paper):
    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state=JobState.CORRECTING.value,
        idempotency_key=f"route-{uuid.uuid4()}",
        request_hash="c" * 64,
        max_attempts=3,
    )
    db_session.add(job)
    db_session.commit()
    repository = JobRepository(db_session)

    repository.transition(
        job,
        JobState.REVIEW_REQUIRED,
        detail={"event": "refused"},
        actor="test",
    )
    db_session.commit()
    assert job.finished_at is not None, "a refused run has stopped executing"

    # Approving it resumes execution, so the timestamp must not survive and
    # back-date the run that is now happening.
    repository.transition(
        job,
        JobState.FINALIZING,
        detail={"event": "approved"},
        actor="test",
    )
    db_session.commit()
    assert job.finished_at is None
