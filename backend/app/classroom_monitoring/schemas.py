"""Contracts for automatic Classroom submission monitoring.

Every model is a projection of stored state.  No Google token, attachment bytes
or marking content crosses this boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MonitorHealth = Literal["DISABLED", "PAUSED", "HEALTHY", "DEGRADED", "BLOCKED", "UNKNOWN"]
SubmissionPipelineState = Literal[
    "DETECTED",
    "DOWNLOADING",
    "INSPECTING",
    "READY",
    "IGNORED",
    "NEEDS_TEACHER",
    "SUPERSEDED",
    "FAILED",
]
CorrectionPipelineState = Literal[
    "NOT_QUEUED",
    "QUEUED",
    "PROCESSING",
    "REVIEW_REQUIRED",
    "COMPLETED",
    "FAILED",
]
Eligibility = Literal["PENDING", "ELIGIBLE", "NEEDS_TEACHER", "BLOCKED"]
Relevance = Literal[
    "UNASSESSED",
    "LIKELY_RELEVANT",
    "POSSIBLY_UNRELATED",
    "INSUFFICIENT_EVIDENCE",
    "CANNOT_DETERMINE",
]
RelevancePolicy = Literal["STRUCTURAL_ALLOW", "TEXT_REQUIRED"]


class MonitorAttachmentRead(BaseModel):
    position: int
    kind: str
    title: str | None = None
    declared_mime: str | None = None
    detected_mime: str | None = None
    size_bytes: int | None = None
    status: str
    page_count: int | None = None
    sha256: str | None = None
    reason: str | None = None
    issues: list[dict[str, str]] = Field(default_factory=list)


class MonitorSubmissionRead(BaseModel):
    """One student's current submission version, with its full history count."""

    submission_link_id: UUID
    google_submission_id: str
    google_user_id: str
    student_id: UUID
    student_ref: str
    student_name: str | None = None
    google_state: str | None = None
    late: bool = False
    detected_at: datetime | None = None
    last_synced_at: datetime | None = None
    version: int
    version_count: int = 1
    state: SubmissionPipelineState
    correction_state: CorrectionPipelineState
    eligibility: Eligibility
    relevance: Relevance
    decision_reasons: list[dict[str, object]] = Field(default_factory=list)
    inspection: dict[str, object] = Field(default_factory=dict)
    attachments: list[MonitorAttachmentRead] = Field(default_factory=list)
    correction_job_id: UUID | None = None
    document_id: UUID | None = None
    last_error: str | None = None
    last_error_code: str | None = None
    superseded_at: datetime | None = None
    resolution_note: str | None = None


class MonitorStateRead(BaseModel):
    coursework_link_id: UUID
    assignment_id: UUID
    assignment_name: str
    course_id: str
    coursework_id: str | None = None
    course_name: str | None = None
    enabled: bool
    paused: bool
    auto_queue: bool
    relevance_policy: RelevancePolicy
    interval_seconds: int
    health: MonitorHealth
    next_poll_at: datetime | None = None
    last_polled_at: datetime | None = None
    last_poll_status: str | None = None
    last_poll_error: str | None = None
    last_error_code: str | None = None
    consecutive_failures: int = 0
    last_counts: dict[str, int] = Field(default_factory=dict)
    monitoring_since: datetime | None = None
    enabled_by_subject: str | None = None
    expected_students: int = 0
    submitted_students: int = 0
    awaiting_review: int = 0
    ready_submissions: int = 0
    queued_corrections: int = 0
    processing_corrections: int = 0
    completed_corrections: int = 0
    failed_corrections: int = 0


class MonitorOverviewRead(BaseModel):
    workspace_id: UUID
    monitoring_enabled_on_server: bool
    states: list[MonitorStateRead] = Field(default_factory=list)
    recent_runs: list[dict[str, object]] = Field(default_factory=list)


class MonitorSyncRead(BaseModel):
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED", "SKIPPED"]
    coursework_link_id: UUID
    counts: dict[str, int] = Field(default_factory=dict)
    problems: list[str] = Field(default_factory=list)
    state: MonitorStateRead


class MonitorToggleRequest(BaseModel):
    enabled: bool | None = None
    paused: bool | None = None
    auto_queue: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=86_400)
    relevance_policy: RelevancePolicy | None = None
    reason: str | None = Field(default=None, max_length=500)


class MonitorResolveRequest(BaseModel):
    """A teacher's explicit decision about a submission awaiting review."""

    action: Literal["ACCEPT", "IGNORE", "REQUEUE"]
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Resolving a submission needs a short note.")
        return cleaned


class MonitorIgnoreRequest(BaseModel):
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Ignoring a submission needs a short note.")
        return cleaned


class MonitorRetryRead(BaseModel):
    submission_link_id: UUID
    state: SubmissionPipelineState
    correction_state: CorrectionPipelineState
    retried: bool
    message: str


class MonitorJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MonitoringHealthRead(BaseModel):
    configured: bool
    server_monitoring_enabled: bool
    monitored_assignments: int
    due_assignments: int
    failing_assignments: int
    last_run_at: datetime | None = None
