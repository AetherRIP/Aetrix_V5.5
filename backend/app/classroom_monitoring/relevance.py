"""Assignment relevance: does this work plausibly belong to this assignment?

This is evidence, never a mark, and never a filename guess.  The comparison is
transparent: title and paper-code matches, question markers from the approved
blueprint, and — when a scan has no text at all — a structural judgement that
says so out loud.

A readable handwritten script has no text layer.  Treating that as "unrelated"
would block the most common real submission, so the monitoring configuration
chooses the policy: ``STRUCTURAL_ALLOW`` marks such work with the limitation
recorded, and ``TEXT_REQUIRED`` sends it to a teacher instead.  Neither policy
ever silently rejects work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LIKELY_RELEVANT = "LIKELY_RELEVANT"
POSSIBLY_UNRELATED = "POSSIBLY_UNRELATED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CANNOT_DETERMINE = "CANNOT_DETERMINE"

_STRUCTURAL_ALLOW = "STRUCTURAL_ALLOW"
_TEXT_REQUIRED = "TEXT_REQUIRED"

_PAPER_CODE = re.compile(r"\b[A-Z]{2,6}[ _-]?\d{1,3}[A-Z]?\b")

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "paper",
        "assignment",
        "test",
        "exam",
        "practice",
        "work",
        "homework",
        "class",
        "year",
        "term",
        "mathematics",
        "maths",
        "math",
        "questions",
        "question",
        "answer",
        "answers",
        "sheet",
    }
)


@dataclass(frozen=True, slots=True)
class RelevanceAssessment:
    relevance: str
    evidence: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    missing_expected: list[str] = field(default_factory=list)
    found_expected: list[str] = field(default_factory=list)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _normalise(value))
        if len(token) >= 4 and token not in _STOPWORDS
    ]


def _paper_codes(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        match.replace(" ", "").replace("_", "-") for match in _PAPER_CODE.findall(value.upper())
    ]


def _question_marker(text: str, question_id: str) -> bool:
    escaped = re.escape(question_id)
    patterns = (
        rf"(?<![\w.]){escaped}(?![\w])",
        rf"\bq\s*{escaped}\b",
    )
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    for pattern in patterns:
        if re.search(pattern, lowered):
            return True
    if question_id.isdigit():
        return bool(re.search(rf"(?<!\d)0*{question_id}(?!\d)", compact))
    return question_id.lower() in compact


def assess(
    *,
    text: str,
    page_count: int,
    readable_pages: int,
    assignment_name: str | None,
    assignment_description: str | None,
    expected_questions: list[str],
    policy: str,
    has_attachments: bool,
) -> RelevanceAssessment:
    """Compare the inspected work with the assignment it was submitted to."""

    evidence: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not has_attachments:
        return RelevanceAssessment(
            relevance=INSUFFICIENT_EVIDENCE,
            warnings=[
                {
                    "code": "NO_ATTACHMENT",
                    "message": "The submission has no attachment to compare.",
                }
            ],
        )

    if readable_pages < 1:
        return RelevanceAssessment(
            relevance=CANNOT_DETERMINE,
            warnings=[
                {
                    "code": "NO_READABLE_PAGE",
                    "message": "No page could be read, so relevance cannot be assessed.",
                }
            ],
        )

    normalised = _normalise(text)
    has_text = len(normalised) >= 40

    if not has_text:
        if policy == _TEXT_REQUIRED:
            return RelevanceAssessment(
                relevance=CANNOT_DETERMINE,
                warnings=[
                    {
                        "code": "RELEVANCE_TEXT_REQUIRED",
                        "message": (
                            "This assignment is configured to require readable text, and "
                            "the work has none. A teacher must confirm it belongs here."
                        ),
                    }
                ],
            )
        return RelevanceAssessment(
            relevance=LIKELY_RELEVANT,
            evidence=[
                {
                    "code": "STRUCTURAL_EVIDENCE",
                    "message": (
                        f"The work is readable across {readable_pages} page(s) but has no "
                        "text layer, so it was assessed structurally rather than by "
                        "content."
                    ),
                }
            ],
            warnings=[
                {
                    "code": "RELEVANCE_TEXT_UNAVAILABLE",
                    "message": (
                        "The text could not be compared with the assignment; this is "
                        "expected for handwritten work and is recorded in the report."
                    ),
                }
            ],
        )

    keywords = _keywords(assignment_name) + _keywords(assignment_description)
    matched_keywords = sorted({word for word in keywords if word in normalised})
    expected_codes = _paper_codes(assignment_name) + _paper_codes(assignment_description)
    compact_text = normalised.replace("-", "").replace(" ", "")

    def _compact(code: str) -> str:
        return code.replace("-", "").lower()

    expected_compact = {_compact(code) for code in expected_codes}
    present_codes = {code for code in _paper_codes(text) if len(code.replace("-", "")) >= 4}
    matched_codes = sorted(code for code in expected_codes if _compact(code) in compact_text)
    # Only a code that is clearly a *different* paper counts as negative
    # evidence; a stray capitalised token is not proof of anything.
    foreign_codes = sorted(code for code in present_codes if _compact(code) not in expected_compact)

    found = [question for question in expected_questions if _question_marker(text, question)]
    missing = [question for question in expected_questions if question not in found]

    if matched_keywords:
        evidence.append(
            {
                "code": "TITLE_MATCH",
                "message": "The work mentions the assignment's own words: "
                + ", ".join(matched_keywords[:5])
                + ".",
            }
        )
    if matched_codes:
        evidence.append(
            {
                "code": "PAPER_CODE_MATCH",
                "message": "The work carries the assignment's paper code "
                + ", ".join(matched_codes[:3])
                + ".",
            }
        )
    if found:
        evidence.append(
            {
                "code": "QUESTION_MARKER_MATCH",
                "message": "Question markers found: " + ", ".join(found[:8]) + ".",
            }
        )
    if missing and found:
        warnings.append(
            {
                "code": "MISSING_EXPECTED_QUESTIONS",
                "message": (
                    "Question markers were not found for: "
                    + ", ".join(missing[:10])
                    + ". A missing marker does not prove the answer is absent, so the "
                    "submission is kept and highlighted."
                ),
            }
        )

    # A negative signal must be affirmative evidence of a different paper, not
    # merely the absence of the expected one: a student may omit a title.
    if expected_codes and foreign_codes and not matched_codes:
        return RelevanceAssessment(
            relevance=POSSIBLY_UNRELATED,
            evidence=evidence,
            warnings=[
                {
                    "code": "DIFFERENT_PAPER_CODE",
                    "message": (
                        "The work carries a different paper code ("
                        + ", ".join(foreign_codes[:3])
                        + ") and not this assignment's. It was not rejected; a teacher "
                        "must confirm it."
                    ),
                }
            ],
            missing_expected=missing,
            found_expected=found,
        )

    if matched_keywords or matched_codes or found:
        return RelevanceAssessment(
            relevance=LIKELY_RELEVANT,
            evidence=evidence,
            warnings=warnings,
            missing_expected=missing,
            found_expected=found,
        )

    return RelevanceAssessment(
        relevance=INSUFFICIENT_EVIDENCE,
        evidence=evidence,
        warnings=[
            *warnings,
            {
                "code": "NO_MATCHING_EVIDENCE",
                "message": (
                    "The work is readable but nothing in it matches the assignment "
                    "title, paper code or expected question markers. A teacher must "
                    "confirm it belongs here."
                ),
            },
        ],
        missing_expected=missing,
        found_expected=found,
    )
