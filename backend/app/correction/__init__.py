"""The correction-engine seam and its safeguards.

This package owns three things that are independent of which engine marks a
paper:

* **which engine runs** (``registry`` + ``engine/``),
* **what a result may claim** (``processing``), and
* **what protects a stored result** (``guard``, ``integrity``, ``recovery``).

AETHRIX keeps ownership of jobs, tenancy, persistence, review and approval.
An engine here only marks a paper and returns an outcome; it never decides who
may read a mark or what a grade means.
"""

from __future__ import annotations

__all__ = [
    "engine",
    "evidence",
    "guard",
    "integrity",
    "processing",
    "recovery",
    "registry",
    "runs",
]
