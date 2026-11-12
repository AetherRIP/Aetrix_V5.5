"""The prompt assets the one engine loads must exist and match their hashes.

A missing or stale asset is a runtime failure on the first marked question, so it
is proven here rather than discovered by a teacher waiting on a job.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from app.core.config import get_settings
from app.correction.aetrix.pipeline import PROMPT_DOUBLE_CHECK, PROMPT_MARKING
from app.prompts.registry import PromptRegistry


def _registry() -> PromptRegistry:
    return PromptRegistry(get_settings().provider.prompt_root)


def _manifest() -> dict:
    root = get_settings().provider.prompt_root
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("prompt_id", [PROMPT_MARKING, PROMPT_DOUBLE_CHECK])
def test_every_prompt_the_engine_loads_resolves(prompt_id: str) -> None:
    asset = _registry().load(prompt_id)

    assert asset.prompt_id == prompt_id
    assert asset.version >= 1
    assert asset.content.strip()
    assert asset.content_hash
    assert asset.model_role in {"primary", "review"}


def test_the_double_check_uses_a_separate_model_role() -> None:
    registry = _registry()

    # A second opinion from the same request repeated is not independent.
    assert registry.load(PROMPT_MARKING).model_role == "primary"
    assert registry.load(PROMPT_DOUBLE_CHECK).model_role == "review"


def test_every_manifest_hash_matches_the_asset_on_disk() -> None:
    root = get_settings().provider.prompt_root

    for entry in _manifest()["prompts"]:
        content = (root / entry["path"]).read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert digest == entry["content_hash"], entry["id"]


def test_the_engine_assets_are_the_marking_prompts_in_the_manifest() -> None:
    ids = {entry["id"] for entry in _manifest()["prompts"]}

    assert {PROMPT_MARKING, PROMPT_DOUBLE_CHECK} <= ids
    # The legacy asset belonged to the removed marking package and is gone.
    assert "question_marking" not in ids
