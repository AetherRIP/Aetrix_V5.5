"""Which questions the independent checkers must examine.

Checking every question on every paper is unaffordable, and checking none is how
an over-award survives.  This module decides, per question, whether verification
is **required**, **advisory** or a **sample**, and which of the two checkers it
needs.  The decision is deterministic: the same paper and the same policy produce
the same plan, so a re-run cannot quietly check a different set.

Two kinds of check exist, and they are not interchangeable:

``transcription``
    A blind reading of the page by a model that does not see the criteria or the
    primary model's marks.  It answers "what is written here?".

``evidence``
    A criterion-level review by a model that does see the approved criteria and
    the student's evidence, which answers "is this award supported?".

Severity
--------
``REQUIRED``
    A risk rule fired.  The question may not be treated as verified unless the
    check actually ran.  If the checker cannot run — no quota, no credential —
    the question stays unverified and the paper escalates; the check is never
    dropped to keep a run green.
``ADVISORY``
    Worth checking, but the paper does not depend on it.
``SAMPLE``
    Selected by the measurement sampler purely to keep a quality signal.

The policy never decides marks.  It decides *attention*.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

TRANSCRIPTION = "transcription"
EVIDENCE = "evidence"


class Severity(StrEnum):
    REQUIRED = "REQUIRED"
    ADVISORY = "ADVISORY"
    SAMPLE = "SAMPLE"


class Reason(StrEnum):
    TRANSCRIPTION_AMBIGUOUS = "TRANSCRIPTION_AMBIGUOUS"
    TRANSCRIPTION_DIFFERS = "TRANSCRIPTION_DIFFERS"
    TRANSCRIPTION_ABSENT = "TRANSCRIPTION_ABSENT"
    TRANSCRIPTION_UNVERIFIABLE = "TRANSCRIPTION_UNVERIFIABLE"
    MATHEMATICAL_FAILURE = "MATHEMATICAL_FAILURE"
    HIGH_MARKS = "HIGH_MARKS"
    CRITERION_DISAGREEMENT = "CRITERION_DISAGREEMENT"
    HISTORICAL_OVER_AWARD = "HISTORICAL_OVER_AWARD"
    UNUSUAL_ANSWER = "UNUSUAL_ANSWER"
    SAMPLED = "SAMPLED"


#: The historical Ch2 L3 questions this engine is known to have over-awarded.
#: They are always verified: a known failure is a standing regression test, not
#: an anecdote.
KNOWN_OVER_AWARD_QUESTIONS: frozenset[str] = frozenset(
    {"13", "21", "26", "30", "31", "34", "37b"}
)


@dataclass(frozen=True, slots=True)
class QuestionFacts:
    """What the policy is allowed to know about one question."""

    question_id: str
    awarded_marks: int
    max_marks: int
    confidence: float | None = None
    transcription_status: str | None = None
    mathematical_status: str | None = None
    criterion_disagreement: bool = False
    unsupported_steps: int = 0


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    question_id: str
    severity: Severity
    checkers: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def required(self) -> bool:
        return self.severity is Severity.REQUIRED

    def as_report(self) -> dict[str, object]:
        return {
            "question_id": self.question_id,
            "severity": self.severity.value,
            "checkers": list(self.checkers),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    decisions: tuple[VerificationDecision, ...]
    dropped_samples: tuple[str, ...] = field(default_factory=tuple)
    budget: int = 0

    @property
    def required_questions(self) -> tuple[str, ...]:
        return tuple(d.question_id for d in self.decisions if d.required)

    def checkers_for(self, question_id: str) -> tuple[str, ...]:
        for decision in self.decisions:
            if decision.question_id == question_id:
                return decision.checkers
        return ()

    def as_report(self) -> dict[str, object]:
        return {
            "decisions": [decision.as_report() for decision in self.decisions],
            "required_questions": list(self.required_questions),
            "dropped_samples": list(self.dropped_samples),
            "budget": self.budget,
            "checking_requests": sum(len(d.checkers) for d in self.decisions),
        }


def _sampled(job_key: str, question_id: str, rate: float) -> bool:
    """A stable sample: the same paper always samples the same questions.

    ``random.random()`` would re-roll every run, so a paper could be re-marked
    with a different verification set and the second run would look better than
    the first for no reason.
    """

    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    digest = hashlib.sha256(f"{job_key}:{question_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 < rate


def _risk(facts: QuestionFacts, *, high_mark_fraction: float) -> tuple[Severity,
                                                                     list[str],
                                                                     list[str]]:
    """The rule set for one question: severity, reasons and checkers."""

    reasons: list[str] = []
    checkers: list[str] = []

    status = (facts.transcription_status or "").upper()
    if status == "UNVERIFIABLE":
        reasons.append(Reason.TRANSCRIPTION_UNVERIFIABLE.value)
        checkers.append(TRANSCRIPTION)
    elif status == "DIFFERS":
        reasons.append(Reason.TRANSCRIPTION_DIFFERS.value)
        checkers.extend((TRANSCRIPTION, EVIDENCE))
    elif status == "ABSENT":
        reasons.append(Reason.TRANSCRIPTION_ABSENT.value)
        checkers.extend((TRANSCRIPTION, EVIDENCE))

    if facts.confidence is not None and facts.confidence < 0.85:
        # A reading the marker itself was unsure of gets a second pair of eyes.
        reasons.append(Reason.TRANSCRIPTION_AMBIGUOUS.value)
        checkers.append(TRANSCRIPTION)

    mathematical = (facts.mathematical_status or "").upper()
    if mathematical in {"FAIL", "MISMATCH", "NOT_EQUIVALENT", "ERROR"}:
        reasons.append(Reason.MATHEMATICAL_FAILURE.value)
        checkers.append(EVIDENCE)

    if facts.max_marks > 0 and facts.awarded_marks / facts.max_marks >= high_mark_fraction:
        reasons.append(Reason.HIGH_MARKS.value)
        checkers.append(EVIDENCE)

    if facts.criterion_disagreement:
        reasons.append(Reason.CRITERION_DISAGREEMENT.value)
        checkers.append(EVIDENCE)

    if facts.unsupported_steps:
        reasons.append(Reason.UNUSUAL_ANSWER.value)
        checkers.append(EVIDENCE)

    if facts.question_id in KNOWN_OVER_AWARD_QUESTIONS:
        reasons.append(Reason.HISTORICAL_OVER_AWARD.value)
        checkers.extend((TRANSCRIPTION, EVIDENCE))

    checkers = list(dict.fromkeys(checkers))
    if not reasons:
        return Severity.SAMPLE, [], []
    return Severity.REQUIRED, reasons, checkers


def plan(
    facts: list[QuestionFacts],
    *,
    job_key: str,
    sample_rate: float = 0.0,
    high_mark_fraction: float = 0.8,
    request_budget: int = 12,
    transcription_available: bool = True,
    evidence_available: bool = True,
) -> VerificationPlan:
    """Decide what to check, without spending anything.

    A required check whose checker is unavailable is *kept* in the plan and
    marked with the checker it needs; the caller escalates the paper rather than
    treating the question as verified.  Only sample checks may be dropped to fit
    the budget.
    """

    decisions: list[VerificationDecision] = []
    for item in facts:
        severity, reasons, checkers = _risk(item, high_mark_fraction=high_mark_fraction)

        if severity is Severity.SAMPLE and _sampled(job_key, item.question_id, sample_rate):
            # Sampling checks one thing per question: what is actually written.
            severity, reasons, checkers = (
                Severity.SAMPLE,
                [Reason.SAMPLED.value],
                [TRANSCRIPTION],
            )

        if severity is Severity.REQUIRED and not checkers:
            # A rule fired that only needs an evidence review.
            checkers = [EVIDENCE]

        decisions.append(
            VerificationDecision(
                question_id=item.question_id,
                severity=severity,
                checkers=tuple(checkers),
                reasons=tuple(reasons),
            )
        )

    # Budget: required checks always run.  Samples are dropped, latest-defined
    # first, so the required set is never trimmed to fit.
    spent = sum(
        len(d.checkers) for d in decisions if d.severity is Severity.REQUIRED
    )
    kept: list[VerificationDecision] = []
    dropped: list[str] = []
    for decision in decisions:
        if decision.severity is Severity.REQUIRED:
            kept.append(decision)
            continue
        # A decision with nothing to run (a clean question nobody sampled) is
        # not a dropped check: it records that no attention was needed.
        if not decision.checkers or spent + len(decision.checkers) <= request_budget:
            kept.append(decision)
            spent += len(decision.checkers)
        else:
            dropped.append(decision.question_id)

    return VerificationPlan(
        decisions=tuple(kept),
        dropped_samples=tuple(dropped),
        budget=request_budget,
    )


def unavailable_checkers(
    plan_report: VerificationPlan,
    *,
    transcription_available: bool,
    evidence_available: bool,
) -> tuple[str, ...]:
    """The required checks that cannot run, as ``question:checker`` labels.

    The caller escalates on a non-empty answer.  It must never be used to
    silently shrink a plan.
    """

    missing: list[str] = []
    for decision in plan_report.decisions:
        if not decision.required:
            continue
        for checker in decision.checkers:
            if checker == TRANSCRIPTION and not transcription_available:
                missing.append(f"{decision.question_id}:{TRANSCRIPTION}")
            if checker == EVIDENCE and not evidence_available:
                missing.append(f"{decision.question_id}:{EVIDENCE}")
    return tuple(missing)


__all__ = [
    "EVIDENCE",
    "KNOWN_OVER_AWARD_QUESTIONS",
    "TRANSCRIPTION",
    "QuestionFacts",
    "Reason",
    "Severity",
    "VerificationDecision",
    "VerificationPlan",
    "plan",
    "unavailable_checkers",
]
