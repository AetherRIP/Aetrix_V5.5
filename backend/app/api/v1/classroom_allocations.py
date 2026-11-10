"""Platform Classroom course allocation and the teacher's read-only view.

Every administrative route is gated on the verified platform claim.  The
workspace route is tenant-scoped from the principal: asking for another
workspace looks like a missing workspace, not a forbidden one.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.classroom_allocations import (
    AllocationCreate,
    AllocationPage,
    AllocationRead,
    AllocationReassign,
    AllocationRelease,
    ClassroomCapabilityRead,
    ClassroomClassCreate,
    ClassroomClassRead,
    WorkspaceAllocationRead,
    WorkspaceTargetRead,
)
from ...services.classroom_allocations import ClassroomAllocationService
from ..deps import get_principal
from .admin_accounts import require_platform_admin

router = APIRouter(tags=["classroom allocation"])


def get_classroom_allocations(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ClassroomAllocationService:
    return ClassroomAllocationService(session, settings)


@router.get("/admin/allocations/capability", response_model=ClassroomCapabilityRead)
def capability(
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> ClassroomCapabilityRead:
    return service.capability()


@router.get("/admin/allocations/workspaces", response_model=list[WorkspaceTargetRead])
def list_workspaces(
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> list[WorkspaceTargetRead]:
    return service.list_workspaces(principal)


@router.get(
    "/admin/allocations/available-classes", response_model=list[ClassroomClassRead]
)
def available_classes(
    q: Annotated[str | None, Query(max_length=200)] = None,
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> list[ClassroomClassRead]:
    return service.list_available_classes(principal, q=q)


@router.get("/admin/allocations", response_model=AllocationPage)
def list_allocations(
    status: Literal["ALL", "ACTIVE", "RELEASED"] = "ALL",
    workspace_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> AllocationPage:
    return service.list_allocations(
        principal,
        status=status,
        workspace_id=workspace_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/admin/allocations/classes",
    response_model=ClassroomClassRead,
    status_code=201,
)
def register_class(
    payload: ClassroomClassCreate,
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> ClassroomClassRead:
    return service.register_class(principal, payload)


@router.post("/admin/allocations", response_model=AllocationRead, status_code=201)
def allocate(
    payload: AllocationCreate,
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> AllocationRead:
    return service.allocate(principal, payload)


@router.post(
    "/admin/allocations/{allocation_id}/release", response_model=AllocationRead
)
def release(
    allocation_id: uuid.UUID,
    payload: AllocationRelease,
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> AllocationRead:
    return service.release(principal, allocation_id, payload)


@router.post(
    "/admin/allocations/{allocation_id}/reassign", response_model=AllocationRead
)
def reassign(
    allocation_id: uuid.UUID,
    payload: AllocationReassign,
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> AllocationRead:
    return service.reassign(principal, allocation_id, payload)


@router.get(
    "/workspaces/{workspace_id}/classroom-allocations",
    response_model=list[WorkspaceAllocationRead],
)
def workspace_allocations(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomAllocationService = Depends(get_classroom_allocations),
) -> list[WorkspaceAllocationRead]:
    return service.workspace_allocations(principal, workspace_id)
