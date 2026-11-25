"""The bounded retry policy, the circuit breaker and the operation budget.

Nothing here contacts a provider.  Every delay is a pure function, every clock is
injected, and every request count is read from the scripted provider, so a claim
like "one retry" or "no request was sent" is measured rather than asserted.

The failure this file exists for: four attempts across five invocations produced
twenty 503s, none of which served a paper, and the ledger recorded all twenty as
consumed quota.  These tests pin the three changes that stop it happening again —
one retry, a request budget, and an open breaker that spends nothing.
"""

from __future__ import annotations

import random

import app.services.provider_calls as provider_calls_module
import pytest
from app.core.config import ModelChainEntry
from app.core.errors import AppError
from app.providers.circuit_breaker import CircuitBreaker
from app.providers.errors import ProviderAuthenticationError, ProviderServerError
from app.providers.retry import (
    RetryPolicy,
    retry_delay,
    transient_attempts_allowed,
)
from app.providers.routing import FailureKind
from app.services.provider_calls import reservation_status_for
from test_model_fallback import (
    CHAIN_AB,
    MODEL_A,
    FakePool,
    FakeUsage,
    ScriptedProvider,
    _call,
    _service,
    _settings,
)

# -- the delay function ------------------------------------------------------


def test_backoff_is_exponential_and_capped() -> None:
    policy = RetryPolicy(backoff_seconds=1.0, max_backoff_seconds=4.0, jitter=0.0)

    assert retry_delay(0, policy=policy) == 1.0
    assert retry_delay(1, policy=policy) == 2.0
    # The third attempt would be 8s; the ceiling holds it at 4s.
    assert retry_delay(3, policy=policy) == 4.0


def test_backoff_is_jittered_within_the_configured_bounds() -> None:
    policy = RetryPolicy(backoff_seconds=2.0, max_backoff_seconds=10.0, jitter=0.5)
    rng = random.Random(1234)

    delays = [retry_delay(0, policy=policy, rng=rng) for _ in range(50)]

    assert all(1.0 <= delay <= 3.0 for delay in delays)
    # A deterministic generator still produces a spread, not one constant.
    assert len(set(delays)) > 1


def test_retry_after_is_honoured_and_clamped() -> None:
    policy = RetryPolicy(backoff_seconds=1.0, max_backoff_seconds=8.0, jitter=0.0)

    assert retry_delay(0, policy=policy, retry_after_seconds=5.0) == 5.0
    # A provider cannot park a worker past the policy ceiling.
    assert retry_delay(0, policy=policy, retry_after_seconds=600.0) == 8.0


def test_retry_after_only_ever_waits_longer_than_asked() -> None:
    policy = RetryPolicy(backoff_seconds=1.0, max_backoff_seconds=8.0, jitter=0.5)
    rng = random.Random(7)

    for _ in range(50):
        delay = retry_delay(0, policy=policy, retry_after_seconds=4.0, rng=rng)
        assert 4.0 <= delay <= 4.5


def test_a_transient_failure_gets_exactly_one_retry() -> None:
    assert transient_attempts_allowed(4, retries=1) == 2
    assert transient_attempts_allowed(8, retries=0) == 1
    # A configured budget of one is a ceiling too, not a floor.
    assert transient_attempts_allowed(1, retries=1) == 1


# -- the breaker -------------------------------------------------------------


def test_the_breaker_opens_at_the_threshold_and_reports_the_wait() -> None:
    now = [0.0]
    breaker = CircuitBreaker(threshold=2, open_seconds=30.0, clock=lambda: now[0])

    assert not breaker.is_open("gemini", MODEL_A)
    breaker.record_failure("gemini", MODEL_A)
    assert not breaker.is_open("gemini", MODEL_A)
    breaker.record_failure("gemini", MODEL_A)

    status = breaker.status("gemini", MODEL_A)
    assert status.open
    assert status.retry_in_seconds == 30.0

    now[0] = 31.0
    assert not breaker.is_open("gemini", MODEL_A)


def test_one_success_closes_the_breaker() -> None:
    breaker = CircuitBreaker(threshold=1, open_seconds=30.0, clock=lambda: 0.0)
    breaker.record_failure("gemini", MODEL_A)
    assert breaker.is_open("gemini", MODEL_A)

    breaker.record_success("gemini", MODEL_A)
    assert not breaker.is_open("gemini", MODEL_A)


def test_the_breaker_is_per_model_not_per_provider() -> None:
    breaker = CircuitBreaker(threshold=1, open_seconds=30.0, clock=lambda: 0.0)
    breaker.record_failure("gemini", MODEL_A)

    assert breaker.is_open("gemini", MODEL_A)
    assert not breaker.is_open("gemini", "gemini-3.5-flash-lite")


# -- the call path -----------------------------------------------------------


def test_the_second_503_of_one_call_is_still_attempted_then_stops() -> None:
    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("down", status_code=503, retry_after_seconds=0.0),
                ProviderServerError("down", status_code=503, retry_after_seconds=0.0),
            ]
        }
    )
    usage = FakeUsage()
    service = _service(provider, chain=[ModelChainEntry(model=MODEL_A)], usage=usage)

    with pytest.raises(AppError):
        _call(service)

    assert provider.calls == [MODEL_A, MODEL_A]
    assert len(usage.rows) == 2


def test_the_service_honours_retry_after_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(provider_calls_module.time, "sleep", delays.append)
    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("busy", status_code=503, retry_after_seconds=3.0),
                "{}",
            ]
        }
    )
    service = _service(provider, chain=[ModelChainEntry(model=MODEL_A)])

    _call(service)

    assert len(delays) == 1
    assert 3.0 <= delays[0] <= 3.75


def test_repeated_overload_opens_the_breaker_and_then_spends_nothing() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderServerError("down", status_code=503) for _ in range(10)]}
    )
    usage = FakeUsage()
    service = _service(
        provider,
        chain=[ModelChainEntry(model=MODEL_A)],
        usage=usage,
    )

    for _ in range(2):
        with pytest.raises(AppError):
            _call(service)
    sent = len(provider.calls)
    assert sent == 4  # two attempts per call: the transient retry cap holds

    with pytest.raises(AppError) as error:
        _call(service)

    # Not one further request, and no usage row invented for it.
    assert len(provider.calls) == sent
    assert len(usage.rows) == sent
    assert error.value.details["breaker_open"] == [MODEL_A]
    assert "overloaded" in error.value.message


def test_a_breaker_open_on_a_marking_model_never_borrows_another() -> None:
    breaker = CircuitBreaker(threshold=1, open_seconds=300.0, clock=lambda: 0.0)
    breaker.record_failure("scripted", MODEL_A)
    provider = ScriptedProvider({})
    service = _service(
        provider,
        chain=CHAIN_AB,
        pool=FakePool(["project-one"]),
    )
    service.breaker = breaker

    with pytest.raises(AppError):
        _call(service)

    assert provider.calls == []


def test_the_operation_budget_is_read_from_settings() -> None:
    base = _settings(chain=[ModelChainEntry(model=MODEL_A)])
    provider_settings = base.provider.model_copy(
        update={"max_requests_per_operation": 1}
    )
    settings = base.model_copy(update={"provider": provider_settings})
    provider = ScriptedProvider(
        {MODEL_A: [ProviderServerError("down", status_code=503), "{}"]}
    )
    service = _service(
        provider, chain=[ModelChainEntry(model=MODEL_A)], settings=settings
    )

    with pytest.raises(AppError):
        _call(service)

    # One request only: the retry it would have made is not in the budget.
    assert provider.calls == [MODEL_A]


# -- reservation states ------------------------------------------------------


def test_a_server_failure_is_unconfirmed_not_consumed() -> None:
    error = ProviderServerError("down", status_code=503, reached_provider=True)

    assert reservation_status_for(FailureKind.PROVIDER_SERVER, error) == "UNCONFIRMED"


def test_a_request_that_never_arrived_is_released() -> None:
    error = ProviderServerError("down", status_code=503, reached_provider=False)

    assert reservation_status_for(FailureKind.PROVIDER_SERVER, error) == "RELEASED"


def test_a_rejected_key_is_released() -> None:
    error = ProviderAuthenticationError("bad", status_code=401, reached_provider=True)

    assert reservation_status_for(FailureKind.AUTHENTICATION, error) == "RELEASED"


def test_a_rate_limit_and_a_bad_request_are_confirmed_consumption() -> None:
    quota = ProviderServerError("slow down", status_code=429, reached_provider=True)
    invalid = ProviderServerError("bad field", status_code=400, reached_provider=True)

    assert reservation_status_for(FailureKind.QUOTA, quota) == "CONSUMED"
    assert reservation_status_for(FailureKind.INVALID_REQUEST, invalid) == "CONSUMED"


def test_the_call_path_records_unconfirmed_for_a_503() -> None:
    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("down", status_code=503),
                ProviderServerError("down", status_code=503),
            ]
        }
    )
    usage = FakeUsage()
    pool = FakePool(["project-one"])
    service = _service(
        provider, chain=[ModelChainEntry(model=MODEL_A)], pool=pool, usage=usage
    )

    with pytest.raises(AppError):
        _call(service)

    assert [row["error_category"] for row in usage.rows] == [
        "provider_server",
        "provider_server",
    ]
    # Neither attempt is claimed as consumed quota: Google never confirmed it.
    assert [entry["reservation_status"] for entry in pool.failures] == [
        "UNCONFIRMED",
        "UNCONFIRMED",
    ]
