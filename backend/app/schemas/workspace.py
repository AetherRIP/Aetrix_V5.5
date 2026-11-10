"""Workspace aggregation: dashboard, inbox, reports, gradebook and audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardRead(BaseModel):
    assignments: int
    submissions: int
    jobs_active: int
    awaiting_review: int
    failed_jobs: int
    approved_results: int
    recent_jobs: list[dict[str, Any]] = Field(default_factory=list)


class InboxItemRead(BaseModel):
    """One actionable event.

    ``read`` is null because read-state is not stored: there is no table for it,
    and reporting every item as unread would be an invented figure.  The screen
    shows the item and its action; it does not pretend to know what was seen.
    """

    id: str
    kind: str
    title: str
    detail: str
    created_at: datetime
    job_id: UUID
    submission_id: UUID | None = None
    read: bool | None = None


class ReportRow(BaseModel):
    assignment_id: UUID
    name: str
    submissions: int
    jobs_completed: int
    awaiting_review: int
    failed: int
    approved: int
    total_marks: int
    mean_percent: float | None
    state: str


class GradebookAssignment(BaseModel):
    id: UUID
    name: str
    total_marks: int
    approved_jobs: int
    provisional_jobs: int


class GradebookCell(BaseModel):
    assignment_id: UUID
    #: Null when this student has no submission for that assignment; a filled-in
    #: placeholder identifier would be invented data.
    submission_id: UUID | None = None
    job_id: UUID | None
    job_state: str | None
    awarded: int | None
    total: int
    approved: bool
    review_required: int


class GradebookStudent(BaseModel):
    student_ref: str
    cells: list[GradebookCell]
    approved_awarded: int
    approved_possible: int


class GradebookRead(BaseModel):
    assignments: list[GradebookAssignment]
    students: list[GradebookStudent]
    approved_jobs: int
    provisional_jobs: int
    mean_percent: float | None
    state: str


class NotificationRead(BaseModel):
    """One real event the account can act on or acknowledge.

    There is no notification table and no read-state: an item is derived from a
    job, an approval or a pending invitation, and ``read`` is null rather than a
    fabricated flag.  ``id`` is namespaced by source so two kinds cannot collide.
    """

    id: str
    kind: str
    title: str
    detail: str
    created_at: datetime
    job_id: UUID | None = None
    submission_id: UUID | None = None
    invitation_id: UUID | None = None
    read: bool | None = None


class MarkingHistoryRow(BaseModel):
    job_id: UUID
    submission_id: UUID
    assignment_id: UUID
    assignment_name: str | None
    student_ref: str | None
    state: str
    progress: float
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    awarded: int
    total: int
    review_required: int
    approved: bool
    approved_at: datetime | None
    approved_by_label: str | None
    updated_at: datetime


class MarkingHistoryPage(BaseModel):
    items: list[MarkingHistoryRow] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class AuditEventRead(BaseModel):
    id: UUID
    created_at: datetime
    action: str
    entity_type: str
    entity_id: str
    actor_type: str
    actor_id: str | None
    actor_label: str | None
    detail: dict[str, Any]
