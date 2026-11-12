"""The blueprint's leaf list and the pipeline's enumeration must agree.

Approval checks coverage against ``BlueprintStructure.scoreable_leaf_ids`` while
the engine marks whatever ``_leaf_questions`` returns.  If the two ever diverge,
a paper could be approved without a result for a question the engine meant to
mark, so the pair is asserted here rather than trusted.
"""

from __future__ import annotations

from app.correction.aetrix.pipeline import _leaf_questions
from app.schemas.blueprint import BlueprintStructure

STRUCTURE = {
    "paper_code": "LEAF-1",
    "questions": [
        {
            "question_id": "1",
            "max_marks": 2,
            "subquestions": [
                {"question_id": "1a", "max_marks": 2},
                {
                    "question_id": "1b",
                    "max_marks": 3,
                    "excluded": True,
                    "exclusion_reason": "not set on this paper",
                },
            ],
        },
        {"question_id": "2", "max_marks": 2},
        {
            "question_id": "3",
            "max_marks": 4,
            "excluded": True,
            "exclusion_reason": "practical work, not marked here",
        },
    ],
    "total_marks": 4,
}


def test_excluded_questions_and_subquestions_are_never_expected() -> None:
    structure = BlueprintStructure.model_validate(STRUCTURE)

    assert structure.scoreable_leaf_ids == ["1a", "2"]


def test_the_blueprint_and_the_pipeline_enumerate_the_same_leaves() -> None:
    structure = BlueprintStructure.model_validate(STRUCTURE)

    assert structure.scoreable_leaf_ids == [leaf[0] for leaf in _leaf_questions(structure)]


def test_a_plain_question_is_its_own_leaf() -> None:
    structure = BlueprintStructure.model_validate(
        {"questions": [{"question_id": "4", "max_marks": 5}], "total_marks": 5}
    )

    assert structure.scoreable_leaf_ids == ["4"]
    assert [leaf[0] for leaf in _leaf_questions(structure)] == ["4"]
