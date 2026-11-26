"""Persisted correction progress for the manual workspace.

Every field is read from a row the engine already wrote.  There is no timer, no
interpolated percentage and no invented "currently processing" count: a question
with no stored result is ``PENDING``, not zero.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProgressEventRead(BaseModel):
    seq: int
    from_state: str | None
    state: str
    detail: dict
    actor: str
    at: datetime


class ProgressStageRead(BaseModel):
    stage: str
    outcome: str
    at: datetime
    prompt_version: str | None = None
    detail: dict = Field(default_factory=dict)


class ProgressQuestionRead(BaseModel):
    question_id: str
    max_marks: int
    status: str
    processing_state: str | None = None
    awarded_marks: int | None = None
    confidence: float | None = None
    review_required: bool = False
    verification_status: str | None = None
    result_id: UUID | None = None


class JobProgressRead(BaseModel):
    job_id: UUID
    submission_id: UUID
    assignment_id: UUID
    state: str
    progress: float
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime
    last_updated_at: datetime
    elapsed_seconds: int | None
    total_questions: int
    completed_questions: int
    processing_questions: int
    review_questions: int
    failed_questions: int
    pending_questions: int
    awarded_marks: int
    available_marks: int
    estimated_remaining_seconds: int | None
    questions: list[ProgressQuestionRead]
    stages: list[ProgressStageRead]
    events: list[ProgressEventRead]
    documents: list[dict]
    error_code: str | None
    error_message: str | None
    retryable: bool | None
    result_source: str | None
    verification_status: str | None
