"""Contracts for the Google Classroom integration.

Every model here is a projection of stored state.  None of them carries a token,
a client secret or a raw Google payload: a publication record says which grade
was written and what Google answered, never the bearer token that wrote it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RosterStatus = Literal["ACTIVE", "REMOVED"]
MatchSource = Literal["EXTERNAL_ID", "CREATED", "MANUAL"]
CourseworkState = Literal["DRAFT", "PUBLISHING", "PUBLISHED", "FAILED"]
SubmissionState = Literal[
    "DISCOVERED",
    "INGESTED",
    "INGEST_FAILED",
    "CORRECTING",
    "CORRECTED",
    "WITHDRAWN",
]
PublicationState = Literal["SUCCEEDED", "FAILED", "UNKNOWN", "CONFLICT"]
SyncKind = Literal["COURSES", "ROSTER", "SUBMISSIONS"]
RunStatus = Literal["RUNNING", "SUCCEEDED", "PARTIAL", "FAILED"]


class ClassroomSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: SyncKind
    status: RunStatus
    course_id: str | None = None
    actor_subject: str
    counts: dict[str, int] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ClassroomCourseRead(BaseModel):
    """A discovered course with its allocation, as platform administration sees it."""

    id: UUID
    course_id: str
    name: str
    section: str | None
    room: str | None = None
    course_state: Literal["ACTIVE", "ARCHIVED", "DELETED"]
    teacher_name: str | None = None
    owner_email: str | None = None
    verification: Literal["UNVERIFIED", "VERIFIED"]
    synced_at: datetime | None
    workspace_id: UUID | None = None
    workspace_name: str | None = None
    allocation_id: UUID | None = None
    allocated_at: datetime | None = None


class TeacherCourseRead(BaseModel):
    """One allocated course in the teacher's workspace."""

    allocation_id: UUID
    classroom_class_id: UUID
    course_id: str
    name: str
    section: str | None
    course_state: str
    students: int
    coursework: int


class RosterEntryRead(BaseModel):
    google_user_id: str
    student_id: UUID
    student_ref: str
    display_name: str | None
    google_name: str | None
    email: str | None
    status: RosterStatus
    match_source: MatchSource
    last_seen_at: datetime


class RosterSyncRead(BaseModel):
    status: Literal["SUCCEEDED", "PARTIAL"]
    course_id: str
    counts: dict[str, int]
    truncated: bool
    entries: list[RosterEntryRead] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class RosterLinkRequest(BaseModel):
    """Attach one Google identity to an existing Aetrix student explicitly."""

    google_user_id: str = Field(min_length=1, max_length=200)
    student_id: UUID
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("google_user_id", "reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field cannot be empty.")
        return cleaned


class CourseworkCreate(BaseModel):
    assignment_id: UUID
    classroom_class_id: UUID
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=30_000)
    due_at: datetime | None = None
    max_points: Decimal | None = Field(default=None, ge=0, le=10_000)

    @field_validator("title", "description")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CourseworkUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=30_000)
    due_at: datetime | None = None
    max_points: Decimal | None = Field(default=None, ge=0, le=10_000)


class CourseworkRead(BaseModel):
    id: UUID
    assignment_id: UUID
    assignment_name: str
    classroom_class_id: UUID
    course_id: str
    coursework_id: str | None
    state: CourseworkState
    title: str
    description: str | None
    due_at: datetime | None
    max_points: Decimal | None
    publish_attempts: int
    published_at: datetime | None
    published_by_subject: str | None
    last_error_code: str | None
    last_error_message: str | None
    submissions: int = 0
    created_at: datetime


class SubmissionSyncRequest(BaseModel):
    coursework_link_id: UUID
    #: Fetch every submission, or only those Google reports as turned in.
    only_turned_in: bool = True


class SubmissionSyncRead(BaseModel):
    status: Literal["SUCCEEDED", "PARTIAL"]
    coursework_link_id: UUID
    counts: dict[str, int]
    truncated: bool
    submissions: list[SubmissionRead] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class SubmissionRead(BaseModel):
    id: UUID
    coursework_link_id: UUID
    assignment_id: UUID
    google_submission_id: str
    google_user_id: str
    student_id: UUID
    student_ref: str
    student_name: str | None
    state: SubmissionState
    submission_state: str | None
    late: bool
    submission_id: UUID | None
    document_id: UUID | None
    attachments: list[dict[str, object]] = Field(default_factory=list)
    content_hash: str | None
    last_synced_at: datetime | None
    ingest_error: str | None
    correction_job_id: UUID | None
    correction_state: str | None
    approved_total: Decimal | None
    approved_max: Decimal | None
    approved_at: datetime | None
    last_publication_state: PublicationState | None
    created_at: datetime


class CorrectionStartRead(BaseModel):
    submission_link_id: UUID
    job_id: UUID
    job_state: str
    created: bool


class ReviewRead(BaseModel):
    """The uncertain decisions that block approval, and the totals so far."""

    submission_link_id: UUID
    job_id: UUID | None
    job_state: str | None
    total: Decimal
    maximum: Decimal
    uncertain: list[dict[str, object]] = Field(default_factory=list)
    approvable: bool
    reason: str


class ApprovalRequest(BaseModel):
    """A reviewer's explicit approval of the final result."""

    confirm: bool
    note: str | None = Field(default=None, max_length=500)

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Approval must be confirmed explicitly.")
        return value


class GradePublishRequest(BaseModel):
    """Publishing is never automatic: the caller confirms and states why."""

    confirm: bool
    reason: str = Field(min_length=5, max_length=500)
    #: Write ``assignedGrade`` (the grade a student sees) or ``draftGrade``
    #: (a provisional mark only a teacher sees).  A final grade is the default.
    grade_field: Literal["assignedGrade", "draftGrade"] = "assignedGrade"
    #: Return the work to the student after writing the grade.  Google only
    #: allows this when the submission is TURNED_IN.
    return_to_student: bool = False
    #: Overwrite an assigned grade that Google already holds and that this
    #: integration did not write.  Without it, the write is refused.
    allow_overwrite_external: bool = False

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Grade publication must be confirmed explicitly.")
        return value

    @field_validator("reason")
    @classmethod
    def _reason_shape(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Publishing a grade needs a stated reason.")
        return cleaned


class GradePublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    submission_link_id: UUID
    state: PublicationState
    draft_grade: Decimal | None
    assigned_grade: Decimal | None
    approved_by_subject: str
    approved_by_role: str
    authorized_by_subject: str
    reason: str | None
    external_grade_before: Decimal | None
    response_detail: dict[str, object] = Field(default_factory=dict)
    error_code: str | None
    error_message: str | None
    attempted_at: datetime
    resolved_at: datetime | None
    created_at: datetime


class PublicationStatusRead(BaseModel):
    submission_link_id: UUID
    approved_total: Decimal | None
    published: bool
    state: PublicationState | None
    attempts: int
    history: list[GradePublicationRead] = Field(default_factory=list)
