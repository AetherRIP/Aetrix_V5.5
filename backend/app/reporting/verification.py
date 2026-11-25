"""The incomplete-correction summary, extracted from Math Checker V5.

Source: GitHub ``AetherRIP/MATH_CHECKER_V5`` at commit
``fe27e4220f42f14d4f6ad684e118b999901bc765``, file
``backend/app/engine/verify.py``.  ``partial_summary`` is copied verbatim: the
report generator's rule that a partially marked paper prints "Marked only" and
a DRAFT callout instead of a percentage is V5's, and it depends on this
function's shape (``partial``, ``coverage``, ``unresolved_marks``,
``paper_total_marks``).
"""

from __future__ import annotations


def partial_summary(verification: dict | None) -> dict | None:
    """A compact "this correction is INCOMPLETE" block for list surfaces.

    Returns ``None`` for a complete correction, so callers can simply test the
    value. A partial correction has no publishable score: the UI must show
    which questions are missing instead of a percentage that reads as a mark.
    """
    if not isinstance(verification, dict):
        return None
    # Rows written before the explicit flag existed are still partial when the
    # score was computed on a marked subset or marks are unresolved.
    if not verification.get("partial"):
        unresolved_marks = int(verification.get("unresolved_marks") or 0)
        if verification.get("score_basis") != "MARKED_ONLY" and unresolved_marks <= 0:
            return None
    coverage = verification.get("coverage") or {}
    marked = coverage.get("marked")
    expected = coverage.get("expected")
    unresolved_q = coverage.get("requires_review")
    if marked is None:
        # Legacy partial row: derive the counts from what it did record.
        expected = int(verification.get("verified_questions") or 0) or None
        unresolved_q = len(verification.get("unresolved_questions") or [])
        marked = max(0, expected - unresolved_q) if expected else 0
    return {
        "marked_questions": int(marked or 0),
        "expected_questions": int(expected or 0),
        "unresolved_questions": int(unresolved_q or 0),
        "paper_marks": verification.get("paper_total_marks"),
        "unresolved_marks": int(verification.get("unresolved_marks") or 0),
        "earned": int(verification.get("earned") or 0),
        "marked_available": int(verification.get("available") or 0),
    }
