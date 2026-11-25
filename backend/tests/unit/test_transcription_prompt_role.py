"""Which role a prompt is called under: the manifest, never a stored row.

Mission 6.1 found production's ``prompt_versions`` row for transcription v1
saying ``model_role = primary`` while the manifest says ``review``.  The row is
historical: ``get_or_create`` never rewrites one, and the router reads the role
from the asset it just loaded.  These tests pin both halves of that answer, so a
stale row can never quietly send a blind reading down the marking chain.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import get_settings
from app.core.errors import AppError
from app.prompts.registry import PromptRegistry
from app.services.provider_calls import ProviderCallService


def test_the_transcription_prompt_is_a_review_asset_in_every_version() -> None:
    import json

    root = get_settings().provider.prompt_root
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    roles = {
        entry["version"]: entry["model_role"]
        for entry in manifest["prompts"]
        if entry["id"] == "aetrix_v5_5_transcription"
    }

    assert roles, "the transcription prompt has no manifest entry"
    assert set(roles.values()) == {"review"}


def test_the_newest_transcription_asset_is_what_a_call_loads() -> None:
    asset = PromptRegistry(get_settings().provider.prompt_root).load(
        "aetrix_v5_5_transcription"
    )

    assert asset.model_role == "review"


class _RecordingService(ProviderCallService):
    """Records the role whose chain the call walked; sends nothing."""

    def __init__(self, settings, registry) -> None:
        super().__init__(None, settings, None, registry)  # type: ignore[arg-type]
        self.roles: list[str] = []

    def model_chain(self, role: str, *, capability=None):  # type: ignore[override]
        self.roles.append(role)
        return []


class _StalePromptVersions:
    """A stored row whose recorded role disagrees with the manifest."""

    def get_or_create(self, **_kwargs):
        return SimpleNamespace(model_role="primary")


def test_a_stale_stored_role_cannot_change_the_chain_that_is_walked() -> None:
    """The router uses the asset it loaded, not the row that was already there."""

    settings = get_settings()
    service = _RecordingService(
        settings, PromptRegistry(settings.provider.prompt_root)
    )
    service.prompt_versions = _StalePromptVersions()  # type: ignore[assignment]

    with pytest.raises(AppError):
        service.call(
            tenant_id=None,  # type: ignore[arg-type]
            purpose="transcription",
            prompt_id="aetrix_v5_5_transcription",
        )

    assert service.roles == ["review"]
