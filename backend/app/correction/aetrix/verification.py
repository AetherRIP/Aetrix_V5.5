"""Verification of a question mark.

Two independent questions are answered here:

* **integrity** — is the award internally possible?  Marks within the maximum,
  component total equal to the award, confidence above the configured floor.
* **mathematical** — where the script and the scheme both state an expression,
  is the student's answer actually equivalent?  SymPy decides, and a result it
  cannot prove is ``UNKNOWN``, which forces review rather than a silent zero.

Verification never changes an award.  It classifies it, and any uncertainty is
reported so the job can stop at ``REVIEW_REQUIRED``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sympy

from .schema import QuestionMark

_SAFE_EXPRESSION = re.compile(r"^[0-9a-zA-Z_+\-*/^().,\s]*$")
_NAMED = {
    "sqrt": sympy.sqrt,
    "pi": sympy.pi,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "log": sympy.log,
    "ln": sympy.log,
    "exp": sympy.exp,
    "E": sympy.E,
}


@dataclass(slots=True)
class VerificationRecord:
    kind: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationOutcome:
    review_required: bool
    reasons: list[str]
    records: list[VerificationRecord]


#: Notation a teacher or a model writes, but SymPy cannot read as typed.
_SYMBOLS = str.maketrans(
    {
        "\u00d7": "*",  # multiplication sign
        "\u00b7": "*",  # middle dot
        "\u00f7": "/",  # division sign
        "\u2212": "-",  # minus sign
        "\u2013": "-",  # en dash
    }
)
#: Implicit multiplication after a number or a bracket: ``2x``, ``3(x+1)``,
#: ``(x-3)(x+3)``.  A letter followed by ``(`` is left alone so ``sin(x)`` and
#: friends keep their names.
_IMPLICIT = re.compile(r"(?<=[0-9)])\s*(?=[A-Za-z(])")


def _normalise(expression: str) -> str:
    text = expression.strip().rstrip(".").strip().translate(_SYMBOLS)
    text = text.replace("^", "**")
    return _IMPLICIT.sub("*", text)


def _candidates(expression: str) -> list[str]:
    """Every form of the answer worth trying as an expression.

    A script states its result as an equation (``x = 4``, ``gradient = 3``) far
    more often than as a bare value, and SymPy has no opinion about ``=``.  The
    value side is a candidate in its own right; if it matches the expected
    answer the award is proven, and if it does not the check stays honest.
    """

    normalised = _normalise(expression)
    candidates = [normalised]
    parts = normalised.split("=")
    if len(parts) == 2:
        candidates.extend(part.strip() for part in parts if part.strip())
    return candidates


def _parse(expression: str) -> sympy.Expr | None:
    text = _normalise(expression)
    if not text or len(text) > 200 or not _SAFE_EXPRESSION.match(text):
        return None
    try:
        return sympy.parse_expr(
            text,
            local_dict=dict(_NAMED),
            evaluate=True,
        )
    except Exception:
        return None


def _parse_candidates(expression: str, *, fold_case: bool) -> list[sympy.Expr]:
    """Every form of the expression that SymPy can read, optionally case-folded."""

    items = _candidates(expression)
    if fold_case:
        items = [item.lower() for item in items]
    return [parsed for parsed in (_parse(item) for item in items) if parsed is not None]


def _decide(left: sympy.Expr, right: sympy.Expr) -> bool | None:
    try:
        difference = sympy.simplify(left - right)
        if difference == 0:
            return True
        if difference.is_number:
            return bool(abs(complex(difference)) < 1e-9)
        return False
    except Exception:
        return None


def equivalent(left: str, right: str) -> bool | None:
    """True / False when SymPy can decide, ``None`` when it cannot.

    Both sides are tried in every form they might be written in, and a single
    proven pair is enough: a correct answer must not be sent to review merely
    because it was stated as ``x = 4`` rather than ``4``.  ``None`` is not a
    failure of the student: it is the honest answer to "these expressions are
    not decidable by this check", and the caller must review it.
    """

    different = False
    for candidate in _parse_candidates(left, fold_case=False):
        for expected in _parse_candidates(right, fold_case=False):
            verdict = _decide(candidate, expected)
            if verdict is True:
                return True
            if verdict is False:
                different = True
    # A script writes a variable in capitals where the scheme writes it in lower
    # case ("24X-9" against "24x-9"), and exam marking reads the letter as the
    # same letter either way.  The case-folded pass may therefore *prove*
    # equivalence, but it never proves a difference: the strict pass above keeps
    # its verdict, so this can only remove a false alarm, never create one.
    for candidate in _parse_candidates(left, fold_case=True):
        for expected in _parse_candidates(right, fold_case=True):
            if _decide(candidate, expected) is True:
                return True
    return False if different else None


def verify_question(
    mark: QuestionMark,
    *,
    max_marks: int,
    min_confidence: float,
    page_quality: list[str] | None = None,
) -> VerificationOutcome:
    reasons: list[str] = list(mark.review_reasons)
    records: list[VerificationRecord] = []

    integrity_detail: dict[str, Any] = {
        "awarded_marks": mark.awarded_marks,
        "max_marks": max_marks,
        "confidence": mark.confidence,
        "component_total": mark.component_total,
    }
    integrity_ok = True
    if mark.awarded_marks > max_marks:
        integrity_ok = False
        reasons.append(f"Award {mark.awarded_marks} exceeds the question maximum {max_marks}.")
    if mark.component_total is not None and mark.component_total != mark.awarded_marks:
        integrity_ok = False
        reasons.append(
            "The component marks awarded "
            f"({mark.component_total}) do not equal the stated award ({mark.awarded_marks})."
        )
    if mark.confidence < min_confidence:
        integrity_ok = False
        reasons.append(
            f"Model confidence {mark.confidence:.2f} is below the review floor "
            f"{min_confidence:.2f}."
        )
    if mark.awarded_marks == 0 and mark.confidence < 0.85:
        # A zero must be a positive finding, not the absence of one.
        integrity_ok = False
        reasons.append("A zero award without high confidence requires a human decision.")
    quality = page_quality or []
    if "UNREADABLE" in quality:
        integrity_ok = False
        reasons.append("At least one page of the script is unreadable.")
    if "EMPTY" in quality:
        integrity_ok = False
        reasons.append("At least one page of the script appears blank.")
    if quality.count("LOW_QUALITY") >= 2:
        integrity_ok = False
        reasons.append("Two or more pages are of low quality, so the reading is unreliable.")

    records.append(
        VerificationRecord(
            kind="INTEGRITY",
            status="PASS" if integrity_ok else "REVIEW_REQUIRED",
            detail=integrity_detail,
        )
    )

    if mark.answer_check is not None:
        decision = equivalent(
            mark.answer_check.student_expression, mark.answer_check.expected_expression
        )
        if decision is True:
            status = "EQUIVALENT"
        elif decision is False:
            status = "DIFFERENT"
            # A different final answer is worth a person's attention even when
            # the method marks are plausible: it is a real discrepancy.
            reasons.append(
                "The final answer is not mathematically equivalent to the expected answer."
            )
        else:
            status = "UNKNOWN"
            reasons.append("The final answer could not be verified mathematically.")
        records.append(
            VerificationRecord(
                kind="MATHEMATICAL",
                status=status,
                detail={
                    "student_expression": mark.answer_check.student_expression,
                    "expected_expression": mark.answer_check.expected_expression,
                },
            )
        )

    # De-duplicate while preserving order so the screen does not repeat itself.
    unique_reasons = list(dict.fromkeys(reason for reason in reasons if reason.strip()))
    return VerificationOutcome(
        review_required=bool(unique_reasons),
        reasons=unique_reasons,
        records=records,
    )
