"""Identifiers and deterministic hashes.

Hashes are used for idempotency and audit provenance.  They must be stable
across processes, so they are built from canonical JSON rather than Python's
``repr`` or dictionary order.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(UTC)


def sha256_hex(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def content_hash(*parts: Any) -> str:
    """Hash an ordered tuple of values, preserving separation between parts."""
    digest = hashlib.sha256()
    for part in parts:
        encoded = canonical_json(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def short_id(value: uuid.UUID | str) -> str:
    return str(value)[:8]
