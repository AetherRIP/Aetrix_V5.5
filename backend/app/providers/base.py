"""Provider-neutral model types.

Nothing in this module imports a provider SDK.  The rest of the engine depends
only on ``LLMProvider``; the Gemini adapter is an implementation detail at the
edge.  Provider request identifiers, token counts and finish reasons are copied
into plain dataclasses so no SDK object can leak through the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import SecretStr


@dataclass(frozen=True, slots=True)
class LLMInput:
    text: str | None = None
    image: bytes | None = None
    mime_type: str | None = None

    @classmethod
    def text_part(cls, text: str) -> LLMInput:
        return cls(text=text)

    @classmethod
    def image_part(cls, image: bytes, mime_type: str) -> LLMInput:
        return cls(image=image, mime_type=mime_type)


@dataclass(frozen=True, slots=True)
class LLMRequest:
    model: str
    prompt: str
    inputs: tuple[LLMInput, ...] = ()
    response_schema: dict[str, Any] | None = None
    temperature: float = 0.0
    max_output_tokens: int = 16384


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None

    @property
    def reported(self) -> bool:
        return self.input_tokens is not None or self.output_tokens is not None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None
    provider_request_id: str | None = None
    latency_ms: int = 0


class LLMProvider(Protocol):
    name: str

    def generate(self, request: LLMRequest, api_key: SecretStr) -> LLMResponse: ...


class ProviderNotConfigured(RuntimeError):
    """The build has no live provider configured; it must not fake a response."""
