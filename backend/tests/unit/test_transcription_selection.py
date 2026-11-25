"""Which question earns a blind second reading, and why.

Mission 5 found the mechanism worked and the selection did not: on the Mission 3
pilot paper the transcription budget was two, three questions tied at the
blank-zero weight, and lexicographic question-id order put Q6 third.  The defect
the whole stage exists for was therefore never checked.

These tests pin the replacement policy against the pilot's real 39 rows: risk
signals decide, the ordering is explainable, and question id is only the last
tie-break.  The fixture is a read-only capture of the stored rows; no production
record is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.core.config import MarkingSettings
from app.correction.sampling import (
    MODE_ACCURACY,
    MODE_BALANCED,
    MODE_ECONOMY,
    policy_for,
)
from app.correction.transcription import (
    rank_transcription_targets,
    transcribe_targets,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "transcription_pilot_rows.json"


def _pilot() -> tuple[list[SimpleNamespace], dict[str, list[str]]]:
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = [SimpleNamespace(**row) for row in stored["rows"]]
    readings = {row.question_id: row.quotes for row in rows}
    return rows, readings


def _row(
    question_id: str,
    *,
    awarded: int = 0,
    max_marks: int = 3,
    answer: str | None = None,
    confidence: float | None = 1.0,
    state: str = "CONFIRMED_ZERO",
    concerns: list | None = None,
    review_required: bool = False,
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
        normalisation_anomaly=None,
    )


def _settings(**overrides) -> SimpleNamespace:
    return SimpleNamespace(marking=MarkingSettings(**overrides))


# -- the Mission 3 pilot ---------------------------------------------------


def test_the_pilot_q6_is_the_first_question_selected() -> None:
    """The confident zero taken from a misread sign must be re-read."""

    rows, readings = _pilot()

    ranking = rank_transcription_targets(rows, readings=readings)
    selected = transcribe_targets(rows, budget=2, readings=readings)

    assert ranking[0].question_id == "6"
    assert next(iter(target.question_id for target in selected)) == "6"
    assert "6" in {target.question_id for target in selected}


def test_the_pilot_q6_is_selected_by_its_risk_not_its_identifier() -> None:
    """Renaming the row must not change its rank: no question-id overfit."""

    rows, readings = _pilot()
    renamed = [row for row in rows if row.question_id != "6"]
    six = next(row for row in rows if row.question_id == "6")
    renamed.append(SimpleNamespace(**{**vars(six), "question_id": "99"}))
    renamed_readings = {**readings, "99": readings["6"]}

    ranking = rank_transcription_targets(renamed, readings=renamed_readings)
    selected = transcribe_targets(renamed, budget=2, readings=renamed_readings)

    assert ranking[0].question_id == "99"
    assert selected[0].question_id == "99"


def test_the_pilot_ranking_is_explainable() -> None:
    rows, readings = _pilot()

    ranking = rank_transcription_targets(rows, readings=readings)
    six = ranking[0]

    assert six.question_id == "6"
    assert six.rank == 1
    assert set(six.signals) == {
        "BLANK_ZERO",
        "CONFIDENT_ZERO",
        "BARE_NUMERIC_FINAL",
        "SIGN_DISTRIBUTION",
        "MARKS_AT_STAKE",
    }
    assert all(reason.split(":")[0] in six.signals for reason in six.reasons)
    # Two signals are what Mission 5 could not see: the marking pass quoted a
    # bare final answer beside a zero, in a long signed sum with no bracket.
    assert "BARE_NUMERIC_FINAL" in six.signals
    assert "SIGN_DISTRIBUTION" in six.signals


def test_the_other_zero_questions_are_ranked_by_risk_not_by_identifier() -> None:
    """Q27 sorts before Q37b as a string; risk puts Q37b first."""

    rows, readings = _pilot()

    ranking = rank_transcription_targets(rows, readings=readings)
    order = [target.question_id for target in ranking]

    assert order[:3] == ["6", "37b", "27"]
    assert "27" < "37b"  # the string order the old tie-break used
    assert order.index("37b") < order.index("27")


def test_a_harmless_question_does_not_displace_a_high_risk_one() -> None:
    """A marked question with nothing doubtful about it buys no request."""

    rows, readings = _pilot()
    rows.append(
        _row("99", awarded=2, answer="x = 3", confidence=0.95, state="MARKED")
    )

    ranking = rank_transcription_targets(rows, readings=readings)

    assert "99" not in {target.question_id for target in ranking}
    assert ranking[0].question_id == "6"
    assert len(transcribe_targets(rows, budget=2, readings=readings)) == 2


def test_selection_is_deterministic() -> None:
    rows, readings = _pilot()

    first = transcribe_targets(rows, budget=2, readings=readings)
    second = transcribe_targets(rows, budget=2, readings=readings)

    assert [target.question_id for target in first] == [
        target.question_id for target in second
    ]
    assert [target.score for target in first] == [target.score for target in second]


def test_the_budget_is_respected_and_nothing_is_selected_twice() -> None:
    rows, readings = _pilot()

    for budget in (0, 1, 2, 3):
        selected = transcribe_targets(rows, budget=budget, readings=readings)
        assert len(selected) == min(budget, 3)
        assert len({target.question_id for target in selected}) == len(selected)


def test_a_question_already_read_is_skipped() -> None:
    rows, readings = _pilot()
    ranking = rank_transcription_targets(rows, readings=readings)

    skipped = transcribe_targets(
        rows, budget=2, readings=readings, skip={ranking[0].question_id}
    )

    assert ranking[0].question_id not in {target.question_id for target in skipped}
    assert len(skipped) == 2


def test_missing_risk_metadata_is_handled_conservatively() -> None:
    """An unknown confidence is a risk, not a reason to skip the question."""

    row = SimpleNamespace(
        question_id="4",
        awarded_marks=0,
        max_marks=3,
        student_answer=None,
        confidence=None,
        processing_state="CONFIRMED_ZERO",
    )

    ranking = rank_transcription_targets([row], readings={"4": ["18"]})

    assert [target.question_id for target in ranking] == ["4"]
    assert "LOW_CONFIDENCE" in ranking[0].signals
    assert "CONFIDENT_ZERO" not in ranking[0].signals


def test_a_row_with_no_readings_still_scores_its_zero() -> None:
    row = _row("5", awarded=0, answer=None, confidence=1.0)

    ranking = rank_transcription_targets([row])

    assert ranking[0].question_id == "5"
    assert "BLANK_ZERO" in ranking[0].signals


def test_an_open_review_row_is_not_selected_again() -> None:
    """A question a person already decides does not buy another reading."""

    row = _row("8", state="NEEDS_REVIEW", review_required=True)

    assert rank_transcription_targets([row], readings={"8": ["18"]}) == []


def test_an_evidence_disagreement_is_a_signal() -> None:
    row = _row("9", awarded=0, answer="x = 3", confidence=1.0)

    ranking = rank_transcription_targets([row], readings={"9": ["y + 2"]})

    assert "EVIDENCE_DISAGREEMENT" in ranking[0].signals


# -- what each review mode spends -----------------------------------------


def test_the_modes_keep_their_budgets_on_the_pilot_ranking() -> None:
    rows, readings = _pilot()

    economy = policy_for(MODE_ECONOMY, settings=_settings())
    balanced = policy_for(MODE_BALANCED, settings=_settings())
    accuracy = policy_for(MODE_ACCURACY, settings=_settings())

    assert economy.transcription_budget == 0
    assert balanced.transcription_budget == 2
    assert accuracy.transcription_budget == 4

    assert transcribe_targets(
        rows, budget=economy.transcription_budget, readings=readings
    ) == []
    balanced_targets = transcribe_targets(
        rows, budget=balanced.transcription_budget, readings=readings
    )
    accuracy_targets = transcribe_targets(
        rows, budget=accuracy.transcription_budget, readings=readings
    )

    # Only three rows on this paper carry a risk signal at all, so ACCURACY
    # spends three of its four requests rather than inventing a fourth.
    assert len(balanced_targets) == 2
    assert len(accuracy_targets) == 3
    assert {target.question_id for target in balanced_targets} <= {
        target.question_id for target in accuracy_targets
    }
