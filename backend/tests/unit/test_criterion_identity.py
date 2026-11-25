"""A reply's component order must not decide which criterion is awarded.

The pilot scheme repeats codes: ``M1 M1 A1`` is a method mark, its follow-through
and the answer.  A reply names codes, not row numbers, so the engine has to decide
which printed row an award belongs to.  These tests pin that decision:

* it never depends on the order the reply lists its components in;
* a duplicate cannot earn a mark point twice;
* a bare repeated code credits the printed order (the earlier row), which is the
  only convention that cannot invent an award;
* a decorated follow-through (``M1FT``) is the one explicit identity and is
  pinned to the dependent row.

The data is the real pilot payload, so the tests exercise the scheme the pilot
will mark against rather than a synthetic one.
"""

from __future__ import annotations

import itertools
import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
from app.correction import scheme_check

BACKEND = pathlib.Path(__file__).resolve().parents[2]
PAYLOAD = BACKEND / "seed" / "pilot_scheme_v1_criteria.json"


def _criteria(question_id: str) -> list[SimpleNamespace]:
    document = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    for question in document["questions"]:
        if question["question_id"] == question_id:
            return [SimpleNamespace(**criterion) for criterion in question["criteria"]]
    raise AssertionError(f"question {question_id} is not in the payload")


def _component(code: str, marks: int = 1, awarded: bool = True) -> SimpleNamespace:
    return SimpleNamespace(code=code, marks=marks, awarded=awarded)


def _findings(question_id: str, components: list[Any], awarded: int) -> list[str]:
    return [
        finding.code
        for finding in scheme_check.check_against_scheme(
            awarded=awarded,
            components=components,
            criteria=_criteria(question_id),
            question_id=question_id,
            max_marks=None,
        )
    ]


def _credits(question_id: str, components: list[Any]) -> tuple[list[int], dict[str, int]]:
    criteria = _criteria(question_id)
    codes = [
        scheme_check._normalise_code(criterion.code, question_id) for criterion in criteria
    ]
    defined = codes + [
        scheme_check._normalise_code(alternative, question_id)
        for alternative in scheme_check.alternative_codes(criteria)
    ]
    credits, earned = scheme_check._awarded_criteria(
        criteria, codes, components, defined, question_id
    )
    return credits, dict(earned)


def test_repeated_method_marks_are_credited_identically_in_either_order() -> None:
    forward = [_component("M1"), _component("M1")]
    backward = list(reversed(forward))

    assert _credits("18", forward) == _credits("18", backward) == ([1, 1, 0], {"M1": 2})
    assert _findings("18", forward, 2) == _findings("18", backward, 2)


@pytest.mark.parametrize("order", list(itertools.permutations(["M1", "M1", "A1"])))
def test_every_order_of_a_full_award_is_the_same_award(order: tuple[str, ...]) -> None:
    """The six orderings of ``M1 M1 A1`` are one award, not six decisions."""

    components = [_component(code) for code in order]

    assert _credits("18", components) == ([1, 1, 1], {"M1": 2, "A1": 1})
    assert _findings("18", components, 3) == []


def test_the_follow_through_is_pinned_by_its_decoration_in_either_position() -> None:
    """``M1FT`` names the dependent row; where it appears in the list is irrelevant."""

    forward = [_component("M1"), _component("M1FT")]
    backward = list(reversed(forward))

    assert _credits("18", forward) == _credits("18", backward) == ([1, 1, 0], {"M1": 2})
    # The answer mark is still missing, but the decision about the method marks
    # is identical in both orders — including that the follow-through is earned.
    assert _findings("18", forward, 2) == _findings("18", backward, 2)
    assert "UNMET_DEPENDENCY" not in _findings("18", forward, 2)


def test_a_follow_through_named_alone_is_rejected_whichever_way_it_is_written() -> None:
    assert "UNMET_DEPENDENCY" in _findings("18", [_component("M1FT")], 1)
    # A bare single M1 is the first method mark, so it is not a follow-through.
    assert _credits("18", [_component("M1")])[0] == [1, 0, 0]


def test_a_missing_component_is_never_invented() -> None:
    """Only the first method mark was awarded; the follow-through row stays empty."""

    credits, earned = _credits("18", [_component("M1"), _component("A1")])

    assert credits == [1, 0, 1]
    assert earned == {"M1": 1, "A1": 1}


def test_a_duplicated_component_cannot_earn_a_mark_point_twice() -> None:
    """Three ``M1`` awards against a two-mark-point method is a contradiction."""

    codes = _findings("18", [_component("M1"), _component("M1"), _component("M1")], 3)

    assert codes == ["EXCESS_CRITERION_AWARD"]


def test_a_duplicated_award_beyond_capacity_is_reported_as_capacity() -> None:
    """A duplicate answer mark cannot hide behind an award that fits the maximum."""

    codes = _findings(
        "18",
        [_component("M1"), _component("M1"), _component("A1"), _component("A1")],
        4,
    )

    assert "OVER_SCHEME_CAPACITY" in codes


def test_an_unknown_code_is_reported_and_not_credited() -> None:
    assert "UNKNOWN_CRITERION" in _findings("18", [_component("Z9")], 1)
    assert _credits("18", [_component("Z9")])[0] == [0, 0, 0]


def test_a_code_carried_by_the_question_it_belongs_to_resolves() -> None:
    """``18_M1`` is the same mark point as ``M1`` for question 18."""

    assert _findings("18", [_component("18_M1"), _component("18_M1"), _component("18_A1")], 3) == []


def test_an_alternative_route_resolves_the_same_way_in_any_position() -> None:
    forward = [_component("M2", 2), _component("A1")]
    backward = list(reversed(forward))

    assert _findings("34", forward, 3) == _findings("34", backward, 3) == []
    assert _findings("34", [_component("A1"), _component("M2", 2)], 3) == []


def test_a_repeated_alternative_route_cannot_earn_its_marks_twice() -> None:
    """Two copies of the same route are a capacity contradiction, not two routes."""

    codes = _findings("34", [_component("M2", 2), _component("M2", 2)], 4)

    assert "OVER_SCHEME_CAPACITY" in codes


def test_the_pilot_repeats_codes_where_the_tests_say_it_does() -> None:
    """Guard the premise: a payload edit that removed the repetition must fail here."""

    for question_id in ("13", "18", "34", "36", "37a"):
        codes = [criterion.code for criterion in _criteria(question_id)]
        assert codes.count("M1") >= 2, question_id


# -- ambiguity ----------------------------------------------------------
#
# The resolver is deterministic for a repeated code, but determinism is not the
# same as knowing which printed point was earned.  These tests pin the difference:
# an award the engine cannot attribute is reported, not silently assigned.


def _component_evidence(code: str, marks: int, evidence: str) -> SimpleNamespace:
    return SimpleNamespace(
        code=code, marks=marks, awarded=True, evidence=evidence
    )


@pytest.mark.parametrize("question_id", ["6", "11", "13", "28", "37b"])
def test_one_award_of_an_independently_shared_code_is_an_ambiguity(
    question_id: str,
) -> None:
    """These questions print two independent points under one code.

    A single award names neither of them, so the engine reports the ambiguity
    instead of presenting the printed order as if it were the answer.
    """

    findings = _findings(question_id, [_component("M1")], 1)

    assert "AMBIGUOUS_CRITERION_CODE" in findings


@pytest.mark.parametrize("question_id", ["6", "11", "13", "28", "37b"])
def test_two_awards_of_a_shared_code_are_not_ambiguous(question_id: str) -> None:
    """One award per printed point is exactly what the scheme asks for."""

    findings = _findings(question_id, [_component("M1"), _component("M1")], 2)

    assert "AMBIGUOUS_CRITERION_CODE" not in findings


@pytest.mark.parametrize("question_id", ["6", "11", "13", "28"])
def test_engine_disambiguated_duplicate_awards_are_not_ambiguous(
    question_id: str,
) -> None:
    """Both printed points awarded is not ambiguous, suffix or no suffix.

    ``_disambiguate_component_codes`` renames the second award of a repeated code
    (``M1`` -> ``M1-2``) so a real reply survives validation.  Attribution must read
    that suffix off: treating ``M1-2`` as a different code made a fully awarded
    pair look like one award against an ambiguous code, and the pilot's first
    whole-paper reply was sent to a person for a reason it had already answered.
    """

    findings = _findings(question_id, [_component("M1"), _component("M1-2")], 2)

    assert "AMBIGUOUS_CRITERION_CODE" not in findings


def test_a_lone_disambiguated_award_is_still_ambiguous() -> None:
    """Stripping the suffix must not excuse a genuine single award."""

    assert "AMBIGUOUS_CRITERION_CODE" in _findings("13", [_component("M1-2")], 1)


def test_quoted_evidence_does_not_resolve_the_ambiguity() -> None:
    """The verifier cannot tell which point a quoted fragment belongs to."""

    findings = _findings(
        "13",
        [
            _component_evidence("M1", 1, "first pair expanded"),
            SimpleNamespace(code="M1", marks=1, awarded=False, evidence=""),
        ],
        2,
    )

    assert "AMBIGUOUS_CRITERION_CODE" in findings


def test_two_awarded_components_with_different_evidence_are_not_ambiguous() -> None:
    findings = _findings(
        "13",
        [
            _component_evidence("M1", 1, "first pair expanded"),
            _component_evidence("M1", 1, "second pair expanded"),
        ],
        2,
    )

    assert "AMBIGUOUS_CRITERION_CODE" not in findings


def test_a_follow_through_pair_is_determinate_not_ambiguous() -> None:
    """Q18's second M1 cannot be earned without the first, so one award is the first.

    This is the case where deterministic resolution and correct resolution agree,
    which is why it must not be reported as ambiguous.
    """

    assert "AMBIGUOUS_CRITERION_CODE" not in _findings(
        "18", [_component("M1"), _component("A1")], 2
    )


def test_a_decorated_award_is_an_explicit_identity_not_an_ambiguity() -> None:
    assert "AMBIGUOUS_CRITERION_CODE" not in _findings("18", [_component("M1FT")], 1)


def test_one_component_claiming_every_shared_point_is_not_ambiguous() -> None:
    """A single award worth both marks credits both printed points."""

    credits, _earned = _credits("6", [_component("M1", 2)])
    findings = _findings("6", [_component("M1", 2)], 2)

    assert credits[:2] == [1, 1]
    assert "AMBIGUOUS_CRITERION_CODE" not in findings
