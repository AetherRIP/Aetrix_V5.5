"""Read-only contracts for the correction preview.

The preview composes three stored sources for one question: the student's
scanned page, the printed mark scheme, and the archived reply that produced the
award.  Nothing here is computed by a model and nothing here writes: the models
mirror records that already exist, and an absent record is ``None`` with a stated
reason rather than a plausible-looking substitute.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PreviewDocumentRead(BaseModel):
    id: UUID
    kind: str
    original_filename: str
    sha256: str
    size_bytes: int
    page_count: int
    ordering_status: str
    ordering_reasons: list[dict[str, Any]]
    mapping_status: str
    mapping_reasons: list[dict[str, Any]]


class PreviewSchemeDocumentRead(BaseModel):
    """The printed scheme pages, and how they were matched to this version."""

    document_id: UUID | None = None
    original_filename: str | None = None
    page_count: int = 0
    content_hash_matches: bool = False
    #: The scheme document recorded against the exam, when there is one.
    exam_document_filename: str | None = None
    exam_document_size_bytes: int | None = None
    note: str


class PreviewCriterionRead(BaseModel):
    """One structured marking point, as reviewed in Aetrix."""

    code: str
    ordinal: int
    marks: int
    description: str
    expected_answer: str | None = None
    required_evidence: str | None = None
    award_conditions: str | None = None
    withhold_conditions: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    source_page: int | None = None
    source_quote: str | None = None


class PreviewDecisionRead(BaseModel):
    """A scheme point beside the award the archived reply made against it."""

    code: str
    #: The scheme row this assessment belongs to; ``None`` for a reply component
    #: the scheme does not name.
    scheme_ordinal: int | None = None
    scheme_marks: int | None = None
    #: ``None`` means the reply recorded no separate assessment for this point.
    awarded: bool | None = None
    awarded_marks: int | None = None
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    component_description: str | None = None
    #: The reply printed the code once while the scheme prints it more than once.
    ambiguous: bool = False
    note: str | None = None


class PreviewVerificationRead(BaseModel):
    kind: str
    status: str
    detail: dict[str, Any]


class PreviewArchiveRead(BaseModel):
    """The archived reply this question came from."""

    provider_response_id: UUID
    content_sha256: str
    model: str | None = None
    finish_reason: str | None = None
    response_source: str
    created_at: datetime


class PreviewLocationRead(BaseModel):
    page_index: int
    confidence: float
    method: str
    quality_status: str
    width: int | None = None
    height: int | None = None


class PreviewQuestionRead(BaseModel):
    question_id: str
    label: str
    question_text: str | None = None
    special_instructions: list[str] = Field(default_factory=list)
    max_marks: int
    awarded_marks: int
    raw_awarded_marks: int | None = None
    status: str
    processing_state: str
    review_required: bool
    student_answer: str | None = None
    working_summary: str | None = None
    confidence: float | None = None
    answer_check: str | None = None
    notes: str | None = None
    response_source: str | None = None
    response_sequence: int | None = None
    prompt_version: str | None = None
    scheme_criteria: list[PreviewCriterionRead] = Field(default_factory=list)
    criteria: list[PreviewDecisionRead] = Field(default_factory=list)
    scheme_marks: int = 0
    component_total: int | None = None
    component_consistent: bool | None = None
    location: PreviewLocationRead | None = None
    mapping_note: str | None = None
    verifications: list[PreviewVerificationRead] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    concerns: list[dict[str, Any]] = Field(default_factory=list)
    archive: PreviewArchiveRead | None = None


class PreviewWarningRead(BaseModel):
    code: str
    message: str


class PreviewPaperRead(BaseModel):
    exam_id: UUID
    exam_title: str
    board: str | None = None
    paper_code: str | None = None
    assignment_id: UUID
    assignment_name: str
    blueprint_version_id: UUID
    scheme_version_id: UUID
    blueprint_total_marks: int
    marking_mode: str | None = None
    engine_name: str | None = None
    engine_version: str | None = None
    primary_model: str | None = None
    secondary_model: str | None = None
    prompt_version: str | None = None
    job_state: str
    result_source: str | None = None
    #: The result guard's action for this run, when it recorded one.
    guard_decision: str | None = None
    guard_reason: str | None = None
    questions_reviewed: int
    attention: int
    #: Marks over every stored question row, including rows flagged for review.
    paper_awarded: int
    paper_total: int
    #: Marks over formally decided questions only — the totals the results API
    #: reports, kept separate so neither figure is mistaken for the other.
    decided_awarded: int
    decided_total: int
    decided: int
    scoreable: int
    undecided: int
    review_required: int
    approved: bool
    approved_at: datetime | None = None
    approved_by: str | None = None


class PreviewStudentRead(BaseModel):
    submission_id: UUID
    job_id: UUID
    student_ref: str
    awarded_marks: int
    total_marks: int
    review_required: int
    job_state: str
    result_source: str | None = None
    current: bool


class CorrectionPreviewRead(BaseModel):
    job_id: UUID
    submission_id: UUID
    student_ref: str
    paper: PreviewPaperRead
    student_document: PreviewDocumentRead | None = None
    scheme_document: PreviewSchemeDocumentRead
    students: list[PreviewStudentRead] = Field(default_factory=list)
    questions: list[PreviewQuestionRead] = Field(default_factory=list)
    warnings: list[PreviewWarningRead] = Field(default_factory=list)
