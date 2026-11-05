"""Storage abstraction for uploaded documents and rendered pages.

The engine never writes a document with a bare filesystem call.  Production can
replace the local backend with an object-store adapter without changing the
ingestion pipeline, and tests can point the local backend at a temporary
directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    sha256: str
    size_bytes: int


class StorageError(RuntimeError):
    """A storage operation failed or was asked for an unsafe key."""


class Storage(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def read(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...
