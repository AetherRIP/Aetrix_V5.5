"""A prompt identity may not be re-pointed at different bytes.

``prompt_versions`` records the SHA-256 of the exact bytes each provider call
used, and ``PromptVersionRepository`` refuses to write a different hash under an
identity that already exists.  That refusal is what parked the first pilot
attempt — correctly — because the asset behind marking v2 had been edited without
a version bump.

``test_prompt_manifest.py`` already proves every declared hash matches its file.
These tests cover the case that check cannot see: two versions of one prompt that
ship identical bytes.  That is the shape a silent re-pointing leaves behind, and
it must name the version it reissues so a reader can tell a new identity from a
changed one.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
from app.prompts.registry import PromptRegistry

PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts"


def _entries() -> list[dict[str, Any]]:
    payload = json.loads((PROMPT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    return list(payload["prompts"])


def test_a_duplicate_content_hash_declares_what_it_reissues() -> None:
    """Same bytes under a new version is a re-identity, and must say so."""

    by_prompt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in _entries():
        by_prompt[str(entry["id"])].append(entry)

    silent: list[str] = []
    for prompt_id, entries in by_prompt.items():
        seen: dict[str, int] = {}
        for entry in sorted(entries, key=lambda item: int(item["version"])):
            digest = str(entry["content_hash"])
            if digest in seen:
                earlier = seen[digest]
                if entry.get("reissues") != earlier:
                    silent.append(
                        f"{prompt_id} v{entry['version']} repeats v{earlier} exactly "
                        f"and declares reissues={entry.get('reissues')!r}"
                    )
            else:
                seen[digest] = int(entry["version"])
    assert not silent, "duplicate prompt content must name the version it reissues: " + (
        "; ".join(silent)
    )


def test_a_reissue_names_an_earlier_version_of_the_same_prompt() -> None:
    """A reissue claim that points nowhere is worse than no claim."""

    versions: dict[str, set[int]] = defaultdict(set)
    for entry in _entries():
        versions[str(entry["id"])].add(int(entry["version"]))

    for entry in _entries():
        if "reissues" not in entry:
            continue
        declared = int(entry["reissues"])
        version = int(entry["version"])
        assert declared < version, (
            f"{entry['id']} v{version} claims to reissue v{declared}, which is not earlier"
        )
        assert declared in versions[str(entry["id"])], (
            f"{entry['id']} v{version} claims to reissue v{declared}, which no longer "
            "exists in the manifest; the claim cannot be checked"
        )


@pytest.mark.parametrize("prompt_id", ["aetrix_v5_5_marking", "aetrix_v5_5_double_check"])
def test_the_provenance_fields_do_not_stop_the_registry_loading(prompt_id: str) -> None:
    """The fields are documentation; they must not change how an asset loads."""

    asset = PromptRegistry(PROMPT_ROOT).load(prompt_id)
    assert asset.version >= 2
    assert len(asset.content_hash) == 64
