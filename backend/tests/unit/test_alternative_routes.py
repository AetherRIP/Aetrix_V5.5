"""Alternative routes replace specific criteria, and a mixed award is refused.

The pilot prints routes for Q34 (one-stage ``M2``), Q36 (``M2`` and a no-working
``B2``) and Q37a (``B2``).  A route is worth marks the schedule does not carry twice,
so an award that earns the route *and* the criteria it replaces is a contradiction
even when its total happens to equal the question's maximum.  These tests cover the
combinations, not just each route on its own:

* the valid route plus the marks it does not replace;
* every over-award combination that was previously invisible;
* two routes at once;
* the approved data itself: every route must name what it replaces.
"""

from __future__ import annotations

import copy
import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
from app.correction import scheme_check
from app.correction.scheme_criteria import validate

BACKEND = pathlib.Path(__file__).resolve().parents[2]
PAYLOAD = BACKEND / "seed" / "pilot_scheme_v1_criteria.json"


def _payload() -> dict:
    return json.loads(PAYLOAD.read_text(encoding="utf-8"))


def _criteria(question_id: str) -> list[SimpleNamespace]:
    for question in _payload()["questions"]:
        if question["question_id"] == question_id:
            return [SimpleNamespace(**criterion) for criterion in question["criteria"]]
    raise AssertionError(f"question {question_id} is not in the payload")


def _component(code: str, marks: int = 1) -> SimpleNamespace:
    return SimpleNamespace(code=code, marks=marks, awarded=True)


def _codes(question_id: str, components: list[Any], awarded: int) -> list[str]:
    return [
        finding.code
        for finding in scheme_check.check_against_scheme(
            awarded=awarded,
            components=components,
            criteria=_criteria(question_id),
            question_id=question_id,
            max_marks=3,
        )
    ]


# -- the valid routes ------------------------------------------------------


def test_q34_one_stage_route_plus_accuracy_is_valid() -> None:
    assert _codes("34", [_component("M2", 2), _component("A1")], 3) == []


def test_q34_printed_two_stage_route_is_valid() -> None:
    assert _codes("34", [_component("M1"), _component("M1"), _component("A1")], 3) == []


def test_q36_expansion_route_plus_accuracy_is_valid() -> None:
    assert _codes("36", [_component("M2", 2), _component("A1")], 3) == []


def test_q36_no_working_route_stands_alone() -> None:
    assert _codes("36", [_component("B2", 2)], 2) == []


def test_q37a_no_working_route_stands_alone() -> None:
    assert _codes("37a", [_component("B2", 2)], 2) == []


def test_q37a_printed_route_is_valid() -> None:
    assert _codes("37a", [_component("M1"), _component("M1"), _component("A1")], 3) == []


# -- the invalid combinations ---------------------------------------------


@pytest.mark.parametrize(
    ("question_id", "components", "awarded"),
    [
        # A two-mark route plus a method mark totals the three marks exactly, so
        # a capacity check alone cannot see that one method was counted twice.
        ("34", [("M2", 2), ("M1", 1)], 3),
        ("36", [("M2", 2), ("M1", 1)], 3),
        # The no-working route excludes the method marks and the answer mark.
        ("36", [("B2", 2), ("A1", 1)], 3),
        ("36", [("B2", 2), ("M1", 1)], 3),
        ("37a", [("B2", 2), ("A1", 1)], 3),
        ("37a", [("B2", 2), ("M1", 1)], 3),
        # Both routes of one question cannot be earned for the same work.
        ("36", [("M2", 2), ("B2", 2)], 4),
    ],
)
def test_a_mixed_award_is_a_route_conflict(
    question_id: str, components: list[tuple[str, int]], awarded: int
) -> None:
    findings = _codes(
        question_id,
        [_component(code, marks) for code, marks in components],
        awarded,
    )

    assert "ROUTE_CONFLICT" in findings


@pytest.mark.parametrize(
    ("question_id", "components", "awarded"),
    [
        ("34", [("M2", 2), ("M1", 1), ("A1", 1)], 4),
        ("34", [("M2", 2), ("M1", 1), ("M1", 1)], 4),
        ("36", [("B2", 2), ("M1", 1), ("M1", 1), ("A1", 1)], 5),
        ("37a", [("B2", 2), ("M1", 1), ("M1", 1), ("A1", 1)], 5),
    ],
)
def test_no_combination_exceeds_the_question_maximum(
    question_id: str, components: list[tuple[str, int]], awarded: int
) -> None:
    findings = _codes(
        question_id,
        [_component(code, marks) for code, marks in components],
        awarded,
    )

    assert "OVER_SCHEME_CAPACITY" in findings
    assert "ROUTE_CONFLICT" in findings


def test_a_route_conflict_is_not_reported_when_only_the_route_is_awarded() -> None:
    """The conflict check must not fire on the route's own code."""

    assert "ROUTE_CONFLICT" not in _codes("36", [_component("B2", 2)], 2)


def test_the_route_scope_covers_every_row_of_a_repeated_code() -> None:
    """``replaces: ["M1"]`` means every printed ``M1`` of that question."""

    routes = scheme_check.alternative_routes(_criteria("34"), "34")

    assert routes["M2"].replaces == ("M1",)
    assert routes["M2"].excluded == {"M1"}


def test_the_no_working_route_excludes_the_answer_mark_too() -> None:
    routes = scheme_check.alternative_routes(_criteria("36"), "36")

    assert routes["B2"].excluded == {"M1", "A1"}


# -- the approved data -----------------------------------------------------


def _question(document: dict, question_id: str) -> dict:
    for question in document["questions"]:
        if question["question_id"] == question_id:
            return question
    raise AssertionError(question_id)


def _alternative(document: dict, question_id: str, host: str, code: str) -> dict:
    for criterion in _question(document, question_id)["criteria"]:
        if criterion["code"] != host:
            continue
        for alternative in criterion.get("alternatives") or []:
            if alternative.get("code") == code:
                return alternative
    raise AssertionError(f"{question_id}/{host}/{code}")


def _structure(document: dict) -> dict:
    return {
        "questions": [
            {
                "question_id": question["question_id"],
                "max_marks": question["max_marks"],
                "excluded": False,
                "subquestions": [],
            }
            for question in document["questions"]
        ],
        "total_marks": sum(question["max_marks"] for question in document["questions"]),
    }


def test_every_route_in_the_approved_payload_names_what_it_replaces() -> None:
    document = _payload()
    report = validate(document, _structure(document))

    assert report.complete, report.problems
    for question in document["questions"]:
        for criterion in question["criteria"]:
            for alternative in criterion.get("alternatives") or []:
                if alternative.get("code"):
                    assert alternative.get("replaces"), (
                        question["question_id"],
                        criterion["code"],
                        alternative["code"],
                    )


def test_a_route_without_a_replacement_scope_is_refused() -> None:
    document = _payload()
    del _alternative(document, "34", "M1", "M2")["replaces"]

    report = validate(document, _structure(document))

    assert not report.complete
    assert any("names no criteria it replaces" in problem for problem in report.problems)


def test_a_route_that_does_not_replace_its_own_mark_point_is_refused() -> None:
    document = _payload()
    _alternative(document, "36", "A1", "B2")["replaces"] = ["M1"]

    report = validate(document, _structure(document))

    assert not report.complete
    assert any("does not replace it" in problem for problem in report.problems)


def test_a_route_that_replaces_an_undefined_code_is_refused() -> None:
    document = _payload()
    _alternative(document, "34", "M1", "M2")["replaces"] = ["M1", "Z9"]

    report = validate(document, _structure(document))

    assert not report.complete
    assert any("Z9" in problem for problem in report.problems)


def test_a_route_that_leaves_its_prerequisite_active_is_refused() -> None:
    """A route on a dependent point must replace the point it follows through from."""

    document = _payload()
    question = _question(document, "18")
    # The prerequisite keeps its own code, so replacing only the host's code no
    # longer covers it.
    question["criteria"][0]["code"] = "M2"
    dependent = question["criteria"][1]
    dependent["dependencies"] = ["M2"]
    dependent["alternatives"][0]["replaces"] = ["M1"]

    report = validate(document, _structure(document))

    assert not report.complete
    assert any("leaves 'M2' active" in problem for problem in report.problems)


def test_a_route_carrying_more_marks_than_it_replaces_is_refused() -> None:
    document = _payload()
    _alternative(document, "34", "M1", "M2")["marks"] = 3

    report = validate(document, _structure(document))

    assert not report.complete
    assert any("carries 3 mark(s) but replaces" in problem for problem in report.problems)


def test_a_duplicated_route_code_is_refused() -> None:
    document = _payload()
    dependent = _question(document, "34")["criteria"][1]
    dependent["alternatives"].append(
        {"code": "M2", "marks": 2, "rule": "a second M2", "replaces": ["M1"]}
    )

    report = validate(document, copy.deepcopy(_structure(document)))

    assert not report.complete
    assert any("defines alternative route M2 more than once" in p for p in report.problems)
