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
    ProviderError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTruncatedResponse,
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
        thinking_budget: int | None = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self.thinking_budget = thinking_budget
        #: Models that answered ``INVALID_ARGUMENT`` to ``thinkingConfig``.
        #: Google rejects a zero thinking budget on models whose smallest
        #: supported budget is positive (``gemini-3.5-flash-lite`` does), and its
        #: 400 names no field.  The first such request is retried once without the
        #: block and the model is remembered, so no later request pays a second
        #: call to rediscover the same incompatibility.
        self._thinking_refused: set[str] = set()

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(timeout or self.timeout_seconds),
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

    def _payload(
        self, request: LLMRequest, *, include_thinking: bool = True
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": request.prompt}]
        parts.extend(self._part(item) for item in request.inputs)
        generation: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_output_tokens,
        }
        if (
            include_thinking
            and not request.omit_thinking_config
            and self.thinking_budget is not None
        ):
            # Gemini 3 bills thinking against maxOutputTokens. Without this a
            # small probe can spend its entire budget reasoning and return no
            # content at all, which is a request-shape problem, not a bad key.
            generation["thinkingConfig"] = {
                "thinkingBudget": self.thinking_budget,
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
    def _error_details(
        response: httpx.Response,
    ) -> tuple[str, str | None, int | None, TokenUsage]:
        """Extract Google's message, status enum, numeric code and usage."""

        try:
            body = response.json()
        except ValueError:
            return "provider returned a non-JSON error response", None, None, TokenUsage()
        if not isinstance(body, dict):
            return "provider returned a malformed error response", None, None, TokenUsage()
        error = body.get("error")
        if not isinstance(error, dict):
            return "provider returned an error", None, None, GeminiProvider._usage(body)
        message = error.get("message")
        provider_code = error.get("status")
        numeric_code = error.get("code")
        return (
            message[:300] if isinstance(message, str) else "provider returned an error",
            provider_code[:80] if isinstance(provider_code, str) else None,
            numeric_code if isinstance(numeric_code, int) else None,
            GeminiProvider._usage(body),
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        status = response.status_code
        message, provider_code, numeric_code, usage = self._error_details(response)
        retry_after: float | None = None
        raw_retry = response.headers.get("retry-after")
        if raw_retry:
            try:
                retry_after = float(raw_retry)
            except ValueError:
                retry_after = None
        details = {
            "status_code": status,
            "provider_message": message,
            "provider_code": provider_code
            or (str(numeric_code) if numeric_code is not None else None),
            "reached_provider": True,
            "usage": usage,
        }
        if status == 401:
            raise ProviderAuthenticationError(
                "The provider rejected the credential.", **details
            )
        if status == 403:
            raise ProviderPermissionError(
                "The provider refused access to this key or model.", **details
            )
        if status == 429:
            raise ProviderQuotaError(
                "The provider quota is exhausted for this key.",
                retry_after_seconds=retry_after,
                **details,
            )
        if status >= 500:
            # A 503 often carries ``Retry-After``.  It is passed through so the
            # single retry waits as long as Google asked instead of guessing.
            raise ProviderServerError(
                "The provider is temporarily unavailable.",
                retry_after_seconds=retry_after,
                **details,
            )
        if status == 404:
            raise ProviderRequestError(
                "The configured model is not available to this provider.", **details
            )
        raise ProviderRequestError(
            "The provider rejected the request.", **details
        )

    @staticmethod
    def _text_from_body(
        body: dict[str, Any], *, status_code: int, usage: TokenUsage
    ) -> tuple[str, str | None]:
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderResponseError(
                "The provider returned no candidates.",
                status_code=status_code,
                reached_provider=True,
                usage=usage,
            )
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ProviderResponseError(
                "The provider returned a malformed candidate.",
                status_code=status_code,
                reached_provider=True,
                usage=usage,
            )
        finish_reason = candidate.get("finishReason")
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ProviderResponseError(
                "The provider returned no content parts.",
                status_code=status_code,
                provider_code=finish_reason if isinstance(finish_reason, str) else None,
                reached_provider=True,
                usage=usage,
            )
        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict) or part.get("thought") is True:
                continue
            if isinstance(part.get("text"), str):
                chunks.append(part["text"])
        if not chunks:
            if finish_reason == "MAX_TOKENS":
                raise ProviderTruncatedResponse(
                    "The provider exhausted its output budget before returning text "
                    "(MAX_TOKENS).",
                    status_code=status_code,
                    provider_code="MAX_TOKENS",
                    reached_provider=True,
                    usage=usage,
                )
            raise ProviderResponseError(
                "The provider returned an empty answer.",
                status_code=status_code,
                provider_code=finish_reason if isinstance(finish_reason, str) else None,
                reached_provider=True,
                usage=usage,
            )
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

    def _post(
        self, url: str, payload: dict[str, Any], request: LLMRequest, api_key: SecretStr
    ) -> httpx.Response:
        try:
            with self._client(request.timeout_seconds) as client:
                return client.post(
                    url,
                    headers={
                        "x-goog-api-key": api_key.get_secret_value(),
                        "content-type": "application/json",
                    },
                    json=payload,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            # The connection was never established, so the request provably never
            # left the process and nothing could have been metered.
            raise ProviderNetworkError(
                "The provider could not be reached.", reached_provider=False
            ) from error
        except httpx.TimeoutException as error:
            # A read timeout is not proof the request was free: the request was
            # sent and Google may have metered it before the answer was lost.
            # ``None`` records that nobody can say, which is what makes the
            # reservation UNCONFIRMED rather than RELEASED.
            raise ProviderNetworkError(
                "The provider request timed out.", reached_provider=None
            ) from error
        except httpx.HTTPError as error:
            # Any other transport error happened while the request was in flight.
            raise ProviderNetworkError(
                "The connection to the provider failed mid-request.",
                reached_provider=None,
            ) from error

    def generate(self, request: LLMRequest, api_key: SecretStr) -> LLMResponse:
        url = f"{self.base_url}/models/{request.model}:generateContent"
        started = time.perf_counter()
        payload = self._payload(
            request, include_thinking=request.model not in self._thinking_refused
        )
        response = self._post(url, payload, request, api_key)
        if (
            response.status_code == 400
            and "thinkingConfig" in payload["generationConfig"]
        ):
            # One bounded retry, only for the field Google refuses without naming
            # it.  The rejected request is not billed, so the retry costs a round
            # trip, not a paid call.  The model is remembered as incompatible
            # only when the retry *succeeds*: remembering it after a second 400
            # would let an unrelated malformed request blacklist the model for
            # the life of the process and hide the real defect behind it.
            payload = self._payload(request, include_thinking=False)
            retry = self._post(url, payload, request, api_key)
            if retry.status_code < 400:
                self._thinking_refused.add(request.model)
            response = retry

        latency_ms = int((time.perf_counter() - started) * 1000)
        request_id = response.headers.get("x-goog-request-id")
        try:
            self._raise_for_status(response)
        except ProviderError as error:
            error.provider_request_id = request_id
            error.latency_ms = latency_ms
            raise
        try:
            body = response.json()
        except ValueError as error:
            raise ProviderResponseError(
                "The provider returned invalid JSON.",
                status_code=response.status_code,
                reached_provider=True,
                provider_request_id=request_id,
                latency_ms=latency_ms,
            ) from error
        if not isinstance(body, dict):
            raise ProviderResponseError(
                "The provider returned a malformed body.",
                status_code=response.status_code,
                reached_provider=True,
                provider_request_id=request_id,
                latency_ms=latency_ms,
            )
        usage = self._usage(body)
        try:
            text, finish_reason = self._text_from_body(
                body, status_code=response.status_code, usage=usage
            )
        except ProviderError as error:
            error.provider_request_id = request_id
            error.latency_ms = latency_ms
            raise
        if finish_reason in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"}:
            raise ProviderResponseError(
                "The provider refused to produce usable content.",
                status_code=response.status_code,
                provider_message=f"finishReason={finish_reason}",
                provider_code=finish_reason,
                reached_provider=True,
                usage=usage,
                provider_request_id=request_id,
                latency_ms=latency_ms,
            )
        return LLMResponse(
            text=text,
            model=request.model,
            usage=usage,
            finish_reason=finish_reason,
            provider_request_id=request_id,
            latency_ms=latency_ms,
        )

    @staticmethod
    def parse_json_response(text: str) -> Any:
        """Parse prose/fenced JSON; callers validate the decoded shape."""
        return parse_json_text(text)
