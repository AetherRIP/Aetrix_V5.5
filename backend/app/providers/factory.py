"""Provider selection.

There is no fake provider in this factory.  When the live path is disabled the
application receives an object that raises ``ProviderNotConfigured``; the API
reports that state rather than returning invented extraction output.
"""

from __future__ import annotations

from pydantic import SecretStr

from ..core.config import Settings
from .base import LLMProvider, LLMRequest, LLMResponse, ProviderNotConfigured
from .gemini import GeminiProvider


class UnavailableProvider:
    name = "unavailable"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or (
            "No live language-model provider is configured. "
            "Set AETRIX_FEATURES__LIVE_PROVIDER=true and provision a credential."
        )

    def generate(self, request: LLMRequest, api_key: SecretStr) -> LLMResponse:
        raise ProviderNotConfigured(self.reason)


def build_provider(settings: Settings) -> LLMProvider:
    if not settings.features.live_provider:
        return UnavailableProvider()
    return GeminiProvider(
        base_url=settings.provider.gemini_base_url,
        timeout_seconds=settings.provider.request_timeout_seconds,
        thinking_budget=settings.provider.thinking_budget,
    )
