"""Versioned, file-backed prompt assets.

Prompts are content, not inline Python strings.  The manifest pins each asset's
version, model role and SHA-256.  A file edited without a version bump fails to
load, and the database records the exact asset used for every provider call.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import AppError, ErrorCode


@dataclass(frozen=True, slots=True)
class PromptAsset:
    prompt_id: str
    version: int
    path: str
    model_role: str
    content_hash: str
    content: str
    description: str = ""

    @property
    def identity(self) -> str:
        return f"{self.prompt_id}@v{self.version}"


class PromptRegistry:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.manifest_path = self.root / "manifest.json"
        self._entries = self._read_manifest()
        self._assets: dict[tuple[str, int], PromptAsset] = {}

    def _read_manifest(self) -> dict[tuple[str, int], dict[str, Any]]:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ValueError(f"prompt manifest not found at {self.manifest_path}") from error
        except ValueError as error:
            raise ValueError(f"prompt manifest is not valid JSON: {self.manifest_path}") from error
        entries: dict[tuple[str, int], dict[str, Any]] = {}
        for raw in payload.get("prompts", []):
            prompt_id = str(raw.get("id", "")).strip()
            version = raw.get("version")
            relative = str(raw.get("path", "")).strip()
            if not prompt_id or not isinstance(version, int) or version < 1 or not relative:
                raise ValueError("each prompt entry needs id, positive integer version and path")
            key = (prompt_id, version)
            if key in entries:
                raise ValueError(f"duplicate prompt entry: {prompt_id} v{version}")
            entries[key] = raw
        if not entries:
            raise ValueError("prompt manifest contains no prompts")
        return entries

    def _load_asset(self, prompt_id: str, version: int) -> PromptAsset:
        key = (prompt_id, version)
        if key in self._assets:
            return self._assets[key]
        entry = self._entries.get(key)
        if entry is None:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                f"Prompt {prompt_id!r} version {version} is not in the manifest.",
                details={"prompt_id": prompt_id, "version": version},
            )
        relative = str(entry["path"])
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise ValueError(f"prompt path escapes the prompt root: {relative}") from error
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ValueError(f"prompt asset is missing: {relative}") from error
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        expected = str(entry.get("content_hash", "")).strip()
        if expected and expected != digest:
            raise ValueError(
                f"prompt asset {relative} does not match its manifest hash; "
                "edit the manifest and bump the version when changing a prompt"
            )
        asset = PromptAsset(
            prompt_id=prompt_id,
            version=version,
            path=str(path),
            model_role=str(entry.get("model_role", "primary")),
            content_hash=digest,
            content=content,
            description=str(entry.get("description", "")),
        )
        self._assets[key] = asset
        return asset

    def load(self, prompt_id: str, version: int | None = None) -> PromptAsset:
        if version is not None:
            return self._load_asset(prompt_id, version)
        versions = [v for (pid, v) in self._entries if pid == prompt_id]
        if not versions:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                f"Prompt {prompt_id!r} is not configured.",
                details={"prompt_id": prompt_id},
            )
        return self._load_asset(prompt_id, max(versions))
