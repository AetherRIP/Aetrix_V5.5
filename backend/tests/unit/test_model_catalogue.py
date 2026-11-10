"""Discovery reads Google's list; it never invents a catalogue.

Every request here goes through an in-process ``httpx`` transport: no network,
no quota.  The tests pin the properties that keep the selector honest — exact
model ids, per-project availability, and specialised endpoints excluded from
correction rather than presented as choices.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.core.config import get_settings
from app.core.ids import utcnow
from app.providers.errors import ProviderAuthenticationError, ProviderTransientError
from app.services.model_catalogue import build_catalogue, fetch_project_models
from pydantic import SecretStr

BASE = "https://generativelanguage.googleapis.com/v1beta"
KEY = SecretStr("AIza-model-list-key-that-must-not-appear")


def _raw(
    model_id: str,
    methods: tuple[str, ...] = ("generateContent", "countTokens"),
    **extra: Any,
) -> dict[str, Any]:
    return {
        "name": f"models/{model_id}",
        "displayName": model_id,
        "supportedGenerationMethods": list(methods),
        "inputTokenLimit": 1_048_576,
        "outputTokenLimit": 65_536,
        **extra,
    }


def test_pagination_collects_every_page_and_keeps_exact_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("pageToken") is None:
            return httpx.Response(
                200,
                json={
                    "models": [_raw("gemini-3.8-flash")],
                    "nextPageToken": "page-2",
                },
            )
        return httpx.Response(200, json={"models": [_raw("gemini-3.7-flash")]})

    models = fetch_project_models(
        BASE, KEY, transport=httpx.MockTransport(handler)
    )

    assert [item["name"] for item in models] == [
        "models/gemini-3.8-flash",
        "models/gemini-3.7-flash",
    ]


def test_authentication_failure_keeps_its_status_and_hides_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"code": 401, "message": "API key not valid"}}
        )

    with pytest.raises(ProviderAuthenticationError) as caught:
        fetch_project_models(BASE, KEY, transport=httpx.MockTransport(handler))

    assert caught.value.status_code == 401
    assert "AIza" not in str(caught.value)
    assert KEY.get_secret_value() not in str(caught.value)


def test_provider_outage_is_transient_not_a_bad_credential() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503, json={"error": {"code": 503, "message": "unavailable"}}
        )

    with pytest.raises(ProviderTransientError) as caught:
        fetch_project_models(BASE, KEY, transport=httpx.MockTransport(handler))

    assert caught.value.status_code == 503


def test_catalogue_classifies_status_and_per_project_availability() -> None:
    raw_by_project = {
        "proj-a": [
            _raw("gemini-3.8-flash"),
            _raw("gemini-3.1-pro-preview"),
            _raw("gemini-3.1-flash-lite-preview"),
            _raw("gemini-2.5-flash-image"),
        ],
        "proj-b": [
            _raw("gemini-3.8-flash"),
            _raw("gemini-3.6-flash"),
            _raw("gemini-3.7-flash"),
        ],
    }

    catalogue = build_catalogue(
        raw_by_project, get_settings(), discovered_at=utcnow(), cached=False
    )
    by_id = {model["id"]: model for model in catalogue["models"]}

    assert by_id["gemini-3.8-flash"]["status"] == "stable"
    assert by_id["gemini-3.1-pro-preview"]["status"] == "preview"
    assert by_id["gemini-3.1-flash-lite-preview"]["status"] == "deprecated"
    assert by_id["gemini-2.5-flash-image"]["status"] == "unsupported"
    assert by_id["gemini-2.5-flash-image"]["status_detail"]

    # Availability is per project and never inferred from the union.
    assert by_id["gemini-3.8-flash"]["projects"] == [
        {"project_id": "proj-a", "available": True},
        {"project_id": "proj-b", "available": True},
    ]
    assert by_id["gemini-3.6-flash"]["projects"] == [
        {"project_id": "proj-a", "available": False},
        {"project_id": "proj-b", "available": True},
    ]

    # Only configured rates are reported; a missing price stays null.
    assert by_id["gemini-3.8-flash"]["input_usd_per_million"] == 0.75
    # 3.7 Flash is listed but has no configured rate, so no price is invented.
    assert by_id["gemini-3.7-flash"]["input_usd_per_million"] is None

    # Supported models sort before the excluded ones.
    assert catalogue["models"][0]["status"] != "unsupported"
    assert catalogue["models"][-1]["status"] == "unsupported"


def test_documented_inputs_are_carried_with_their_source() -> None:
    catalogue = build_catalogue(
        {"proj-a": [_raw("gemini-3.8-flash")]},
        get_settings(),
        discovered_at=utcnow(),
        cached=True,
    )
    capabilities = catalogue["models"][0]["capabilities"]

    assert capabilities["documented_inputs"] == [
        "text",
        "image",
        "video",
        "audio",
        "pdf",
    ]
    assert capabilities["source"]
    # Nothing verified structured output for this model, so it is not claimed.
    assert capabilities["structured_outputs"] is None
    assert catalogue["cached"] is True
