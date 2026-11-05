"""Local filesystem storage with path-traversal protection.

Keys are logical object names, never caller-supplied paths.  Every key is
resolved under the configured root and rejected if it escapes it.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from .base import StorageError, StoredObject


class LocalStorage:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key or "\x00" in key:
            raise StorageError("unsafe storage key")
        candidate = (self.root / key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise StorageError("storage key escapes the configured root") from error
        return candidate

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        del content_type  # local storage does not persist metadata separately
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredObject(
            key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )

    def read(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise StorageError("stored object does not exist") from error

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
