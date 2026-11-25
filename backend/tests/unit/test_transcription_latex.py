"""A LaTeX macro is part of the reading, not decoration.

Mission 6.1 found the comparator deleting every ``\\command`` it did not
recognise, together with the symbol the command named.  ``2\\theta`` compared
equal to ``2``, ``\\sin x`` to ``x`` and ``2\\pi r`` to ``2 r``: a material
difference in the mathematics classified as agreement.

These tests pin the replacement.  Only typography is removed.  A known
mathematical command becomes a stable word token, an unknown one stays in the
stream as its own token, and an equivalence command is rewritten to the
operation it names.  Nothing may turn two different expressions into one.
"""

from __future__ import annotations

import pytest
from app.correction.transcription_compare import (
    STATUS_AGREES,
    STATUS_DIFFERS,
    compare_readings,
    normalise_math,
    tokens,
)

#: The three cases Mission 6.1 reproduced against the shipped comparator.
MATERIAL_SYMBOL_CASES = [
    (r"2\theta", "2"),
    (r"\sin x", "x"),
    (r"2\pi r", "2 r"),
]


@pytest.mark.parametrize("marking,blind", MATERIAL_SYMBOL_CASES)
def test_a_lost_symbol_is_a_difference_not_an_agreement(marking: str, blind: str) -> None:
    comparison = compare_readings([marking], blind)

    assert comparison.status == STATUS_DIFFERS
    assert comparison.material
    assert normalise_math(marking) != normalise_math(blind)


@pytest.mark.parametrize(
    "expression", [r"2\theta", r"\sin x", r"2\pi r"]
)
def test_the_same_expression_written_twice_still_agrees(expression: str) -> None:
    """The repair must not make every LaTeX reading differ from itself."""

    assert compare_readings([expression], expression).status == STATUS_AGREES


def test_a_known_command_becomes_a_reading_not_whitespace() -> None:
    assert normalise_math(r"2\theta") == "2 theta"
    assert tokens(r"2\theta") == ["2", "theta"]
    assert tokens(r"\sin x") == ["sin", "x"]
    assert tokens(r"2\pi r") == ["2", "pi", "r"]


def test_an_unknown_command_keeps_its_own_token() -> None:
    """An unanticipated macro can never cancel a difference."""

    normalised = normalise_math(r"2\foobar x")

    assert "foobar" in normalised
    assert tokens(r"2\foobar x")[:2] == ["2", "\\"]
    assert compare_readings([r"2\foobar x"], "2 x").status == STATUS_DIFFERS
    # The same unknown macro on both sides is still the same reading.
    assert compare_readings([r"2\foobar x"], r"2\foobar x").status == STATUS_AGREES


def test_typography_alone_is_removed() -> None:
    assert compare_readings([r"\left( x + 1 \right)"], "(x + 1)").status == STATUS_AGREES
    assert compare_readings([r"\bigl( x \bigr)"], "( x )").status == STATUS_AGREES
    assert normalise_math(r"\displaystyle x + 1") == "x + 1"


def test_a_wrapper_command_keeps_its_content() -> None:
    assert compare_readings([r"\mathrm{d}x"], "dx").status == STATUS_AGREES
    assert compare_readings([r"\text{hence } x = 3"], "hence x = 3").status == STATUS_AGREES
    # Content is compared, so different content is a difference.
    assert compare_readings([r"\text{hence} x"], r"\text{therefore} x").status == STATUS_DIFFERS


def test_a_left_arrow_is_not_read_as_left_typography() -> None:
    """``\\leftarrow`` must survive the negative lookahead the typography rule uses."""

    assert normalise_math(r"A \leftarrow B") != normalise_math(r"A  B")
    assert compare_readings([r"A \leftarrow B"], "A B").status == STATUS_DIFFERS


def test_equivalence_commands_are_rewritten_not_deleted() -> None:
    assert compare_readings([r"2 \cdot 3"], "2 * 3").status == STATUS_AGREES
    assert compare_readings([r"6 \div 2"], "6 / 2").status == STATUS_AGREES
    assert compare_readings([r"2^{3}"], "2^(3)").status == STATUS_AGREES


def test_escaped_symbols_survive_normalisation() -> None:
    assert compare_readings([r"\theta + \pi"], r"\theta + \pi").status == STATUS_AGREES
    assert compare_readings([r"\theta + \pi"], r"\theta + 2").status == STATUS_DIFFERS
    assert compare_readings([r"\{ x \}"], r"\{ x \}").status == STATUS_AGREES


def test_fractions_with_nested_braces_stay_distinct() -> None:
    """A pattern that cannot read the braces must not fall back to deletion."""

    nested = r"\frac{x^{2}}{2}"
    normalised = normalise_math(nested)

    assert "frac" in normalised, normalised
    assert compare_readings([nested], r"\frac{x^{3}}{2}").status == STATUS_DIFFERS
    assert compare_readings([nested], nested).status == STATUS_AGREES


def test_superscripts_subscripts_and_relations_are_still_compared() -> None:
    assert compare_readings([r"x^{2} + 3x"], "x^2 + 3x").status == STATUS_AGREES
    assert compare_readings([r"x^{2}"], "x^{5}").status == STATUS_DIFFERS
    assert compare_readings([r"a_{1} + a_{2}"], "a_1 + a_2").status == STATUS_AGREES
    assert compare_readings([r"x \le 3"], "x <= 3").status == STATUS_AGREES
    assert compare_readings([r"x \ne 3"], "x = 3").status == STATUS_DIFFERS


def test_mixed_text_and_mathematics_keeps_both_parts() -> None:
    assert (
        compare_readings([r"\text{so } x = 3"], "so x = 3").status == STATUS_AGREES
    )
    assert (
        compare_readings([r"\text{so } x = 3"], "so x = 4").status == STATUS_DIFFERS
    )


def test_the_item_cannot_erase_a_symbol_from_a_recorded_line() -> None:
    """The Q6 shape, with a symbol the marking pass may write."""

    recorded = r"2\pi r"
    blind = "2 r + 0"

    assert compare_readings([recorded], blind).status == STATUS_DIFFERS
