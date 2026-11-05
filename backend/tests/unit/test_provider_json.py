from __future__ import annotations

import json

import pytest
from app.providers.json import parse_json_text

STRUCTURE = {
    "questions": [{"question_id": "1", "max_marks": 2}],
    "total_marks": 2,
}


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(STRUCTURE),
        "Here is the extracted blueprint:\n" + json.dumps(STRUCTURE),
        "```json\n" + json.dumps(STRUCTURE) + "\n```",
        "Result follows.\n```\n" + json.dumps(STRUCTURE) + "\n```\nEnd of result.",
        "The model says {not json} before the result: " + json.dumps(STRUCTURE),
    ],
)
def test_parse_json_text_accepts_prose_and_fences(text: str) -> None:
    assert parse_json_text(text) == STRUCTURE


@pytest.mark.parametrize(
    "text",
    [
        "Here is the JSON requested",
        '```json\n{"questions": [\n```',
        'prefix {"questions": [} suffix',
        "",
    ],
)
def test_parse_json_text_rejects_malformed_or_incomplete_json(text: str) -> None:
    with pytest.raises(ValueError):
        parse_json_text(text)
