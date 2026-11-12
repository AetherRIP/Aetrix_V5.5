from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.correction.aetrix.pipeline import validation_failed_for
from app.correction.evidence import MODEL_RESPONSE_INVALID
from app.correction.guard import (
    ACTION_BLOCKED,
    ACTION_INSERT,
    ACTION_KEEP_EXISTING,
    ACTION_UPDATE,
    CONFIDENCE_LARGE_SCORE_CHANGE,
    CONFIDENCE_VALIDATION_FAILED,
    PriorResult,
    evaluate_overwrite,
    percentage,
)


def _prior(*, earned: int, available: int = 100, approved=False, override=False) -> PriorResult:
    return PriorResult(
        job_id=uuid.uuid4(),
        earned=earned,
        available=available,
        approved=approved,
        teacher_override=override,
    )


def test_the_first_result_is_stored() -> None:
    decision = evaluate_overwrite(prior=None, earned=57, available=91)

    assert decision.action == ACTION_INSERT
    assert decision.may_present is True
    assert decision.review_required is False


def test_a_failed_first_run_is_blocked_rather_than_stored() -> None:
    decision = evaluate_overwrite(
        prior=None, earned=0, available=91, validation_failed=True
    )

    assert decision.action == ACTION_BLOCKED
    assert decision.confidence == CONFIDENCE_VALIDATION_FAILED
    assert decision.may_present is False


def test_an_approved_result_cannot_be_replaced() -> None:
    decision = evaluate_overwrite(
        prior=_prior(earned=60, approved=True), earned=70, available=100
    )

    assert decision.action == ACTION_BLOCKED
    assert "approved" in decision.reason
    assert decision.may_present is False


def test_a_teacher_override_outranks_the_engine() -> None:
    decision = evaluate_overwrite(
        prior=_prior(earned=60, override=True), earned=61, available=100
    )

    assert decision.action == ACTION_KEEP_EXISTING
    assert "overrode" in decision.reason


def test_a_failed_re_run_keeps_the_stored_result() -> None:
    decision = evaluate_overwrite(
        prior=_prior(earned=60), earned=0, available=100, validation_failed=True
    )

    assert decision.action == ACTION_KEEP_EXISTING
    assert decision.confidence == CONFIDENCE_VALIDATION_FAILED


def test_zero_where_the_stored_run_awarded_marks_is_suspicious() -> None:
    decision = evaluate_overwrite(prior=_prior(earned=67, available=103), earned=0, available=103)

    assert decision.action == ACTION_KEEP_EXISTING
    assert decision.confidence == CONFIDENCE_LARGE_SCORE_CHANGE
    assert "67" in decision.reason


def test_a_thirty_point_drop_is_suspicious_and_a_smaller_one_is_not() -> None:
    dropped = evaluate_overwrite(prior=_prior(earned=80), earned=50, available=100)
    assert dropped.action == ACTION_KEEP_EXISTING

    accepted = evaluate_overwrite(prior=_prior(earned=80), earned=51, available=100)
    assert accepted.action == ACTION_UPDATE
    assert accepted.may_present is True


def test_a_consistent_re_mark_updates_the_result() -> None:
    decision = evaluate_overwrite(prior=_prior(earned=57, available=91), earned=58, available=91)

    assert decision.action == ACTION_UPDATE
    assert decision.review_required is False
    assert decision.may_present is True


def test_a_zero_valued_paper_does_not_divide_by_zero() -> None:
    assert percentage(0, 0) == 0.0
    decision = evaluate_overwrite(prior=None, earned=0, available=0)
    assert decision.action == ACTION_INSERT


def test_a_refused_decision_never_presents() -> None:
    for decision in (
        evaluate_overwrite(prior=_prior(earned=60, approved=True), earned=70, available=100),
        evaluate_overwrite(prior=_prior(earned=60, override=True), earned=60, available=100),
        evaluate_overwrite(prior=_prior(earned=67), earned=0, available=100),
    ):
        assert decision.may_present is False
        assert decision.review_required is True


@pytest.mark.parametrize("earned", [0, 1, 99, 100])
def test_every_score_is_a_plausible_update_against_an_empty_prior(earned: int) -> None:
    decision = evaluate_overwrite(prior=None, earned=earned, available=100)
    assert decision.action in {ACTION_INSERT}


def test_an_unparseable_reply_means_the_run_did_not_validate() -> None:
    rows = [
        SimpleNamespace(normalisation_anomaly=None),
        SimpleNamespace(normalisation_anomaly=MODEL_RESPONSE_INVALID),
    ]

    assert validation_failed_for(rows, []) is True


def test_an_integrity_finding_means_the_run_did_not_validate() -> None:
    assert validation_failed_for([], ["1a: COMPONENT_TOTAL_MISMATCH"]) is True


def test_a_clean_run_has_validated() -> None:
    rows = [SimpleNamespace(normalisation_anomaly=None)]

    assert validation_failed_for(rows, []) is False
    assert validation_failed_for([], []) is False
