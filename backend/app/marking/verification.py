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

from ..marking.schema import QuestionMark

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


def _parse(expression: str) -> sympy.Expr | None:
    text = expression.strip()
    if not text or len(text) > 200 or not _SAFE_EXPRESSION.match(text):
        return None
    try:
        return sympy.parse_expr(
            text.replace("^", "**"),
            local_dict=dict(_NAMED),
            evaluate=True,
        )
    except Exception:
        return None


def equivalent(left: str, right: str) -> bool | None:
    """True / False when SymPy can decide, ``None`` when it cannot.

    ``None`` is not a failure of the student: it is the honest answer to "these
    expressions are not decidable by this check", and the caller must review it.
    """

    a = _parse(left)
    b = _parse(right)
    if a is None or b is None:
        return None
    try:
        difference = sympy.simplify(a - b)
        if difference == 0:
            return True
        if difference.is_number:
            return bool(abs(complex(difference)) < 1e-9)
        return False
    except Exception:
        return None


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
