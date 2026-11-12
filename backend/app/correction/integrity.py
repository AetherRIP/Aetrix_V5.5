"""Evidence-based mark integrity.

These checks answer one narrow question: is this award internally supportable by
what the model itself reported?  They are not a proof of mathematical
correctness and must never be presented as one — symbolic verification lives in
``marking.verification`` and is a separate verdict.

Every check here is deterministic and never rewrites a mark.  A finding turns
the question into ``NEEDS_REVIEW`` so a person decides; the award is left as the
model's, or as the normalisation rule left it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IntegrityFinding:
    code: str
    message: str


def _blank_answer(text: str | None) -> bool:
    return not (text or "").strip()


def _has_quoted_evidence(components: list[Any]) -> bool:
    return any((getattr(component, "evidence", None) or "").strip() for component in components)


def check_mark(
    *,
    awarded: int,
    max_marks: int,
    components: list[Any],
    student_answer: str | None,
    confidence: float | None,
) -> list[IntegrityFinding]:
    """Return every finding for one parsed mark.

    Codes are stable so the review screen and the learning record can group
    them:

    ``NEGATIVE_AWARD``, ``AWARD_ABOVE_MAXIMUM``, ``COMPONENT_TOTAL_MISMATCH``,
    ``AWARD_EXCEEDS_COMPONENT_CAPACITY``, ``MARKS_FOR_BLANK_ANSWER``,
    ``AWARDED_COMPONENT_WITH_NO_MARKS``.
    """

    findings: list[IntegrityFinding] = []

    if awarded < 0:
        findings.append(
            IntegrityFinding("NEGATIVE_AWARD", "The award is negative.")
        )
    if awarded > max_marks:
        findings.append(
            IntegrityFinding(
                "AWARD_ABOVE_MAXIMUM",
                f"The award {awarded} exceeds the question maximum {max_marks}.",
            )
        )

    if components:
        total = sum(component.marks for component in components if component.awarded)
        if total != awarded:
            findings.append(
                IntegrityFinding(
                    "COMPONENT_TOTAL_MISMATCH",
                    f"The awarded components total {total}, but the stated award is {awarded}.",
                )
            )
        capacity = sum(component.marks for component in components)
        if awarded > capacity:
            findings.append(
                IntegrityFinding(
                    "AWARD_EXCEEDS_COMPONENT_CAPACITY",
                    f"The award {awarded} exceeds the {capacity} marks the components "
                    "describe.",
                )
            )
        for component in components:
            if getattr(component, "awarded", False) and getattr(component, "marks", 0) <= 0:
                findings.append(
                    IntegrityFinding(
                        "AWARDED_COMPONENT_WITH_NO_MARKS",
                        f"Component {getattr(component, 'code', '?')!r} is awarded but "
                        "carries no marks.",
                    )
                )

    if awarded > 0 and _blank_answer(student_answer) and not _has_quoted_evidence(components):
        findings.append(
            IntegrityFinding(
                "MARKS_FOR_BLANK_ANSWER",
                "Marks were awarded for a question with no recorded answer and no "
                "quoted evidence.",
            )
        )

    return findings


def duplicate_codes(components: list[Any]) -> list[str]:
    """Component codes that appear more than once, in first-seen order.

    The parser disambiguates repeats rather than rejecting the response, so this
    is reported as context, never as a failure.
    """

    seen: dict[str, int] = {}
    for component in components:
        code = str(getattr(component, "code", "")).strip()
        if not code:
            continue
        seen[code] = seen.get(code, 0) + 1
    return [code for code, count in seen.items() if count > 1]
