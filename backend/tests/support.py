"""Test-only providers and document builders.

These are fixtures, not production fallbacks: the production factory never
returns a fake provider.
"""

from __future__ import annotations

import io

import pymupdf
from app.providers.base import LLMRequest, LLMResponse, TokenUsage
from PIL import Image, ImageDraw


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        text: str = "{}",
        *,
        usage: TokenUsage | None = None,
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.usage = usage or TokenUsage(input_tokens=100, output_tokens=50, cached_tokens=0)
        self.error = error
        self.requests: list[LLMRequest] = []
        self.keys: list[str] = []

    def generate(self, request: LLMRequest, api_key) -> LLMResponse:
        self.requests.append(request)
        self.keys.append(api_key.get_secret_value())
        if self.error is not None:
            raise self.error
        return LLMResponse(
            text=self.text,
            model=request.model,
            usage=self.usage,
            finish_reason="STOP",
            provider_request_id="fake-request",
            latency_ms=1,
        )


def make_pdf(pages: list[str]) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 72), text, fontsize=12)
    data = document.tobytes()
    document.close()
    return data


def make_image_pdf() -> bytes:
    """A PDF with a drawn rectangle but no text layer."""
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.draw_rect(pymupdf.Rect(100, 100, 500, 700), color=(0, 0, 0), width=2)
    data = document.tobytes()
    document.close()
    return data


def make_png(width: int = 1000, height: int = 1400, *, text: str | None = None) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    if text:
        draw = ImageDraw.Draw(image)
        draw.text((50, 50), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
