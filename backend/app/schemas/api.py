"""API contracts for the Phase 1 endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExamCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    board: str | None = Field(default=None, max_length=80)
    paper_code: str | None = Field(default=None, max_length=80)


class ExamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    board: str | None
    paper_code: str | None
    created_at: datetime


class AssignmentCreate(BaseModel):
    exam_id: UUID
    blueprint_version_id: UUID
    scheme_version_id: UUID
    name: str = Field(min_length=1, max_length=300)
    completion_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    review_mode: str = Field(default="BALANCED", pattern="^(ECONOMY|BALANCED|ACCURACY)$")


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exam_id: UUID
    blueprint_version_id: UUID | None
    scheme_version_id: UUID | None
    name: str
    completion_threshold: float
    review_mode: str
    created_at: datetime


class SubmissionCreate(BaseModel):
    assignment_id: UUID
    student_ref: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assignment_id: UUID
    student_ref: str
    status: str
    content_hash: str
    created_at: datetime


class CorrectionCreate(BaseModel):
    assignment_id: UUID
    submission_id: UUID
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)

    @field_validator("idempotency_key")
    @classmethod
    def _key_shape(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if len(value) < 8:
                raise ValueError("idempotency_key must be at least 8 characters")
        return value


class JobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_seq: int
    from_state: str | None
    to_state: str
    detail: dict[str, Any]
    actor: str
    created_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    assignment_id: UUID
    submission_id: UUID
    blueprint_version_id: UUID
    scheme_version_id: UUID
    state: str
    progress: float
    attempts: int
    max_attempts: int
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    retryable: bool | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    record_version: int


class JobDetailRead(JobRead):
    events: list[JobEventRead] = Field(default_factory=list)


class ProviderHealthRead(BaseModel):
    id: UUID
    account_label: str
    key_fingerprint: str
    health: str
    cooldown_until: datetime | None
    last_success_at: datetime | None
    last_error: str | None


class UsageSummaryRead(BaseModel):
    tenant_id: UUID
    requests: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float
    by_model: dict[str, int]


class HealthRead(BaseModel):
    status: str
    service: str
    version: str


class ReadinessRead(BaseModel):
    status: str
    database: str
    detail: str | None = None
