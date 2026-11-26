"""Teacher-facing routes for automatic submission monitoring.

Every route is workspace-scoped on the verified tenant and additionally checks
the class allocation: an assistant assigned to one class cannot see another
class in the same workspace, and a class belonging to another workspace is
reported as missing rather than forbidden.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...classroom_monitoring.monitor import ClassroomMonitorService
from ...classroom_monitoring.schemas import (
    MonitorIgnoreRequest,
    MonitorOverviewRead,
    MonitorResolveRequest,
    MonitorRetryRead,
    MonitorStateRead,
    MonitorSubmissionRead,
    MonitorSyncRead,
    MonitorToggleRequest,
)
from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.session import get_db_session
from ...storage.base import Storage
from ..deps import get_principal, get_storage

router = APIRouter(tags=["classroom monitoring"])

BASE = "/workspaces/{workspace_id}/classroom"


def _monitor(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> ClassroomMonitorService:
    return ClassroomMonitorService(session, settings, storage)


def _workspace(principal: Principal, workspace_id: uuid.UUID) -> uuid.UUID:
    if workspace_id != principal.tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
    return workspace_id


@router.get(f"{BASE}/monitoring", response_model=MonitorOverviewRead)
def monitoring_overview(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> MonitorOverviewRead:
    _workspace(principal, workspace_id)
    return service.overview(principal)


@router.get(f"{BASE}/coursework/{{link_id}}/monitoring", response_model=MonitorStateRead)
def monitor_state(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> MonitorStateRead:
    _workspace(principal, workspace_id)
    return service.read_state(principal, link_id)


@router.patch(f"{BASE}/coursework/{{link_id}}/monitoring", response_model=MonitorStateRead)
def update_monitoring(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: MonitorToggleRequest,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> MonitorStateRead:
    _workspace(principal, workspace_id)
    return service.update(principal, link_id, payload)


@router.post(f"{BASE}/coursework/{{link_id}}/monitoring/sync", response_model=MonitorSyncRead)
def sync_monitoring(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> MonitorSyncRead:
    _workspace(principal, workspace_id)
    return service.manual_sync(principal, link_id)


@router.get(
    f"{BASE}/coursework/{{link_id}}/monitoring/submissions",
    response_model=list[MonitorSubmissionRead],
)
def monitored_submissions(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> list[MonitorSubmissionRead]:
    _workspace(principal, workspace_id)
    return service.submissions(principal, link_id)


@router.post(
    f"{BASE}/submissions/{{link_id}}/monitoring/retry",
    response_model=MonitorRetryRead,
)
def retry_submission(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> MonitorRetryRead:
    _workspace(principal, workspace_id)
    return service.retry(principal, link_id)


@router.post(
    f"{BASE}/submissions/{{link_id}}/monitoring/ignore",
    response_model=MonitorSubmissionRead,
)
def ignore_submission(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: MonitorIgnoreRequest,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> MonitorSubmissionRead:
    _workspace(principal, workspace_id)
    return service.ignore(principal, link_id, payload)


@router.post(
    f"{BASE}/submissions/{{link_id}}/monitoring/resolve",
    response_model=MonitorSubmissionRead,
)
def resolve_submission(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: MonitorResolveRequest,
    principal: Principal = Depends(get_principal),
    service: ClassroomMonitorService = Depends(_monitor),
) -> MonitorSubmissionRead:
    _workspace(principal, workspace_id)
    return service.resolve(principal, link_id, payload)
