from __future__ import annotations

import pytest
from app.schemas.blueprint import BlueprintPut, BlueprintStructure
from pydantic import ValidationError


def _question(question_id: str, marks: int, **extra) -> dict:
    return {"question_id": question_id, "max_marks": marks, **extra}


def test_valid_blueprint_accepts_subquestion_sum() -> None:
    structure = BlueprintStructure.model_validate(
        {
            "questions": [
                _question(
                    "1",
                    5,
                    subquestions=[
                        _question("1a", 2),
                        _question("1b", 3),
                    ],
                ),
                _question("2", 4),
            ],
            "total_marks": 9,
        }
    )
    assert structure.total_marks == 9
    assert structure.scoreable_question_ids == ["1", "2"]


def test_duplicate_identifiers_are_rejected_case_insensitively() -> None:
    with pytest.raises(ValidationError, match="duplicate question identifier"):
        BlueprintStructure.model_validate(
            {
                "questions": [_question("1", 2), _question(" 1 ", 2)],
                "total_marks": 4,
            }
        )


def test_declared_total_must_match_included_marks() -> None:
    with pytest.raises(ValidationError, match="declared total_marks"):
        BlueprintStructure.model_validate({"questions": [_question("1", 3)], "total_marks": 4})


def test_subquestion_sum_must_match_parent() -> None:
    with pytest.raises(ValidationError, match="sub-question marks"):
        BlueprintStructure.model_validate(
            {
                "questions": [
                    _question("1", 5, subquestions=[_question("1a", 2), _question("1b", 2)])
                ],
                "total_marks": 5,
            }
        )


def test_exclusion_requires_a_reason_and_is_excluded_from_total() -> None:
    with pytest.raises(ValidationError, match="exclusion_reason"):
        BlueprintStructure.model_validate(
            {
                "questions": [_question("1", 2), _question("2", 3, excluded=True)],
                "total_marks": 2,
            }
        )

    structure = BlueprintStructure.model_validate(
        {
            "questions": [
                _question("1", 2),
                _question("2", 3, excluded=True, exclusion_reason="not printed"),
            ],
            "total_marks": 2,
        }
    )
    assert structure.scoreable_question_ids == ["1"]


def test_a_blueprint_needs_a_scoreable_question() -> None:
    with pytest.raises(ValidationError, match="at least one non-excluded"):
        BlueprintStructure.model_validate(
            {
                "questions": [_question("1", 2, excluded=True, exclusion_reason="source mismatch")],
                "total_marks": 0,
            }
        )


def test_approval_requires_a_reason() -> None:
    structure = {"questions": [_question("1", 2)], "total_marks": 2}
    with pytest.raises(ValidationError, match="approving a blueprint requires a reason"):
        BlueprintPut.model_validate({"structure": structure, "approve": True})
    BlueprintPut.model_validate(
        {"structure": structure, "approve": True, "reason": "checked against the paper"}
    )
