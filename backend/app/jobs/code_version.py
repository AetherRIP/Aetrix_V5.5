"""Fingerprint of the routing code a worker process is running.

A worker keeps the routing policy in memory.  If the files change underneath it
-- a fix applied while the resident worker keeps polling, or a deploy that
replaces the checkout -- that process would keep marking new jobs with the old
policy and record nothing about it.  A lease cannot detect this: the process is
alive, its heartbeat is fresh, and the job it claims is legitimately its own.

The fingerprint is what makes the mismatch visible.  The worker records it at
startup, stamps it on the terminal event of every job it finishes, and refuses
to claim another job once the code on disk no longer matches the code it loaded.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]

#: The modules whose behaviour decides how an attempt is routed, retried and
#: recorded.  A change to any of them makes a loaded process out of date for the
#: purpose of marking, even when it still runs.
_ROUTING_SOURCES: tuple[str, ...] = (
    "providers/routing.py",
    "services/provider_calls.py",
    "providers/gemini.py",
    "providers/base.py",
    "core/config.py",
    "correction/aetrix/pipeline.py",
)

#: mtime/size key -> digest, so a poll loop does not re-read ~200 KB every
#: iteration.  The key covers every source, so any edit invalidates it.
_cache: tuple[tuple[tuple[str, int, int], ...], str] | None = None


def code_fingerprint() -> str:
    """A stable digest of the routing sources currently on disk."""

    global _cache
    paths = [_APP / relative for relative in _ROUTING_SOURCES]
    stamp: list[tuple[str, int, int]] = []
    for relative, path in zip(_ROUTING_SOURCES, paths, strict=True):
        try:
            stat = path.stat()
            stamp.append((relative, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            stamp.append((relative, -1, -1))
    key = tuple(stamp)
    if _cache is not None and _cache[0] == key:
        return _cache[1]

    digest = hashlib.sha256()
    for relative, path in zip(_ROUTING_SOURCES, paths, strict=True):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    value = digest.hexdigest()
    _cache = (key, value)
    return value


__all__ = ["code_fingerprint"]
