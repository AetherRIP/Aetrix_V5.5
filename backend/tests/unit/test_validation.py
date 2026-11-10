"""The validation probe must distinguish a bad key from a bad request.

Everything here runs against an in-process ``httpx`` transport: no network and no
real quota.  The regression these tests pin down is the one that made three
valid credentials look broken: a probe with an 8-token budget, no thinking
configuration and a parser that reported "no content parts" as a provider error
with no HTTP status.
"""

from __future__ import annotations

import httpx
import pytest
from app.providers.base import LLMRequest
from app.providers.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTruncatedResponse,
)
from app.providers.gemini import GeminiProvider
from app.services.provider_fleet import classify_validation_error
from pydantic import SecretStr

BASE = "https://generativelanguage.googleapis.com/v1beta"
KEY = SecretStr("AIza-test-key-that-must-never-appear-in-an-error")


def _provider(handler, **kwargs) -> GeminiProvider:
    return GeminiProvider(
        base_url=BASE, transport=httpx.MockTransport(handler), **kwargs
    )


def _request(**kwargs) -> LLMRequest:
    return LLMRequest(
        model="gemini-3.6-flash",
        prompt="Reply with the single word: ok",
        temperature=0.0,
        max_output_tokens=64,
        **kwargs,
    )


def _answer(text: str = "ok", finish: str = "STOP") -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": finish}
        ],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
    }


def test_probe_leaves_room_for_an_answer_and_disables_thinking() -> None:
    provider = _provider(lambda request: httpx.Response(200, json=_answer()))

    payload = provider._payload(_request())

    assert payload["generationConfig"]["maxOutputTokens"] == 64
    # Gemini 3 bills reasoning against maxOutputTokens; without this the probe
    # can finish with MAX_TOKENS before writing a single visible token.
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_thinking_can_be_left_to_the_provider() -> None:
    provider = _provider(
        lambda request: httpx.Response(200, json=_answer()), thinking_budget=None
    )

    assert "thinkingConfig" not in provider._payload(_request())["generationConfig"]


def test_a_valid_key_returns_text_and_usage() -> None:
    provider = _provider(lambda request: httpx.Response(200, json=_answer()))

    response = provider.generate(_request(), KEY)

    assert response.text == "ok"
    assert response.usage.input_tokens == 3
    assert response.usage.output_tokens == 2


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            401,
            {"error": {"code": 401, "message": "API key not valid", "status": "UNAUTHENTICATED"}},
            ProviderAuthenticationError,
        ),
        (
            403,
            {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}},
            ProviderPermissionError,
        ),
        (
            429,
            {
                "error": {
                    "code": 429,
                    "message": "Quota exceeded for quota metric",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
            ProviderQuotaError,
        ),
        (
            404,
            {"error": {"code": 404, "message": "models/nope is not found"}},
            ProviderRequestError,
        ),
        (500, {"error": {"code": 500, "message": "internal error"}}, ProviderServerError),
        (503, {"error": {"code": 503, "message": "unavailable"}}, ProviderServerError),
    ],
)
def test_http_failures_keep_their_status_and_never_leak_the_key(
    status: int, body: dict, expected: type[ProviderError]
) -> None:
    provider = _provider(lambda request: httpx.Response(status, json=body))

    with pytest.raises(expected) as caught:
        provider.generate(_request(), KEY)

    assert caught.value.status_code == status
    assert "AIza" not in str(caught.value)
    assert caught.value.provider_message
    assert KEY.get_secret_value() not in str(caught.value)


def test_a_budget_spent_thinking_is_not_an_authentication_failure() -> None:
    """The exact recorded failure: HTTP 200, MAX_TOKENS, thought-only parts."""

    body = {
        "candidates": [
            {
                "content": {"parts": [{"text": "reasoning…", "thought": True}]},
                "finishReason": "MAX_TOKENS",
            }
        ],
        "usageMetadata": {"thoughtsTokenCount": 4},
    }
    provider = _provider(lambda request: httpx.Response(200, json=body))

    with pytest.raises(ProviderTruncatedResponse) as caught:
        provider.generate(_request(), KEY)

    assert caught.value.status_code == 200
    verdict = classify_validation_error(caught.value)
    assert verdict.health is None
    assert verdict.category == "provider_response"


def test_a_network_timeout_is_temporary_not_unhealthy() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    provider = _provider(boom)

    with pytest.raises(ProviderNetworkError) as caught:
        provider.generate(_request(), KEY)

    assert caught.value.reached_provider is False
    assert classify_validation_error(caught.value).health is None
    assert classify_validation_error(caught.value).category == "network"


def test_unparseable_success_body_reports_the_http_status() -> None:
    provider = _provider(lambda request: httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(ProviderResponseError) as caught:
        provider.generate(_request(), KEY)

    assert caught.value.status_code == 200
    assert "invalid JSON" in str(caught.value)


@pytest.mark.parametrize(
    ("error", "health", "category"),
    [
        (ProviderAuthenticationError("revoked", status_code=401), "INVALID", "authentication"),
        (ProviderPermissionError("forbidden", status_code=403), None, "permission"),
        (ProviderQuotaError("quota", status_code=429), None, "quota"),
        (ProviderNetworkError("timeout"), None, "network"),
        (ProviderServerError("unavailable", status_code=503), None, "provider_server"),
        (ProviderRequestError("bad model", status_code=404), None, "unsupported_model"),
        (ProviderRequestError("bad argument", status_code=400), None, "invalid_request"),
        (ProviderTruncatedResponse("empty", status_code=200), None, "provider_response"),
        (ProviderResponseError("malformed", status_code=200), None, "provider_response"),
        (ProviderError("unclassified"), None, "internal"),
    ],
)
def test_classification_names_a_health_state_and_an_action(
    error: ProviderError, health: str | None, category: str
) -> None:
    verdict = classify_validation_error(error)

    assert verdict.health == health
    assert verdict.category == category
    assert verdict.recommendation
