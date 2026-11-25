"""Every review flag must carry a reason, and coverage must not go stale."""

from __future__ import annotations

from types import SimpleNamespace

from app.correction.aetrix.pipeline import review_reasons_for, sync_coverage_concerns


def _row(**kwargs):
    defaults = {
        "question_id": "1a",
        "awarded_marks": 2,
        "max_marks": 2,
        "confidence": 0.95,
        "review_required": False,
        "processing_state": "MARKED",
        "status": "AWARDED",
        "scheme_concerns": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_a_flag_without_a_concern_still_produces_a_reason() -> None:
    reasons = review_reasons_for([_row(review_required=True, scheme_concerns=[])])

    assert len(reasons) == 1
    assert "without a recorded reason" in reasons[0]


def test_every_concern_becomes_a_reason_and_duplicates_collapse() -> None:
    row = _row(
        review_required=True,
        scheme_concerns=[
            {"code": "A", "message": "first"},
            {"code": "A", "message": "first"},
            {"code": "B", "message": "second"},
        ],
    )

    reasons = review_reasons_for([row])

    assert len(reasons) == 2
    assert reasons[0].endswith("first")


def test_an_unflagged_row_produces_no_reason() -> None:
    assert review_reasons_for([_row()]) == []


def test_a_new_coverage_gap_flags_the_row() -> None:
    row = _row()

    change = sync_coverage_concerns(
        row,
        ["3 readable page(s) are not mapped"],
        integrity_passed=True,
        min_confidence=0.6,
    )

    assert change["changed"] is True
    assert row.review_required is True
    assert row.processing_state == "NEEDS_REVIEW"
    assert row.scheme_concerns[0]["code"] == "PAGE_COVERAGE"


def test_a_closed_gap_clears_only_its_own_flag() -> None:
    row = _row(
        review_required=True,
        processing_state="NEEDS_REVIEW",
        status="REVIEW_REQUIRED",
        scheme_concerns=[
            {"code": "PAGE_COVERAGE", "message": "PAGE_COVERAGE: old gap"},
        ],
    )

    change = sync_coverage_concerns(
        row, [], integrity_passed=True, min_confidence=0.6
    )

    assert change["removed"] == ["PAGE_COVERAGE: old gap"]
    assert row.review_required is False
    assert row.processing_state == "MARKED"
    assert row.scheme_concerns == []


def test_another_reason_keeps_the_row_in_review() -> None:
    row = _row(
        review_required=True,
        processing_state="NEEDS_REVIEW",
        status="REVIEW_REQUIRED",
        scheme_concerns=[
            {"code": "PAGE_COVERAGE", "message": "PAGE_COVERAGE: old gap"},
            {"code": "DOUBLE_CHECK_DISAGREEMENT", "message": "examiners differ"},
        ],
    )

    sync_coverage_concerns(row, [], integrity_passed=True, min_confidence=0.6)

    assert row.review_required is True
    assert row.processing_state == "NEEDS_REVIEW"
    assert row.scheme_concerns == [
        {"code": "DOUBLE_CHECK_DISAGREEMENT", "message": "examiners differ"}
    ]


def test_a_failed_integrity_check_keeps_the_flag_when_coverage_closes() -> None:
    row = _row(
        review_required=True,
        processing_state="NEEDS_REVIEW",
        status="REVIEW_REQUIRED",
        scheme_concerns=[
            {"code": "PAGE_COVERAGE", "message": "PAGE_COVERAGE: old gap"},
        ],
    )

    sync_coverage_concerns(row, [], integrity_passed=False, min_confidence=0.6)

    assert row.review_required is True
    assert row.processing_state == "NEEDS_REVIEW"
    assert row.scheme_concerns == []
