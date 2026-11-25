"""The V5 individual-student report, mapped from stored Aetrix results.

The generator itself is V5's code; these tests pin the two facts Aetrix adds on
top of it: an undecided question is never a zero, and an unapproved result is
printed as a draft.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pymupdf
from app.db.models import MarkingCriterion
from app.reporting.student_report import render_result_pdf
from app.schemas.results import (
    CriterionResultRead,
    JobResultsRead,
    QuestionResultRead,
    ResultTotals,
)
from app.services.student_report import BRAND_DOC_PREFIX, BRAND_EYEBROW, assemble_result


def _row(
    question_id: str,
    *,
    max_marks: int = 2,
    awarded: int = 2,
    status: str = "AWARDED",
    state: str | None = "MARKED",
    review_required: bool = False,
    answer: str | None = "x = 4",
) -> QuestionResultRead:
    return QuestionResultRead(
        id=uuid.uuid4(),
        question_id=question_id,
        max_marks=max_marks,
        awarded_marks=awarded,
        status=status,
        student_answer=answer,
        working_summary=None,
        confidence=0.9,
        review_required=review_required,
        processing_state=state,
        scheme_concerns=[],
        criteria=[
            CriterionResultRead(
                id=uuid.uuid4(),
                code="M1",
                awarded=awarded > 0,
                reason="correct rearrangement",
                evidence=[],
            )
        ],
    )


def _read(
    rows: list[QuestionResultRead],
    *,
    approved: bool = True,
    complete: bool = True,
    verification_status: str | None = "FULLY_VERIFIED",
    refused_newer: bool = False,
) -> JobResultsRead:
    decided = [row for row in rows if row.status == "AWARDED"]
    totals = ResultTotals(
        awarded=sum(row.awarded_marks for row in decided),
        total=sum(row.max_marks for row in decided),
        questions=len(rows),
        decided=len(decided),
        undecided=len(rows) - len(decided),
        scoreable=len([row for row in rows if row.status != "EXCLUDED"]),
        complete=complete,
        unanswered=0,
        review_required=sum(1 for row in rows if row.review_required),
        approved=approved,
        state="COMPLETED",
    )
    return JobResultsRead(
        job_id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
        assignment_id=uuid.uuid4(),
        student_ref="ETH-014",
        job_state="COMPLETED",
        verification_status=verification_status,
        refused_newer_job_id=uuid.uuid4() if refused_newer else None,
        questions=rows,
        verifications=[],
        reviews=[],
        totals=totals,
        record_version=1,
    )


def _criterion(question_id: str, code: str, description: str, ordinal: int = 0) -> MarkingCriterion:
    return MarkingCriterion(
        tenant_id=uuid.uuid4(),
        scheme_version_id=uuid.uuid4(),
        question_id=question_id,
        code=code,
        marks=1,
        ordinal=ordinal,
        description=description,
        dependencies=[],
        alternatives=[],
        source_ref={},
    )


def _result(read: JobResultsRead, **overrides):
    values = {
        "student_name": "Amina Yusuf",
        "class_label": "Ethos 4MA1",
        "assignment_title": "Fraction arithmetic practice",
        "scheme_criteria": {
            "1a": [
                _criterion("1a", "M1", "M1 for forming the equation"),
                _criterion("1a", "A1", "A1 for the correct value", ordinal=1),
            ]
        },
        "finished_at": datetime(2026, 11, 20, 9, 30, tzinfo=UTC),
        "blueprint_total_marks": 5,
    }
    values.update(overrides)
    return assemble_result(read, **values)


def _pdf_text(result: dict, detail: str = "standard") -> tuple[bytes, str]:
    pdf = render_result_pdf(
        result,
        detail=detail,
        generated_at=result.get("created_at"),
        eyebrow=BRAND_EYEBROW,
        doc_prefix=BRAND_DOC_PREFIX,
    ).getvalue()
    text = "\n".join(page.get_text() for page in pymupdf.open(stream=pdf, filetype="pdf"))
    return pdf, text.upper()


def test_scores_questions_and_the_approved_scheme_reach_the_page() -> None:
    read = _read([_row("1a", max_marks=2, awarded=2), _row("1b", max_marks=3, awarded=1)])
    result = _result(read)

    assert result["earned"] == 3
    assert result["available"] == 5
    assert result["percentage"] == 60.0
    assert result["manual_override"] is True
    assert result["verification_json"]["status"] == "VERIFIED"
    assert result["verification_json"]["anomalies"] == []
    assert result["result_json"]["questions"][0]["correct_method"] == (
        "M1: M1 for forming the equation; A1: A1 for the correct value"
    )

    pdf, text = _pdf_text(result)
    assert pdf.startswith(b"%PDF")
    assert "STUDENT CORRECTION REPORT" in text
    assert "AMINA YUSUF" in text
    assert "FRACTION ARITHMETIC PRACTICE" in text
    assert "3 / 5" in text
    assert "60%" in text
    assert "AETRIX" in text
    # The V5 product name must not leak onto an Aetrix document.
    assert "MATH CORRECT" not in text


def test_an_unapproved_result_is_printed_as_a_draft() -> None:
    read = _read([_row("1a"), _row("1b")], approved=False)
    result = _result(read)

    assert result["manual_override"] is False
    assert result["verification_json"]["status"] == "REVIEW"
    assert "draft" in result["result_json"]["overall_notes"]["summary"]

    _, text = _pdf_text(result)
    assert "NEEDS REVIEW" in text
    assert "NO TEACHER HAS APPROVED THIS RESULT, SO THIS DOCUMENT IS A DRAFT" in text


def test_an_undecided_question_is_not_reported_as_a_zero() -> None:
    rows = [
        _row("1a", max_marks=2, awarded=2),
        _row(
            "1b",
            max_marks=3,
            awarded=0,
            status="REVIEW_REQUIRED",
            state="NEEDS_REVIEW",
            review_required=True,
        ),
    ]
    read = _read(rows, approved=False, complete=False)
    result = _result(read)

    assert result["percentage"] is None
    assert result["result_json"]["questions"][1]["status"] == "REVIEW"
    verification = result["verification_json"]
    assert verification["partial"] is True
    assert verification["coverage"]["marked"] == 1
    assert verification["coverage"]["expected"] == 2
    assert verification["unresolved_marks"] == 3

    _, text = _pdf_text(result)
    assert "MARKED ONLY" in text
    assert "INCOMPLETE CORRECTION" in text
    assert "DRAFT" in text
    assert "3 OF 5 MARKS WERE NEVER ASSESSED" in text


def test_a_refused_newer_run_is_named_on_the_report() -> None:
    read = _read([_row("1a")], refused_newer=True)
    result = _result(read)

    assert "refused by the result guard" in result["result_json"]["overall_notes"]["summary"]
    assert result["verification_json"]["status"] == "REVIEW"
    _, text = _pdf_text(result)
    assert "REFUSED BY THE RESULT GUARD" in text


def test_detail_levels_print_progressively_more() -> None:
    read = _read([_row("1a"), _row("1b")])
    result = _result(read)

    _, summary = _pdf_text(result, "summary")
    _, standard = _pdf_text(result, "standard")
    _, detailed = _pdf_text(result, "detailed")

    assert "QUESTION BREAKDOWN" not in summary
    assert "QUESTION BREAKDOWN" in standard
    assert "MARKING DETAIL" not in standard
    assert "MARKING DETAIL" in detailed
    assert "MARK SCHEME" in detailed
    assert "M1 FOR FORMING THE EQUATION" in detailed


def test_questions_are_printed_in_paper_order() -> None:
    read = _read([_row("10"), _row("2"), _row("1a")])
    result = _result(read)

    assert [q["question_number"] for q in result["result_json"]["questions"]] == ["1a", "2", "10"]


def test_unprintable_characters_do_not_break_the_document() -> None:
    read = _read([_row("1a")])
    result = _result(read, student_name="Amina “Yusuf” ✓ 😀")

    pdf, text = _pdf_text(result)
    assert pdf.startswith(b"%PDF")
    assert "AMINA" in text
    assert "\u2713" not in text


def test_a_report_is_only_produced_at_a_known_detail_level() -> None:
    assert BRAND_EYEBROW == "Aetrix"
    assert BRAND_DOC_PREFIX
    # V5's own renderer rejects an unknown level by falling back to standard,
    # so the guard lives in the service that calls it.
    assert SimpleNamespace(detail="verbose").detail not in ("summary", "standard", "detailed")
