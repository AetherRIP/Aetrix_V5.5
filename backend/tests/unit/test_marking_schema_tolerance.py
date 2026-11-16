"""Auxiliary fields must not cost a question its mark.

The marking decision is carried by ``question_id``, ``awarded_marks`` and
``components``.  The other fields — quoted evidence, reasons, a note, the
optional mathematical answer check — are supporting detail.  A model that writes
a very long quotation, or an answer check this build cannot read, has still
marked the question, and discarding that marking over a size limit turns a real
decision into an unmarked question.

These tests prove the split in both directions: supporting detail is clipped or
dropped, while a structural fault (a missing award, an award with no evidence, a
mark for the wrong question) still rejects the response.
"""

from __future__ import annotations

import json

import pytest
from app.correction.aetrix import schema
from app.correction.aetrix.schema import (
    MAX_ANSWER_CHARS,
    MAX_EVIDENCE_CHARS,
    MAX_NOTES_CHARS,
    MAX_REASON_CHARS,
    MAX_REVIEW_REASONS,
    MarkingResponseInvalid,
    parse_question_mark,
)


def _payload(**overrides):
    payload = {
        "question_id": "1a",
        "student_answer": "x = 3",
        "awarded_marks": 1,
        "components": [
            {
                "code": "A1",
                "marks": 1,
                "awarded": True,
                "reason": "the value is correct",
                "evidence": "x = 3",
            }
        ],
        "confidence": 0.9,
    }
    payload.update(overrides)
    return payload


def test_json_wrapped_in_prose_is_still_read() -> None:
    """A model that introduces its JSON has not failed to mark the question."""

    text = (
        "Here is the marking result for question 1a:\n"
        + json.dumps(_payload())
        + "\nThat is the only question requested."
    )

    mark = parse_question_mark(text, question_id="1a")

    assert mark.awarded_marks == 1
    assert mark.components[0].evidence == "x = 3"


def test_a_fenced_json_block_is_still_read() -> None:
    text = "```json\n" + json.dumps(_payload()) + "\n```"

    assert parse_question_mark(text, question_id="1a").awarded_marks == 1


def test_a_very_long_quotation_is_clipped_rather_than_rejected() -> None:
    long_quote = "x" * (MAX_EVIDENCE_CHARS + 500)

    mark = parse_question_mark(
        json.dumps(_payload(components=[
            {
                "code": "A1",
                "marks": 1,
                "awarded": True,
                "reason": "quoted",
                "evidence": long_quote,
            }
        ])),
        question_id="1a",
    )

    assert mark.awarded_marks == 1
    assert len(mark.components[0].evidence) == MAX_EVIDENCE_CHARS


def test_a_long_reason_and_note_are_clipped_not_rejected() -> None:
    mark = parse_question_mark(
        json.dumps(
            _payload(
                notes="n" * (MAX_NOTES_CHARS + 100),
                student_answer="s" * (MAX_ANSWER_CHARS + 100),
                components=[
                    {
                        "code": "A1",
                        "marks": 1,
                        "awarded": True,
                        "reason": "r" * (MAX_REASON_CHARS + 100),
                        "evidence": "x = 3",
                    }
                ],
            )
        ),
        question_id="1a",
    )

    assert len(mark.notes) == MAX_NOTES_CHARS
    assert len(mark.student_answer) == MAX_ANSWER_CHARS
    assert len(mark.components[0].reason) == MAX_REASON_CHARS


def test_a_flood_of_review_reasons_is_kept_bounded() -> None:
    mark = parse_question_mark(
        json.dumps(_payload(review_reasons=["reason"] * (MAX_REVIEW_REASONS + 10))),
        question_id="1a",
    )

    assert len(mark.review_reasons) == MAX_REVIEW_REASONS


def test_an_unreadable_answer_check_is_dropped_and_the_mark_kept() -> None:
    """The optional mathematical check is advisory; it cannot void the award."""

    mark = parse_question_mark(
        json.dumps(
            _payload(
                answer_check={"student_expression": "", "expected_expression": "x"},
            )
        ),
        question_id="1a",
    )

    assert mark.awarded_marks == 1
    assert mark.answer_check is None


def test_an_answer_check_with_no_student_expression_is_dropped() -> None:
    mark = parse_question_mark(
        json.dumps(
            _payload(
                answer_check={"student_expression": "   ", "expected_expression": "3"},
            )
        ),
        question_id="1a",
    )

    assert mark.answer_check is None


def test_a_readable_answer_check_is_kept() -> None:
    mark = parse_question_mark(
        json.dumps(
            _payload(
                answer_check={"student_expression": "3/4", "expected_expression": "0.75"},
            )
        ),
        question_id="1a",
    )

    assert mark.answer_check is not None
    assert mark.answer_check.student_expression == "3/4"


def test_a_missing_award_is_still_rejected() -> None:
    payload = _payload()
    payload.pop("awarded_marks")

    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(json.dumps(payload), question_id="1a")


def test_an_award_above_the_contract_ceiling_is_still_rejected() -> None:
    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(
            json.dumps(_payload(awarded_marks=schema.AWARD_RESPONSE_CEILING + 1)),
            question_id="1a",
        )


def test_an_awarded_component_without_evidence_is_still_rejected() -> None:
    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(
            json.dumps(
                _payload(
                    components=[
                        {"code": "A1", "marks": 1, "awarded": True, "evidence": "   "}
                    ]
                )
            ),
            question_id="1a",
        )


def test_a_mark_for_another_question_is_still_rejected() -> None:
    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(json.dumps(_payload(question_id="2b")), question_id="1a")


def test_a_negative_award_is_still_rejected() -> None:
    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(json.dumps(_payload(awarded_marks=-1)), question_id="1a")
