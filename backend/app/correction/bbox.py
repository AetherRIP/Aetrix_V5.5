"""Validation of an evidence bounding box.

A bounding box is only ever kept when it is well formed.  It is never repaired,
recomputed or invented: a box that points at the wrong region is worse than no
box, because a reader trusts it.  This module is deliberately dependency-free so
both the reply contract and the provenance check can use it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The only keys a stored bounding box may carry, in normalised image space.
BBOX_KEYS = ("x0", "y0", "x1", "y1")


def check_bbox(value: Any) -> tuple[list[float] | None, str | None]:
    """Validate a bounding box in normalised image space.

    Returns ``(box, problem)``.  ``(None, None)`` means no box was offered.
    A box that is present but unusable is returned as ``(None, reason)``.
    Coordinates map the page as 0 to 1 from its top-left corner, so a page of
    any pixel size uses the same box.
    """

    if value is None:
        return None, None
    raw: Any = value
    if isinstance(raw, Mapping):
        missing = [key for key in BBOX_KEYS if key not in raw]
        if missing:
            return None, f"a bounding box is missing {', '.join(missing)}"
        raw = [raw.get(key) for key in BBOX_KEYS]
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None, "a bounding box must be four normalised numbers"
    numbers: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None, "a bounding box coordinate is not a number"
        number = float(item)
        if number < 0.0 or number > 1.0:
            return None, "a bounding box coordinate is outside the page (0 to 1)"
        numbers.append(number)
    x0, y0, x1, y1 = numbers
    if x1 <= x0 or y1 <= y0:
        return None, "a bounding box has no area (its lower corner is not below its upper one)"
    return numbers, None
