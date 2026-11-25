"""What one finished reading does to a result — every combination, in one table.

Mission 6.1 found the asymmetry: an unusable reading on a zero raised a concern,
an unusable reading on a positive award raised nothing.  The policy now lives in
one pure function, so every outcome can be tested against both a zero and a
positive award, and against a page the marking pass chose for itself.

The function only names concerns.  It never returns a mark, a state or a
replacement reading, which is what makes "a transcription can never change an
award" a property of its shape rather than a promise in a docstring.
"""

from __future__ import annotations

import pytest
from app.correction.transcription import (
    CONCERN_DIFFERS,
    CONCERN_NO_READING,
    CONCERN_PAGE_UNVERIFIED,
    CONCERN_UNVERIFIED,
    PAGE_CONFIDENCE_CIRCULAR,
    PAGE_CONFIDENCE_INDEPENDENT,
    PAGE_CONFIDENCE_NONE,
    STATUS_ABSENT,
    STATUS_AGREES,
    STATUS_DIFFERS,
    STATUS_UNVERIFIABLE,
    outcome_concerns,
)


def test_an_agreement_on_an_independently_chosen_page_raises_nothing() -> None:
    assert outcome_concerns(
        STATUS_AGREES, awarded=0, page_confidence=PAGE_CONFIDENCE_INDEPENDENT
    ) == ()
    assert outcome_concerns(
        STATUS_AGREES, awarded=3, page_confidence=PAGE_CONFIDENCE_INDEPENDENT
    ) == ()


def test_an_agreement_on_the_marking_pass_own_page_is_circular() -> None:
    for awarded in (0, 3):
        assert outcome_concerns(
            STATUS_AGREES, awarded=awarded, page_confidence=PAGE_CONFIDENCE_CIRCULAR
        ) == (CONCERN_PAGE_UNVERIFIED,)


def test_two_blank_readings_agree_on_a_zero() -> None:
    assert outcome_concerns(
        STATUS_ABSENT, awarded=0, page_confidence=PAGE_CONFIDENCE_INDEPENDENT
    ) == ()


def test_an_absent_reading_with_marks_awarded_has_no_transcription_behind_it() -> None:
    assert outcome_concerns(
        STATUS_ABSENT, awarded=3, page_confidence=PAGE_CONFIDENCE_INDEPENDENT
    ) == (CONCERN_NO_READING,)


def test_an_absent_reading_can_be_both_unbacked_and_circular() -> None:
    assert outcome_concerns(
        STATUS_ABSENT, awarded=3, page_confidence=PAGE_CONFIDENCE_CIRCULAR
    ) == (CONCERN_NO_READING, CONCERN_PAGE_UNVERIFIED)
    assert outcome_concerns(
        STATUS_ABSENT, awarded=0, page_confidence=PAGE_CONFIDENCE_CIRCULAR
    ) == (CONCERN_PAGE_UNVERIFIED,)


@pytest.mark.parametrize("awarded", [0, 2, 10])
def test_a_difference_is_a_definite_concern_whatever_the_award(awarded: int) -> None:
    assert outcome_concerns(
        STATUS_DIFFERS, awarded=awarded, page_confidence=PAGE_CONFIDENCE_INDEPENDENT
    ) == (CONCERN_DIFFERS,)


@pytest.mark.parametrize("awarded", [0, 2, 10])
def test_an_unusable_reading_is_a_concern_whatever_the_award(awarded: int) -> None:
    assert outcome_concerns(
        STATUS_UNVERIFIABLE,
        awarded=awarded,
        page_confidence=PAGE_CONFIDENCE_INDEPENDENT,
    ) == (CONCERN_UNVERIFIED,)


def test_an_unavailable_page_selection_never_claims_a_verification() -> None:
    """``NONE`` is not circular — there was no reading to locate at all."""

    assert outcome_concerns(
        STATUS_AGREES, awarded=0, page_confidence=PAGE_CONFIDENCE_NONE
    ) == ()


def test_a_negative_award_is_not_treated_as_a_zero() -> None:
    """Defensive: an impossible award must not silence a concern."""

    assert outcome_concerns(
        STATUS_ABSENT, awarded=-1, page_confidence=PAGE_CONFIDENCE_INDEPENDENT
    ) == (CONCERN_NO_READING,)


def test_the_policy_has_no_way_to_return_a_mark() -> None:
    from app.correction.transcription import outcome_concerns as policy

    result = policy(STATUS_DIFFERS, awarded=3, page_confidence=PAGE_CONFIDENCE_CIRCULAR)

    assert isinstance(result, tuple)
    assert all(isinstance(code, str) for code in result)
    assert set(result) <= {
        CONCERN_DIFFERS,
        CONCERN_NO_READING,
        CONCERN_PAGE_UNVERIFIED,
        CONCERN_UNVERIFIED,
    }
