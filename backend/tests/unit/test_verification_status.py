"""Verification completeness is derived, never assumed.

The tests are pure: stored rows and stored verdicts in, an explicit state out.
No provider is called and no award is touched.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.correction import verification_status as status


def _row(question_id: str = "1a", *, awarded: int = 2, review: bool = False):
    return SimpleNamespace(
        question_id=question_id,
        awarded_marks=awarded,
        max_marks=2,
        processing_state="MARKED" if awarded else "CONFIRMED_ZERO",
        review_required=review,
        confidence=0.95,
    )


def _records(**kwargs: str) -> dict[str, tuple[str, dict]]:
    return {kind: (value, {}) for kind, value in kwargs.items()}


def test_integrity_alone_is_not_an_independent_verification() -> None:
    result = status.question_verification(_row(awarded=0), _records(INTEGRITY="PASS"))

    assert result.status == status.STATUS_NOT_REQUIRED
    assert result.required == ("INTEGRITY",)
    assert result.verified == ("INTEGRITY",)


def test_a_scheme_answer_makes_the_mathematical_check_required() -> None:
    result = status.question_verification(
        _row(awarded=5),
        _records(INTEGRITY="PASS", SCHEME_MATHEMATICAL="EQUIVALENT", EVIDENCE="PASS"),
    )

    assert result.status == status.STATUS_FULLY_VERIFIED
    assert "SCHEME_MATHEMATICAL" in result.verified


def test_a_contradicted_answer_fails_verification_even_if_the_row_is_flagged() -> None:
    result = status.question_verification(
        _row(awarded=5, review=True),
        _records(INTEGRITY="PASS", MATHEMATICAL="DIFFERENT"),
    )

    assert result.status == status.STATUS_VERIFICATION_FAILED
    assert "MATHEMATICAL" in result.contradicted


def test_an_award_without_an_evidence_check_is_only_partially_verified() -> None:
    result = status.question_verification(
        _row(awarded=2), _records(INTEGRITY="PASS")
    )

    assert result.status == status.STATUS_PARTIALLY_VERIFIED
    assert result.missing == ("EVIDENCE",)
    assert any("evidence" in reason.lower() for reason in result.reasons)


def test_a_zero_award_does_not_require_an_evidence_check() -> None:
    result = status.question_verification(
        _row(awarded=0), _records(INTEGRITY="PASS", TRANSCRIPTION="AGREES")
    )

    assert result.status == status.STATUS_FULLY_VERIFIED


def test_an_unverifiable_reading_requires_review_not_a_pass() -> None:
    result = status.question_verification(
        _row(awarded=2),
        _records(INTEGRITY="PASS", TRANSCRIPTION="UNVERIFIABLE", EVIDENCE="UNVERIFIABLE"),
    )

    assert result.status == status.STATUS_REVIEW_REQUIRED
    assert set(result.unverifiable) == {"TRANSCRIPTION", "EVIDENCE"}


def test_a_failed_evidence_check_is_a_contradiction() -> None:
    result = status.question_verification(
        _row(awarded=2),
        _records(INTEGRITY="PASS", EVIDENCE="FAIL"),
    )

    assert result.status == status.STATUS_VERIFICATION_FAILED
    assert result.contradicted == ("EVIDENCE",)


def test_skipped_mathematics_is_not_applicable_and_does_not_fail_the_row() -> None:
    result = status.question_verification(
        _row(awarded=2),
        _records(INTEGRITY="PASS", MATHEMATICAL="SKIPPED", EVIDENCE="PASS"),
    )

    assert result.status == status.STATUS_FULLY_VERIFIED
    assert result.not_applicable == ("MATHEMATICAL",)


def test_a_review_flag_alone_requires_review() -> None:
    result = status.question_verification(
        _row(awarded=0, review=True), _records(INTEGRITY="PASS")
    )

    assert result.status == status.STATUS_REVIEW_REQUIRED


def test_a_row_without_a_decision_cannot_be_verified() -> None:
    row = SimpleNamespace(
        question_id="1a",
        awarded_marks=0,
        max_marks=2,
        processing_state="NEEDS_REVIEW",
        review_required=True,
        confidence=None,
    )
    result = status.question_verification(row, _records(INTEGRITY="REVIEW_REQUIRED"))

    assert result.status == status.STATUS_VERIFICATION_FAILED
    assert any("no stored decision" in reason for reason in result.reasons)


def test_paper_status_prefers_the_worst_outcome() -> None:
    rows = [_row("1a", awarded=2), _row("1b", awarded=0, review=True)]
    records = {
        "1a": _records(INTEGRITY="PASS", EVIDENCE="PASS"),
        "1b": _records(INTEGRITY="PASS"),
    }

    summary = status.summarise(rows, records)

    assert summary.status == status.STATUS_REVIEW_REQUIRED
    assert summary.counts[status.STATUS_FULLY_VERIFIED] == 1
    assert summary.question("1a") is not None


def test_a_fully_verified_paper_requires_every_question() -> None:
    rows = [_row("1a", awarded=2), _row("1b", awarded=0)]
    records = {
        "1a": _records(INTEGRITY="PASS", EVIDENCE="PASS"),
        "1b": _records(INTEGRITY="PASS", TRANSCRIPTION="AGREES"),
    }

    assert status.summarise(rows, records).status == status.STATUS_FULLY_VERIFIED


def test_one_unverified_question_keeps_the_paper_partial() -> None:
    rows = [_row("1a", awarded=2), _row("1b", awarded=0)]
    records = {
        "1a": _records(INTEGRITY="PASS", EVIDENCE="PASS"),
        "1b": _records(INTEGRITY="PASS"),
    }

    assert status.summarise(rows, records).status == status.STATUS_PARTIALLY_VERIFIED


def test_no_required_checks_at_all_is_not_fully_verified() -> None:
    rows = [_row("1a", awarded=0), _row("1b", awarded=0)]
    records = {row.question_id: _records(INTEGRITY="PASS") for row in rows}

    assert status.summarise(rows, records).status == status.STATUS_NOT_REQUIRED


def test_empty_paper_is_not_required_rather_than_verified() -> None:
    assert status.summarise([], {}).status == status.STATUS_NOT_REQUIRED


def test_records_from_rows_groups_by_question_and_kind() -> None:
    rows = [
        SimpleNamespace(question_id="1a", kind="INTEGRITY", status="PASS", detail={}),
        SimpleNamespace(question_id="1a", kind="EVIDENCE", status="FAIL", detail={"x": 1}),
    ]

    grouped = status.records_from_rows(rows)

    assert grouped["1a"]["INTEGRITY"] == ("PASS", {})
    assert grouped["1a"]["EVIDENCE"] == ("FAIL", {"x": 1})


# -- the evidence gate ------------------------------------------------------
# A mark whose quotation was never compared with the script is not a verified
# mark.  The gate names those questions so the pipeline can route them to a
# person; it never changes an award.
def test_an_award_with_no_evidence_check_is_ungrounded() -> None:
    rows = [_row("1a", awarded=2)]

    ungrounded = status.awards_without_evidence(
        rows, {"1a": _records(INTEGRITY="PASS")}
    )

    assert ungrounded == ("1a",)


def test_a_recorded_evidence_check_clears_the_gate_whatever_it_concluded() -> None:
    """PASS, FAIL and UNVERIFIABLE are all *checks taken*; only absence is not.

    A failed or unverifiable reading already routes its own concern, so the gate
    adds nothing there; re-flagging it would duplicate the reviewer's reason.
    """

    for verdict in ("PASS", "FAIL", "UNVERIFIABLE"):
        rows = [_row("1a", awarded=2)]
        records = {"1a": _records(INTEGRITY="PASS", EVIDENCE=verdict)}

        assert status.awards_without_evidence(rows, records) == (), verdict


def test_a_question_without_records_is_ungrounded_only_when_it_holds_marks() -> None:
    rows = [_row("1a", awarded=0), _row("1b", awarded=2)]

    assert status.awards_without_evidence(rows, {}) == ("1b",)


def test_the_gate_reports_every_ungrounded_question_in_row_order() -> None:
    rows = [_row("1a", awarded=1), _row("1b", awarded=0), _row("2", awarded=3)]
    records = {"1a": _records(INTEGRITY="PASS", EVIDENCE="PASS")}

    assert status.awards_without_evidence(rows, records) == ("2",)


def test_the_gate_code_is_a_stable_contract() -> None:
    """The code is stored on the row and read by the review screen."""

    assert status.CODE_EVIDENCE_NOT_CHECKED == "EVIDENCE_NOT_CHECKED"


def test_an_ungrounded_award_is_partially_verified_not_fully_verified() -> None:
    """The gate and the derived status must agree about the same fact."""

    result = status.question_verification(
        _row("1a", awarded=2), _records(INTEGRITY="PASS")
    )

    assert result.status == status.STATUS_PARTIALLY_VERIFIED
    assert result.missing == ("EVIDENCE",)
