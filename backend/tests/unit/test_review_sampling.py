"""What a review mode buys, and how the second opinion is targeted.

The selection is the cost story: every chosen question is one provider request.
These tests pin the three modes' budgets and thresholds, the suspicion signals,
and the determinism that makes a re-run reproduce the same cost.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import MarkingSettings
from app.correction.sampling import (
    MODE_ACCURACY,
    MODE_BALANCED,
    MODE_ECONOMY,
    policy_for,
    select_targets,
    suspicion_for,
)


def _settings(**overrides) -> SimpleNamespace:
    marking = MarkingSettings(**overrides)
    return SimpleNamespace(marking=marking)


def _row(
    question_id: str = "1a",
    *,
    awarded: int = 1,
    max_marks: int = 2,
    confidence: float | None = 0.95,
    state: str = "MARKED",
    concerns: list | None = None,
    student_answer: str | None = "x = 3",
    anomaly: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        question_id=question_id,
        awarded_marks=awarded,
        max_marks=max_marks,
        confidence=confidence,
        processing_state=state,
        scheme_concerns=concerns or [],
        student_answer=student_answer,
        normalisation_anomaly=anomaly,
    )


# -- modes -----------------------------------------------------------------


def test_economy_buys_no_second_opinion() -> None:
    policy = policy_for(MODE_ECONOMY, settings=_settings())

    assert policy.double_check_budget == 0
    assert policy.high_confidence_sample == 0
    assert policy.recovery_rounds == 1


def test_balanced_uses_the_operator_threshold_and_budget() -> None:
    policy = policy_for(MODE_BALANCED, settings=_settings())

    assert policy.double_check_budget == MarkingSettings().double_check_max_questions
    assert policy.double_check_threshold == MarkingSettings().double_check_min_confidence
    assert policy.high_confidence_sample == 0
    assert policy.recovery_rounds == 2


def test_accuracy_widens_the_net_and_samples_confident_answers() -> None:
    policy = policy_for(MODE_ACCURACY, settings=_settings())

    assert policy.double_check_threshold >= 0.95
    assert policy.double_check_budget >= 12
    assert policy.high_confidence_sample == 2
    assert policy.recovery_rounds == 3


def test_an_operator_threshold_above_the_mode_floor_is_respected() -> None:
    policy = policy_for(MODE_ACCURACY, settings=_settings(double_check_min_confidence=0.99))

    assert policy.double_check_threshold == 0.99


def test_a_missing_mode_defaults_to_balanced() -> None:
    assert policy_for(None, settings=_settings()).mode == MODE_BALANCED


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError):
        policy_for("LENIENT", settings=_settings())


# -- suspicion -------------------------------------------------------------


def test_low_confidence_is_a_risk_signal() -> None:
    item = suspicion_for(_row(confidence=0.4), threshold=0.85)

    assert item.low_confidence is True
    assert item.score > 0
    assert any(reason.startswith("CONFIDENCE") for reason in item.reasons)


def test_full_marks_on_a_valuable_question_is_a_risk_signal() -> None:
    item = suspicion_for(_row(awarded=4, max_marks=4, confidence=0.99), threshold=0.85)

    assert item.low_confidence is False
    assert any(reason.startswith("FULL_MARKS_VALUABLE") for reason in item.reasons)


def test_marks_beside_a_blank_answer_are_a_risk_signal() -> None:
    item = suspicion_for(
        _row(awarded=2, student_answer="   "), threshold=0.85
    )

    assert any(reason.startswith("MARKS_FOR_BLANK") for reason in item.reasons)


def test_a_normalised_award_is_a_risk_signal() -> None:
    item = suspicion_for(_row(anomaly="OVER_MAX_AWARD"), threshold=0.85)

    assert any(reason.startswith("NORMALISED_AWARD") for reason in item.reasons)


def test_a_past_disagreement_raises_the_score() -> None:
    plain = suspicion_for(_row(), threshold=0.85)
    repeated = suspicion_for(_row(), threshold=0.85, history={"1a": 2})

    assert repeated.score > plain.score
    assert any(reason.startswith("PAST_DISAGREEMENT") for reason in repeated.reasons)


def test_a_plain_confident_award_has_no_suspicion() -> None:
    item = suspicion_for(_row(awarded=1, max_marks=2, confidence=0.95), threshold=0.85)

    assert item.score == 0
    assert item.reasons == ()


# -- selection -------------------------------------------------------------


def test_economy_selects_nothing() -> None:
    rows = [_row("1a", confidence=0.2), _row("1b", awarded=3, max_marks=3)]

    assert select_targets(rows, policy=policy_for(MODE_ECONOMY, settings=_settings())) == []


def test_low_confidence_questions_come_first() -> None:
    rows = [
        _row("1a", confidence=0.3),
        _row("1b", awarded=3, max_marks=3, confidence=0.99),
    ]

    targets = select_targets(rows, policy=policy_for(MODE_BALANCED, settings=_settings()))

    assert [item.question_id for item in targets] == ["1a", "1b"]
    assert targets[0].low_confidence is True


def test_the_budget_is_never_exceeded() -> None:
    rows = [_row(f"1{index}", awarded=6, max_marks=6, confidence=0.99) for index in range(10)]
    policy = policy_for(MODE_BALANCED, settings=_settings(double_check_max_questions=3))

    targets = select_targets(rows, policy=policy)

    assert len(targets) == 3


def test_a_question_with_a_recorded_verdict_is_skipped() -> None:
    rows = [_row("1a", confidence=0.3), _row("1b", confidence=0.3)]

    targets = select_targets(
        rows, policy=policy_for(MODE_BALANCED, settings=_settings()), skip={"1a"}
    )

    assert [item.question_id for item in targets] == ["1b"]


def test_selection_is_deterministic_for_a_job() -> None:
    rows = [_row(f"1{index}", awarded=6, max_marks=6, confidence=0.99) for index in range(6)]
    policy = policy_for(MODE_ACCURACY, settings=_settings())

    first = select_targets(rows, policy=policy, seed="job-1")
    second = select_targets(rows, policy=policy, seed="job-1")

    assert [item.question_id for item in first] == [item.question_id for item in second]


def test_accuracy_samples_confident_answers_balanced_does_not() -> None:
    rows = [_row(f"q{index}", awarded=1, max_marks=2, confidence=0.99) for index in range(5)]

    balanced = select_targets(
        rows, policy=policy_for(MODE_BALANCED, settings=_settings()), seed="job-2"
    )
    accuracy = select_targets(
        rows, policy=policy_for(MODE_ACCURACY, settings=_settings()), seed="job-2"
    )

    assert balanced == []
    assert len(accuracy) == 2


def test_the_accuracy_threshold_is_active_above_the_operator_default() -> None:
    """ACCURACY raises the review threshold to 0.95; it does not disable it.

    A MARKED row may carry 0.85-0.949 confidence because the pipeline only
    requires ``marking.min_confidence`` (0.6 by default). ACCURACY reviews such a
    row; BALANCED leaves it alone. A log that called this threshold inert was
    wrong, and this test pins the difference.
    """

    rows = [_row("q1", awarded=1, max_marks=2, confidence=0.90)]
    balanced = policy_for(MODE_BALANCED, settings=_settings())
    accuracy = policy_for(MODE_ACCURACY, settings=_settings())

    assert balanced.double_check_threshold == MarkingSettings().double_check_min_confidence
    assert accuracy.double_check_threshold == 0.95
    assert balanced.double_check_threshold < 0.90 < accuracy.double_check_threshold
    assert select_targets(rows, policy=balanced, seed="job-threshold") == []
    assert [target.question_id for target in select_targets(
        rows, policy=accuracy, seed="job-threshold"
    )] == ["q1"]


def test_a_confirmed_zero_is_not_offered_for_a_second_opinion() -> None:
    """The pipeline only passes markable rows; the sampler must not invent one."""

    rows = [_row("2", awarded=0, max_marks=3, state="CONFIRMED_ZERO", confidence=0.99)]
    policy = policy_for(MODE_ACCURACY, settings=_settings())

    assert select_targets(rows, policy=policy, seed="job-3") == []
