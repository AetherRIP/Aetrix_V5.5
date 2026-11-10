"""Verification classifies an award; it never silently changes one."""

from __future__ import annotations

import pytest
from app.marking.schema import MarkComponent, QuestionMark
from app.marking.verification import equivalent, verify_question


def _mark(**overrides) -> QuestionMark:
    body = {
        "question_id": "1a",
        "student_answer": "x = 3",
        "awarded_marks": 2,
        "components": [
            MarkComponent(code="M1", marks=1, awarded=True, evidence="x = 3"),
            MarkComponent(code="A1", marks=1, awarded=True, evidence="x = 3"),
        ],
        "confidence": 0.94,
    }
    body.update(overrides)
    return QuestionMark.model_validate(body)


def test_a_consistent_award_passes_integrity() -> None:
    outcome = verify_question(_mark(), max_marks=2, min_confidence=0.6)

    assert outcome.review_required is False
    assert outcome.reasons == []
    assert [record.kind for record in outcome.records] == ["INTEGRITY"]
    assert outcome.records[0].status == "PASS"


def test_an_award_above_the_maximum_requires_review() -> None:
    outcome = verify_question(_mark(awarded_marks=3), max_marks=2, min_confidence=0.6)

    assert outcome.review_required is True
    assert any("exceeds the question maximum" in reason for reason in outcome.reasons)


def test_components_that_do_not_sum_to_the_award_require_review() -> None:
    mark = _mark(
        components=[
            MarkComponent(code="M1", marks=1, awarded=True, evidence="substituted"),
            MarkComponent(code="A1", marks=1, awarded=False),
        ]
    )

    outcome = verify_question(mark, max_marks=2, min_confidence=0.6)

    assert outcome.review_required is True
    assert any("do not equal the stated award" in reason for reason in outcome.reasons)


def test_low_confidence_requires_review_rather_than_a_mark() -> None:
    outcome = verify_question(_mark(confidence=0.41), max_marks=2, min_confidence=0.6)

    assert outcome.review_required is True
    assert any("below the review floor" in reason for reason in outcome.reasons)


def test_a_zero_needs_high_confidence() -> None:
    zero = _mark(
        awarded_marks=0,
        components=[MarkComponent(code="A1", marks=2, awarded=False)],
        confidence=0.7,
    )

    outcome = verify_question(zero, max_marks=2, min_confidence=0.4)

    assert outcome.review_required is True
    assert any("zero award" in reason for reason in outcome.reasons)


def test_unreadable_and_blank_pages_force_review() -> None:
    outcome = verify_question(
        _mark(), max_marks=2, min_confidence=0.6, page_quality=["UNREADABLE", "OK"]
    )
    assert outcome.review_required is True
    assert any("unreadable" in reason for reason in outcome.reasons)

    blank = verify_question(_mark(), max_marks=2, min_confidence=0.6, page_quality=["EMPTY"])
    assert any("blank" in reason for reason in blank.reasons)


def test_two_low_quality_pages_are_not_trusted() -> None:
    outcome = verify_question(
        _mark(),
        max_marks=2,
        min_confidence=0.6,
        page_quality=["LOW_QUALITY", "LOW_QUALITY"],
    )

    assert outcome.review_required is True


def test_equivalent_expressions_are_proven_and_recorded() -> None:
    mark = _mark(answer_check={"student_expression": "1/2", "expected_expression": "0.5"})

    outcome = verify_question(mark, max_marks=2, min_confidence=0.6)

    assert outcome.review_required is False
    mathematical = [record for record in outcome.records if record.kind == "MATHEMATICAL"]
    assert mathematical and mathematical[0].status == "EQUIVALENT"


def test_a_different_final_answer_requires_a_person() -> None:
    mark = _mark(answer_check={"student_expression": "4", "expected_expression": "1+2"})

    outcome = verify_question(mark, max_marks=2, min_confidence=0.6)

    assert outcome.review_required is True
    assert any("not mathematically equivalent" in reason for reason in outcome.reasons)


def test_an_undecidable_expression_is_unknown_not_zero() -> None:
    mark = _mark(
        answer_check={"student_expression": "not a formula", "expected_expression": "3"}
    )

    outcome = verify_question(mark, max_marks=2, min_confidence=0.6)

    assert outcome.review_required is True
    statuses = {record.kind: record.status for record in outcome.records}
    assert statuses["MATHEMATICAL"] == "UNKNOWN"
    assert any("could not be verified" in reason for reason in outcome.reasons)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("2 + 2", "4", True),
        ("x + x", "2*x", True),
        ("3", "4", False),
        ("__import__('os')", "3", None),
    ],
)
def test_equivalence_is_decided_or_admits_ignorance(left, right, expected) -> None:
    assert equivalent(left, right) is expected
