"""The approved scheme is a second, independent account of a marking decision.

These tests prove what the comparison reports and — as importantly — what it
does not: a scheme whose criteria state no comparable answer produces silence,
never a guessed verdict.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.correction.scheme_check import (
    CODE_ANSWER_NOT_CAO,
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


def _part(code: str, awarded: bool = True, marks: int = 1) -> SimpleNamespace:
    return SimpleNamespace(code=code, awarded=awarded, marks=marks)


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


def test_an_unattempted_question_is_a_confirmed_zero() -> None:
    """A reply that awarded nothing has withheld nothing to review."""

    findings = check_against_scheme(
        awarded=0,
        components=[_part("A1", awarded=False)],
        criteria=[_criterion("M1"), _criterion("A1")],
        max_marks=2,
    )

    assert findings == []


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


# -- "depends on M1" when both marks are printed as M1 -------------------------
def _two_method_marks(dependencies: list[str]) -> list[SimpleNamespace]:
    return [
        _criterion("M1"),
        _criterion("M1", dependencies=dependencies),
        _criterion("A1"),
    ]


def test_a_dependent_point_sharing_its_code_needs_a_second_award() -> None:
    """The pilot prints two ``M1`` points; the second is the follow-through.

    A reply that awarded only the first ``M1`` left the follow-through unwon, so
    there is no dependent award to judge; a reply that awarded both is clean.
    """

    criteria = _two_method_marks(["M1"])

    first_only = check_against_scheme(
        awarded=2,
        components=[_part("M1"), _part("A1")],
        criteria=criteria,
        question_id="18",
    )
    both = check_against_scheme(
        awarded=3,
        components=[_part("M1"), _part("M1"), _part("A1")],
        criteria=criteria,
        question_id="18",
    )

    assert CODE_UNMET_DEPENDENCY not in [finding.code for finding in first_only]
    assert both == []


def test_a_follow_through_award_without_the_mark_it_follows_is_reported() -> None:
    """``M1FT`` names the dependent point itself, so its prerequisite is checked."""

    criteria = _two_method_marks(["M1"])

    alone = check_against_scheme(
        awarded=1,
        components=[_part("M1FT")],
        criteria=criteria,
        question_id="18",
    )
    completed = check_against_scheme(
        awarded=2,
        components=[_part("M1"), _part("M1FT")],
        criteria=criteria,
        question_id="18",
    )

    unmet = [finding for finding in alone if finding.code == CODE_UNMET_DEPENDENCY]
    assert len(unmet) == 1
    assert unmet[0].definite
    assert CODE_UNMET_DEPENDENCY not in [finding.code for finding in completed]


def test_no_award_at_all_leaves_every_dependent_point_unjudged() -> None:
    """Nothing was awarded, so no dependent point was won without its marks."""

    findings = check_against_scheme(
        awarded=0,
        components=[
            _part("M1", awarded=False),
            _part("M1", awarded=False),
            _part("A1", awarded=False),
        ],
        criteria=_two_method_marks(["M1"]),
        question_id="18",
    )

    assert findings == []


def test_two_marks_recorded_on_one_component_are_two_awards() -> None:
    """One line of evidence can carry both method marks; it is not one award."""

    findings = check_against_scheme(
        awarded=3,
        components=[_part("M1", marks=2), _part("A1")],
        criteria=_two_method_marks(["M1"]),
        question_id="18",
    )

    assert findings == []


def test_a_dependent_mark_without_any_named_component_is_not_judged() -> None:
    """Silence about evidence is not evidence of a missing prerequisite."""

    findings = check_against_scheme(
        awarded=2,
        components=[],
        criteria=_two_method_marks(["M1"]),
        question_id="18",
    )

    assert findings == []


# -- a documented M2/B2 alternative route --------------------------------------
def _alternative_scheme() -> list[SimpleNamespace]:
    return [
        _criterion("M1"),
        _criterion(
            "M1",
            alternatives=[
                {"code": "M2", "marks": 2, "rule": "complete expansion, four of eight correct"}
            ],
        ),
        _criterion("A1"),
    ]


def test_a_documented_alternative_is_not_an_unknown_mark_point() -> None:
    findings = check_against_scheme(
        awarded=3,
        components=[_part("M2", marks=2), _part("A1")],
        criteria=_alternative_scheme(),
        question_id="18",
        max_marks=3,
    )

    assert findings == []


def test_a_documented_alternative_does_not_raise_the_capacity() -> None:
    """The alternative replaces marks already printed; it never adds another."""

    criteria = _alternative_scheme()

    assert scheme_capacity(criteria) == 3
    findings = check_against_scheme(
        awarded=4, components=[], criteria=criteria, max_marks=3
    )
    assert [finding.code for finding in findings] == [CODE_OVER_SCHEME_CAPACITY]


def test_using_an_alternative_route_is_not_ignoring_the_primary_points() -> None:
    """A reply that took ``M2`` did not omit the two ``M1`` points it replaces."""

    findings = check_against_scheme(
        awarded=2,
        components=[_part("M2", marks=2)],
        criteria=_alternative_scheme(),
        question_id="18",
        max_marks=3,
    )

    assert all(finding.code != CODE_MISSING_MARK_POINT for finding in findings)


# -- an accuracy mark the scheme prints as "cao" ---------------------------------
def _cao_scheme(award_conditions: str = "cao") -> list[SimpleNamespace]:
    return [
        _criterion("M1", description="two brackets multiplied with 3 of 4 terms correct"),
        _criterion("A1", description="y^2 + 8y - 20", award_conditions=award_conditions),
    ]


def test_the_printed_answer_and_an_equal_answer_are_told_apart() -> None:
    """``cao`` needs the printed form; equality alone is not enough."""

    printed = check_answer_against_scheme(
        student_expression="y^2 + 8y - 20", criteria=_cao_scheme()
    )
    reordered = check_answer_against_scheme(
        student_expression="8y + y^2 - 20", criteria=_cao_scheme()
    )
    factorised = check_answer_against_scheme(
        student_expression="(y + 10)(y - 2)", criteria=_cao_scheme()
    )

    assert printed.status == "EQUIVALENT"
    assert printed.correct_answer_only
    assert printed.printed_form
    assert reordered.printed_form  # the same answer, written in another order
    assert factorised.status == "EQUIVALENT"
    assert not factorised.printed_form  # equal, but not the form the scheme prints


def test_a_mark_without_cao_is_not_held_to_the_printed_form() -> None:
    check = check_answer_against_scheme(
        student_expression="(y + 10)(y - 2)", criteria=_cao_scheme(award_conditions=None)
    )

    assert not check.correct_answer_only


def test_awarding_a_cao_mark_for_another_form_is_definite() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(
            status="EQUIVALENT",
            expected_expression="y^2 + 8y - 20",
            expected_criterion="A1",
            student_expression="(y + 10)(y - 2)",
            correct_answer_only=True,
            printed_form=False,
        ),
        awarded=2,
        max_marks=2,
        components=[_part("M1"), _part("A1")],
        criteria=_cao_scheme(),
        question_id="1d",
    )

    assert [finding.code for finding in findings] == [CODE_ANSWER_NOT_CAO]
    assert findings[0].severity == "DEFINITE_MISMATCH"
    assert "cao" in findings[0].message


def test_withholding_a_cao_mark_for_another_form_is_correct_marking() -> None:
    """``cao`` is why the accuracy mark is withheld; that is not a mismatch."""

    findings = scheme_math_findings(
        SchemeMathCheck(
            status="EQUIVALENT",
            expected_expression="y^2 + 8y - 20",
            expected_criterion="A1",
            student_expression="(y + 10)(y - 2)",
            correct_answer_only=True,
            printed_form=False,
        ),
        awarded=1,
        max_marks=2,
        components=[_part("M1"), _part("A1", awarded=False)],
        criteria=_cao_scheme(),
        question_id="1d",
    )

    assert findings == []


def test_a_cao_mark_that_also_prints_an_allowance_is_only_possible() -> None:
    """The scheme's own cell admits another form, so a person weighs the award."""

    criteria = _cao_scheme(award_conditions="cao; Allow 2(5x + 11)")
    findings = scheme_math_findings(
        SchemeMathCheck(
            status="EQUIVALENT",
            expected_expression="10x + 22",
            expected_criterion="A1",
            student_expression="2(5x + 11)",
            correct_answer_only=True,
            printed_form=False,
        ),
        awarded=2,
        max_marks=2,
        components=[_part("M1"), _part("A1")],
        criteria=criteria,
        question_id="9",
    )

    assert [finding.code for finding in findings] == [CODE_ANSWER_NOT_CAO]
    assert findings[0].severity == "POSSIBLE_MISMATCH"


# -- brackets that only group a term versus brackets that multiply ---------------
def test_harmless_surrounding_brackets_are_the_printed_form() -> None:
    """A bracket around the whole answer is padding, not another form."""

    padded = check_answer_against_scheme(
        student_expression="(y^2 + 8y - 20)", criteria=_cao_scheme()
    )

    assert padded.status == "EQUIVALENT"
    assert padded.correct_answer_only
    assert padded.printed_form


def test_harmless_surrounding_brackets_are_the_printed_form_for_a_linear_answer() -> None:
    criteria = [_criterion("A1", description="11p + 6", award_conditions="cao")]

    padded = check_answer_against_scheme(
        student_expression="(11p + 6)", criteria=criteria
    )

    assert padded.status == "EQUIVALENT"
    assert padded.printed_form


def test_a_plus_sign_before_a_grouped_term_is_padding_too() -> None:
    """``y^2 + 8y + (-20)`` groups one term; it is not a product."""

    padded = check_answer_against_scheme(
        student_expression="y^2 + 8y + (-20)", criteria=_cao_scheme()
    )

    assert padded.status == "EQUIVALENT"
    assert padded.printed_form


def test_a_single_term_after_a_minus_is_padding_too() -> None:
    """``y^2 + 8y - (20)`` negates one term; the brackets are harmless."""

    padded = check_answer_against_scheme(
        student_expression="y^2 + 8y - (20)", criteria=_cao_scheme()
    )

    assert padded.status == "EQUIVALENT"
    assert padded.correct_answer_only
    assert padded.printed_form


def test_a_bracket_after_a_minus_that_holds_a_sum_is_not_padding() -> None:
    """Removing that bracket would change the expression, so it is left alone."""

    check = check_answer_against_scheme(
        student_expression="y^2 + 8y - (20 - 0 + 0)", criteria=_cao_scheme()
    )

    assert check.status == "EQUIVALENT"
    assert not check.printed_form


def test_a_factor_multiplying_a_bracket_is_not_the_printed_form() -> None:
    """``2(5x + 11)`` is equal to ``10x + 22``; only the expanded form is printed."""

    criteria = [_criterion("A1", description="10x + 22")]
    factored = check_answer_against_scheme(
        student_expression="2(5x + 11)", criteria=criteria
    )

    assert factored.status == "EQUIVALENT"
    assert not factored.printed_form


def test_padding_brackets_do_not_hide_an_unexpanded_product() -> None:
    """A product in brackets is still another form, whatever surrounds it."""

    padded = check_answer_against_scheme(
        student_expression="((y + 10)(y - 2))", criteria=_cao_scheme()
    )

    assert padded.status == "EQUIVALENT"
    assert not padded.printed_form


def test_awarding_cao_for_the_padded_printed_form_is_not_a_mismatch() -> None:
    findings = scheme_math_findings(
        SchemeMathCheck(
            status="EQUIVALENT",
            expected_expression="y^2 + 8y - 20",
            expected_criterion="A1",
            student_expression="(y^2 + 8y - 20)",
            correct_answer_only=True,
            printed_form=True,
        ),
        awarded=2,
        max_marks=2,
        components=[_part("M1"), _part("A1")],
        criteria=_cao_scheme(),
        question_id="1d",
    )

    assert findings == []


def test_a_genuinely_different_form_still_needs_the_printed_one() -> None:
    """A factorised structure still contradicts ``cao``, padding or not."""

    check = check_answer_against_scheme(
        student_expression="(y - 2)(y + 10)", criteria=_cao_scheme()
    )

    assert check.status == "EQUIVALENT"
    assert not check.printed_form

    findings = scheme_math_findings(
        check,
        awarded=2,
        max_marks=2,
        components=[_part("M1"), _part("A1")],
        criteria=_cao_scheme(),
        question_id="1d",
    )

    assert [finding.code for finding in findings] == [CODE_ANSWER_NOT_CAO]
    assert findings[0].definite
