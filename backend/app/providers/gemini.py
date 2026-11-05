"""Gemini REST adapter.

This is the only module that knows Gemini's wire format.  It uses the plain
REST endpoint through ``httpx`` rather than a provider SDK, and places the key in
the ``x-goog-api-key`` header so it never appears in a URL, access log or error
message.  Tests inject an ``httpx.MockTransport``; production uses the configured
base URL.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx
from pydantic import SecretStr

from .base import LLMInput, LLMRequest, LLMResponse, TokenUsage
from .errors import (
    ProviderAuthenticationError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTransientError,
)
from .json import parse_json_text


class GeminiProvider:
    name = "google"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int = 300,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(self.timeout_seconds),
            transport=self._transport,
            follow_redirects=False,
        )

    @staticmethod
    def _part(item: LLMInput) -> dict[str, Any]:
        if item.image is not None:
            if not item.mime_type:
                raise ProviderRequestError("an image input needs a MIME type")
            return {
                "inlineData": {
                    "mimeType": item.mime_type,
                    "data": base64.b64encode(item.image).decode("ascii"),
                }
            }
        if item.text is not None:
            return {"text": item.text}
        raise ProviderRequestError("an empty provider input is not allowed")

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": request.prompt}]
        parts.extend(self._part(item) for item in request.inputs)
        generation: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_output_tokens,
        }
        if request.response_schema is not None:
            generation["responseMimeType"] = "application/json"
            # Gemini 3 uses JSON Schema here.  responseSchema is the older
            # OpenAPI subset and is deliberately not sent alongside it.
            generation["responseJsonSchema"] = request.response_schema
        return {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation,
        }

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return "provider returned a non-JSON error response"
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message[:300]
        return "provider returned an error"

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        status = response.status_code
        message = self._error_message(response)
        retry_after: float | None = None
        raw_retry = response.headers.get("retry-after")
        if raw_retry:
            try:
                retry_after = float(raw_retry)
            except ValueError:
                retry_after = None
        if status in {401, 403}:
            raise ProviderAuthenticationError(
                "The provider rejected the credential.",
                status_code=status,
                provider_message=message,
            )
        if status == 429:
            raise ProviderQuotaError(
                "The provider quota is exhausted for this key.",
                status_code=status,
                provider_message=message,
                retry_after_seconds=retry_after,
            )
        if status >= 500:
            raise ProviderTransientError(
                "The provider is temporarily unavailable.",
                status_code=status,
                provider_message=message,
            )
        if status == 404:
            raise ProviderRequestError(
                "The configured model is not available to this provider.",
                status_code=status,
                provider_message=message,
            )
        raise ProviderRequestError(
            "The provider rejected the request.",
            status_code=status,
            provider_message=message,
        )

    @staticmethod
    def _text_from_body(body: dict[str, Any]) -> tuple[str, str | None]:
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderResponseError("The provider returned no candidates.")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ProviderResponseError("The provider returned a malformed candidate.")
        finish_reason = candidate.get("finishReason")
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ProviderResponseError("The provider returned no content parts.")
        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict) or part.get("thought") is True:
                continue
            if isinstance(part.get("text"), str):
                chunks.append(part["text"])
        if not chunks:
            raise ProviderResponseError("The provider returned an empty answer.")
        return "".join(chunks), finish_reason if isinstance(finish_reason, str) else None

    @staticmethod
    def _usage(body: dict[str, Any]) -> TokenUsage:
        raw = body.get("usageMetadata")
        if not isinstance(raw, dict):
            return TokenUsage()
        candidates = raw.get("candidatesTokenCount")
        thoughts = raw.get("thoughtsTokenCount")
        output = None
        if isinstance(candidates, int) or isinstance(thoughts, int):
            output = int(candidates or 0) + int(thoughts or 0)
        return TokenUsage(
            input_tokens=(
                int(raw["promptTokenCount"])
                if isinstance(raw.get("promptTokenCount"), int)
                else None
            ),
            output_tokens=output,
            cached_tokens=(
                int(raw["cachedContentTokenCount"])
                if isinstance(raw.get("cachedContentTokenCount"), int)
                else None
            ),
        )

    def generate(self, request: LLMRequest, api_key: SecretStr) -> LLMResponse:
        url = f"{self.base_url}/models/{request.model}:generateContent"
        started = time.perf_counter()
        try:
            with self._client() as client:
                response = client.post(
                    url,
                    headers={
                        "x-goog-api-key": api_key.get_secret_value(),
                        "content-type": "application/json",
                    },
                    json=self._payload(request),
                )
        except httpx.TimeoutException as error:
            raise ProviderTransientError("The provider request timed out.") from error
        except httpx.HTTPError as error:
            raise ProviderTransientError("The provider could not be reached.") from error

        self._raise_for_status(response)
        try:
            body = response.json()
        except ValueError as error:
            raise ProviderResponseError("The provider returned invalid JSON.") from error
        if not isinstance(body, dict):
            raise ProviderResponseError("The provider returned a malformed body.")
        text, finish_reason = self._text_from_body(body)
        if finish_reason in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"}:
            raise ProviderResponseError(
                "The provider refused to produce usable content.",
                provider_message=f"finishReason={finish_reason}",
            )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return LLMResponse(
            text=text,
            model=request.model,
            usage=self._usage(body),
            finish_reason=finish_reason,
            provider_request_id=response.headers.get("x-goog-request-id"),
            latency_ms=latency_ms,
        )

    @staticmethod
    def parse_json_response(text: str) -> Any:
        """Parse prose/fenced JSON; callers validate the decoded shape."""
        return parse_json_text(text)
