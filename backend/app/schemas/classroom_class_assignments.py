"""Contracts for explicit user-to-Classroom-class assignments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ClassroomClassAssignmentCreate(BaseModel):
    """Assign one workspace teacher or reviewer to the course in the path."""

    user_id: UUID


class ClassroomClassAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    allocation_id: UUID
    classroom_class_id: UUID
    course_id: str
    class_name: str
    user_id: UUID
    user_label: str | None
    user_email: str | None
    user_role: str
    assigned_by_label: str | None
    assigned_at: datetime