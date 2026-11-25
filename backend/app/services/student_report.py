"""Aetrix's mapping for the Math Checker V5 single-student correction report.

The PDF is produced by V5's own ``render_result_pdf`` in
:mod:`app.reporting.student_report`; this module only turns persisted Aetrix
results into the mapping that generator reads, and decides what may be said
about them.

Two rules are enforced here because the report is student-facing:

* an undecided question has no award, so it is reported as ``REVIEW`` rather
  than as a zero;
* a result that no teacher approved is a draft.  The PDF still renders (a
  teacher needs it to review), but it carries "Needs review" and an explicit
  note instead of being described as a returned result.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..correction.processing import effective_state, is_scoreable
from ..db.models import (
    Assignment,
    CorrectionJob,
    Exam,
    ExamBlueprintVersion,
    MarkingCriterion,
    SchoolClass,
    Student,
)
from ..reporting.student_report import render_result_pdf
from ..schemas.results import JobResultsRead, QuestionResultRead
from .results import ResultsService

#: The detail levels V5's generator implements.  ``summary`` stops after the
#: overview, ``standard`` adds the question breakdown, ``detailed`` adds one
#: block per question with the student's work and the scheme.
DETAIL_LEVELS = ("summary", "standard", "detailed")

#: Aetrix's own product identity on the document, in place of V5's.  The V5
#: project's logo and signature are deliberately not shipped, so the design
#: system draws its neutral monogram instead.
BRAND_EYEBROW = "Aetrix"
BRAND_DOC_PREFIX = "AX-"

UNASSIGNED_CLASS = "Not assigned"

#: Verification states that mean a person still has to decide something.
_OPEN_VERIFICATION = frozenset({"REVIEW_REQUIRED", "VERIFICATION_FAILED"})

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _sort_key(question_id: str) -> tuple[tuple[int, Any], ...]:
    """Paper order: Q2 before Q10, and never a crash on a mixed id."""
    parts = re.split(r"(\d+)", str(question_id))
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in parts)


def _slug(value: str) -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", str(value or "")).strip("_")
    return cleaned or "report"


def _decided(row: QuestionResultRead) -> bool:
    """Whether this row carries a decision, using the engine's own rules."""
    state = effective_state(
        row.status,
        row.processing_state,
        review_required=bool(row.review_required),
    )
    return is_scoreable(state)


def _scheme_text(criteria: list[MarkingCriterion]) -> str | None:
    """The approved mark points for one question, as the report's "Mark scheme"."""
    if not criteria:
        return None
    parts = [
        f"{criterion.code}: {criterion.description}"
        if criterion.code
        else criterion.description
        for criterion in criteria
        if (criterion.description or "").strip()
    ]
    return "; ".join(parts)[:800] or None


def assemble_result(
    read: JobResultsRead,
    *,
    student_name: str,
    class_label: str,
    assignment_title: str,
    scheme_criteria: dict[str, list[MarkingCriterion]],
    finished_at: datetime | None,
    blueprint_total_marks: int | None,
) -> dict[str, Any]:
    """Build the ``result`` mapping ``render_result_pdf`` reads.

    Pure: no session, no tenant lookup, no I/O.  Everything it states comes from
    the stored result or the approved blueprint the job was marked against.
    """
    totals = read.totals
    in_scope = [row for row in read.questions if row.status != "EXCLUDED"]
    undecided = [row for row in in_scope if not _decided(row)]
    unresolved_marks = sum(row.max_marks for row in undecided)

    questions = []
    for row in sorted(read.questions, key=lambda item: _sort_key(item.question_id)):
        decided = _decided(row)
        questions.append(
            {
                "question_number": row.question_id,
                "max_marks": row.max_marks,
                "awarded_marks": row.awarded_marks,
                "status": "MARKED" if decided else "REVIEW",
                "student_answer": row.student_answer,
                "working_summary": row.working_summary,
                "correct_method": _scheme_text(scheme_criteria.get(row.question_id, [])),
                "mark_breakdown": [
                    {
                        "code": criterion.code,
                        "awarded": criterion.awarded,
                        "reason": criterion.reason or "",
                    }
                    for criterion in row.criteria
                ],
            }
        )

    #: Facts about the result's standing.  They go in the report's overview, not
    #: in V5's verification callout: that callout says verification flagged the
    #: result, which is only true when a check actually did.
    notes: list[str] = []
    if not totals.approved:
        notes.append(
            "No teacher has approved this result, so this document is a draft "
            "for review - not a returned result and not a grade."
        )
    if read.refused_newer_job_id is not None:
        notes.append(
            "A newer marking run for this submission was refused by the result "
            "guard; these marks come from an earlier run and are not a result."
        )

    anomalies: list[str] = []
    if read.verification_status == "VERIFICATION_FAILED":
        anomalies.append(
            "A verification check contradicted an award, so a person has to "
            "decide before this result can be approved."
        )
    elif read.verification_status == "REVIEW_REQUIRED":
        anomalies.append(
            "Verification requires a person to decide before this result can be "
            "approved."
        )

    status = (
        "VERIFIED" if totals.complete and not anomalies and not notes else "REVIEW"
    )
    percentage = (
        round(totals.awarded / totals.total * 100, 1)
        if totals.complete and totals.total
        else None
    )

    return {
        "id": str(read.job_id),
        "display_name": student_name,
        "class_label": class_label,
        "assignment_title": assignment_title,
        "created_at": finished_at.timestamp() if finished_at is not None else None,
        "earned": totals.awarded,
        "available": totals.total,
        "percentage": percentage,
        # V5 prints "Approved by teacher" only when a person approved the
        # result.  In Aetrix that fact is the job approval, not an override.
        "manual_override": totals.approved,
        "result_json": {
            "questions": questions,
            "overall_notes": {"summary": " ".join(notes)} if notes else {},
        },
        "verification_json": {
            "partial": not totals.complete,
            "coverage": {
                "marked": totals.decided,
                "expected": totals.scoreable,
                "requires_review": totals.review_required,
            },
            "unresolved_marks": unresolved_marks,
            "paper_total_marks": blueprint_total_marks,
            "earned": totals.awarded,
            "available": totals.total,
            "status": status,
            "anomalies": anomalies,
        },
    }


class StudentReportService:
    """Render the V5 individual-student report from stored Aetrix results."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.results = ResultsService(session)

    # -- reads -----------------------------------------------------------
    def _assignment(self, tenant_id: uuid.UUID, assignment_id: uuid.UUID) -> Assignment:
        assignment = self.session.get(Assignment, assignment_id)
        if assignment is None or assignment.tenant_id != tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        return assignment

    def _exam(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> Exam | None:
        exam = self.session.get(Exam, exam_id)
        return exam if exam is not None and exam.tenant_id == tenant_id else None

    def _student_name(self, tenant_id: uuid.UUID, student_ref: str) -> tuple[str, str]:
        student = self.session.scalar(
            select(Student).where(
                Student.tenant_id == tenant_id,
                Student.student_ref == student_ref,
            )
        )
        if student is None:
            return student_ref, UNASSIGNED_CLASS
        name = (student.display_name or "").strip() or student.student_ref
        if student.class_id is None:
            return name, UNASSIGNED_CLASS
        school_class = self.session.get(SchoolClass, student.class_id)
        if school_class is None or school_class.tenant_id != tenant_id:
            return name, UNASSIGNED_CLASS
        return name, school_class.name

    def _criteria(
        self, tenant_id: uuid.UUID, scheme_version_id: uuid.UUID | None
    ) -> dict[str, list[MarkingCriterion]]:
        if scheme_version_id is None:
            return {}
        rows = self.session.scalars(
            select(MarkingCriterion)
            .where(
                MarkingCriterion.tenant_id == tenant_id,
                MarkingCriterion.scheme_version_id == scheme_version_id,
            )
            .order_by(MarkingCriterion.question_id.asc(), MarkingCriterion.ordinal.asc())
        )
        grouped: dict[str, list[MarkingCriterion]] = {}
        for row in rows:
            grouped.setdefault(row.question_id, []).append(row)
        return grouped

    def _blueprint_total(
        self, tenant_id: uuid.UUID, blueprint_version_id: uuid.UUID | None
    ) -> int | None:
        if blueprint_version_id is None:
            return None
        blueprint = self.session.get(ExamBlueprintVersion, blueprint_version_id)
        if blueprint is None or blueprint.tenant_id != tenant_id:
            return None
        return blueprint.total_marks

    def _job(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> CorrectionJob | None:
        job = self.session.get(CorrectionJob, job_id)
        return job if job is not None and job.tenant_id == tenant_id else None

    def build_result(self, principal: Principal, submission_id: uuid.UUID) -> dict[str, Any]:
        read = self.results.submission_results(principal, submission_id)
        if read is None:
            raise AppError(
                ErrorCode.RESULT_NOT_READY,
                "This submission has no stored correction result, so there is no "
                "report to produce.",
            )
        assignment = self._assignment(principal.tenant_id, read.assignment_id)
        job = self._job(principal.tenant_id, read.job_id)
        student_name, class_label = self._student_name(principal.tenant_id, read.student_ref)
        return assemble_result(
            read,
            student_name=student_name,
            class_label=class_label,
            assignment_title=assignment.name,
            scheme_criteria=self._criteria(principal.tenant_id, assignment.scheme_version_id),
            finished_at=(
                job.finished_at or job.started_at or job.created_at if job is not None else None
            ),
            blueprint_total_marks=self._blueprint_total(
                principal.tenant_id, assignment.blueprint_version_id
            ),
        )

    # -- render ----------------------------------------------------------
    def render(
        self,
        principal: Principal,
        submission_id: uuid.UUID,
        *,
        detail: str = "standard",
    ) -> tuple[bytes, str]:
        """Return ``(pdf_bytes, filename)`` for one submission's result."""
        level = (detail or "standard").lower()
        if level not in DETAIL_LEVELS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "A report is available at the summary, standard or detailed level.",
                details={"detail": detail, "allowed": list(DETAIL_LEVELS)},
            )
        result = self.build_result(principal, submission_id)
        buffer = render_result_pdf(
            result,
            detail=level,
            generated_at=result.get("created_at"),
            eyebrow=BRAND_EYEBROW,
            doc_prefix=BRAND_DOC_PREFIX,
        )
        filename = _slug(
            f"{result['display_name']} {result['assignment_title']} {level} report"
        )
        return buffer.getvalue(), f"{filename}.pdf"
