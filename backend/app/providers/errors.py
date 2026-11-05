"""Provider failures with enough structure for quota and retry handling."""

from __future__ import annotations


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
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_message = provider_message
        self.retry_after_seconds = retry_after_seconds


class ProviderAuthenticationError(ProviderError):
    """The key is rejected; retrying the same key cannot help."""


class ProviderQuotaError(ProviderError):
    """The key is rate-limited or out of quota; put it in cooldown."""


class ProviderTransientError(ProviderError):
    """Timeout, transport failure or provider 5xx; another attempt may work."""


class ProviderRequestError(ProviderError):
    """The request/schema was rejected; retrying unchanged cannot help."""


class ProviderResponseError(ProviderError):
    """The provider answered but the response could not be used."""
