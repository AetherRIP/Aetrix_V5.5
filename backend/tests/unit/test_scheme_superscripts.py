"""A printed scheme's lost superscript must not become a wrong answer.

The pilot's criteria were transcribed from printed pages, where ``12x³`` arrives
as ``12x3``.  Read literally that is twelve times a symbol called ``x3``, so a
correct script looked different from the scheme on every cubic question — and a
withheld accuracy mark for a provably equivalent answer is exactly the
under-award the scheme layer exists to notice.

The repair reads the artefact on the *scheme* side only, and only where it can
prove equivalence.  These tests pin both halves: the equivalence it recovers and
the difference it must keep reporting.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.correction.aetrix.verification import (
    equivalent,
    equivalent_to_scheme,
    restore_printed_superscripts,
)
from app.correction.scheme_check import (
    CODE_ANSWER_DIFFERENT,
    CODE_ANSWER_WITHHELD,
    answer_is_printed_form,
    check_answer_against_scheme,
    scheme_expected_expression,
    scheme_math_findings,
)


def _criterion(code: str, description: str, marks: int = 1, **overrides) -> SimpleNamespace:
    body = {
        "code": code,
        "marks": marks,
        "description": description,
        "award_conditions": None,
        "dependencies": [],
    }
    body.update(overrides)
    return SimpleNamespace(**body)


def _part(code: str, awarded: bool, marks: int = 1) -> SimpleNamespace:
    return SimpleNamespace(code=code, awarded=awarded, marks=marks)


# -- the artefact -----------------------------------------------------------
def test_a_lost_superscript_is_restored_where_a_letter_precedes_digits() -> None:
    assert restore_printed_superscripts("12x3 - 60x2 + 75x") == "12x^3 - 60x^2 + 75x"
    assert restore_printed_superscripts("a3b2") == "a^3b^2"


def test_an_expression_without_the_artefact_is_unchanged() -> None:
    for expression in ("24 - 18y", "8y - 2", "2x^3 - 7x^2", "3(x + 1)"):
        assert restore_printed_superscripts(expression) == expression


# -- what the repair recovers ----------------------------------------------
def test_a_correct_answer_matches_a_flattened_scheme_answer() -> None:
    """The four pilot answers whose superscripts were lost in transcription."""

    cases = [
        ("12x^3 - 60x^2 + 75x", "12x3 - 60x2 + 75x"),
        ("2x^3 - 7x^2 - 43x - 42", "2x3 - 7x2 - 43x - 42"),
        ("-3x^3 - 7x^2 + 22x + 8", "-3x3 - 7x2 + 22x + 8"),
        ("a^3b^2", "a3b2"),
    ]

    for student, expected in cases:
        assert equivalent_to_scheme(student, expected) is True, (student, expected)
        # The strict comparison is unchanged: this is a scheme-side reading, not
        # a general licence to reinterpret the mathematics.
        assert equivalent(student, expected) is False, (student, expected)


def test_a_reordered_answer_still_matches() -> None:
    assert equivalent_to_scheme("75x + 12x^3 - 60x^2", "12x3 - 60x2 + 75x") is True


# -- what the repair must not swallow --------------------------------------
def test_a_sign_difference_is_still_a_difference() -> None:
    assert equivalent_to_scheme("12x^3 + 60x^2 + 75x", "12x3 - 60x2 + 75x") is False


def test_a_wrong_coefficient_is_still_a_difference() -> None:
    assert equivalent_to_scheme("12x^3 - 60x^2 + 70x", "12x3 - 60x2 + 75x") is False


def test_a_wrong_power_is_still_a_difference() -> None:
    assert equivalent_to_scheme("12x^4 - 60x^2 + 75x", "12x3 - 60x2 + 75x") is False


def test_a_flattened_scheme_answer_is_accepted_as_the_printed_form() -> None:
    assert answer_is_printed_form("12x^3 - 60x^2 + 75x", "12x3 - 60x2 + 75x")
    assert not answer_is_printed_form("3x(4x^2 - 20x + 25)", "12x3 - 60x2 + 75x")


# -- what the marking layer now reports ------------------------------------
def _flattened_scheme() -> list[SimpleNamespace]:
    return [
        _criterion("M1", "Expanding two brackets with 3 of 4 terms correct"),
        _criterion("M1", "Multiplying by the third bracket", dependencies=["M1"]),
        _criterion("A1", "12x3 - 60x2 + 75x", marks=1),
    ]


def test_a_correct_answer_against_a_flattened_scheme_is_equivalent_not_different() -> None:
    check = check_answer_against_scheme(
        student_expression="12x^3 - 60x^2 + 75x", criteria=_flattened_scheme()
    )

    assert check.status == "EQUIVALENT"
    assert check.expected_criterion == "A1"


def test_a_correct_answer_is_no_longer_contradicted_when_full_marks_were_awarded() -> None:
    criteria = _flattened_scheme()
    check = check_answer_against_scheme(
        student_expression="12x^3 - 60x^2 + 75x", criteria=criteria
    )

    findings = scheme_math_findings(
        check,
        awarded=3,
        max_marks=3,
        components=[_part("M1", True), _part("M1", True), _part("A1", True)],
        criteria=criteria,
        question_id="34",
    )

    assert [finding.code for finding in findings if finding.code == CODE_ANSWER_DIFFERENT] == []


def test_a_withheld_accuracy_mark_for_an_equivalent_answer_is_visible() -> None:
    """The under-award the flattened text used to hide.

    The script's answer is the scheme's answer and the accuracy point was
    withheld: that is a possible under-award, and it must be reported as one.
    """

    criteria = _flattened_scheme()
    check = check_answer_against_scheme(
        student_expression="12x^3 - 60x^2 + 75x", criteria=criteria
    )

    findings = scheme_math_findings(
        check,
        awarded=2,
        max_marks=3,
        components=[_part("M1", True), _part("M1", True), _part("A1", False)],
        criteria=criteria,
        question_id="34",
    )

    assert CODE_ANSWER_WITHHELD in {finding.code for finding in findings}


def test_a_wrong_answer_against_a_flattened_scheme_is_still_different() -> None:
    criteria = _flattened_scheme()
    check = check_answer_against_scheme(
        student_expression="12x^3 + 60x^2 + 75x", criteria=criteria
    )

    assert check.status == "DIFFERENT"


# -- the field that actually states the answer -----------------------------
def test_the_expected_answer_field_is_read_when_the_description_is_prose() -> None:
    """A prose criterion still states its answer, and the check must use it."""

    criteria = [
        _criterion("M1", "Expanding with at least 3 of 4 terms correct"),
        _criterion("A1", "Correct final answer", expected_answer="24x3 - 28x2 - 12x"),
    ]

    check = check_answer_against_scheme(
        student_expression="24x^3 - 28x^2 - 12x", criteria=criteria
    )

    assert check.status == "EQUIVALENT"
    assert check.expected_criterion == "A1"


def test_the_same_answer_in_two_notations_is_one_candidate_not_two() -> None:
    """A caret description and a flattened expected answer agree."""

    criteria = [
        _criterion(
            "A1",
            "12x^3 - 60x^2 + 75x",
            expected_answer="12x3 - 60x2 + 75x",
        )
    ]

    assert scheme_expected_expression(criteria) is not None
    check = check_answer_against_scheme(
        student_expression="12x^3 - 60x^2 + 75x", criteria=criteria
    )

    assert check.status == "EQUIVALENT"


def test_two_different_answers_on_one_question_remain_ambiguous() -> None:
    """An allow-listed second form is not a second expected answer."""

    criteria = [
        _criterion("A1", "12x^3 - 60x^2 + 75x"),
        _criterion("A1", "4x(3x^2 - 15x)", marks=1),
    ]

    assert scheme_expected_expression(criteria) is None
    check = check_answer_against_scheme(
        student_expression="12x^3 - 60x^2 + 75x", criteria=criteria
    )

    assert check.status == "SKIPPED"


# -- what the repair must not reinterpret ----------------------------------
def test_a_name_ending_in_a_digit_is_not_a_power() -> None:
    """``sin2x`` is sin(2x) and ``sqrt2`` is a root: neither is an exponent."""

    for expression in ("sin2x", "cos2x", "sqrt2", "log2", "ln2", "exp2", "xy2"):
        assert restore_printed_superscripts(expression) == expression, expression


def test_a_multi_letter_symbol_is_still_different_from_a_power() -> None:
    assert equivalent_to_scheme("x*y^2", "xy2") is False


def test_a_power_on_a_bracket_is_not_read_at_all() -> None:
    """No letter precedes the digit, so recall is lost rather than invented."""

    assert restore_printed_superscripts("2(x + 1)3") == "2(x + 1)3"


def test_the_one_indistinguishable_case_is_the_printed_power() -> None:
    """``x2`` as a product cannot be told from ``x^2``; the scheme reading wins.

    Plain text carries no superscript, so this residue is inherent.  It is pinned
    here so that changing which reading the repair prefers — or letting it touch
    the script's side — is a deliberate decision rather than an accident.
    """

    assert restore_printed_superscripts("x2") == "x^2"
    assert equivalent("x2", "x^2") is False
