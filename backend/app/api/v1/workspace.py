"""Workspace aggregation and audit routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.workspace import (
    AuditEventRead,
    DashboardRead,
    GradebookRead,
    InboxItemRead,
    MarkingHistoryPage,
    NotificationRead,
    ReportRow,
)
from ...services.workspace import WorkspaceService
from ..deps import get_principal

router = APIRouter(tags=["workspace"])


@router.get("/workspaces/{workspace_id}/dashboard", response_model=DashboardRead)
def get_dashboard(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> DashboardRead:
    return WorkspaceService(session).dashboard(principal, workspace_id)


@router.get("/workspaces/{workspace_id}/inbox", response_model=list[InboxItemRead])
def get_inbox(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[InboxItemRead]:
    return WorkspaceService(session).inbox(principal, workspace_id)


@router.get("/workspaces/{workspace_id}/reports", response_model=list[ReportRow])
def get_reports(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[ReportRow]:
    return WorkspaceService(session).reports(principal, workspace_id)


@router.get("/workspaces/{workspace_id}/gradebook", response_model=GradebookRead)
def get_gradebook(
    workspace_id: uuid.UUID,
    assignment_id: uuid.UUID | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> GradebookRead:
    return WorkspaceService(session).gradebook(principal, workspace_id, assignment_id)


@router.get(
    "/workspaces/{workspace_id}/notifications", response_model=list[NotificationRead]
)
def get_notifications(
    workspace_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[NotificationRead]:
    return WorkspaceService(session).notifications(principal, workspace_id, limit=limit)


@router.get("/workspaces/{workspace_id}/marking-history", response_model=MarkingHistoryPage)
def get_marking_history(
    workspace_id: uuid.UUID,
    state: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MarkingHistoryPage:
    return WorkspaceService(session).marking_history(
        principal, workspace_id, limit=limit, offset=offset, state=state
    )


@router.get("/workspaces/{workspace_id}/audit", response_model=list[AuditEventRead])
def get_workspace_audit(
    workspace_id: uuid.UUID,
    action: str | None = Query(default=None, max_length=120),
    entity_type: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[AuditEventRead]:
    return WorkspaceService(session).audit(
        principal,
        workspace_id,
        action=action,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/audit", response_model=list[AuditEventRead])
def get_platform_audit(
    action: str | None = Query(default=None, max_length=120),
    entity_type: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[AuditEventRead]:
    return WorkspaceService(session).platform_audit(
        principal,
        action=action,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )
