"""Read-side projection for the audit ledger.

The API exposes rows the engine already wrote.  Nothing here inserts, updates,
deletes or backfills: the endpoint is a query over ``audit_events`` and the
append-only database guards stay exactly as they are.

Two jobs live in this module:

* **Redaction.**  Audit writers are supposed to record identifiers and
  decisions, never credentials.  A projection that trusts every historical row
  to obey that rule would turn one bad writer into a leak, so known-sensitive
  key names are replaced and oversized values are truncated before the row
  leaves the process.  Ordinary metadata is returned unchanged.
* **Stable paging.**  Events are ordered newest first by ``(created_at, id)``.
  The second key makes rows with the same timestamp deterministic, so a page
  boundary cannot skip or repeat an event.
"""

from __future__ import annotations

from typing import Any

#: Key fragments that identify a value as a secret rather than event metadata.
#: Matching is on the normalised key name, so ``apiKey``, ``api_key`` and
#: ``x-api-key`` are all caught.
_SENSITIVE_FRAGMENTS = (
    "secret",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
    "ciphertext",
    "credential",
    "signature",
)

REDACTED = "[redacted]"

#: Deeper than this, a payload is structure nobody reads in a viewer.
_MAX_DEPTH = 6

#: One value longer than this is truncated rather than shipped whole.
_MAX_STRING = 2_000
_TRUNCATION_MARKER = "…[truncated]"


def _normalise(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def is_sensitive_key(key: str) -> bool:
    normalised = _normalise(key)
    return any(fragment in normalised for fragment in _SENSITIVE_FRAGMENTS)


def redact_detail(value: Any, *, depth: int = 0) -> Any:
    """Return a JSON-safe copy of an audit ``detail`` payload.

    Sensitive keys are replaced wholesale, strings are bounded, and nesting is
    capped.  The function never raises on unexpected shapes: an audit row must
    stay readable even if a historical payload is odd.
    """

    if depth >= _MAX_DEPTH:
        return _TRUNCATION_MARKER
    if isinstance(value, dict):
        return {
            str(key): (
                REDACTED if is_sensitive_key(str(key)) else redact_detail(item, depth=depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_detail(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        if len(value) > _MAX_STRING:
            return value[:_MAX_STRING] + _TRUNCATION_MARKER
        return value
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    # A JSON column should only contain JSON types, but a historical row or a
    # driver adaptation can hand back something else.  Its text is still
    # inspectable; its object is not safe to serialise.
    return str(value)
