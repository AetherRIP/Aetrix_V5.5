from __future__ import annotations

import pytest
from app.core.errors import AppError
from app.schemas.blueprint import BlueprintStructure
from app.schemas.documents import BlueprintOverrideOperation
from app.services.blueprint_overrides import apply_operations


def _structure() -> BlueprintStructure:
    return BlueprintStructure.model_validate(
        {
            "questions": [
                {
                    "question_id": "1",
                    "max_marks": 5,
                    "subquestions": [
                        {"question_id": "1a", "max_marks": 2},
                        {"question_id": "1b", "max_marks": 3},
                    ],
                },
                {"question_id": "2", "max_marks": 5},
            ],
            "total_marks": 10,
        }
    )


def test_override_recomputes_total_and_preserves_subquestions() -> None:
    updated = apply_operations(
        _structure(),
        [BlueprintOverrideOperation(op="set_question_marks", question_id="2", max_marks=7)],
    )
    assert updated.total_marks == 12
    assert updated.questions[1].max_marks == 7
    assert [sub.max_marks for sub in updated.questions[0].subquestions] == [2, 3]


def test_subquestion_mark_override_recomputes_parent_and_total() -> None:
    updated = apply_operations(
        _structure(),
        [BlueprintOverrideOperation(op="set_question_marks", question_id="1a", max_marks=4)],
    )
    assert updated.questions[0].max_marks == 7
    assert updated.questions[0].subquestions[0].max_marks == 4
    assert updated.questions[0].subquestions[1].max_marks == 3
    assert updated.total_marks == 12


def test_exclude_recomputes_total_and_requires_a_reason_at_schema_level() -> None:
    updated = apply_operations(
        _structure(),
        [BlueprintOverrideOperation(op="exclude_question", question_id="2", reason="not printed")],
    )
    assert updated.total_marks == 5
    assert updated.questions[1].excluded is True

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BlueprintOverrideOperation.model_validate({"op": "exclude_question", "question_id": "2"})


def test_unknown_question_is_rejected() -> None:
    with pytest.raises(AppError):
        apply_operations(
            _structure(),
            [BlueprintOverrideOperation(op="set_question_marks", question_id="99", max_marks=1)],
        )
