from __future__ import annotations

import httpx
import pytest
from app.providers.base import LLMRequest
from app.providers.errors import ProviderAuthenticationError, ProviderQuotaError
from app.providers.gemini import GeminiProvider
from pydantic import SecretStr


def _provider(handler) -> GeminiProvider:
    return GeminiProvider(
        base_url="https://generativelanguage.example/v1beta",
        transport=httpx.MockTransport(handler),
    )


def test_gemini_adapter_sends_key_in_header_not_url() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key_header"] = request.headers.get("x-goog-api-key")
        captured["body"] = request.content
        return httpx.Response(
            200,
            headers={"x-goog-request-id": "provider-req-1"},
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 7,
                    "cachedContentTokenCount": 2,
                },
            },
        )

    response = _provider(handler).generate(
        LLMRequest(model="gemini-3.6-flash", prompt="Return JSON"), SecretStr("top-secret-key")
    )
    assert "top-secret-key" not in str(captured["url"])
    assert captured["key_header"] == "top-secret-key"
    assert b"Return JSON" in captured["body"]
    assert response.text == '{"ok": true}'
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 7
    assert response.usage.cached_tokens == 2
    assert response.provider_request_id == "provider-req-1"


def test_gemini_quota_and_auth_are_classified() -> None:
    def quota_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    with pytest.raises(ProviderQuotaError):
        _provider(quota_handler).generate(
            LLMRequest(model="gemini-3.6-flash", prompt="x"), SecretStr("key")
        )

    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(ProviderAuthenticationError):
        _provider(auth_handler).generate(
            LLMRequest(model="gemini-3.6-flash", prompt="x"), SecretStr("key")
        )


def test_gemini_requests_json_schema_and_ignores_thought_parts() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "internal reasoning", "thought": True},
                                {"text": '{"ok": true}'},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            },
        )

    response = _provider(handler).generate(
        LLMRequest(
            model="gemini-3.6-flash",
            prompt="Return JSON",
            response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        ),
        SecretStr("key"),
    )
    generation = captured["body"]["generationConfig"]  # type: ignore[index]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"]["type"] == "object"
    assert "responseSchema" not in generation
    assert response.text == '{"ok": true}'
