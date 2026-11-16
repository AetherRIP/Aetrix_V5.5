"""Which questions earn a second opinion, and what a review mode buys.

The independent double check costs one provider request per question, so the
selection is the whole cost story.  Three things decide it:

* **the review mode** on the assignment — ``ECONOMY`` takes no second opinion,
  ``BALANCED`` re-marks the questions the first examiner was unsure about, and
  ``ACCURACY`` widens the net and includes a deterministic sample of confident
  answers, which is the only way a confidently wrong mark is ever caught;
* **suspicion** — deterministic signals that a mark may be wrong even when the
  model was sure: full marks on a valuable question, marks beside a blank answer,
  a normalised award, outstanding concerns, or a question that has disagreed with
  a second examiner before;
* **a budget** — a hard cap on requests per job, so a mode can never become an
  uncontrolled spend.

Selection is deterministic: the same job and the same rows always choose the same
questions, so a re-run reproduces the cost and the result.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

MODE_ECONOMY = "ECONOMY"
MODE_BALANCED = "BALANCED"
MODE_ACCURACY = "ACCURACY"
MODES = (MODE_ECONOMY, MODE_BALANCED, MODE_ACCURACY)

#: A question worth this many marks, answered for full marks, is where an
#: over-award is most expensive and least visible.
VALUABLE_QUESTION_MARKS = 3

#: Suspicion weights.  They order the queue; they are not probabilities.
_WEIGHT_LOW_CONFIDENCE = 4.0
_WEIGHT_NORMALISED_AWARD = 4.0
_WEIGHT_MARKS_FOR_BLANK = 3.0
_WEIGHT_FULL_MARKS_VALUABLE = 2.0
_WEIGHT_OUTSTANDING_CONCERN = 2.0
_WEIGHT_PAST_DISAGREEMENT = 2.0


@dataclass(frozen=True, slots=True)
class ReviewPolicy:
    """What a review mode actually does, in requests and thresholds."""

    mode: str
    double_check_budget: int
    double_check_threshold: float
    high_confidence_sample: int
    recovery_rounds: int
    transcription_budget: int = 0

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "double_check_budget": self.double_check_budget,
            "double_check_threshold": self.double_check_threshold,
            "high_confidence_sample": self.high_confidence_sample,
            "recovery_rounds": self.recovery_rounds,
            "transcription_budget": self.transcription_budget,
        }


def policy_for(mode: str | None, *, settings: Any) -> ReviewPolicy:
    """Resolve an assignment's review mode into a concrete policy.

    ``settings.marking`` remains the operator's floor and ceiling: a mode widens
    or narrows what the operator configured, and never overrides the global
    ``double_check_enabled`` switch.
    """

    marking = settings.marking
    selected = (mode or MODE_BALANCED).strip().upper()
    if selected not in MODES:
        raise ValueError(f"unknown review mode {mode!r}")
    # Transcription is an operator switch first and a mode budget second: a mode
    # can spend more of it, never enable it against the setting.
    transcribe_cap = (
        int(getattr(marking, "transcription_max_questions", 0) or 0)
        if getattr(marking, "transcription_enabled", False)
        else 0
    )
    if selected == MODE_ECONOMY:
        return ReviewPolicy(
            mode=MODE_ECONOMY,
            double_check_budget=0,
            double_check_threshold=1.0,
            high_confidence_sample=0,
            recovery_rounds=1,
            transcription_budget=0,
        )
    if selected == MODE_ACCURACY:
        return ReviewPolicy(
            mode=MODE_ACCURACY,
            double_check_budget=max(int(marking.double_check_max_questions), 12),
            double_check_threshold=min(
                1.0, max(float(marking.double_check_min_confidence), 0.95)
            ),
            high_confidence_sample=2,
            recovery_rounds=3,
            transcription_budget=min(transcribe_cap, 6),
        )
    return ReviewPolicy(
        mode=MODE_BALANCED,
        double_check_budget=int(marking.double_check_max_questions),
        double_check_threshold=float(marking.double_check_min_confidence),
        high_confidence_sample=0,
        recovery_rounds=2,
        transcription_budget=min(transcribe_cap, 2),
    )


@dataclass(frozen=True, slots=True)
class Suspicion:
    question_id: str
    score: float
    confidence: float | None
    reasons: tuple[str, ...]

    @property
    def low_confidence(self) -> bool:
        return any(reason.startswith("CONFIDENCE") for reason in self.reasons)


def _blank(text: str | None) -> bool:
    return not (text or "").strip()


def suspicion_for(
    row: Any,
    *,
    threshold: float,
    history: dict[str, int] | None = None,
) -> Suspicion:
    """Score one stored result for a second opinion."""

    question_id = str(row.question_id)
    confidence = getattr(row, "confidence", None)
    awarded = int(getattr(row, "awarded_marks", 0) or 0)
    max_marks = int(getattr(row, "max_marks", 0) or 0)
    reasons: list[str] = []
    score = 0.0

    if confidence is None or float(confidence) < threshold:
        score += _WEIGHT_LOW_CONFIDENCE
        reasons.append(
            f"CONFIDENCE: {confidence if confidence is not None else 'unrecorded'} is "
            f"below the {threshold:.2f} threshold."
        )
    if getattr(row, "normalisation_anomaly", None):
        score += _WEIGHT_NORMALISED_AWARD
        reasons.append(
            f"NORMALISED_AWARD: the reply was changed before storage "
            f"({row.normalisation_anomaly})."
        )
    if awarded > 0 and _blank(getattr(row, "student_answer", None)):
        score += _WEIGHT_MARKS_FOR_BLANK
        reasons.append("MARKS_FOR_BLANK: marks were awarded without a recorded answer.")
    if max_marks >= VALUABLE_QUESTION_MARKS and awarded == max_marks:
        score += _WEIGHT_FULL_MARKS_VALUABLE
        reasons.append(
            f"FULL_MARKS_VALUABLE: full marks on a {max_marks}-mark question."
        )
    if getattr(row, "scheme_concerns", None):
        score += _WEIGHT_OUTSTANDING_CONCERN
        reasons.append("OUTSTANDING_CONCERN: the stored result already carries a concern.")
    past = int((history or {}).get(question_id, 0))
    if past:
        score += _WEIGHT_PAST_DISAGREEMENT * min(past, 2)
        reasons.append(
            f"PAST_DISAGREEMENT: this question has disagreed with a second examiner "
            f"{past} time(s) before."
        )
    return Suspicion(
        question_id=question_id,
        score=score,
        confidence=None if confidence is None else float(confidence),
        reasons=tuple(reasons),
    )


def select_targets(
    rows: Iterable[Any],
    *,
    policy: ReviewPolicy,
    skip: set[str] | None = None,
    history: dict[str, int] | None = None,
    seed: str = "",
) -> list[Suspicion]:
    """Choose the questions to re-mark, within the policy's budget.

    Low-confidence questions are considered first, then the most suspicious
    confident ones, then a deterministic sample of the rest up to
    ``high_confidence_sample``.  The result is stable for a given seed.
    """

    if policy.double_check_budget <= 0:
        return []
    skip = skip or set()
    # Only a decided, marked question can be re-marked: a confirmed zero is
    # already a decision, and a review item is already with a person.  Enforcing
    # that here means a caller cannot buy a second opinion that cannot change
    # anything.
    scored = [
        suspicion_for(row, threshold=policy.double_check_threshold, history=history)
        for row in rows
        if str(row.question_id) not in skip
        and str(getattr(row, "processing_state", "MARKED")) == "MARKED"
    ]
    low = [item for item in scored if item.low_confidence]
    confident = [item for item in scored if not item.low_confidence]

    chosen: list[Suspicion] = list(low)
    chosen_ids = {item.question_id for item in chosen}
    extra = [
        item
        for item in sorted(confident, key=lambda item: (-item.score, item.question_id))
        if item.score > 0 and item.question_id not in chosen_ids
    ]
    for item in extra:
        if len(chosen) >= policy.double_check_budget:
            break
        chosen.append(item)
        chosen_ids.add(item.question_id)

    if policy.high_confidence_sample > 0:
        pool = [
            item.question_id
            for item in sorted(confident, key=lambda item: item.question_id)
            if item.question_id not in chosen_ids
        ]
        rng = random.Random(f"{seed}:{policy.mode}")
        sample = rng.sample(pool, min(policy.high_confidence_sample, len(pool)))
        by_id = {item.question_id: item for item in confident}
        for question_id in sample:
            if len(chosen) >= policy.double_check_budget:
                break
            chosen.append(by_id[question_id])

    chosen.sort(key=lambda item: (-item.score, item.question_id))
    return chosen[: policy.double_check_budget]
