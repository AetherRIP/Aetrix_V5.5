"""The whole-paper reply is one document, validated question by question.

A single bad item must not cost the other 38 answers, and a truncated reply must
keep the questions the model finished.  These tests pin both properties, plus the
output bounds the paper budget depends on.
"""

from __future__ import annotations

import json
import re

import pytest
from app.core.config import get_settings
from app.correction.aetrix.pipeline import PROMPT_MARKING_WHOLE_PAPER
from app.correction.aetrix.whole_paper import (
    MAX_WHOLE_PAPER_COMPONENTS,
    MAX_WHOLE_PAPER_EVIDENCE_CHARS,
    MAX_WHOLE_PAPER_REASON_CHARS,
    WHOLE_PAPER_RESPONSE_SCHEMA,
    WholePaperResponseInvalid,
    detect_truncation,
    parse_whole_paper,
)
from app.prompts.registry import PromptRegistry

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _item(question_id: str = "1a", **overrides) -> dict:
    body = {
        "question_id": question_id,
        "student_answer": "x = 3",
        "awarded_marks": 1,
        "components": [
            {
                "code": "M1",
                "description": "Correct substitution",
                "marks": 1,
                "awarded": True,
                "reason": "Substituted x = 3.",
                "evidence": "x = 3",
            }
        ],
        "confidence": 0.9,
    }
    body.update(overrides)
    return body


def _payload(*items: dict) -> str:
    return json.dumps({"questions": list(items)})


def test_every_answered_question_parses_and_is_keyed_by_id() -> None:
    parse = parse_whole_paper(
        _payload(_item("1a"), _item("1b", awarded_marks=0, components=[])),
        expected_ids=["1a", "1b"],
    )

    assert sorted(parse.marks) == ["1a", "1b"]
    assert parse.marks["1a"].awarded_marks == 1
    assert parse.marks["1b"].awarded_marks == 0
    assert parse.missing == []
    assert parse.complete is True
    assert parse.describe()["parsed"] == 2


def test_a_question_this_blueprint_does_not_contain_is_reported_not_fatal() -> None:
    parse = parse_whole_paper(
        _payload(_item("1a"), _item("9z")), expected_ids=["1a"]
    )

    assert sorted(parse.marks) == ["1a"]
    assert parse.unknown_ids == ["9z"]
    assert parse.missing == []


def test_a_repeated_question_keeps_its_first_reading() -> None:
    parse = parse_whole_paper(
        _payload(_item("1a"), _item("1a", awarded_marks=0, components=[])),
        expected_ids=["1a"],
    )

    assert parse.marks["1a"].awarded_marks == 1
    assert parse.duplicates == ["1a"]


def test_one_invalid_item_does_not_discard_the_rest_of_the_paper() -> None:
    broken = _item("1b")
    broken["components"][0]["evidence"] = None

    parse = parse_whole_paper(
        _payload(_item("1a"), broken, _item("1c")), expected_ids=["1a", "1b", "1c"]
    )

    assert sorted(parse.marks) == ["1a", "1c"]
    assert list(parse.invalid) == ["1b"]
    assert parse.missing == ["1b"]
    assert "contract" in parse.invalid["1b"]


def test_an_impossible_award_invalidates_only_its_own_question() -> None:
    parse = parse_whole_paper(
        _payload(_item("1a"), _item("1b", awarded_marks=5000)),
        expected_ids=["1a", "1b"],
    )

    assert sorted(parse.marks) == ["1a"]
    assert list(parse.invalid) == ["1b"]


def test_supporting_text_is_clipped_to_the_whole_paper_bounds() -> None:
    long_text = "q" * (MAX_WHOLE_PAPER_EVIDENCE_CHARS + 50)
    item = _item("1a")
    item["components"][0]["evidence"] = long_text
    item["components"][0]["reason"] = "r" * (MAX_WHOLE_PAPER_REASON_CHARS + 50)

    parse = parse_whole_paper(_payload(item), expected_ids=["1a"])

    component = parse.marks["1a"].components[0]
    assert len(component.evidence) == MAX_WHOLE_PAPER_EVIDENCE_CHARS
    assert len(component.reason) == MAX_WHOLE_PAPER_REASON_CHARS
    assert parse.clipped_supporting_text == 2


@pytest.mark.parametrize(
    "text",
    ["Awarded two marks.", "", "   ", '{"questions": "none"}', '{"questions": []}'],
)
def test_a_reply_that_is_not_a_paper_document_is_a_typed_failure(text: str) -> None:
    with pytest.raises(WholePaperResponseInvalid):
        parse_whole_paper(text, expected_ids=["1a"])


def test_truncation_is_recognised_from_the_finish_reason() -> None:
    assert detect_truncation("MAX_TOKENS") is True
    assert detect_truncation("maxtokens") is True
    assert detect_truncation("STOP") is False
    assert detect_truncation(None) is False


def test_a_truncated_reply_keeps_the_questions_the_model_finished() -> None:
    complete = _payload(_item("1a"), _item("1b"), _item("1c"))
    truncated = complete[: complete.index('"1c"')]

    parse = parse_whole_paper(
        truncated, expected_ids=["1a", "1b", "1c"], truncated=True
    )

    assert sorted(parse.marks) == ["1a", "1b"]
    assert parse.missing == ["1c"]
    assert parse.complete is False


def test_a_truncated_reply_without_a_complete_question_is_refused() -> None:
    with pytest.raises(WholePaperResponseInvalid, match="cut off"):
        parse_whole_paper(
            '{"questions": [{"question_id": "1a"',
            expected_ids=["1a"],
            truncated=True,
        )


def test_the_schema_declares_shape_only_so_a_model_can_serve_it() -> None:
    """Length bounds must not be schema constraints.

    Google answered the bounded schema with HTTP 400 INVALID_ARGUMENT — "the
    specified schema produces a constraint that has too many states for
    serving" — because a ``maxLength`` on every supporting string of 39
    questions (and ``maxItems`` on the arrays inside them) explodes constrained
    decoding.  The bounds are still applied, on the reply, by ``_bound_item``.
    """

    questions = WHOLE_PAPER_RESPONSE_SCHEMA["properties"]["questions"]
    item = questions["items"]
    component = item["properties"]["components"]["items"]

    assert WHOLE_PAPER_RESPONSE_SCHEMA["required"] == ["questions"]
    assert "maxItems" not in questions
    assert "maxItems" not in item["properties"]["components"]
    for field in ("evidence", "reason", "description"):
        assert "maxLength" not in component["properties"][field]
    for field in ("question_id", "student_answer", "notes"):
        assert "maxLength" not in item["properties"][field]
    assert set(item["required"]) == {
        "question_id",
        "awarded_marks",
        "components",
        "confidence",
    }


def test_over_long_supporting_text_is_clipped_on_the_reply() -> None:
    """The output bound still holds now that the schema cannot state it."""

    parse = parse_whole_paper(
        json.dumps(
            {
                "questions": [
                    {
                        "question_id": "1a",
                        "awarded_marks": 1,
                        "confidence": 0.9,
                        "components": [
                            {
                                "code": "M1",
                                "marks": 1,
                                "awarded": True,
                                "evidence": "x" * 400,
                            }
                        ],
                    }
                ]
            }
        ),
        expected_ids=["1a"],
    )

    assert parse.clipped_supporting_text == 1
    assert len(parse.marks["1a"].components[0].evidence) == MAX_WHOLE_PAPER_EVIDENCE_CHARS


def _prompt_example() -> dict:
    asset = PromptRegistry(get_settings().provider.prompt_root).load(
        PROMPT_MARKING_WHOLE_PAPER
    )
    match = _JSON_BLOCK.search(asset.content)
    assert match is not None, "the whole-paper prompt must show a reply example"
    return json.loads(match.group(1))


def test_the_prompt_example_is_a_valid_whole_paper_reply() -> None:
    example = _prompt_example()
    expected = [item["question_id"] for item in example["questions"]]

    parse = parse_whole_paper(json.dumps(example), expected_ids=expected)

    assert sorted(parse.marks) == sorted(expected)
    assert parse.invalid == {}
    assert parse.missing == []


@pytest.mark.parametrize("prompt_id", [PROMPT_MARKING_WHOLE_PAPER])
def test_the_prompt_example_obeys_the_integrity_rule_it_teaches(prompt_id: str) -> None:
    example = _prompt_example()

    for item in example["questions"]:
        awarded = sum(
            component["marks"]
            for component in item["components"]
            if component.get("awarded")
        )
        assert awarded == item["awarded_marks"], item["question_id"]
        assert all(
            (component.get("evidence") or "").strip()
            for component in item["components"]
            if component.get("awarded")
        ), item["question_id"]
        assert len(item["components"]) <= MAX_WHOLE_PAPER_COMPONENTS
