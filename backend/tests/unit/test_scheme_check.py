"""The approved scheme is a second, independent account of a marking decision.

These tests prove what the comparison reports and — as importantly — what it
does not: a scheme whose criteria state no comparable answer produces silence,
never a guessed verdict.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.correction.scheme_check import (
    CODE_MISSING_MARK_POINT,
    CODE_OVER_SCHEME_CAPACITY,
    CODE_UNKNOWN_CRITERION,
    CODE_UNMET_DEPENDENCY,
    SchemeMathCheck,
    check_against_scheme,
    check_answer_against_scheme,
    scheme_capacity,
    scheme_expected_expression,
    scheme_math_findings,
)


def _criterion(code: str, marks: int = 1, **overrides) -> SimpleNamespace:
    body = {
        "code": code,
        "marks": marks,
        "description": f"{code} mark point",
        "award_conditions": None,
        "dependencies": [],
    }
    body.update(overrides)
    return SimpleNamespace(**body)


def _part(code: str, awarded: bool = True) -> SimpleNamespace:
    return SimpleNamespace(code=code, awarded=awarded, marks=1)


def test_capacity_is_the_sum_of_the_schemes_marks() -> None:
    criteria = [_criterion("M1", 1), _criterion("M2", 2), _criterion("A1", 1)]

    assert scheme_capacity(criteria) == 4


def test_criterion_findings_are_possible_not_definite() -> None:
    """Notation the scheme does not use is worth a look, not proof of error."""

    findings = check_against_scheme(
        awarded=1,
        components=[_part("X9")],
        criteria=[_criterion("M1")],
    )

    assert findings
    assert all(finding.severity == "POSSIBLE_MISMATCH" for finding in findings)


def test_an_award_beyond_capacity_is_definite() -> None:
    findings = check_against_scheme(
        awarded=3, components=[], criteria=[_criterion("M1"), _criterion("A1")]
    )

    assert [finding.severity for finding in findings] == ["DEFINITE_MISMATCH"]


def test_an_award_beyond_an_incomplete_scheme_is_only_possible() -> None:
    """Fewer stored criteria than marks is an incomplete record, not a bad award."""

    findings = check_against_scheme(
        awarded=2,
        components=[_part("M1")],
        criteria=[_criterion("M1")],
        max_marks=2,
    )

    capacity = [f for f in findings if f.code == CODE_OVER_SCHEME_CAPACITY]
    assert capacity and capacity[0].severity == "POSSIBLE_MISMATCH"
    assert "incomplete" in capacity[0].message


def test_an_award_beyond_a_complete_scheme_stays_definite() -> None:
    findings = check_against_scheme(
        awarded=3,
        components=[],
        criteria=[_criterion("M1"), _criterion("A1")],
        max_marks=2,
    )

    capacity = [f for f in findings if f.code == CODE_OVER_SCHEME_CAPACITY]
    assert [finding.severity for finding in capacity] == ["DEFINITE_MISMATCH"]


def test_a_matching_reply_has_no_findings() -> None:
    findings = check_against_scheme(
        awarded=2,
        components=[_part("M1"), _part("A1")],
        criteria=[_criterion("M1"), _criterion("A1")],
    )

    assert findings == []


def test_no_scheme_detail_means_no_findings() -> None:
    """Silence is honest when there is nothing independent to compare."""

    assert check_against_scheme(awarded=2, components=[_part("M1")], criteria=[]) == []


def test_an_award_on_an_undefined_mark_point_is_reported() -> None:
    findings = check_against_scheme(
        awarded=1,
        components=[_part("X9")],
        criteria=[_criterion("M1"), _criterion("A1", awarded=False)],
    )

    codes = [finding.code for finding in findings]
    assert CODE_UNKNOWN_CRITERION in codes
    assert any("'X9'" in finding.message for finding in findings)


def test_an_undefined_mark_point_that_was_not_awarded_is_not_reported() -> None:
    findings = check_against_scheme(
        awarded=1,
        components=[_part("M1"), SimpleNamespace(code="X9", awarded=False, marks=1)],
        criteria=[_criterion("M1")],
    )

    assert all(finding.code != CODE_UNKNOWN_CRITERION for finding in findings)


def test_a_scheme_mark_point_the_reply_never_names_is_reported() -> None:
    findings = check_against_scheme(
        awarded=1,
        components=[_part("M1")],
        criteria=[_criterion("M1"), _criterion("A1")],
    )

    missing = [finding for finding in findings if finding.code == CODE_MISSING_MARK_POINT]
    assert missing
    assert "A1" in missing[0].message


def test_an_unnamed_mark_point_does_not_matter_when_the_full_award_was_made() -> None:
    """A reply cannot have withheld a point while awarding the scheme's capacity."""

    findings = check_against_scheme(
        awarded=2,
        components=[_part("M1")],
        criteria=[_criterion("M1"), _criterion("A1")],
    )

    assert findings == []


def test_an_award_beyond_the_schemes_capacity_is_reported() -> None:
    findings = check_against_scheme(
        awarded=3,
        components=[],
        criteria=[_criterion("M1"), _criterion("A1")],
    )

    assert [finding.code for finding in findings] == [CODE_OVER_SCHEME_CAPACITY]


def test_a_reply_may_qualify_a_mark_point_with_its_question() -> None:
    """The scheme says ``B1``; a reply saying ``1a_B1`` names the same point."""

    findings = check_against_scheme(
        awarded=1,
        components=[_part("1a_B1")],
        criteria=[_criterion("B1")],
        question_id="1a",
    )

    assert findings == []


def test_a_variant_code_resolves_to_its_base_mark_point() -> None:
    """``M1FT`` is the scheme's follow-through notation for ``M1``, not a new point."""

    findings = check_against_scheme(
        awarded=1,
        components=[_part("M1FT")],
        criteria=[_criterion("M1")],
        question_id="2",
    )

    assert findings == []


def test_a_qualified_code_the_scheme_lacks_is_still_reported() -> None:
    findings = check_against_scheme(
        awarded=1,
        components=[_part("1a_Z9")],
        criteria=[_criterion("B1")],
        question_id="1a",
    )

    assert CODE_UNKNOWN_CRITERION in [finding.code for finding in findings]


def test_a_dependent_mark_without_its_prerequisite_is_reported() -> None:
    findings = check_against_scheme(
        awarded=1,
        components=[_part("M1", awarded=False), _part("A1")],
        criteria=[_criterion("M1"), _criterion("A1", dependencies=["M1"])],
    )

    assert CODE_UNMET_DEPENDENCY in [finding.code for finding in findings]


def test_a_dependent_mark_with_its_prerequisite_is_accepted() -> None:
    findings = check_against_scheme(
        awarded=2,
        components=[_part("M1"), _part("A1")],
        criteria=[_criterion("M1"), _criterion("A1", dependencies=["M1"])],
    )

    assert findings == []


def test_a_stated_answer_in_the_scheme_is_read() -> None:
    criteria = [_criterion("A1", description="24 - 18y")]

    assert scheme_expected_expression(criteria) == ("24 - 18y", "A1")


def test_prose_descriptions_are_not_treated_as_expressions() -> None:
    criteria = [
        _criterion("M1", description="M1 for expanding the bracket"),
        _criterion("A1", description="oe"),
    ]

    assert scheme_expected_expression(criteria) is None


def test_two_different_stated_answers_are_ambiguous() -> None:
    criteria = [
        _criterion("A1", description="24 - 18y"),
        _criterion("A2", description="3x + 4"),
    ]

    assert scheme_expected_expression(criteria) is None


def test_an_equivalent_answer_is_proven_against_the_scheme() -> None:
    check = check_answer_against_scheme(
        student_expression="24-18y", criteria=[_criterion("A1", description="24 - 18y")]
    )

    assert check.status == "EQUIVALENT"
    assert check.expected_criterion == "A1"


def test_a_different_answer_is_detected() -> None:
    check = check_answer_against_scheme(
        student_expression="24 - 18x", criteria=[_criterion("A1", description="24 - 18y")]
    )

    assert check.status == "DIFFERENT"


def test_an_undecidable_answer_says_unknown_not_different() -> None:
    check = check_answer_against_scheme(
        student_expression="the answer is obvious", criteria=[_criterion("A1", description="4")]
    )

    assert check.status == "UNKNOWN"


def test_no_stated_answer_means_the_check_is_skipped() -> None:
    check = check_answer_against_scheme(
        student_expression="4", criteria=[_criterion("M1", description="M1 for method")]
    )

    assert check.status == "SKIPPED"


def test_a_different_answer_with_full_marks_requires_review() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(status="DIFFERENT", expected_expression="4"), awarded=2, max_marks=2
    )

    assert [finding.code for finding in findings] == ["SCHEME_ANSWER_DIFFERENT"]
    assert findings[0].severity == "DEFINITE_MISMATCH"


def test_a_different_answer_with_method_marks_only_is_not_a_mismatch() -> None:
    """Awarding method marks and withholding the accuracy mark is correct marking.

    The reply gave ``M1`` and withheld ``A1``; a wrong final answer is exactly what
    that award predicts, so there is nothing to review.
    """

    findings = scheme_math_findings(
        SchemeMathCheck(
            status="DIFFERENT", expected_expression="8x^3 - 28x^2 - 60x", expected_criterion="A1"
        ),
        awarded=1,
        max_marks=3,
        components=[_part("1a_M1")],
        criteria=[
            _criterion("M1", description="one factor pair expanded"),
            _criterion("A1", description="8x^3 - 28x^2 - 60x"),
        ],
        question_id="1a",
    )

    assert findings == []


def test_a_different_answer_with_the_accuracy_mark_awarded_is_definite() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(
            status="DIFFERENT", expected_expression="24x^3 - 28x^2 - 12x", expected_criterion="A1"
        ),
        awarded=2,
        max_marks=3,
        components=[_part("1a_M1"), _part("1a_M1_dep"), _part("1a_A1")],
        criteria=[
            _criterion("M1", description="two of three factors expanded"),
            _criterion("M1", description="dependent third-factor expansion"),
            _criterion("A1", description="24x^3 - 28x^2 - 12x"),
        ],
        question_id="1a",
    )

    assert [finding.code for finding in findings] == ["SCHEME_ANSWER_DIFFERENT"]
    assert findings[0].severity == "DEFINITE_MISMATCH"


def test_a_different_answer_with_no_marks_is_not_flagged() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(status="DIFFERENT", expected_expression="4"), awarded=0, max_marks=2
    )

    assert findings == []


def test_an_equivalent_answer_with_the_accuracy_mark_withheld_is_possible() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(
            status="EQUIVALENT", expected_expression="4n^3 + 8n^2 - 60n", expected_criterion="A1"
        ),
        awarded=1,
        max_marks=2,
        components=[_part("21_M1")],
        criteria=[
            _criterion("M1", description="correct partial expansion"),
            _criterion("A1", description="4n^3 + 8n^2 - 60n"),
        ],
        question_id="21",
    )

    assert [finding.code for finding in findings] == ["SCHEME_ANSWER_WITHHELD"]
    assert findings[0].severity == "POSSIBLE_MISMATCH"


def test_an_equivalent_answer_with_its_mark_awarded_is_clean() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(
            status="EQUIVALENT", expected_expression="4n^3 + 8n^2 - 60n", expected_criterion="A1"
        ),
        awarded=2,
        max_marks=2,
        components=[_part("21_M1"), _part("21_A1")],
        criteria=[
            _criterion("M1", description="correct partial expansion"),
            _criterion("A1", description="4n^3 + 8n^2 - 60n"),
        ],
        question_id="21",
    )

    assert findings == []


def test_an_unknown_comparison_never_produces_a_finding() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(status="UNKNOWN"), awarded=0, max_marks=2
    )

    assert findings == []
