"""A second reading only helps if the comparison can see a sign.

The defect these tests exist for: the marking pass read the Q6 line

    (4x^2 + 12x + 9) - (4x^2 - 12x + 9)

as ``4x^2 + 12x + 9 - 4x^2 - 12x + 9``, concluded both expansions were wrong and
recorded a confident zero.  Every character the marking pass stored is on the
page; the meaning is not.  A comparator that treats mathematical equivalence as
agreement, or that strips brackets before comparing, cannot see it.
"""

from __future__ import annotations

import pytest
from app.correction.transcription import recorded_readings
from app.correction.transcription_compare import (
    KIND_BRACKET,
    KIND_DECIMAL,
    KIND_EXPONENT,
    KIND_FRACTION,
    KIND_INDEPENDENT_ABSENT,
    KIND_MISSING_EXPRESSION,
    KIND_RELATION,
    KIND_SIGN,
    KIND_WORKING_NOT_RECORDED,
    STATUS_ABSENT,
    STATUS_AGREES,
    STATUS_DIFFERS,
    compare_readings,
    expressions,
    flatten,
    normalise_math,
    tokens,
)

#: Exactly what the marking pass recorded for Q6 in production job 7ed1c143.
Q6_MARKING_QUOTE = "4x^2 + 12x + 9 - 4x^2 - 12x + 9"

#: What an examiner reading the page sees: the second bracket keeps its minus.
Q6_BLIND_TRANSCRIPT = "(4x^2 + 12x + 9) - (4x^2 - 12x + 9)"


def test_the_q6_misreading_is_a_material_difference() -> None:
    comparison = compare_readings([Q6_MARKING_QUOTE], Q6_BLIND_TRANSCRIPT)

    assert comparison.status == STATUS_DIFFERS
    assert comparison.material
    assert comparison.kinds == (KIND_SIGN,)
    difference = comparison.differences[0]
    assert difference.marking == Q6_MARKING_QUOTE
    assert difference.independent == Q6_BLIND_TRANSCRIPT


def test_the_q6_line_read_correctly_agrees() -> None:
    """The same page read correctly is the *flattened* form, and it agrees."""

    comparison = compare_readings(
        ["4x^2 + 12x + 9 - 4x^2 + 12x - 9"], Q6_BLIND_TRANSCRIPT
    )

    assert comparison.status == STATUS_AGREES
    assert comparison.differences == ()


def test_a_bracket_carries_the_sign_it_encloses() -> None:
    """``-(a - b + c)`` and ``-a - b + c`` share every character but one sign."""

    assert tokens(Q6_BLIND_TRANSCRIPT) != tokens(Q6_MARKING_QUOTE)
    assert tokens(Q6_BLIND_TRANSCRIPT) == tokens("4x^2 + 12x + 9 - 4x^2 + 12x - 9")


def test_a_minus_and_a_plus_are_never_the_same_reading() -> None:
    comparison = compare_readings(["y^2 - 2y + 10y - 20"], "y^2 + 2y + 10y - 20")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_SIGN,)


def test_an_exponent_is_compared_as_written() -> None:
    comparison = compare_readings(["8x^3 - 6x^2 - 60x"], "8x^3 - 6x^2 - 60x^2")

    assert comparison.status == STATUS_DIFFERS

    power = compare_readings(["(2x + 3)^2"], "(2x + 3)^3")
    assert power.status == STATUS_DIFFERS
    assert power.kinds == (KIND_EXPONENT,)


def test_a_fraction_boundary_is_material() -> None:
    comparison = compare_readings(["a + b/c"], "(a + b)/c")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds[0] in {KIND_BRACKET, KIND_FRACTION}


def test_a_decimal_point_is_material() -> None:
    comparison = compare_readings(["0.75"], "0.705")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_DECIMAL,)


def test_an_equality_and_an_inequality_are_different() -> None:
    comparison = compare_readings(["x = 3"], "x < 3")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_RELATION,)


def test_equal_values_written_differently_do_not_agree() -> None:
    """No algebraic equivalence: a scheme can award a fraction and not a decimal."""

    comparison = compare_readings(["3/4"], "0.75")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_FRACTION,)

    expanded = compare_readings(["(x + 1)^2"], "x^2 + 2x + 1")
    assert expanded.status == STATUS_DIFFERS


def test_whitespace_and_decoration_are_not_differences() -> None:
    assert compare_readings(["24 - 18y"], "24-18y").status == STATUS_AGREES
    assert compare_readings(["$24 - 18y$"], "24 - 18y").status == STATUS_AGREES
    assert compare_readings([r"\frac{3}{4}"], "3/4").status == STATUS_AGREES
    assert compare_readings([r"\left( x + 1 \right)"], "(x + 1)").status == STATUS_AGREES
    assert compare_readings(["4x**2"], "4x^2").status == STATUS_AGREES
    assert compare_readings(["4x\u00b2"], "4x^2").status == STATUS_AGREES
    # A unicode minus is a minus, not a different character.
    assert compare_readings(["24 \u2212 18y"], "24 - 18y").status == STATUS_AGREES


def test_two_blank_readings_are_absent_not_agreement() -> None:
    comparison = compare_readings([None, "  "], "")

    assert comparison.status == STATUS_ABSENT
    assert comparison.differences == ()


def test_writing_the_marking_pass_did_not_record_is_a_difference() -> None:
    comparison = compare_readings([None], "x = 3")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_WORKING_NOT_RECORDED,)


def test_a_blind_reader_that_finds_nothing_where_the_mark_quotes_work_differs() -> None:
    comparison = compare_readings(["x = 3"], None)

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_INDEPENDENT_ABSENT,)


def test_a_line_the_blind_reader_missed_is_a_difference() -> None:
    comparison = compare_readings(["x = 3", "y = 2x + 1"], "x = 3")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds[0] in {KIND_MISSING_EXPRESSION, KIND_SIGN, "TERM"}


def test_an_extra_line_in_the_blind_reading_is_not_a_difference() -> None:
    """A blind reader transcribes the whole question; the marking pass quotes."""

    comparison = compare_readings(
        ["x = 3"], "2x + 6 = 12\nx = 3\nThe answer is 3."
    )

    assert comparison.status == STATUS_AGREES


def test_a_bracket_that_is_a_factor_is_not_dropped() -> None:
    """``2(x + 1)`` and ``2x + 2`` are the same value and different working."""

    assert compare_readings(["2(x + 1)"], "2x + 2").status == STATUS_DIFFERS
    assert compare_readings(["(x + 1)(x - 1)"], "x^2 - 1").status == STATUS_DIFFERS
    # The same product written the same way agrees.
    assert compare_readings(["(x + 1)(x - 1)"], "(x+1)(x-1)").status == STATUS_AGREES


def test_a_bracket_around_one_value_is_grouping() -> None:
    assert tokens("(3)") == tokens("3")
    assert tokens("(2x)") == tokens("2x")
    # A bracket that multiplies something, or raises it to a power, stays.
    assert tokens("(2x)^2") != tokens("2x^2")
    assert tokens("2(2x)") != tokens("2 2x")


def test_flatten_distributes_only_the_sign() -> None:
    assert flatten(list("-(a-b)")) == ["-", "a", "+", "b"]
    assert flatten(list("+(a-b)")) == ["a", "-", "b"]
    # No expansion of products and no reordering.
    assert flatten(list("(a+b)(a-b)")) == ["(", "a", "+", "b", ")", "(", "a", "-", "b", ")"]
    # A bracket that is only grouping goes, at the start or in the middle.
    assert flatten(list("(a+b)-c")) == ["a", "+", "b", "-", "c"]


def test_expressions_keeps_lines_and_drops_empties() -> None:
    assert expressions("x = 3\n\n  y = 2x + 1  ") == ["x = 3", "y = 2x + 1"]
    assert expressions(None) == []
    assert normalise_math("  $ x = 3 . $ ") == "x = 3 ."


def test_recorded_readings_include_the_quotations() -> None:
    readings = recorded_readings(None, ["4x^2 + 12x + 9", None, "  ", "18"])

    assert readings == ["4x^2 + 12x + 9", "18"]


def test_missing_quotes_and_answers_are_absent() -> None:
    assert recorded_readings(None, [None, ""]) == []


# -- formatting that must not be a difference ------------------------------


def test_a_trailing_full_stop_is_not_a_difference() -> None:
    """A reader copying the page's punctuation has not misread the maths."""

    assert compare_readings(["24x"], "24x.").status == STATUS_AGREES
    assert compare_readings(["24x."], "24x").status == STATUS_AGREES
    assert compare_readings(["x = 3"], "x = 3.").status == STATUS_AGREES
    # A decimal point is never trailing, so it is never stripped.
    assert compare_readings(["0.75"], "0.7").status == STATUS_DIFFERS


def test_a_wrapped_line_is_still_one_expression() -> None:
    assert compare_readings(["2x + 3"], "2x\n+ 3").status == STATUS_AGREES
    assert compare_readings(["x = 3, y = 7"], "x = 3,\ny = 7").status == STATUS_AGREES


def test_a_final_answer_written_on_the_working_line_is_found() -> None:
    """The Mission 5 live reply merged its answer onto the working line."""

    comparison = compare_readings(
        [Q6_MARKING_QUOTE, "18"], "(4x^2+12x+9)-(4x^2-12x+9)18"
    )

    assert comparison.status == STATUS_DIFFERS
    # The only differences are the two signs the misread produced: the separate
    # ``18`` is not reported as missing.
    assert comparison.kinds == (KIND_SIGN,)
    assert {difference.kind for difference in comparison.differences} == {KIND_SIGN}


def test_expressions_split_an_appended_final_answer() -> None:
    assert expressions("(a+b)18") == ["(a+b)", "18"]
    # A number in the middle of an expression is part of it.
    assert expressions("(a+b)2x") == ["(a+b)2x"]


# -- every material difference, not only the first -------------------------


def test_two_wrong_signs_are_two_findings() -> None:
    comparison = compare_readings([Q6_MARKING_QUOTE], Q6_BLIND_TRANSCRIPT)

    assert comparison.status == STATUS_DIFFERS
    signs = [
        difference
        for difference in comparison.differences
        if difference.kind == KIND_SIGN
    ]
    assert len(signs) == 2
    assert {difference.position for difference in signs} == {14, 17}
    assert all(difference.marking == Q6_MARKING_QUOTE for difference in signs)
    assert all(difference.independent == Q6_BLIND_TRANSCRIPT for difference in signs)


def test_one_replaced_token_is_one_difference_not_a_cascade() -> None:
    comparison = compare_readings(["8x^3 - 6x^2 - 60x"], "8x^3 - 6x^5 - 60x")

    assert comparison.status == STATUS_DIFFERS
    assert len(comparison.differences) == 1
    assert comparison.differences[0].kind == KIND_EXPONENT


def test_a_lost_bracket_is_reported_as_a_bracket() -> None:
    comparison = compare_readings(["a + b/c"], "(a+b)/c")

    assert comparison.status == STATUS_DIFFERS
    assert KIND_BRACKET in comparison.kinds


def test_a_distributed_minus_without_its_bracket_is_a_sign_difference() -> None:
    assert compare_readings(["-(a - b)"], "-a - b").status == STATUS_DIFFERS
    assert compare_readings(["-(a - b)"], "-a - b").kinds == (KIND_SIGN,)


def test_two_signs_on_two_lines_are_both_reported() -> None:
    comparison = compare_readings(
        ["x^2 - 2x + 1", "y^2 - 4y + 4"], "x^2 + 2x + 1\ny^2 + 4y + 4"
    )

    assert comparison.status == STATUS_DIFFERS
    assert len(comparison.differences) == 2
    assert comparison.kinds == (KIND_SIGN,)


def test_a_wrong_relation_is_still_a_relation_difference() -> None:
    comparison = compare_readings(["2x + 3 = 11"], "2x + 3 > 11")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_RELATION,)


def test_every_difference_keeps_its_expression_for_the_reviewer() -> None:
    comparison = compare_readings([Q6_MARKING_QUOTE], Q6_BLIND_TRANSCRIPT)

    serialised = comparison.as_dict()["differences"]

    assert len(serialised) == 2
    assert all(item["marking"] == Q6_MARKING_QUOTE for item in serialised)
    assert all(isinstance(item["position"], int) for item in serialised)


@pytest.mark.parametrize(
    "marking,blind",
    [
        (["((("], ")))"),
        (["x^"], "^x"),
        ([""], ""),
        (["a"], "a"),
        (["\\frac{1}{"], "1/"),
        (["1..2"], "1.2"),
    ],
)
def test_the_comparison_never_raises(marking: list[str], blind: str) -> None:
    comparison = compare_readings(marking, blind)

    assert comparison.status in {
        STATUS_AGREES,
        STATUS_DIFFERS,
        STATUS_ABSENT,
        "UNVERIFIABLE",
    }
    assert isinstance(comparison.as_dict()["material"], bool)
