from __future__ import annotations

from app.documents.blueprint_extraction import _repair_total


def test_the_total_is_derived_from_the_extracted_questions() -> None:
    payload = {
        "questions": [
            {"question_id": "1", "max_marks": 2},
            {"question_id": "2", "max_marks": 3},
            {
                "question_id": "3",
                "max_marks": 5,
                "excluded": True,
                "exclusion_reason": "not printed on the paper",
            },
        ],
        "total_marks": 4,
    }

    repaired = _repair_total(payload)

    assert repaired["total_marks"] == 5
    assert any("derived from the questions" in note for note in repaired["notes"])


def test_a_consistent_total_is_left_untouched() -> None:
    payload = {
        "questions": [{"question_id": "1", "max_marks": 2}],
        "total_marks": 2,
    }

    assert _repair_total(payload) == payload
    assert "notes" not in _repair_total(payload)


def test_a_non_integer_mark_is_left_for_the_schema_to_reject() -> None:
    payload = {
        "questions": [{"question_id": "1", "max_marks": "two"}],
        "total_marks": 2,
    }

    assert _repair_total(payload) == payload
