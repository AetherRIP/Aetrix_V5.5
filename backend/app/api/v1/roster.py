"""Workspace classes and the student roster.

Every route resolves the workspace from the verified principal; a workspace id
in the path that is not the caller's is a 404, never a cross-tenant read.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.roster import (
    ClassCreate,
    ClassRead,
    ClassUpdate,
    StudentCreate,
    StudentImportResult,
    StudentRead,
    StudentUpdate,
)
from ...services.roster import MAX_IMPORT_BYTES, RosterService
from ..deps import get_principal

router = APIRouter(tags=["roster"])


@router.get("/workspaces/{workspace_id}/classes", response_model=list[ClassRead])
def list_classes(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[ClassRead]:
    return RosterService(session).list_classes(principal, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/classes",
    response_model=ClassRead,
    status_code=status.HTTP_201_CREATED,
)
def create_class(
    workspace_id: uuid.UUID,
    payload: ClassCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ClassRead:
    return RosterService(session).create_class(principal, workspace_id, payload)


@router.patch("/classes/{class_id}", response_model=ClassRead)
def update_class(
    class_id: uuid.UUID,
    payload: ClassUpdate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ClassRead:
    return RosterService(session).update_class(principal, class_id, payload)


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class(
    class_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> None:
    RosterService(session).delete_class(principal, class_id)


@router.get("/workspaces/{workspace_id}/students", response_model=list[StudentRead])
def list_students(
    workspace_id: uuid.UUID,
    class_id: uuid.UUID | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[StudentRead]:
    return RosterService(session).list_students(
        principal, workspace_id, class_id=class_id
    )


@router.post(
    "/workspaces/{workspace_id}/students",
    response_model=StudentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_student(
    workspace_id: uuid.UUID,
    payload: StudentCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> StudentRead:
    return RosterService(session).create_student(principal, workspace_id, payload)


_CSV_CONTENT_TYPES = {
    "text/csv",
    "text/plain",
    "application/csv",
    "application/vnd.ms-excel",
}


@router.post(
    "/workspaces/{workspace_id}/students/import", response_model=StudentImportResult
)
async def import_students(
    workspace_id: uuid.UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> StudentImportResult:
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    filename = (file.filename or "").lower()
    if content_type not in _CSV_CONTENT_TYPES and not filename.endswith(".csv"):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "The roster import accepts a CSV file only.",
            status_code=415,
            details={"accepted": sorted(_CSV_CONTENT_TYPES), "received": content_type or None},
        )
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "The CSV is larger than the 1 MB import limit.",
            status_code=413,
            details={"max_bytes": MAX_IMPORT_BYTES},
        )
    return RosterService(session).import_students(principal, workspace_id, data)


@router.patch("/students/{student_id}", response_model=StudentRead)
def update_student(
    student_id: uuid.UUID,
    payload: StudentUpdate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> StudentRead:
    return RosterService(session).update_student(principal, student_id, payload)


@router.delete("/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(
    student_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> None:
    RosterService(session).delete_student(principal, student_id)
