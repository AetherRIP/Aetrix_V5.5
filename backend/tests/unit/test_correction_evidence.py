from __future__ import annotations

from app.correction.evidence import (
    MODEL_RESPONSE_INVALID,
    OVER_MAX_AWARD,
    RAW_RESPONSE_LIMIT,
    capture_raw_response,
    normalise_award,
)


def test_a_json_reply_is_stored_as_it_arrived() -> None:
    captured = capture_raw_response('{"awarded_marks": 2, "components": []}')

    assert captured.truncated is False
    assert captured.value == {"awarded_marks": 2, "components": []}


def test_an_unparseable_reply_is_still_kept() -> None:
    captured = capture_raw_response("Awarded two marks for the method.")

    assert captured.truncated is False
    assert captured.value["format"] == "UNPARSEABLE_TEXT"
    assert "Awarded two marks" in captured.value["text"]


def test_an_empty_reply_is_stored_as_nothing() -> None:
    assert capture_raw_response("   ").value is None
    assert capture_raw_response(None).value is None


def test_a_very_long_reply_is_capped_and_says_so() -> None:
    captured = capture_raw_response("x" * (RAW_RESPONSE_LIMIT + 10))

    assert captured.truncated is True
    assert captured.value["format"] == "TEXT_TRUNCATED"
    assert len(captured.value["text"]) == RAW_RESPONSE_LIMIT


def test_an_award_within_the_maximum_is_not_altered() -> None:
    normalised = normalise_award(2, max_marks=3)

    assert (normalised.raw, normalised.normalised) == (2, 2)
    assert normalised.anomaly is None
    assert normalised.detail is None


def test_an_over_maximum_award_keeps_the_model_value() -> None:
    normalised = normalise_award(5, max_marks=3)

    assert normalised.raw == 5
    assert normalised.normalised == 0
    assert normalised.anomaly == OVER_MAX_AWARD
    assert normalised.detail is not None
    assert normalised.detail["raw_awarded_marks"] == 5
    assert normalised.detail["max_marks"] == 3


def test_a_negative_award_is_never_applied() -> None:
    normalised = normalise_award(-2, max_marks=3)

    assert normalised.normalised == 0
    assert normalised.anomaly == OVER_MAX_AWARD
    assert normalised.raw == -2


def test_the_invalid_response_anomaly_is_a_stable_code() -> None:
    assert MODEL_RESPONSE_INVALID == "MODEL_RESPONSE_INVALID"
