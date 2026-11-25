"""A written expression may be wrapped more than once.

Mission 6.1 measured that a single line wrap was joined but two wraps were not:
``4x^2`` / ``+ 12x`` / ``+ 9`` against the one-line form produced a false
``DIFFERS`` with a ``SIGN`` finding.  A reader wrapping a long expansion onto
three lines had not misread anything.

The repair joins runs of lines only across breaks the writing itself explains,
so two wraps are found without gluing a separate final answer or a new line of
working onto the line above it.
"""

from __future__ import annotations

from app.correction.transcription_compare import (
    KIND_SIGN,
    STATUS_AGREES,
    STATUS_DIFFERS,
    compare_readings,
    expressions,
)


def test_two_line_wraps_inside_one_expression_agree() -> None:
    comparison = compare_readings(
        ["4x^2 + 12x + 9"], "4x^2\n+ 12x\n+ 9"
    )

    assert comparison.status == STATUS_AGREES
    assert comparison.differences == ()


def test_three_line_wraps_inside_one_expression_agree() -> None:
    comparison = compare_readings(["a + b + c + d"], "a\n+ b\n+ c\n+ d")

    assert comparison.status == STATUS_AGREES


def test_a_line_break_around_an_operator_is_a_wrap() -> None:
    assert compare_readings(["2x + 3"], "2x\n+ 3").status == STATUS_AGREES
    assert compare_readings(["2x + 3"], "2x\n+\n3").status == STATUS_AGREES
    assert compare_readings(["6 / 2"], "6\n/\n2").status == STATUS_AGREES


def test_a_line_break_inside_a_fraction_is_a_wrap() -> None:
    assert compare_readings([r"\frac{3}{4}"], "3\n/\n4").status == STATUS_AGREES
    assert compare_readings(["3/4"], "3/\n4").status == STATUS_AGREES


def test_a_product_split_across_two_lines_is_a_wrap() -> None:
    assert (
        compare_readings(["(x + 1)(x - 1)"], "(x + 1)\n(x - 1)").status
        == STATUS_AGREES
    )


def test_an_unclosed_bracket_carries_the_expression_to_the_next_line() -> None:
    assert compare_readings(["(2x + 3)(x - 1)"], "(2x + 3\n)(x - 1)").status == STATUS_AGREES


def test_a_separate_final_answer_is_not_glued_onto_the_working() -> None:
    """``…+ 9`` then ``18`` are two lines; ``…+ 918`` is a different reading."""

    comparison = compare_readings(["4x^2 + 12x + 918"], "4x^2 + 12x + 9\n18")

    assert comparison.status == STATUS_DIFFERS
    # The answer line is compared on its own, so the recorded reading is not
    # found by concatenating the two lines.
    assert expressions("4x^2 + 12x + 9\n18") == ["4x^2 + 12x + 9", "18"]


def test_a_separate_line_of_working_stays_a_separate_line() -> None:
    assert compare_readings(["x = 3"], "x = 3\ny = 2x + 1").status == STATUS_AGREES
    comparison = compare_readings(["y = 2x + 1"], "x = 3\ny = 2x + 1\n18")
    assert comparison.status == STATUS_AGREES


def test_a_missing_term_across_a_line_break_is_a_difference() -> None:
    comparison = compare_readings(["4x^2 + 12x + 9"], "4x^2\n+ 12x")

    assert comparison.status == STATUS_DIFFERS


def test_a_different_expression_wrapped_the_same_way_is_still_different() -> None:
    comparison = compare_readings(["x^2 + 2x + 1"], "x^2\n+ 2x\n+ 5")

    assert comparison.status == STATUS_DIFFERS


def test_a_changed_sign_across_a_wrap_is_still_a_sign_difference() -> None:
    comparison = compare_readings(["2x + 3"], "2x\n- 3")

    assert comparison.status == STATUS_DIFFERS
    assert comparison.kinds == (KIND_SIGN,)


def test_a_short_recorded_line_is_not_found_in_a_glued_pair() -> None:
    """Line breaks between two values are boundaries, never joins."""

    comparison = compare_readings(["18"], "9\n18")

    assert comparison.status == STATUS_AGREES

    different = compare_readings(["918"], "9\n18")

    assert different.status == STATUS_DIFFERS
