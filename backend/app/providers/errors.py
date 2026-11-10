"""Provider failures with enough structure for quota and retry handling.

An exception class alone is not a diagnosis.  Every provider error carries the
HTTP status when a response arrived, Google's own status code when it supplied
one, a short provider message, whether the request reached Google at all, and
any token metadata Google returned with the error.  The ledger stores those
fields so a failure can be investigated after the fact instead of guessed at.
"""

from __future__ import annotations

from .base import TokenUsage


class ProviderError(RuntimeError):
    """Base for safe, classified provider failures.

    ``provider_message`` is deliberately short and never contains a credential.
    Gemini errors do not echo the API key, but the adapter still truncates the
    message before it reaches a log or API response.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_message: str | None = None,
        provider_code: str | None = None,
        retry_after_seconds: float | None = None,
        reached_provider: bool | None = None,
        usage: TokenUsage | None = None,
        provider_request_id: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_message = provider_message
        self.provider_code = provider_code
        self.retry_after_seconds = retry_after_seconds
        self.reached_provider = reached_provider
        self.usage = usage
        self.provider_request_id = provider_request_id
        self.latency_ms = latency_ms


class ProviderAuthenticationError(ProviderError):
    """The key is rejected (401); retrying the same key cannot help."""


class ProviderPermissionError(ProviderError):
    """Google accepted the key but refused access (403).

    The credential may still be valid.  The Generative Language API may be
    disabled, the key restricted, or the project not entitled to the model, so
    this must never be collapsed into "invalid key".
    """


class ProviderQuotaError(ProviderError):
    """The project is rate-limited or out of quota; pause the project."""


class ProviderTransientError(ProviderError):
    """A network, transport or provider 5xx failure; another attempt may work."""


class ProviderNetworkError(ProviderTransientError):
    """No HTTP response arrived: DNS, connect, timeout or transport failure."""


class ProviderServerError(ProviderTransientError):
    """Google answered with a 5xx; the credential was not judged."""


class ProviderRequestError(ProviderError):
    """The request/schema was rejected; retrying unchanged cannot help."""


class ProviderResponseError(ProviderError):
    """The provider answered but the response could not be used."""


class ProviderTruncatedResponse(ProviderResponseError):
    """The output budget ran out before any text was produced.

    A thinking model bills its reasoning against ``maxOutputTokens``.  A probe
    with a tiny budget therefore returns HTTP 200, ``finishReason=MAX_TOKENS``
    and no content parts — which says nothing about the credential and must not
    be reported as an authentication failure.
    """


def failure_category(error: ProviderError) -> str:
    """Classify a provider failure for the ledger and the operator screen."""

    if isinstance(error, ProviderAuthenticationError):
        return "authentication"
    if isinstance(error, ProviderPermissionError):
        return "permission"
    if isinstance(error, ProviderQuotaError):
        return "quota"
    if isinstance(error, ProviderNetworkError):
        return "network"
    if isinstance(error, ProviderServerError):
        return "provider_server"
    if isinstance(error, ProviderTransientError):
        return "network" if error.status_code is None else "provider_server"
    if isinstance(error, ProviderTruncatedResponse):
        return "provider_response"
    if isinstance(error, ProviderResponseError):
        return "provider_response"
    if isinstance(error, ProviderRequestError):
        return "unsupported_model" if error.status_code == 404 else "invalid_request"
    return "internal"


def category_for_legacy_error(
    error_class: str | None, http_status: int | None
) -> str | None:
    """Recover a category for rows written before structured diagnostics existed.

    This is a read-time interpretation of the recorded class, not new evidence:
    a historical ``ProviderTransientError`` with no HTTP status is a network
    failure, while one with a 5xx is a provider server failure.
    """

    if not error_class:
        return None
    mapping = {
        "ProviderAuthenticationError": "authentication",
        "ProviderPermissionError": "permission",
        "ProviderQuotaError": "quota",
        "ProviderNetworkError": "network",
        "ProviderServerError": "provider_server",
        "ProviderTruncatedResponse": "provider_response",
        "ProviderResponseError": "provider_response",
        "ProviderRequestError": (
            "unsupported_model" if http_status == 404 else "invalid_request"
        ),
    }
    if error_class in mapping:
        return mapping[error_class]
    if error_class == "ProviderTransientError":
        return "provider_server" if (http_status or 0) >= 500 else "network"
    return "internal"


__all__ = [
    "ProviderAuthenticationError",
    "ProviderError",
    "ProviderNetworkError",
    "ProviderPermissionError",
    "ProviderQuotaError",
    "ProviderRequestError",
    "ProviderResponseError",
    "ProviderServerError",
    "ProviderTransientError",
    "ProviderTruncatedResponse",
    "category_for_legacy_error",
    "failure_category",
]
