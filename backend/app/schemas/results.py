"""Question results, review decisions and approval contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CriterionResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    awarded: bool
    reason: str | None
    evidence: list[dict[str, Any]]


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    quote: str | None
    page_id: UUID | None
    bbox: dict[str, Any] | None


class VerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question_id: str
    kind: str
    status: str
    detail: dict[str, Any]


class ReviewDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question_id: str
    requested_reason: str
    outcome: str | None
    first_award: int | None
    second_award: int | None
    decided_by: str | None
    decided_at: datetime | None


class QuestionResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question_id: str
    max_marks: int
    awarded_marks: int
    status: str
    student_answer: str | None
    working_summary: str | None
    confidence: float | None
    review_required: bool
    #: The engine's explicit claim about this question.  ``None`` only for rows
    #: written before the column existed; readers fall back to ``status``.
    processing_state: str | None = None
    #: The model's own award and the mark that was actually stored, so a
    #: normalisation or a teacher's change is visible instead of silent.
    raw_awarded_marks: int | None = None
    normalised_awarded_marks: int | None = None
    normalisation_anomaly: str | None = None
    scheme_concerns: list[dict[str, Any]]
    criteria: list[CriterionResultRead] = Field(default_factory=list)
    evidence: list[EvidenceRead] = Field(default_factory=list)


class ResultTotals(BaseModel):
    """Totals over decided questions only.

    ``awarded`` and ``total`` describe the questions the engine actually
    decided.  An undecided question has no mark, so it contributes to neither
    side of that fraction; ``undecided`` and ``complete`` say how much of the
    paper the figures cover.
    """

    awarded: int
    total: int
    questions: int
    decided: int
    undecided: int
    scoreable: int
    complete: bool
    unanswered: int
    review_required: int
    approved: bool
    state: str


class JobResultsRead(BaseModel):
    job_id: UUID
    submission_id: UUID
    assignment_id: UUID
    student_ref: str
    job_state: str
    #: What produced these marks.  ``AUTOMATED_REFUSED`` means this run was not
    #: presented; a direct job read still says so.
    result_source: str | None = None
    #: A newer run was refused by the result guard and is deliberately not shown.
    refused_newer_job_id: UUID | None = None
    questions: list[QuestionResultRead]
    verifications: list[VerificationRead]
    reviews: list[ReviewDecisionRead]
    totals: ResultTotals
    approved_at: datetime | None = None
    approved_by: str | None = None
    record_version: int


class MarkOverride(BaseModel):
    awarded_marks: int = Field(ge=0, le=200)
    reason: str = Field(min_length=5, max_length=2000)
    expected_record_version: int | None = Field(default=None, ge=0)

    @field_validator("reason")
    @classmethod
    def _reason_shape(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("a mark override needs a stated reason")
        return value


class QuestionReviewRequest(BaseModel):
    """A reviewer's decision on one question the engine flagged for review.

    ``UPHOLD`` keeps the engine's award; ``CHANGE`` replaces it; ``INDEPENDENT``
    records a second mark arrived at separately.  A change never happens without
    a stated reason, and never above the question maximum.
    """

    decision: Literal["UPHOLD", "CHANGE", "INDEPENDENT"]
    awarded_marks: int | None = Field(default=None, ge=0, le=200)
    reason: str = Field(min_length=5, max_length=2000)

    @model_validator(mode="after")
    def _award_required_when_changing(self) -> QuestionReviewRequest:
        if self.decision != "UPHOLD" and self.awarded_marks is None:
            raise ValueError("changing or second-marking a question needs an awarded mark")
        return self


class JobApprovalRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    expected_record_version: int | None = Field(default=None, ge=0)


class PageRead(BaseModel):
    page_index: int
    document_id: UUID
    quality_status: str
    width: int | None
    height: int | None
