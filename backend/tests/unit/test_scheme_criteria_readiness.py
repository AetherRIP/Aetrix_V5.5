"""Imported criteria are inert until approved against the blueprint being marked.

The pipeline can only mark a question against criteria it holds.  These tests pin
the four conditions that make those rows usable — imported, approved, reviewed
against the same blueprint, covering every leaf — and the reason a refusal names.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.correction.scheme_criteria import (
    REASON_CRITERIA_BLUEPRINT_MISMATCH,
    REASON_CRITERIA_INCOMPLETE,
    REASON_CRITERIA_MISSING,
    REASON_CRITERIA_NOT_APPROVED,
    REASON_CRITERIA_RULES_CHANGED,
    REASON_CRITERIA_RULES_UNVERIFIED,
    criteria_readiness,
    criteria_rules_hash,
)

BLUEPRINT = uuid.UUID(int=1)
OTHER_BLUEPRINT = uuid.UUID(int=2)
APPROVED_AT = datetime(2026, 11, 17, tzinfo=UTC)

#: Three leaves and four marks: 1a (1), 1b (2), 2 (1).
STRUCTURE = {
    "questions": [
        {
            "question_id": "1",
            "max_marks": 3,
            "subquestions": [
                {"question_id": "1a", "max_marks": 1},
                {"question_id": "1b", "max_marks": 2},
            ],
        },
        {"question_id": "2", "max_marks": 1, "subquestions": []},
    ]
}


def _rows() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(question_id="1a", code="B1", marks=1),
        SimpleNamespace(question_id="1b", code="M1", marks=1),
        SimpleNamespace(question_id="1b", code="A1", marks=1),
        SimpleNamespace(question_id="2", code="B1", marks=1),
    ]


def _readiness(
    rows,
    *,
    approved_at=APPROVED_AT,
    approved_against=BLUEPRINT,
    blueprint_version_id=BLUEPRINT,
    approved_rules_hash="computed",
):
    recorded = (
        criteria_rules_hash(rows, STRUCTURE)
        if approved_rules_hash == "computed"
        else approved_rules_hash
    )
    return criteria_readiness(
        rows,
        STRUCTURE,
        blueprint_version_id=blueprint_version_id,
        approved_against=approved_against,
        approved_at=approved_at,
        approved_rules_hash=recorded,
    )


def test_complete_approved_criteria_are_ready_and_carry_the_paper_marks() -> None:
    readiness = _readiness(_rows())

    assert readiness.ready
    assert readiness.reason is None
    assert readiness.problems == ()
    assert readiness.questions == 3
    assert readiness.total_marks == 4


def test_no_imported_rows_are_not_ready() -> None:
    readiness = _readiness([])

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_MISSING
    assert "no mark-scheme criteria" in readiness.problems[0]


def test_unapproved_criteria_are_not_ready() -> None:
    readiness = _readiness(_rows(), approved_at=None)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_NOT_APPROVED
    assert any("criteria_approved_at" in problem for problem in readiness.problems)


def test_criteria_reviewed_against_another_blueprint_are_not_ready() -> None:
    readiness = _readiness(_rows(), approved_against=OTHER_BLUEPRINT)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_BLUEPRINT_MISMATCH
    assert any(str(OTHER_BLUEPRINT) in problem for problem in readiness.problems)


def test_criteria_that_name_no_blueprint_are_not_ready() -> None:
    readiness = _readiness(_rows(), approved_against=None)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_BLUEPRINT_MISMATCH


def test_a_question_with_no_criteria_is_not_ready() -> None:
    readiness = _readiness([row for row in _rows() if row.question_id != "2"])

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_INCOMPLETE
    assert any("'2' has no criteria" in problem for problem in readiness.problems)


def test_criteria_that_carry_the_wrong_number_of_marks_are_not_ready() -> None:
    rows = _rows()
    rows[1].marks = 2  # 1b now carries 3 marks for a 2-mark question

    readiness = _readiness(rows)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_INCOMPLETE
    assert any("'1b'" in problem and "3" in problem for problem in readiness.problems)


def test_a_criterion_for_a_non_leaf_question_is_not_ready() -> None:
    """The parent question ``1`` is never marked, so criteria for it are a mistake."""

    rows = _rows()
    rows.append(SimpleNamespace(question_id="1", code="B1", marks=3))

    readiness = _readiness(rows)

    assert not readiness.ready
    assert any("not a scoreable leaf" in problem for problem in readiness.problems)


def test_an_approval_that_records_no_rules_is_not_ready() -> None:
    """Without a digest the approval cannot show that these are the rules reviewed."""

    readiness = _readiness(_rows(), approved_rules_hash=None)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_RULES_UNVERIFIED
    assert any("records no digest" in problem for problem in readiness.problems)


def test_rules_changed_after_approval_are_not_ready() -> None:
    """A tolerance edited after review invalidates the approval, not just the row."""

    approved = _rows()
    recorded = criteria_rules_hash(approved, STRUCTURE)
    approved[0].description = "B1 for a different tolerance"

    readiness = _readiness(approved, approved_rules_hash=recorded)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_RULES_CHANGED
    assert any("changed after they were approved" in p for p in readiness.problems)


def test_a_changed_dependency_invalidates_the_approval() -> None:
    rows = _rows()
    recorded = criteria_rules_hash(rows, STRUCTURE)
    rows[1].dependencies = ["M1"]

    readiness = _readiness(rows, approved_rules_hash=recorded)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_RULES_CHANGED


def test_a_changed_alternative_route_invalidates_the_approval() -> None:
    rows = _rows()
    recorded = criteria_rules_hash(rows, STRUCTURE)
    rows[2].alternatives = [
        {"code": "B2", "marks": 2, "rule": "3 out of 4 terms correct"}
    ]

    readiness = _readiness(rows, approved_rules_hash=recorded)

    assert not readiness.ready
    assert readiness.reason == REASON_CRITERIA_RULES_CHANGED


def test_the_rules_digest_does_not_depend_on_row_order() -> None:
    """A re-imported row set is the same approval if the rules are the same."""

    rows = _rows()

    assert criteria_rules_hash(rows, STRUCTURE) == criteria_rules_hash(
        list(reversed(rows)), STRUCTURE
    )


def test_the_rules_digest_covers_the_blueprint_they_mark() -> None:
    """The same rules against a differently marked paper are a different approval."""

    other_structure = {
        "questions": [
            {
                "question_id": "1",
                "max_marks": 3,
                "subquestions": [
                    {"question_id": "1a", "max_marks": 2},
                    {"question_id": "1b", "max_marks": 1},
                ],
            },
            {"question_id": "2", "max_marks": 1, "subquestions": []},
        ]
    }

    assert criteria_rules_hash(_rows(), STRUCTURE) != criteria_rules_hash(
        _rows(), other_structure
    )
