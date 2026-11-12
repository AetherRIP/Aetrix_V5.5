"""The correction engine and its safeguards.

This package owns three things:

* **the one engine that marks a paper** (``aetrix`` behind ``engine.aetrix``),
* **what a result may claim** (``processing``), and
* **what protects a stored result** (``guard``, ``integrity``, ``recovery``).

AETHRIX keeps ownership of jobs, tenancy, persistence, review and approval.  The
engine only marks a paper and returns an outcome; it never decides who may read a
mark or what a grade means.
"""

from __future__ import annotations

__all__ = [
    "aetrix",
    "engine",
    "evidence",
    "guard",
    "integrity",
    "processing",
    "recovery",
    "runs",
]
