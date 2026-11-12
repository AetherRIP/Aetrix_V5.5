"""The marking JSON contract is strict: a bad response is a failure, not a mark."""

from __future__ import annotations

import pytest
from app.correction.aetrix.schema import MarkingResponseInvalid, parse_question_mark


def _payload(**overrides) -> str:
    import json

    body = {
        "question_id": "1a",
        "student_answer": "x = 3",
        "awarded_marks": 2,
        "components": [
            {
                "code": "M1",
                "description": "Correct substitution",
                "marks": 1,
                "awarded": True,
                "reason": "Substituted x = 3.",
                "evidence": "x = 3",
            },
            {
                "code": "A1",
                "description": "Correct final answer",
                "marks": 1,
                "awarded": True,
                "reason": "Answer matches the scheme.",
                "evidence": "x = 3",
            },
        ],
        "confidence": 0.93,
    }
    body.update(overrides)
    return json.dumps(body)


def test_valid_response_parses_with_components_and_confidence() -> None:
    mark = parse_question_mark(_payload(), question_id="1a")

    assert mark.question_id == "1a"
    assert mark.awarded_marks == 2
    assert [component.code for component in mark.components] == ["M1", "A1"]
    assert mark.component_total == 2
    assert mark.confidence == pytest.approx(0.93)
    assert mark.student_answer == "x = 3"


def test_a_fenced_code_block_is_tolerated() -> None:
    fenced = "```json\n" + _payload() + "\n```"

    assert parse_question_mark(fenced, question_id="1a").awarded_marks == 2


def test_an_award_without_quoted_evidence_is_rejected() -> None:
    payload = _payload()
    payload = payload.replace('"evidence": "x = 3"', '"evidence": null')

    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(payload, question_id="1a")


def test_a_mark_for_the_wrong_question_is_rejected() -> None:
    with pytest.raises(MarkingResponseInvalid, match="while question"):
        parse_question_mark(_payload(), question_id="1b")


def test_a_reused_component_code_is_disambiguated_not_discarded() -> None:
    """A scheme reuses M1 legitimately; a repeated label must not lose the mark."""

    payload = _payload(
        components=[
            {"code": "M1", "marks": 1, "awarded": True, "evidence": "x = 3"},
            {"code": "M1", "marks": 1, "awarded": True, "evidence": "x = 3"},
        ]
    )

    mark = parse_question_mark(payload, question_id="1a")

    assert [component.code for component in mark.components] == ["M1", "M1-2"]
    assert [component.awarded for component in mark.components] == [True, True]
    assert [component.evidence for component in mark.components] == ["x = 3", "x = 3"]
    assert mark.component_total == 2


def test_non_json_and_empty_responses_are_typed_failures() -> None:
    with pytest.raises(MarkingResponseInvalid, match="not valid JSON"):
        parse_question_mark("Awarded two marks.", question_id="1a")
    with pytest.raises(MarkingResponseInvalid, match="empty response"):
        parse_question_mark("   ", question_id="1a")


def test_negative_or_out_of_range_marks_are_rejected() -> None:
    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(_payload(awarded_marks=-1), question_id="1a")
    with pytest.raises(MarkingResponseInvalid):
        parse_question_mark(_payload(confidence=1.4), question_id="1a")


def test_optional_answer_check_is_parsed_when_present() -> None:
    payload = _payload(
        answer_check={"student_expression": "3", "expected_expression": "1+2"}
    )

    mark = parse_question_mark(payload, question_id="1a")

    assert mark.answer_check is not None
    assert mark.answer_check.student_expression == "3"


def test_component_total_is_none_without_components() -> None:
    mark = parse_question_mark(
        _payload(awarded_marks=0, components=[], confidence=0.9), question_id="1a"
    )

    assert mark.component_total is None
