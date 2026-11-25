"""How thoroughly a result has been verified, as a fact rather than a feeling.

Correction completion and verification completeness are different questions.
A paper is *complete* when every scoreable leaf has a decided row; it is
*verified* only when the checks that policy requires for those rows actually ran
and came back positive.  The default policy samples the expensive AI checks, so
a complete paper is normally only partially verified — and saying so is the
point.

Everything here is deterministic: it reads the stored result rows and the
stored verification records.  It never calls a provider and never changes an
award.

Required checks per question
----------------------------
``INTEGRITY``
    Always.  Marks within the maximum, components adding to the award, a
    confidence above the floor.
``MATHEMATICAL`` (or ``SCHEME_MATHEMATICAL``)
    When the run produced a mathematical verdict at all.  A ``SKIPPED`` verdict
    means neither the reply nor the approved scheme stated an answer, so there
    is nothing to check — that is *not applicable*, not a pass.
``EVIDENCE``
    For every awarded question.  Each award must rest on a quotation the blind
    reading could find in the script.  A question with no evidence check is
    partially verified, never verified.
``TRANSCRIPTION`` / ``DOUBLE_CHECK``
    When the run actually bought one for this question.  Once a check has been
    attempted, its outcome is required: an ``UNVERIFIABLE`` reading is a reason
    for a person, not a missing optional step.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

STATUS_FULLY_VERIFIED = "FULLY_VERIFIED"
STATUS_PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATUS_NOT_REQUIRED = "VERIFICATION_NOT_REQUIRED"

STATUSES = (
    STATUS_FULLY_VERIFIED,
    STATUS_PARTIALLY_VERIFIED,
    STATUS_REVIEW_REQUIRED,
    STATUS_VERIFICATION_FAILED,
    STATUS_NOT_REQUIRED,
)

KIND_INTEGRITY = "INTEGRITY"
KIND_MATHEMATICAL = "MATHEMATICAL"
KIND_SCHEME_MATHEMATICAL = "SCHEME_MATHEMATICAL"
KIND_TRANSCRIPTION = "TRANSCRIPTION"
KIND_EVIDENCE = "EVIDENCE"
KIND_DOUBLE_CHECK = "DOUBLE_CHECK"

#: The check kinds that make a question "independently verified" rather than
#: merely internally consistent.
INDEPENDENT_KINDS = frozenset(
    {
        KIND_MATHEMATICAL,
        KIND_SCHEME_MATHEMATICAL,
        KIND_TRANSCRIPTION,
        KIND_EVIDENCE,
        KIND_DOUBLE_CHECK,
    }
)

_VERIFIED = "VERIFIED"
_CONTRADICTED = "CONTRADICTED"
_UNVERIFIABLE = "UNVERIFIABLE"
_MISSING = "MISSING"
_NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class QuestionVerification:
    """One question's verification state, with every check accounted for."""

    question_id: str
    status: str
    required: tuple[str, ...] = ()
    verified: tuple[str, ...] = ()
    contradicted: tuple[str, ...] = ()
    unverifiable: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    not_applicable: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "status": self.status,
            "required": list(self.required),
            "verified": list(self.verified),
            "contradicted": list(self.contradicted),
            "unverifiable": list(self.unverifiable),
            "missing": list(self.missing),
            "not_applicable": list(self.not_applicable),
            "reasons": list(self.reasons)[:10],
        }


@dataclass(frozen=True, slots=True)
class PaperVerification:
    """The paper's derived verification state and the per-question evidence."""

    status: str
    questions: tuple[QuestionVerification, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "counts": dict(self.counts),
            "questions": [item.describe() for item in self.questions],
        }

    def question(self, question_id: str) -> QuestionVerification | None:
        for item in self.questions:
            if item.question_id == question_id:
                return item
        return None


def _pick_math(records: Mapping[str, tuple[str, dict[str, Any]]]) -> tuple[str | None, str | None]:
    """The mathematical verdict that should count, preferring the scheme's.

    A model's own answer check and the approved scheme's stated answer are two
    different checks.  When both exist the scheme's verdict is the independent
    one, so it decides; ``UNKNOWN`` still means unverifiable.
    """

    for kind in (KIND_SCHEME_MATHEMATICAL, KIND_MATHEMATICAL):
        found = records.get(kind)
        if found is not None and found[0] != "SKIPPED":
            return kind, found[0]
    if KIND_MATHEMATICAL in records:
        return KIND_MATHEMATICAL, "SKIPPED"
    return None, None


def _verdicts(
    kind: str, status: str, *, awarded: int
) -> tuple[str, str]:
    """``(state, reason)`` for one check's stored status."""

    if kind == KIND_INTEGRITY:
        if status == "PASS":
            return _VERIFIED, ""
        return _CONTRADICTED, "The award failed its integrity check."
    if kind in (KIND_MATHEMATICAL, KIND_SCHEME_MATHEMATICAL):
        if status == "EQUIVALENT":
            return _VERIFIED, ""
        if status == "DIFFERENT":
            return _CONTRADICTED, "The final answer contradicts the expected answer."
        return _UNVERIFIABLE, "The final answer could not be verified mathematically."
    if kind == KIND_EVIDENCE:
        if status == "PASS":
            return _VERIFIED, ""
        if status == "FAIL":
            return _CONTRADICTED, "A quoted piece of evidence was not found in the script."
        return _UNVERIFIABLE, "The quoted evidence could not be checked against the script."
    if kind == KIND_TRANSCRIPTION:
        if status == "AGREES":
            return _VERIFIED, ""
        if status == "DIFFERS":
            return _CONTRADICTED, "The independent reading disagrees with the marking pass."
        if status == "ABSENT" and awarded == 0:
            # Both readings found nothing: for a zero this is agreement about
            # the script, and it is recorded as such.
            return _VERIFIED, ""
        return _UNVERIFIABLE, "The independent reading could not verify this answer."
    if kind == KIND_DOUBLE_CHECK:
        if status == "AGREES":
            return _VERIFIED, ""
        if status == "DISAGREES":
            return _CONTRADICTED, "An independent examiner awarded a different mark."
        return _UNVERIFIABLE, "The second marking could not be read."
    return _UNVERIFIABLE, f"Unknown verification kind {kind!r}."


def question_verification(
    row: Any,
    records: Mapping[str, tuple[str, dict[str, Any]]],
) -> QuestionVerification:
    """Derive one question's status from its row and stored verdicts."""

    question_id = str(getattr(row, "question_id", "") or "")
    awarded = int(getattr(row, "awarded_marks", 0) or 0)
    scoreable = str(getattr(row, "processing_state", "") or "") in {
        "MARKED",
        "CONFIRMED_ZERO",
    }
    review_required = bool(getattr(row, "review_required", False))

    required: list[str] = [KIND_INTEGRITY]
    math_kind, math_status = _pick_math(records)
    if math_status is not None and math_status != "SKIPPED":
        required.append(str(math_kind))
    if awarded > 0:
        required.append(KIND_EVIDENCE)
    for kind in (KIND_TRANSCRIPTION, KIND_DOUBLE_CHECK):
        if kind in records:
            required.append(kind)

    verified: list[str] = []
    contradicted: list[str] = []
    unverifiable: list[str] = []
    missing: list[str] = []
    not_applicable: list[str] = []
    reasons: list[str] = []

    for kind in required:
        found = records.get(kind)
        if found is None:
            # A required check with no record is a gap, not a pass.  The one
            # exception is a mathematical check the reply and the scheme both
            # left undefined: the explicit SKIPPED record covers that.
            missing.append(kind)
            reasons.append(f"The required {kind.lower()} verification has no record.")
            continue
        status = found[0]
        state, reason = _verdicts(kind, status, awarded=awarded)
        if state == _VERIFIED:
            verified.append(kind)
        elif state == _CONTRADICTED:
            contradicted.append(kind)
            reasons.append(reason)
        else:
            unverifiable.append(kind)
            reasons.append(reason)

    if math_status == "SKIPPED":
        not_applicable.append("MATHEMATICAL")

    if not scoreable:
        status = (
            STATUS_VERIFICATION_FAILED if contradicted else STATUS_REVIEW_REQUIRED
        )
        reasons.append("The question has no stored decision, so it cannot be verified.")
    elif contradicted:
        status = STATUS_VERIFICATION_FAILED
    elif review_required or unverifiable:
        status = STATUS_REVIEW_REQUIRED
    elif missing:
        status = STATUS_PARTIALLY_VERIFIED
    elif set(required) <= set(verified) and INDEPENDENT_KINDS & set(required):
        status = STATUS_FULLY_VERIFIED
    else:
        # Only integrity ran: the paper is complete, but no independent check
        # was required for this question.
        status = STATUS_NOT_REQUIRED

    return QuestionVerification(
        question_id=question_id,
        status=status,
        required=tuple(required),
        verified=tuple(verified),
        contradicted=tuple(contradicted),
        unverifiable=tuple(unverifiable),
        missing=tuple(missing),
        not_applicable=tuple(not_applicable),
        reasons=tuple(dict.fromkeys(reason for reason in reasons if reason)),
    )


def summarise(
    rows: Iterable[Any],
    records_by_question: Mapping[str, Mapping[str, tuple[str, dict[str, Any]]]],
) -> PaperVerification:
    """Derive the paper's status from every question's verification state."""

    questions = tuple(
        question_verification(row, records_by_question.get(str(row.question_id), {}))
        for row in rows
    )
    statuses = [item.status for item in questions]
    counts = {status: statuses.count(status) for status in STATUSES if status in statuses}

    if not questions:
        status = STATUS_NOT_REQUIRED
    elif STATUS_VERIFICATION_FAILED in statuses:
        status = STATUS_VERIFICATION_FAILED
    elif STATUS_REVIEW_REQUIRED in statuses:
        status = STATUS_REVIEW_REQUIRED
    elif all(item == STATUS_NOT_REQUIRED for item in statuses):
        status = STATUS_NOT_REQUIRED
    elif all(item == STATUS_FULLY_VERIFIED for item in statuses):
        status = STATUS_FULLY_VERIFIED
    else:
        status = STATUS_PARTIALLY_VERIFIED

    return PaperVerification(status=status, questions=questions, counts=counts)


#: The concern a row carries when it holds marks no evidence check has examined.
CODE_EVIDENCE_NOT_CHECKED = "EVIDENCE_NOT_CHECKED"


def awards_without_evidence(
    rows: Iterable[Any],
    records_by_question: Mapping[str, Mapping[str, tuple[str, dict[str, Any]]]],
) -> tuple[str, ...]:
    """Questions that hold marks and have no evidence check at all.

    A quotation is only compared with the script when the blind reading is bought
    for that question, and a review mode buys it for a handful of questions.  A
    question whose award was never examined therefore has no ``EVIDENCE`` record
    — not a failed check, but the absence of one — and an award resting on it is
    an unverified reading.  Those are the questions this returns, with the award
    left exactly as the reply stated it.

    A recorded check of any status is *not* returned: ``FAIL`` and
    ``UNVERIFIABLE`` already route the question to a person through their own
    concerns, and re-flagging them here would only duplicate the reason.
    """

    ungrounded: list[str] = []
    for row in rows:
        try:
            awarded = int(getattr(row, "awarded_marks", 0) or 0)
        except (TypeError, ValueError):
            awarded = 0
        if awarded <= 0:
            continue
        question_id = str(getattr(row, "question_id", "") or "")
        if KIND_EVIDENCE in records_by_question.get(question_id, {}):
            continue
        ungrounded.append(question_id)
    return tuple(ungrounded)


def records_from_rows(rows: Iterable[Any]) -> dict[str, dict[str, tuple[str, dict[str, Any]]]]:
    """``{question_id: {kind: (status, detail)}}`` from stored verification rows."""

    grouped: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}
    for item in rows:
        grouped.setdefault(str(item.question_id), {})[str(item.kind)] = (
            str(item.status),
            dict(getattr(item, "detail", None) or {}),
        )
    return grouped


__all__ = [
    "CODE_EVIDENCE_NOT_CHECKED",
    "INDEPENDENT_KINDS",
    "KIND_DOUBLE_CHECK",
    "KIND_EVIDENCE",
    "KIND_INTEGRITY",
    "KIND_MATHEMATICAL",
    "KIND_SCHEME_MATHEMATICAL",
    "KIND_TRANSCRIPTION",
    "STATUSES",
    "STATUS_FULLY_VERIFIED",
    "STATUS_NOT_REQUIRED",
    "STATUS_PARTIALLY_VERIFIED",
    "STATUS_REVIEW_REQUIRED",
    "STATUS_VERIFICATION_FAILED",
    "PaperVerification",
    "QuestionVerification",
    "awards_without_evidence",
    "question_verification",
    "records_from_rows",
    "summarise",
]
