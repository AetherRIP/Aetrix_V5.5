"""A blind second reading is only useful if it cannot agree by habit.

These tests pin the comparison's four outcomes, the distinction between an absent
answer and an unreadable one, and the selection that decides which questions are
worth the extra request.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import MarkingSettings
from app.correction.sampling import MODE_ACCURACY, MODE_BALANCED, MODE_ECONOMY, policy_for
from app.correction.transcription import (
    STATUS_ABSENT,
    STATUS_AGREES,
    STATUS_DIFFERS,
    compare_transcripts,
    normalise_text,
    transcribe_targets,
)


def _row(
    question_id: str = "1a",
    *,
    awarded: int = 0,
    answer: str | None = None,
    confidence: float | None = 0.95,
    state: str = "MARKED",
    concerns: list | None = None,
    review_required: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        question_id=question_id,
        awarded_marks=awarded,
        student_answer=answer,
        confidence=confidence,
        processing_state=state,
        scheme_concerns=concerns or [],
        review_required=review_required,
    )


# -- comparison ------------------------------------------------------------


def test_identical_answers_agree() -> None:
    assert compare_transcripts("x = 3", "x = 3") == STATUS_AGREES


def test_spacing_and_latex_wrappers_are_not_a_difference() -> None:
    assert compare_transcripts("24 - 18y", "$24-18y$") == STATUS_AGREES


def test_a_decimal_and_a_fraction_are_different_working() -> None:
    """Equality of value is not equality of writing.

    ``0.75`` and ``3/4`` are the same number and different working, and a scheme
    can award one and withhold the other.  Algebraic equivalence is deliberately
    not treated as agreement: the comparison is about what the reader saw.
    """

    assert compare_transcripts("0.75", "3/4") == STATUS_DIFFERS


def test_a_different_answer_differs() -> None:
    assert compare_transcripts("8x^3 - 6x^2 - 60x", "8x^3 - 28x^2 - 60x") == STATUS_DIFFERS


def test_two_blank_readings_are_absent_not_an_agreement() -> None:
    assert compare_transcripts(None, "   ") == STATUS_ABSENT


def test_a_reader_that_finds_writing_where_the_first_saw_none_differs() -> None:
    assert compare_transcripts("", "2x + 6 = 12") == STATUS_DIFFERS


def test_a_reader_that_finds_nothing_where_the_first_saw_writing_differs() -> None:
    assert compare_transcripts("x = 3", None) == STATUS_DIFFERS


def test_unreadable_text_is_not_called_equivalent() -> None:
    """SymPy has no opinion about prose, and prose is still a textual difference."""

    assert compare_transcripts("the answer is obvious", "it is clearly 4") == STATUS_DIFFERS


def test_superscripts_and_subscripts_survive_comparison_forms() -> None:
    assert compare_transcripts("x^2 + 3x", "x^2+3x") == STATUS_AGREES
    assert compare_transcripts("a_1", "a1") == STATUS_DIFFERS


def test_a_half_and_a_decimal_are_different_working() -> None:
    assert compare_transcripts("1/2", "0.5") == STATUS_DIFFERS


def test_a_label_on_a_diagram_is_text_and_must_match() -> None:
    assert compare_transcripts("angle ABC", "angle ABD") == STATUS_DIFFERS


def test_a_rewritten_answer_with_crossed_out_working_is_a_difference() -> None:
    first = "8x^3 - 6x^2 - 60x"
    second = "8x^3 + 6x^2 - 60x"

    assert compare_transcripts(first, second) == STATUS_DIFFERS


def test_a_partially_unreadable_reading_differs_rather_than_agreeing() -> None:
    assert compare_transcripts("24 - 18y", "24 - 1?y") == STATUS_DIFFERS


def test_normalisation_removes_wrappers_and_collapsed_whitespace() -> None:
    assert normalise_text("  $  x   =   3 . $ ") == "x = 3"


# -- selection -------------------------------------------------------------


def test_a_blank_zero_is_the_first_reason_to_transcribe() -> None:
    rows = [
        _row("1a", awarded=2, answer="x = 3"),
        _row("2", awarded=0, answer=None, state="CONFIRMED_ZERO"),
    ]

    targets = transcribe_targets(rows, budget=4)

    assert [target.question_id for target in targets] == ["2"]
    assert targets[0].reasons[0].startswith("BLANK_ZERO")


def test_page_risk_and_low_confidence_are_selected() -> None:
    rows = [
        _row(
            "1a",
            awarded=1,
            answer="x = 3",
            concerns=[{"code": "REVIEW", "message": "PAGE_LIMIT_TRUNCATED: one page"}],
        ),
        _row("1b", awarded=1, answer="y = 2", confidence=0.4),
    ]

    targets = transcribe_targets(rows, budget=4)

    assert {target.question_id for target in targets} == {"1a", "1b"}


def test_a_confident_complete_award_is_not_transcribed() -> None:
    rows = [_row("1a", awarded=2, answer="x = 3", confidence=0.97)]

    assert transcribe_targets(rows, budget=4) == []


def test_the_budget_is_never_exceeded() -> None:
    rows = [_row(f"q{index}", awarded=0, answer=None) for index in range(6)]

    assert len(transcribe_targets(rows, budget=2)) == 2


def test_a_question_already_transcribed_is_skipped() -> None:
    rows = [_row("1a", awarded=0, answer=None), _row("1b", awarded=0, answer=None)]

    targets = transcribe_targets(rows, budget=4, skip={"1a"})

    assert [target.question_id for target in targets] == ["1b"]


def test_a_question_with_a_person_is_not_transcribed_again() -> None:
    rows = [_row("1a", awarded=0, answer=None, state="NEEDS_REVIEW")]

    assert transcribe_targets(rows, budget=4) == []


# -- budgets ---------------------------------------------------------------


def _settings(**overrides) -> SimpleNamespace:
    return SimpleNamespace(marking=MarkingSettings(**overrides))


def test_economy_never_pays_for_transcription() -> None:
    policy = policy_for(MODE_ECONOMY, settings=_settings(transcription_enabled=True))

    assert policy.transcription_budget == 0


def test_the_operator_switch_still_decides() -> None:
    """The second reading is on by default and the operator can still stop it.

    It was off by default when it was an experiment; a confident zero standing on
    an unverified reading is the defect it exists for, so it is now part of the
    correction.  Disabling it must still cost nothing.
    """

    assert policy_for(MODE_BALANCED, settings=_settings()).transcription_budget == 2
    assert policy_for(MODE_ACCURACY, settings=_settings()).transcription_budget == 4
    assert (
        policy_for(
            MODE_BALANCED, settings=_settings(transcription_enabled=False)
        ).transcription_budget
        == 0
    )
    assert (
        policy_for(
            MODE_ACCURACY, settings=_settings(transcription_enabled=False)
        ).transcription_budget
        == 0
    )


def test_the_modes_spend_different_amounts_of_an_enabled_switch() -> None:
    balanced = policy_for(MODE_BALANCED, settings=_settings(transcription_enabled=True))
    accuracy = policy_for(MODE_ACCURACY, settings=_settings(transcription_enabled=True))

    assert balanced.transcription_budget == 2
    assert accuracy.transcription_budget == 4


def test_an_operator_cap_below_the_mode_budget_is_respected() -> None:
    policy = policy_for(
        MODE_ACCURACY,
        settings=_settings(transcription_enabled=True, transcription_max_questions=1),
    )

    assert policy.transcription_budget == 1


def test_an_unknown_mode_is_still_refused() -> None:
    with pytest.raises(ValueError):
        policy_for("LENIENT", settings=_settings())
