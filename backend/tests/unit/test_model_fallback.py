"""Model-chain fallback in the production provider call path.

Every test here drives the real ``ProviderCallService.call`` — the same method
the marking pipeline, page mapping and blueprint extraction use — with a
scripted provider and an in-memory credential pool.  Nothing is mocked at the
level of "pretend the chain ran": the assertions read the usage rows the service
actually wrote, so a fallback that did not happen cannot pass.

The scripted failures are *simulated* provider responses.  They say how the
routing reacts; they are not evidence about Google's availability.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.core.config import ModelChainEntry, get_settings
from app.core.errors import AppError, ErrorCode
from app.providers.base import LLMResponse, TokenUsage
from app.providers.circuit_breaker import CircuitBreaker
from app.providers.errors import (
    ProviderAuthenticationError,
    ProviderPermissionError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTruncatedResponse,
)
from app.providers.routing import (
    FailureKind,
    RoutingAction,
    classify_failure,
    decide,
)
from app.services.provider_calls import ProviderCallService

TENANT = uuid.uuid4()
#: A generic chain pair.  These tests exercise the routing policy, not the
#: marking-model policy; the production marking id is used so the chain is a
#: configuration the build would actually accept.
MODEL_A = "gemini-3.6-flash"
MODEL_B = "gemini-2.5-flash"
MODEL_C = "gemini-3.8-flash"
REVIEW_MODEL = "gemini-3.1-pro-preview"
DISABLED_MODEL = "gemini-3.1-flash-lite"

CHAIN_AB = [ModelChainEntry(model=MODEL_A), ModelChainEntry(model=MODEL_B)]


# -- fakes -------------------------------------------------------------------


class FakeRegistry:
    def __init__(self, model_role: str = "primary") -> None:
        self.model_role = model_role
        self.loaded: list[tuple[str, int | None]] = []

    def load(self, prompt_id: str, version: int | None = None) -> SimpleNamespace:
        self.loaded.append((prompt_id, version))
        return SimpleNamespace(
            prompt_id=prompt_id,
            version=version or 1,
            content=f"prompt body for {prompt_id}",
            content_hash="0" * 64,
            path=f"{prompt_id}/v1.md",
            model_role=self.model_role,
        )


class FakePromptVersions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_or_create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())


class FakeUsage:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, **kwargs) -> SimpleNamespace:
        self.rows.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())


class FakeCredentialRepository:
    """The one repository method the routing path asks about eligibility."""

    def __init__(self, pool: FakePool) -> None:
        self._pool = pool

    def claim_candidates(self, tenant_id, model, excluded=None):
        excluded = excluded or set()
        return [
            SimpleNamespace(id=credential_id, project_id=project_id)
            for credential_id, project_id in self._pool.keys
            if credential_id not in excluded
        ]


class FakePool:
    """Credentials with explicit project identity.

    ``keys`` is a list of (credential_id, project_id).  Two keys in one project
    are two keys and one quota pool — the distinction the routing has to respect.

    ``verified_projects`` models Google's Resource Manager answer.  ``None`` means
    "every spare project counts as verified", which keeps the older routing tests
    about rotation readable; a set means only those ids may be used for a
    cross-project quota fallback.
    """

    def __init__(
        self,
        projects: list[str],
        *,
        keys_per_model: int | None = None,
        verified_projects: set[str] | None = None,
    ) -> None:
        self.verified_projects = verified_projects
        self.allowance_checked: list[str] = []
        self.keys = [(uuid.uuid4(), project) for project in projects]
        # ``None`` means a credential can be leased again on a later attempt,
        # which is what a real pool does once an attempt has been recorded.
        self.keys_per_model = keys_per_model
        self.leases_taken: list[tuple[str, uuid.UUID]] = []
        self.projects_taken: list[str] = []
        self.failures: list[dict] = []
        self.successes: list[uuid.UUID] = []
        self.no_credential: list[str] = []
        self._taken: dict[str, int] = {}
        self.credentials = FakeCredentialRepository(self)

    def acquire(self, *, tenant_id, model, purpose, excluded=None, skip_projects=None):
        excluded = excluded or set()
        skip_projects = skip_projects or set()
        taken = self._taken.get(model, 0)
        # A real pool skips an exhausted project, not merely the key that saw the
        # 429: every key in it shares the same allowance.
        available = [
            item
            for item in self.keys
            if item[0] not in excluded and item[1] not in skip_projects
        ]
        if not available or (
            self.keys_per_model is not None and taken >= self.keys_per_model
        ):
            self.no_credential.append(model)
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "no credential available",
                details={"model": model},
            )
        credential_id, project_id = available[min(taken, len(available) - 1)]
        self._taken[model] = taken + 1
        self.leases_taken.append((model, credential_id))
        self.projects_taken.append(project_id)
        return SimpleNamespace(
            credential_id=credential_id,
            reservation_id=uuid.uuid4(),
            api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            health="HEALTHY",
            project_id=project_id,
            contributor_id=None,
        )

    def alternatives(self, *, tenant_id, model, excluded, projects_tried):
        available = [item for item in self.keys if item[0] not in excluded]
        if not available:
            return False, False
        return True, any(project not in projects_tried for _, project in available)

    def allowance_problem(self, model: str) -> str | None:
        """No allowance policy is configured in these routing tests."""

        self.allowance_checked.append(model)
        return None

    def verified_independent_project(
        self, *, tenant_id, model, excluded, projects_tried
    ) -> bool:
        spare = [
            project
            for credential_id, project in self.keys
            if credential_id not in excluded and project not in projects_tried
        ]
        if not spare:
            return False
        if self.verified_projects is None:
            return True
        return any(project in self.verified_projects for project in spare)

    def failure(self, lease, **kwargs):
        self.failures.append({"credential_id": lease.credential_id, **kwargs})

    def success(self, lease):
        self.successes.append(lease.credential_id)


class ScriptedProvider:
    """A provider whose replies per model are written by the test."""

    name = "scripted"

    def __init__(self, script: dict[str, list[object]]) -> None:
        self.script = {model: list(replies) for model, replies in script.items()}
        self.calls: list[str] = []
        self.keys_seen: list[str] = []

    def generate(self, request, api_key):
        self.calls.append(request.model)
        self.keys_seen.append(api_key.get_secret_value())
        replies = self.script.get(request.model) or []
        reply = replies.pop(0) if replies else "{}"
        if isinstance(reply, BaseException):
            raise reply
        return LLMResponse(
            text=str(reply),
            model=request.model,
            usage=TokenUsage(input_tokens=100, output_tokens=50, cached_tokens=0),
            finish_reason="STOP",
            provider_request_id=f"req-{request.model}-{len(self.calls)}",
            latency_ms=7,
        )


def _settings(*, chain: list[ModelChainEntry], max_attempts: int = 2, review_chain=None):
    base = get_settings()
    provider = base.provider.model_copy(
        update={
            "model_chains": {
                "primary": chain,
                "review": review_chain
                or [ModelChainEntry(model=REVIEW_MODEL), ModelChainEntry(model="gemini-3.6-flash")],
                "lightweight": [ModelChainEntry(model=MODEL_A)],
            },
            "max_attempts": max_attempts,
            "retry_backoff_seconds": 0.0,
        }
    )
    return base.model_copy(update={"provider": provider})


def _service(provider, *, chain, pool=None, usage=None, settings=None, role="primary"):
    settings = settings or _settings(chain=chain)
    service = ProviderCallService(
        None,
        settings,
        provider,
        FakeRegistry(role),
        pool=pool or FakePool(["project-one"]),
        usage=usage or FakeUsage(),
        prompt_versions=FakePromptVersions(),
        # A fresh breaker per test: the production one is process-wide, and an
        # open breaker from one test must not decide another test's routing.
        breaker=CircuitBreaker(threshold=3, open_seconds=300.0),
    )
    return service


def _call(service):
    return service.call(
        tenant_id=TENANT,
        purpose="marking",
        prompt_id="aetrix_v5_5_marking",
    )


# -- happy path --------------------------------------------------------------


def test_primary_model_succeeds_and_no_fallback_occurs() -> None:
    provider = ScriptedProvider({MODEL_A: ["{}"], MODEL_B: ["{}"]})
    usage = FakeUsage()
    service = _service(provider, chain=CHAIN_AB, usage=usage)

    result = _call(service)

    assert provider.calls == [MODEL_A]
    assert result.response.model == MODEL_A
    assert result.model_chain_position == 0
    assert result.models_attempted == (MODEL_A,)
    assert len(usage.rows) == 1
    assert usage.rows[0]["routing_decision"] == "SUCCESS"
    assert usage.rows[0]["model_role"] == "primary"
    assert usage.rows[0]["model_chain_position"] == 0
    assert usage.rows[0]["attempt_index"] == 0


# -- 5xx: bounded retry, then fallback ---------------------------------------


def test_a_503_is_retried_on_the_same_model_then_succeeds() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderServerError("boom", status_code=503), "{}"]}
    )
    usage = FakeUsage()
    service = _service(provider, chain=CHAIN_AB, usage=usage)

    result = _call(service)

    assert provider.calls == [MODEL_A, MODEL_A]
    assert result.response.model == MODEL_A
    assert [row["routing_decision"] for row in usage.rows] == [
        "RETRY_SAME_MODEL",
        "SUCCESS",
    ]
    assert [row["attempt_index"] for row in usage.rows] == [0, 1]


def test_a_repeated_503_is_retried_once_then_stops() -> None:
    """One retry, then refusals.  A marking chain has no second model.

    ``MODEL_B`` is named by the chain but is not the production marking model, so
    the permission gate removes it before a credential is leased.  The run fails
    with two recorded attempts rather than substituting a model the policy
    refuses.
    """

    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("boom", status_code=503),
                ProviderServerError("boom", status_code=503),
            ],
            MODEL_B: ["{}"],
        }
    )
    usage = FakeUsage()
    service = _service(provider, chain=CHAIN_AB, usage=usage)

    with pytest.raises(AppError) as error:
        _call(service)

    assert provider.calls == [MODEL_A, MODEL_A]
    assert MODEL_B not in provider.calls
    assert [row["model"] for row in usage.rows] == [MODEL_A, MODEL_A]
    assert [row["routing_decision"] for row in usage.rows] == [
        "RETRY_SAME_MODEL",
        "STOP",
    ]
    assert usage.rows[0]["error_category"] == "provider_server"
    assert error.value.code.value == "PROVIDER_UNAVAILABLE"


# -- 429: quota is a project property ---------------------------------------


def test_a_429_rotates_to_an_independent_project_credential() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderQuotaError("quota", status_code=429), "{}"]}
    )
    usage = FakeUsage()
    pool = FakePool(["project-one", "project-two"])
    service = _service(provider, chain=CHAIN_AB, pool=pool, usage=usage)

    result = _call(service)

    assert provider.calls == [MODEL_A, MODEL_A]
    assert result.response.model == MODEL_A
    assert usage.rows[0]["routing_decision"] == "ROTATE_CREDENTIAL"
    assert len({credential for _, credential in pool.leases_taken}) == 2
    # The replacement must bill against a different project: that is the only
    # thing that can recover a project-wide 429.
    assert pool.projects_taken == ["project-one", "project-two"]


def test_two_keys_in_one_project_are_not_independent_quota_pools() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderQuotaError("quota", status_code=429)]}
    )
    usage = FakeUsage()
    # Two keys, one project: swapping the key cannot recover the project ceiling.
    pool = FakePool(["project-one", "project-one"])
    service = _service(provider, chain=CHAIN_AB, pool=pool, usage=usage)

    with pytest.raises(AppError):
        _call(service)

    assert provider.calls == [MODEL_A]
    assert usage.rows[0]["routing_decision"] == "STOP"
    assert usage.rows[0]["error_category"] == "quota"
    # Nothing was leased from a second key, because a second key is not a second
    # quota pool.
    assert len(pool.leases_taken) == 1


def test_a_429_does_not_rotate_to_an_unverified_project() -> None:
    """A cross-project quota fallback needs a project Google has confirmed.

    Without verification a spare key that names another id could be a typo, a
    duplicate of the exhausted project or a deleted project; spending an attempt
    on it would be paid for with the same allowance and buy another 429.
    """

    provider = ScriptedProvider(
        {MODEL_A: [ProviderQuotaError("quota", status_code=429)]}
    )
    usage = FakeUsage()
    pool = FakePool(
        ["project-one", "project-two"], verified_projects=set()
    )
    service = _service(provider, chain=[ModelChainEntry(model=MODEL_A)], pool=pool, usage=usage)

    with pytest.raises(AppError):
        _call(service)

    assert provider.calls == [MODEL_A]
    assert usage.rows[0]["routing_decision"] == "STOP"
    assert pool.projects_taken == ["project-one"]


def test_a_429_with_no_independent_project_and_no_next_model_parks() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderQuotaError("quota", status_code=429)]}
    )
    service = _service(
        provider,
        chain=[ModelChainEntry(model=MODEL_A)],
        pool=FakePool(["project-one", "project-one"]),
    )

    with pytest.raises(AppError) as error:
        _call(service)

    assert error.value.code.value == "PROVIDER_UNAVAILABLE"
    assert provider.calls == [MODEL_A]


# -- 404 / 400: model incompatibility ---------------------------------------


def test_a_404_does_not_repeat_and_does_not_substitute_a_model() -> None:
    """An unsupported model is refused, not answered by another marking model."""

    provider = ScriptedProvider(
        {
            MODEL_A: [ProviderRequestError("gone", status_code=404)],
            MODEL_B: ["{}"],
        }
    )
    usage = FakeUsage()
    service = _service(provider, chain=CHAIN_AB, usage=usage)

    with pytest.raises(AppError):
        _call(service)

    assert provider.calls == [MODEL_A]
    assert MODEL_B not in provider.calls
    assert usage.rows[0]["error_category"] == "unsupported_model"
    assert usage.rows[0]["routing_decision"] == "STOP"


def test_a_400_incompatible_request_is_not_retried_and_not_reassigned() -> None:
    provider = ScriptedProvider(
        {
            MODEL_A: [ProviderRequestError("bad field", status_code=400)],
            MODEL_B: ["{}"],
        }
    )
    usage = FakeUsage()
    service = _service(provider, chain=CHAIN_AB, usage=usage)

    with pytest.raises(AppError):
        _call(service)

    assert provider.calls == [MODEL_A]
    assert usage.rows[0]["error_category"] == "invalid_request"
    assert usage.rows[0]["routing_decision"] == "STOP"


def test_a_400_on_the_last_model_stops_and_reports_a_configuration_problem() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderRequestError("bad field", status_code=400)]}
    )
    service = _service(provider, chain=[ModelChainEntry(model=MODEL_A)])

    with pytest.raises(AppError) as error:
        _call(service)

    assert error.value.details["failure"] == "invalid_request"


# -- 401 / 403: credential, never "the model is broken" ---------------------


def test_a_401_rotates_credentials_and_does_not_mark_the_model_unavailable() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderAuthenticationError("bad key", status_code=401), "{}"]}
    )
    usage = FakeUsage()
    pool = FakePool(["project-one", "project-one"])
    service = _service(provider, chain=CHAIN_AB, pool=pool, usage=usage)

    result = _call(service)

    assert provider.calls == [MODEL_A, MODEL_A]
    assert result.response.model == MODEL_A
    assert usage.rows[0]["error_category"] == "authentication"
    assert usage.rows[0]["routing_decision"] == "ROTATE_CREDENTIAL"
    assert all(row["error_category"] != "unsupported_model" for row in usage.rows)
    assert pool.failures[0]["health"] == "INVALID"


def test_a_401_with_no_other_credential_stops_instead_of_walking_the_chain() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderAuthenticationError("bad key", status_code=401)]}
    )
    service = _service(
        provider,
        chain=CHAIN_AB,
        pool=FakePool(["project-one"]),
    )

    with pytest.raises(AppError) as error:
        _call(service)

    assert error.value.details["failure"] == "authentication"
    assert provider.calls == [MODEL_A]
    assert MODEL_B not in provider.calls


def test_a_403_is_a_permission_failure_not_a_dead_model() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderPermissionError("no access", status_code=403), "{}"]}
    )
    usage = FakeUsage()
    pool = FakePool(["project-one", "project-one"])
    service = _service(provider, chain=[ModelChainEntry(model=MODEL_A)], pool=pool, usage=usage)

    result = _call(service)

    assert result.response.model == MODEL_A
    assert usage.rows[0]["error_category"] == "permission"
    assert usage.rows[0]["routing_decision"] == "ROTATE_CREDENTIAL"


# -- response-format failures ------------------------------------------------


def test_a_truncated_then_empty_response_stops_after_one_retry() -> None:
    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderTruncatedResponse("cut off", status_code=200, provider_code="MAX_TOKENS"),
                ProviderResponseError("empty answer", status_code=200),
            ],
            MODEL_B: ["{}"],
        }
    )
    usage = FakeUsage()
    service = _service(provider, chain=CHAIN_AB, usage=usage)

    with pytest.raises(AppError):
        _call(service)

    assert [row["error_category"] for row in usage.rows] == [
        "truncated",
        "response_invalid",
    ]
    assert [row["routing_decision"] for row in usage.rows] == [
        "RETRY_SAME_MODEL",
        "STOP",
    ]
    assert MODEL_B not in provider.calls


def test_a_safety_refusal_stops_the_chain_instead_of_evading_it() -> None:
    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderResponseError(
                    "refused", status_code=200, provider_code="SAFETY"
                )
            ],
            MODEL_B: ["{}"],
        }
    )
    usage = FakeUsage()
    service = _service(provider, chain=CHAIN_AB, usage=usage)

    with pytest.raises(AppError) as error:
        _call(service)

    assert error.value.details["failure"] == "safety_refusal"
    assert provider.calls == [MODEL_A]
    assert usage.rows[0]["routing_decision"] == "STOP"


# -- exhaustion --------------------------------------------------------------


def test_every_model_failing_reports_one_row_per_real_attempt() -> None:
    """Attempt rows are never collapsed, and the chain cannot multiply them.

    A three-model chain with a two-attempt budget would be six requests.  The
    per-operation budget is three, the transient retry cap is one, and the
    marking role permits one model, so the run makes exactly two requests and
    records exactly two rows.
    """

    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("down", status_code=503),
                ProviderServerError("down", status_code=503),
            ],
            MODEL_B: [
                ProviderServerError("down", status_code=502),
                ProviderServerError("down", status_code=502),
            ],
            MODEL_C: [
                ProviderServerError("down", status_code=504),
                ProviderServerError("down", status_code=504),
            ],
        }
    )
    usage = FakeUsage()
    service = _service(
        provider,
        chain=[
            ModelChainEntry(model=MODEL_A),
            ModelChainEntry(model=MODEL_B),
            ModelChainEntry(model=MODEL_C),
        ],
        usage=usage,
    )

    with pytest.raises(AppError) as error:
        _call(service)

    assert error.value.code.value == "PROVIDER_UNAVAILABLE"
    assert provider.calls == [MODEL_A, MODEL_A]
    assert len(usage.rows) == 2
    assert all(row["success"] is False for row in usage.rows)


def test_the_operation_budget_caps_the_whole_chain() -> None:
    """No nesting: the chain cannot spend more than the operation allows."""

    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("down", status_code=503),
                ProviderServerError("down", status_code=503),
                ProviderServerError("down", status_code=503),
            ]
        }
    )
    usage = FakeUsage()
    base = _settings(chain=[ModelChainEntry(model=MODEL_A)], max_attempts=8)
    provider_settings = base.provider.model_copy(
        update={"max_requests_per_operation": 2}
    )
    settings = base.model_copy(update={"provider": provider_settings})
    service = _service(
        provider,
        chain=[ModelChainEntry(model=MODEL_A)],
        settings=settings,
        usage=usage,
    )

    with pytest.raises(AppError):
        _call(service)

    assert len(provider.calls) == 2
    assert len(usage.rows) == 2


def test_a_model_with_no_available_credential_is_skipped_without_a_fake_attempt() -> None:
    provider = ScriptedProvider({MODEL_B: ["{}"]})
    usage = FakeUsage()
    pool = FakePool(["project-one"], keys_per_model=0)
    service = _service(
        provider,
        chain=CHAIN_AB,
        pool=pool,
        usage=usage,
    )

    with pytest.raises(AppError):
        _call(service)

    # No request was sent, so no usage row was invented for it.  Only the
    # permitted marking model is even considered: the chain's second entry is
    # removed before any credential is leased.
    assert usage.rows == []
    assert pool.no_credential == [MODEL_A]


# -- role-specific chains and configuration ---------------------------------


def test_a_role_with_no_permitted_model_refuses_instead_of_calling_one() -> None:
    """The review role names models the permission table does not permit.

    ``gemini-3.1-pro-preview`` is disabled and the marking model is only
    reserved for review, so nothing in the chain may answer.  The refusal must
    happen before a credential is leased, and it must not borrow the marking
    model to keep the stage running.
    """

    provider = ScriptedProvider({REVIEW_MODEL: ["{}"], MODEL_A: ["{}"]})
    usage = FakeUsage()
    service = _service(
        provider,
        chain=[ModelChainEntry(model=MODEL_A)],
        usage=usage,
        role="review",
    )

    with pytest.raises(AppError) as error:
        _call(service)

    assert error.value.code.value == "CONFIGURATION_ERROR"
    assert "review" in error.value.message
    assert provider.calls == []
    assert usage.rows == []


def test_an_explicit_marking_model_never_falls_back() -> None:
    """The production marking call names one model and refuses a substitution."""

    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("down", status_code=503),
                ProviderServerError("down", status_code=503),
            ],
            MODEL_B: ["{}"],
        }
    )
    service = _service(provider, chain=CHAIN_AB)

    with pytest.raises(AppError) as error:
        service.call(
            tenant_id=TENANT,
            purpose="marking",
            prompt_id="aetrix_v5_5_marking",
            model=MODEL_A,
        )

    assert error.value.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert "does not fall back" in error.value.message
    assert provider.calls == [MODEL_A, MODEL_A]
    assert MODEL_B not in provider.calls


def test_a_legacy_lite_saved_selection_is_never_walked() -> None:
    """A saved Lite row cannot become a review request's first model.

    The review chain is refused outright now that no model is permitted for
    independent review, so the assertion is about what the refusal says: the Lite
    selection is named in it, and no request is sent.
    """

    service = _service(ScriptedProvider({}), chain=CHAIN_AB)
    service.session = SimpleNamespace(  # type: ignore[assignment]
        scalar=lambda *_args, **_kwargs: SimpleNamespace(model=DISABLED_MODEL)
    )

    with pytest.raises(AppError) as error:
        service.model_chain("review")

    # The Lite selection is dropped before the chain is built, and the refusal
    # names the models that were actually considered.
    assert DISABLED_MODEL not in error.value.details["chain"]
    assert MODEL_A in error.value.message
    assert "independent_review" in error.value.message


def test_a_disabled_lite_entry_has_no_fallback_route() -> None:
    """A Lite entry is dropped, and the remaining model is not a marking model."""

    provider = ScriptedProvider({MODEL_B: ["{}"]})
    service = _service(
        provider,
        chain=[ModelChainEntry(model=DISABLED_MODEL), ModelChainEntry(model=MODEL_B)],
    )

    with pytest.raises(AppError) as error:
        _call(service)

    assert error.value.code.value == "CONFIGURATION_ERROR"
    assert provider.calls == []
    # The Lite entry is gone; the remaining entry is refused as a marking model.
    assert DISABLED_MODEL not in error.value.message
    assert MODEL_B in error.value.message


def test_a_disabled_entry_is_skipped_and_order_is_preserved() -> None:
    service = _service(
        ScriptedProvider({}),
        chain=[
            ModelChainEntry(model=MODEL_A, enabled=False),
            ModelChainEntry(model=MODEL_A),
            ModelChainEntry(model=MODEL_B),
        ],
    )

    # The disabled entry is dropped rather than reordered, and the model the
    # marking policy refuses is not offered as a second entry.
    assert [entry.model for entry in service.model_chain("primary")] == [MODEL_A]


def test_an_unknown_role_falls_back_to_the_marking_chain() -> None:
    service = _service(
        ScriptedProvider({}),
        chain=CHAIN_AB,
        role="something-else",
    )

    assert [entry.model for entry in service.model_chain("something-else")] == [
        MODEL_A,
    ]


def test_per_model_output_and_timeout_overrides_reach_the_request() -> None:
    provider = ScriptedProvider({MODEL_A: ["{}"]})
    service = _service(
        provider,
        chain=[
            ModelChainEntry(
                model=MODEL_A,
                max_output_tokens=4096,
                timeout_seconds=33.0,
                thinking_config_unsupported=True,
            )
        ],
    )
    seen: dict = {}

    def capture(request, api_key):
        seen["max_output_tokens"] = request.max_output_tokens
        seen["timeout_seconds"] = request.timeout_seconds
        seen["omit_thinking_config"] = request.omit_thinking_config
        return LLMResponse(text="{}", model=request.model, usage=TokenUsage())

    provider.generate = capture  # type: ignore[method-assign]
    _call(service)

    assert seen == {
        "max_output_tokens": 4096,
        "timeout_seconds": 33.0,
        "omit_thinking_config": True,
    }


def test_an_unpriced_model_reports_cost_unknown_without_inventing_a_price() -> None:
    provider = ScriptedProvider({MODEL_A: ["{}"]})
    usage = FakeUsage()
    base = _settings(chain=[ModelChainEntry(model=MODEL_A)])
    # The price table is empty, which is what an unverified list price looks like.
    provider_settings = base.provider.model_copy(update={"model_rates": {}})
    settings = base.model_copy(update={"provider": provider_settings})
    service = _service(
        provider, chain=[ModelChainEntry(model=MODEL_A)], settings=settings, usage=usage
    )

    result = _call(service)

    assert result.cost_usd is None
    assert usage.rows[0]["cost_status"] == "COST_UNKNOWN"
    # The tokens are still recorded: an unknown price is not an unknown usage.
    assert usage.rows[0]["input_tokens"] == 100
    assert usage.rows[0]["output_tokens"] == 50


def test_a_priced_model_reports_a_known_cost() -> None:
    provider = ScriptedProvider({MODEL_A: ["{}"]})
    usage = FakeUsage()
    service = _service(provider, chain=[ModelChainEntry(model=MODEL_A)], usage=usage)

    result = _call(service)

    assert result.cost_usd is not None and result.cost_usd > 0
    assert usage.rows[0]["cost_status"] == "KNOWN"


# -- the policy itself -------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (ProviderAuthenticationError("x", status_code=401), FailureKind.AUTHENTICATION),
        (ProviderPermissionError("x", status_code=403), FailureKind.PERMISSION),
        (ProviderQuotaError("x", status_code=429), FailureKind.QUOTA),
        (ProviderServerError("x", status_code=503), FailureKind.PROVIDER_SERVER),
        (ProviderRequestError("x", status_code=404), FailureKind.UNSUPPORTED_MODEL),
        (ProviderRequestError("x", status_code=400), FailureKind.INVALID_REQUEST),
        (ProviderTruncatedResponse("x"), FailureKind.TRUNCATED),
        (ProviderResponseError("x", provider_code="SAFETY"), FailureKind.SAFETY_REFUSAL),
        (ProviderResponseError("x"), FailureKind.RESPONSE_INVALID),
    ],
)
def test_classification(error, kind) -> None:
    assert classify_failure(error) is kind


def test_quota_never_rotates_within_one_project() -> None:
    action = decide(
        FailureKind.QUOTA,
        attempt_index=0,
        attempts_allowed=4,
        next_model_available=True,
        other_credential_available=True,
        independent_credential_available=False,
    )
    assert action is RoutingAction.NEXT_MODEL


def test_auth_never_advances_to_another_model_while_a_key_remains() -> None:
    action = decide(
        FailureKind.AUTHENTICATION,
        attempt_index=0,
        attempts_allowed=4,
        next_model_available=True,
        other_credential_available=True,
        independent_credential_available=False,
    )
    assert action is RoutingAction.ROTATE_CREDENTIAL


def test_the_attempt_budget_is_bounded() -> None:
    action = decide(
        FailureKind.PROVIDER_SERVER,
        attempt_index=2,
        attempts_allowed=3,
        next_model_available=False,
        other_credential_available=True,
        independent_credential_available=True,
    )
    assert action is RoutingAction.STOP


def test_safety_refusal_is_always_a_stop() -> None:
    for next_model in (True, False):
        assert (
            decide(
                FailureKind.SAFETY_REFUSAL,
                attempt_index=0,
                attempts_allowed=4,
                next_model_available=next_model,
                other_credential_available=True,
                independent_credential_available=True,
            )
            is RoutingAction.STOP
        )
