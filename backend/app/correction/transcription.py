"""Blind transcription: a second reading of the script that cannot agree by habit.

The marking model is asked for a mark, a scheme comparison and a quoted answer in
one breath.  A transcription pass asks a different question with none of that
context — only the pages and the question — and its answer is compared with the
answer the first pass reported.  Two readers who saw the same script should read
the same characters; when they do not, the award rests on unproven extraction and
a person decides.

Nothing here rewrites evidence.  The first pass's `student_answer` stays exactly
as it was recorded; the transcription is stored beside it, with the comparison,
and only a difference raises a concern.

A transcription costs one provider request, so it is spent where a misread is
most expensive: a zero taken beside a blank answer (the shape of an answer that is
present but unread), a question whose pages are incomplete, a low-confidence
reading, or a result the scheme already doubts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .aetrix.verification import equivalent

STATUS_AGREES = "AGREES"
STATUS_DIFFERS = "DIFFERS"
STATUS_ABSENT = "ABSENT"
STATUS_UNVERIFIABLE = "UNVERIFIABLE"

#: Confidence below which a second reading is worth its request even when the
#: first reading produced text.
LOW_CONFIDENCE = 0.85

_WHITESPACE = re.compile(r"\s+")
#: LaTeX delimiters a reader may or may not copy.
_LATEX_WRAPPERS = re.compile(r"^\$+|\$+$|^\\\(|\\\)$|^\\\[|\\\]$")
_ZERO_STATES = frozenset({"MARKED", "CONFIRMED_ZERO"})

#: Weights.  They order the queue; they are not probabilities.
_WEIGHT_BLANK_ZERO = 5.0
_WEIGHT_PAGE_RISK = 4.0
_WEIGHT_LOW_CONFIDENCE = 3.0
_WEIGHT_SCHEME_DOUBT = 2.0


@dataclass(frozen=True, slots=True)
class TranscriptionTarget:
    question_id: str
    score: float
    reasons: tuple[str, ...]


def normalise_text(text: str | None) -> str:
    """A comparison form: no wrappers, no repeated whitespace, no trailing stop."""

    value = (text or "").strip()
    if not value:
        return ""
    value = _LATEX_WRAPPERS.sub("", value).strip()
    value = _WHITESPACE.sub(" ", value)
    return value.rstrip(".").strip()


def compare_transcripts(original: str | None, transcript: str | None) -> str:
    """``AGREES`` / ``DIFFERS`` / ``ABSENT`` / ``UNVERIFIABLE``.

    Equality is textual after normalisation, with mathematical equivalence as a
    second chance: ``24 - 18y`` and ``24-18y`` are the same answer, while
    equivalence is never claimed for text SymPy cannot read.  A difference in
    either direction is a difference: a reader that finds writing where the first
    pass saw a blank is as informative as the reverse.
    """

    first = normalise_text(original)
    second = normalise_text(transcript)
    if not first and not second:
        return STATUS_ABSENT
    if not first or not second:
        return STATUS_DIFFERS
    if first == second:
        return STATUS_AGREES
    if equivalent(first, second) is True:
        return STATUS_AGREES
    return STATUS_DIFFERS


def transcribe_targets(
    rows: Iterable[Any],
    *,
    budget: int,
    skip: set[str] | None = None,
    seed: str = "",
) -> list[TranscriptionTarget]:
    """Choose the questions whose extraction is worth a second reading."""

    if budget <= 0:
        return []
    skip = skip or set()
    scored: list[TranscriptionTarget] = []
    for row in rows:
        question_id = str(row.question_id)
        if question_id in skip:
            continue
        if str(getattr(row, "processing_state", "") or "") not in _ZERO_STATES:
            continue
        awarded = int(getattr(row, "awarded_marks", 0) or 0)
        answer = (getattr(row, "student_answer", None) or "").strip()
        reasons: list[str] = []
        score = 0.0
        if awarded == 0 and not answer:
            score += _WEIGHT_BLANK_ZERO
            reasons.append(
                "BLANK_ZERO: a zero was taken beside a blank answer, which is also "
                "the shape of an answer that was present but unread."
            )
        concerns = getattr(row, "scheme_concerns", None) or []
        codes = " ".join(str(concern.get("message", "")) for concern in concerns)
        if "PAGE_" in codes:
            score += _WEIGHT_PAGE_RISK
            reasons.append(
                "PAGE_RISK: the pages this question was marked from are incomplete "
                "or partially mapped."
            )
        confidence = getattr(row, "confidence", None)
        if confidence is None or float(confidence) < LOW_CONFIDENCE:
            score += _WEIGHT_LOW_CONFIDENCE
            recorded = confidence if confidence is not None else "no"
            reasons.append(
                f"CONFIDENCE: the first reading recorded {recorded} confidence."
            )
        if getattr(row, "review_required", False):
            score += _WEIGHT_SCHEME_DOUBT
            reasons.append("SCHEME_DOUBT: the result already carries a concern.")
        if score <= 0:
            continue
        scored.append(
            TranscriptionTarget(question_id=question_id, score=score, reasons=tuple(reasons))
        )

    scored.sort(key=lambda item: (-item.score, item.question_id))
    return scored[:budget]
