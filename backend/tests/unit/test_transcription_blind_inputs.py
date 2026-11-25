"""What the blind reader is actually sent.

Mission 5 found the shipped transcription request carried ``Maximum marks: 3``
and a ``Scheme references`` pointer, because it reused the marking header.  A
prompt-only test would not have caught it: the leak was in the request builder.

These tests build the request the engine builds, serialise it with the real
Gemini part encoder, and prove that no marking field reaches the reader — in
both marking modes, because transcription runs per question either way.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.core.config import MarkingSettings
from app.correction.aetrix.pipeline import _MarkingRun, _question_context
from app.correction.transcription import (
    blind_question_context,
    header_is_blind,
)
from app.providers.gemini import GeminiProvider

#: Every field a blind reader must never see, with a value that would be
#: recognisable if it appeared anywhere in the request.
SENTINELS = {
    "maximum_marks": "Maximum marks",
    "scheme_references": "Scheme references",
    "special_instructions": "Special instructions",
    "criterion": "ZEBRA-CRITERION-TEXT",
    "expected_answer": "ZEBRA-EXPECTED-ANSWER",
    "marking_answer": "ZEBRA-MARKING-ANSWER",
    "marking_quote": "ZEBRA-MARKING-QUOTE",
}

BLUEPRINT_QUESTION = SimpleNamespace(
    question_id="2",
    label="Question 2",
    max_marks=5,
    answer_type="working",
    special_instructions=["ZEBRA-INSTRUCTION-FOR-THE-MARKER"],
    criteria_refs=["ZEBRA-SCHEME-REFERENCE"],
)


class _Storage:
    """A page store that returns bytes, so no file system is involved."""

    def read(self, key: str) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + key.encode("ascii")


def _run(marking_mode: str) -> _MarkingRun:
    settings = SimpleNamespace(
        marking=MarkingSettings(marking_mode=marking_mode, transcription_enabled=True)
    )
    return _MarkingRun(
        session=None,  # type: ignore[arg-type]
        job=SimpleNamespace(),  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        structure=None,  # type: ignore[arg-type]
        criteria_by_question={},
        readable=[],
        calls=None,  # type: ignore[arg-type]
        storage=_Storage(),  # type: ignore[arg-type]
        quality=[],
        engine_version="test",
        policy=None,  # type: ignore[arg-type]
    )


def _page(page_index: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"p{page_index}", page_index=page_index, storage_key=f"pages/{page_index}.png"
    )


def _serialised(run: _MarkingRun, pages: list) -> tuple[str, dict]:
    inputs = run._transcription_inputs(("2", 5, "working", "2"), pages=pages)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [GeminiProvider._part(item) for item in inputs],
            }
        ]
    }
    return json.dumps(payload), payload


def test_the_marking_header_is_what_leaked() -> None:
    """The defect the allowlist replaces: the marking header prints the scheme."""

    marking_header = _question_context("2", 5, "working", BLUEPRINT_QUESTION)

    assert "Maximum marks: 5" in marking_header
    assert "Scheme references" in marking_header
    assert "Special instructions" in marking_header


def test_the_blind_header_is_only_the_question_and_its_kind() -> None:
    header = blind_question_context("2", "working")

    assert header == "Question: 2\nAnswer type: working"
    assert header_is_blind(header)
    for value in SENTINELS.values():
        assert value.lower() not in header.lower()


def test_no_marking_field_reaches_the_serialised_request() -> None:
    run = _run("PER_QUESTION")

    serialised, payload = _serialised(run, [_page()])

    for name, value in SENTINELS.items():
        assert value.lower() not in serialised.lower(), f"{name} leaked into the request"
    parts = payload["contents"][0]["parts"]
    assert parts[0] == {"text": "Question: 2\nAnswer type: working"}
    assert "text" in parts[1], "the page label is a text part, not the header"
    assert parts[1]["text"].startswith("Page 2 of 1 supplied")
    assert "inlineData" in parts[2]


def test_the_whole_paper_mode_sends_the_same_blind_request() -> None:
    """Transcription is per question in both modes; the blind rules do not change."""

    per_question, _ = _serialised(_run("PER_QUESTION"), [_page()])
    whole_paper, _ = _serialised(_run("WHOLE_PAPER"), [_page()])

    assert per_question == whole_paper
    for value in SENTINELS.values():
        assert value.lower() not in whole_paper.lower()


def test_every_supplied_page_is_labelled_with_its_original_number() -> None:
    run = _run("PER_QUESTION")

    _, payload = _serialised(run, [_page(2), _page(3)])

    texts = [
        part["text"] for part in payload["contents"][0]["parts"] if "text" in part
    ]
    assert texts[0].startswith("Question: 2")
    assert any(text.startswith("Page 2 of 2 supplied") for text in texts)
    assert any(text.startswith("Page 3 of 2 supplied") for text in texts)
