"""Protecting a stored result from a worse automated one.

A marking run is not an overwrite; presenting its result as the submission's
current result is.  This module decides that second question in plain Python,
with no model and no randomness:

* a teacher's approval is never replaced by an automated pass;
* a teacher's override outranks an automated pass;
* a run that fails validation, or that scores zero where the stored result
  awarded marks, or that drops by an implausible margin, is kept out and sent
  for review instead.

Keeping the stronger stored result is the conservative choice: a false "keep
existing" costs a re-run, a false overwrite costs a real mark.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

#: A drop this large between two runs is treated as suspicious rather than as a
#: legitimate re-mark.
LARGE_CHANGE_POINTS = 30.0

#: ``correction_jobs.result_source`` values.  A run is presentable unless it was
#: refused, so refusal is a fact about presentation rather than a mark.
RESULT_SOURCE_AI = "AI_PRIMARY"
RESULT_SOURCE_REFUSED = "AUTOMATED_REFUSED"

ACTION_INSERT = "INSERT"
ACTION_UPDATE = "UPDATE"
ACTION_KEEP_EXISTING = "KEEP_EXISTING"
ACTION_BLOCKED = "BLOCKED"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_VALIDATION_FAILED = "VALIDATION_FAILED"
CONFIDENCE_LARGE_SCORE_CHANGE = "LARGE_SCORE_CHANGE"


@dataclass(frozen=True, slots=True)
class PriorResult:
    """The result this run would replace, as far as the guard needs to know."""

    job_id: uuid.UUID | None
    earned: int
    available: int
    approved: bool
    teacher_override: bool


@dataclass(frozen=True, slots=True)
class GuardDecision:
    action: str
    reason: str
    confidence: str
    review_required: bool

    @property
    def may_present(self) -> bool:
        """True when this run's result may become the submission's result."""

        return self.action in {ACTION_INSERT, ACTION_UPDATE}


def percentage(earned: int, available: int) -> float:
    return (earned / available * 100.0) if available else 0.0


def evaluate_overwrite(
    *,
    prior: PriorResult | None,
    earned: int,
    available: int,
    validation_failed: bool = False,
) -> GuardDecision:
    """Decide whether this run's result may replace the stored one."""

    if prior is None:
        if validation_failed:
            return GuardDecision(
                action=ACTION_BLOCKED,
                reason=(
                    "The new result failed validation and there is no earlier result "
                    "to fall back on, so nothing was presented."
                ),
                confidence=CONFIDENCE_VALIDATION_FAILED,
                review_required=True,
            )
        return GuardDecision(
            action=ACTION_INSERT,
            reason="No earlier result is stored for this submission.",
            confidence=CONFIDENCE_HIGH,
            review_required=False,
        )

    if prior.approved:
        return GuardDecision(
            action=ACTION_BLOCKED,
            reason=(
                "A teacher approved the stored result, so this automated run cannot "
                "replace it. Reopen the job if the paper must be re-marked."
            ),
            confidence=CONFIDENCE_HIGH,
            review_required=True,
        )

    if prior.teacher_override:
        return GuardDecision(
            action=ACTION_KEEP_EXISTING,
            reason=(
                "A teacher overrode the stored result. The automated re-run was not "
                "applied; a deliberate reprocess is required."
            ),
            confidence=CONFIDENCE_HIGH,
            review_required=True,
        )

    if validation_failed:
        return GuardDecision(
            action=ACTION_KEEP_EXISTING,
            reason="The new result failed validation, so the stored result was kept.",
            confidence=CONFIDENCE_VALIDATION_FAILED,
            review_required=True,
        )

    new_percentage = percentage(earned, available)
    prior_percentage = percentage(prior.earned, prior.available)

    if new_percentage == 0.0 and prior.earned > 0:
        return GuardDecision(
            action=ACTION_KEEP_EXISTING,
            reason=(
                f"The new run scored 0 where the stored result awarded {prior.earned}. "
                "A zero result for a paper that was already marked is almost always a "
                "failed run, so the stored result was kept."
            ),
            confidence=CONFIDENCE_LARGE_SCORE_CHANGE,
            review_required=True,
        )

    drop = prior_percentage - new_percentage
    if drop >= LARGE_CHANGE_POINTS:
        return GuardDecision(
            action=ACTION_KEEP_EXISTING,
            reason=(
                f"The new run scored {new_percentage:.1f}% against a stored "
                f"{prior_percentage:.1f}% (a {drop:.1f} point drop). A change that large "
                "needs a person, so the stored result was kept."
            ),
            confidence=CONFIDENCE_LARGE_SCORE_CHANGE,
            review_required=True,
        )

    return GuardDecision(
        action=ACTION_UPDATE,
        reason="The new result is consistent with the stored one.",
        confidence=CONFIDENCE_HIGH if drop <= 0 else CONFIDENCE_MEDIUM,
        review_required=False,
    )
