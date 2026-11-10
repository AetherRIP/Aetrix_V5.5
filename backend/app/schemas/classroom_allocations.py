"""Contracts for Google Classroom course allocation.

A course row is explicitly either verified against Google or not.  A workspace
course sync sets ``VERIFIED``; an operator-recorded row stays ``UNVERIFIED``
until Google lists it.  The interface must show the difference rather than
implying that every recorded course was discovered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

CourseState = Literal["ACTIVE", "ARCHIVED", "DELETED"]
Verification = Literal["UNVERIFIED", "VERIFIED"]
AllocationStatus = Literal["ACTIVE", "RELEASED"]
AllocationOrigin = Literal["ALLOCATE", "REASSIGN"]


class ClassroomClassCreate(BaseModel):
    course_id: str = Field(min_length=3, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=300)
    section: str | None = Field(default=None, max_length=200)
    owner_email: str | None = Field(default=None, max_length=320)
    #: The operator is attesting that this course was read from Classroom.  The
    #: API cannot verify it because no Classroom integration exists, so the row
    #: is stored as UNVERIFIED and the interface says so.
    attested: Literal[True]

    @field_validator("course_id", "name", "section", "owner_email", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class ClassroomClassRead(BaseModel):
    id: UUID
    course_id: str
    name: str
    section: str | None
    course_state: CourseState
    verification: Verification
    source: str
    owner_email: str | None
    synced_at: datetime | None
    created_at: datetime


class WorkspaceTargetRead(BaseModel):
    id: UUID
    name: str
    slug: str
    owner_label: str | None
    owner_email: str | None
    active_allocations: int


class AllocationRead(BaseModel):
    id: UUID
    classroom_class_id: UUID
    course_id: str
    class_name: str
    class_section: str | None
    verification: Verification
    workspace_id: UUID
    workspace_name: str
    status: AllocationStatus
    origin: AllocationOrigin
    allocated_by_subject: str
    allocated_by_label: str | None
    allocated_at: datetime
    released_by_subject: str | None
    released_by_label: str | None
    released_at: datetime | None
    release_reason: str | None
    reason: str | None
    previous_allocation_id: UUID | None


class AllocationPage(BaseModel):
    items: list[AllocationRead] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class AllocationCreate(BaseModel):
    classroom_class_id: UUID
    workspace_id: UUID
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class AllocationReassign(BaseModel):
    workspace_id: UUID
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return value.strip()


class AllocationRelease(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class WorkspaceAllocationRead(BaseModel):
    """The teacher's read-only view of what their workspace owns."""

    id: UUID
    course_id: str
    class_name: str
    class_section: str | None
    verification: Verification
    allocated_at: datetime
    allocated_by_label: str | None


class AllocationOperationRead(BaseModel):
    name: str
    supported: bool
    note: str


class ClassroomCapabilityRead(BaseModel):
    allocation_available: bool
    discovery_configured: bool
    verification: Verification
    reason: str
    operations: list[AllocationOperationRead] = Field(default_factory=list)
