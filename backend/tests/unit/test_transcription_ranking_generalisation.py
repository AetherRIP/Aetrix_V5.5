"""Does the risk policy generalise beyond the paper that calibrated it?

Mission 6.1 reproduced the pilot ranking exactly, and recorded the honest limit:
the weights were validated on one paper, and ``BARE_NUMERIC_FINAL`` is close to
that paper's own fingerprint.  The response here is not to retune weights —
there is no second paper to calibrate against — but to pin the behaviour on
synthetic rows of other shapes, so the policy's scope and its gaps are visible
and any future change has to be deliberate.

These fixtures prove what the code does.  They do **not** show that the ordering
matches what a human would choose on a real paper.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import MarkingSettings
from app.correction.sampling import MODE_ACCURACY, MODE_BALANCED, MODE_ECONOMY, policy_for
from app.correction.transcription import (
    rank_transcription_targets,
    transcribe_targets,
)


def _row(
    question_id: str,
    *,
    awarded: int = 0,
    max_marks: int = 3,
    answer: str | None = None,
    confidence: float | None = 0.95,
    state: str = "MARKED",
    concerns: list | None = None,
    review_required: bool = False,
    anomaly: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        question_id=question_id,
        awarded_marks=awarded,
        max_marks=max_marks,
        student_answer=answer,
        confidence=confidence,
        processing_state=state,
        scheme_concerns=concerns or [],
        review_required=review_required,
        normalisation_anomaly=anomaly,
    )


def _synthetic_rows() -> list[SimpleNamespace]:
    """Rows of several answer shapes, not the pilot paper's three."""

    return [
        # Algebraic expansion with two subtractions and no bracket.
        _row("3a", confidence=0.9),
        # A bare numeric final answer quoted beside a zero.
        _row("4", confidence=0.9),
        # A fraction: one character changes the value.
        _row("5b", confidence=0.9),
        # Structured notation, low confidence.
        _row("6", confidence=0.7),
        # A low-confidence non-zero award.
        _row("7", awarded=2, answer="x = 3", confidence=0.5),
        # An award its own quotations contradict.
        _row("8", awarded=2, answer="x = 3"),
        # A page problem, first of a deliberate tie.
        _row("9", awarded=1, max_marks=1, answer="24", concerns=[
            {"code": "PAGE_LIMIT_TRUNCATED", "message": "the second page was not sent"}
        ]),
        # The same row under a later question number: the tie must not be decided
        # by lexical order (``10`` before ``9`` would be a string sort).
        _row("10", awarded=1, max_marks=1, answer="24", concerns=[
            {"code": "PAGE_LIMIT_TRUNCATED", "message": "the second page was not sent"}
        ]),
        # A complete, confident award: no request is worth buying.
        _row("11", awarded=3, answer="x = 1", confidence=0.99),
        # Already with a person: a second reading cannot change the outcome.
        _row("12", state="NEEDS_REVIEW", confidence=0.4),
        # A non-zero award with a bare quoted number: the pilot-shaped signal is
        # gated on a zero, so this row carries no signal at all.
        _row("13", awarded=2, answer=None, confidence=0.9),
    ]


READINGS = {
    "3a": ["4x^2 + 12x + 9 - 4x^2 - 12x + 9"],
    "4": ["18"],
    "5b": ["3/4"],
    "6": ["angle ABC = 40"],
    "7": ["x = 3"],
    "8": ["y = 2x + 1"],
    "9": ["24"],
    "10": ["24"],
    "11": ["x = 1"],
    "13": ["3"],
}


def test_the_ranking_is_deterministic() -> None:
    rows = _synthetic_rows()

    first = rank_transcription_targets(rows, readings=READINGS)
    second = rank_transcription_targets(rows, readings=READINGS)

    assert [(item.question_id, item.score) for item in first] == [
        (item.question_id, item.score) for item in second
    ]


def test_several_answer_shapes_are_ranked_not_only_the_pilot_shape() -> None:
    rows = _synthetic_rows()

    ranked = rank_transcription_targets(rows, readings=READINGS)
    ids = [item.question_id for item in ranked]

    # Algebraic, numeric, fraction, structured notation, low-confidence award,
    # evidence contradiction and page risk are all reachable.
    assert {"3a", "4", "5b", "6", "7", "8", "9", "10"} <= set(ids)
    # A confident complete award and a row already with a person are not.
    assert "11" not in ids
    assert "12" not in ids


def test_a_bare_number_only_signals_risk_on_a_zero_award() -> None:
    """The known pilot-shaped limit, pinned rather than papered over.

    ``BARE_NUMERIC_FINAL`` fires only when the marking pass quoted a separate
    number *and awarded zero*.  A non-zero award whose reading is a bare number is
    not treated as a contradiction, because a positive award is what the scheme
    asked for.  Calibrating this on more than one paper is future work.
    """

    blank_zero = _row("q1", confidence=0.9)
    positive = _row("q2", awarded=2, answer=None, confidence=0.9)
    ranked = rank_transcription_targets(
        [blank_zero, positive], readings={"q1": ["18"], "q2": ["3"]}
    )

    signals = {item.question_id: item.signals for item in ranked}

    assert "BARE_NUMERIC_FINAL" in signals["q1"]
    assert "q2" not in signals


def test_every_signal_can_be_explained_from_its_row() -> None:
    rows = _synthetic_rows()

    for target in rank_transcription_targets(rows, readings=READINGS):
        assert target.reasons, target.question_id
        named = {reason.split(":", 1)[0] for reason in target.reasons}
        assert set(target.signals) <= named


def test_equal_risk_is_broken_in_natural_question_order() -> None:
    rows = _synthetic_rows()

    ranked = rank_transcription_targets(rows, readings=READINGS)
    ids = [item.question_id for item in ranked]

    assert ids.index("9") < ids.index("10")


def test_marks_at_stake_is_capped() -> None:
    small = rank_transcription_targets(
        [_row("q1", max_marks=1, confidence=0.9)],
        readings={"q1": ["18"]},
    )[0]
    large = rank_transcription_targets(
        [_row("q1", max_marks=50, confidence=0.9)],
        readings={"q1": ["18"]},
    )[0]

    # BLANK_ZERO + CONFIDENT_ZERO + BARE_NUMERIC_FINAL + the capped stake.
    assert small.score == 13.5
    assert large.score == 16.0


def test_the_ranking_never_exceeds_the_mode_budget() -> None:
    rows = _synthetic_rows()
    settings = SimpleNamespace(marking=MarkingSettings(transcription_enabled=True))

    for mode, expected in (
        (MODE_ECONOMY, 0),
        (MODE_BALANCED, 2),
        (MODE_ACCURACY, 4),
    ):
        budget = policy_for(mode, settings=settings).transcription_budget
        chosen = transcribe_targets(rows, budget=budget, readings=READINGS)

        assert len(chosen) == expected, mode
        assert len(chosen) <= budget


def test_a_budget_beyond_the_ranked_questions_is_not_invented() -> None:
    rows = [_row("q1", confidence=0.9)]

    chosen = transcribe_targets(rows, budget=8, readings={"q1": []})

    assert len(chosen) == 1
