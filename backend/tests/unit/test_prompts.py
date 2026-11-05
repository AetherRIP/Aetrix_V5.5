from __future__ import annotations

import hashlib
import json

import pytest
from app.core.errors import AppError
from app.prompts.registry import PromptRegistry


def test_pinned_assets_load_with_versions() -> None:
    from app.core.config import get_settings

    registry = PromptRegistry(get_settings().provider.prompt_root)
    first = registry.load("blueprint_extraction")
    second = registry.load("page_question_mapping")
    assert first.version == 1
    assert first.identity == "blueprint_extraction@v1"
    assert first.content_hash == hashlib.sha256(first.content.encode()).hexdigest()
    assert second.prompt_id == "page_question_mapping"


def test_changing_content_without_a_version_bump_is_refused(tmp_path) -> None:
    root = tmp_path / "prompts"
    root.mkdir()
    relative = "one/v1.md"
    (root / "one").mkdir()
    (root / relative).write_text("first", encoding="utf-8")
    digest = hashlib.sha256(b"first").hexdigest()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "id": "one",
                        "version": 1,
                        "path": relative,
                        "model_role": "primary",
                        "content_hash": digest,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    PromptRegistry(root).load("one")
    (root / relative).write_text("second", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        PromptRegistry(root).load("one")


def test_unknown_prompt_version_is_a_configuration_error() -> None:
    from app.core.config import get_settings

    registry = PromptRegistry(get_settings().provider.prompt_root)
    with pytest.raises(AppError):
        registry.load("blueprint_extraction", 99)
