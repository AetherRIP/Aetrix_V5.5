"""Storage backends and the factory that selects one honestly."""

from __future__ import annotations

from ..core.config import Settings
from .base import Storage, StorageError, StoredObject
from .local import LocalStorage

__all__ = ["LocalStorage", "Storage", "StorageError", "StoredObject", "build_storage"]


def build_storage(settings: Settings) -> Storage:
    backend = settings.storage.backend.strip().lower()
    if backend == "local":
        return LocalStorage(settings.storage.root)
    raise ValueError(
        f"unsupported storage backend {settings.storage.backend!r}; "
        "no fallback storage is configured"
    )
