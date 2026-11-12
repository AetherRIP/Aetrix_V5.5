from __future__ import annotations

import pytest
from app.correction.processing import (
    ProcessingState,
    ensure_consistent,
    is_scoreable,
    state_for_mark,
    state_for_status,
    status_for,
)


@pytest.mark.parametrize(
    ("state", "status"),
    [
        (ProcessingState.MARKED, "AWARDED"),
        (ProcessingState.CONFIRMED_ZERO, "ZERO"),
        (ProcessingState.UNMARKED, "UNMARKED"),
        (ProcessingState.NEEDS_REVIEW, "REVIEW_REQUIRED"),
    ],
)
def test_each_state_maps_to_one_status(state, status) -> None:
    assert status_for(state) == status
    assert state_for_status(status) is state


def test_a_zero_that_needs_review_is_not_a_confirmed_zero() -> None:
    assert state_for_status("ZERO", review_required=True) is ProcessingState.NEEDS_REVIEW
    assert state_for_status("ZERO", review_required=False) is ProcessingState.CONFIRMED_ZERO


def test_an_excluded_question_is_unmarked_without_rewriting_its_status() -> None:
    assert state_for_status("EXCLUDED") is ProcessingState.UNMARKED
    ensure_consistent("EXCLUDED", ProcessingState.UNMARKED)


def test_an_unknown_historical_status_needs_a_person() -> None:
    assert state_for_status("SOMETHING_NEW") is ProcessingState.NEEDS_REVIEW


def test_a_positive_award_is_marked() -> None:
    assert (
        state_for_mark(
            awarded=2,
            review_required=False,
            integrity_failed=False,
            confidence=0.9,
            min_confidence=0.6,
        )
        is ProcessingState.MARKED
    )


def test_a_confident_zero_is_confirmed() -> None:
    assert (
        state_for_mark(
            awarded=0,
            review_required=False,
            integrity_failed=False,
            confidence=0.9,
            min_confidence=0.6,
        )
        is ProcessingState.CONFIRMED_ZERO
    )


def test_an_unconfident_zero_needs_review() -> None:
    assert (
        state_for_mark(
            awarded=0,
            review_required=False,
            integrity_failed=False,
            confidence=0.5,
            min_confidence=0.6,
        )
        is ProcessingState.NEEDS_REVIEW
    )


def test_a_zero_with_no_confidence_needs_review() -> None:
    assert (
        state_for_mark(
            awarded=0,
            review_required=False,
            integrity_failed=False,
            confidence=None,
            min_confidence=0.6,
        )
        is ProcessingState.NEEDS_REVIEW
    )


def test_an_integrity_failure_always_needs_review() -> None:
    assert (
        state_for_mark(
            awarded=3,
            review_required=False,
            integrity_failed=True,
            confidence=0.99,
            min_confidence=0.6,
        )
        is ProcessingState.NEEDS_REVIEW
    )


def test_a_review_flag_wins_over_a_positive_award() -> None:
    assert (
        state_for_mark(
            awarded=1,
            review_required=True,
            integrity_failed=False,
            confidence=0.99,
            min_confidence=0.6,
        )
        is ProcessingState.NEEDS_REVIEW
    )


def test_contradictory_claims_are_refused() -> None:
    with pytest.raises(ValueError, match="contradicts"):
        ensure_consistent("AWARDED", ProcessingState.NEEDS_REVIEW)


def test_a_historical_row_without_a_state_is_allowed() -> None:
    ensure_consistent("AWARDED", None)


def test_only_a_decision_counts_as_scoreable() -> None:
    assert is_scoreable(ProcessingState.MARKED)
    assert is_scoreable(ProcessingState.CONFIRMED_ZERO)
    assert not is_scoreable(ProcessingState.UNMARKED)
    assert not is_scoreable(ProcessingState.NEEDS_REVIEW)
    assert not is_scoreable(None)
