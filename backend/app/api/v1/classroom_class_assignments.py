"""Class-level assignment management for a workspace's Classroom courses."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.classroom_class_assignments import (
    ClassroomClassAssignmentCreate,
    ClassroomClassAssignmentRead,
)
from ...services.classroom_class_assignments import ClassroomClassAssignmentService
from ..deps import get_principal

router = APIRouter(tags=["classroom class assignments"])


def _service(session: Session = Depends(get_db_session)) -> ClassroomClassAssignmentService:
    return ClassroomClassAssignmentService(session)


@router.get(
    "/workspaces/{workspace_id}/classroom/courses/{course_id}/assignments",
    response_model=list[ClassroomClassAssignmentRead],
)
def list_class_assignments(
    workspace_id: uuid.UUID,
    course_id: str,
    principal: Principal = Depends(get_principal),
    service: ClassroomClassAssignmentService = Depends(_service),
) -> list[ClassroomClassAssignmentRead]:
    return service.list_for_course(principal, workspace_id, course_id)


@router.post(
    "/workspaces/{workspace_id}/classroom/courses/{course_id}/assignments",
    response_model=ClassroomClassAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_class_assignment(
    workspace_id: uuid.UUID,
    course_id: str,
    payload: ClassroomClassAssignmentCreate,
    principal: Principal = Depends(get_principal),
    service: ClassroomClassAssignmentService = Depends(_service),
) -> ClassroomClassAssignmentRead:
    return service.create(principal, workspace_id, course_id, payload)


@router.delete(
    "/workspaces/{workspace_id}/classroom/courses/{course_id}/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_class_assignment(
    workspace_id: uuid.UUID,
    course_id: str,
    assignment_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomClassAssignmentService = Depends(_service),
) -> None:
    service.remove(principal, workspace_id, course_id, assignment_id)