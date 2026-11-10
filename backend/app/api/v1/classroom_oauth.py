"""Google Classroom authorisation and course sync routes.

The workspace is never named in a request: it is the verified principal's
tenant.  Reading the connection status is open to any workspace member; starting
authorisation, completing it, syncing and disconnecting require an owner or
administrator role, checked in the service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.classroom_oauth import (
    ClassroomAuthorizationComplete,
    ClassroomAuthorizationStart,
    ClassroomConnectionRead,
    ClassroomDisconnectRead,
    ClassroomSyncRead,
)
from ...services.classroom_oauth import ClassroomOAuthService
from ..deps import get_principal

router = APIRouter(prefix="/classroom", tags=["google classroom"])


def get_classroom_oauth(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ClassroomOAuthService:
    return ClassroomOAuthService(session, settings)


@router.get("/connection", response_model=ClassroomConnectionRead)
def connection(
    principal: Principal = Depends(get_principal),
    service: ClassroomOAuthService = Depends(get_classroom_oauth),
) -> ClassroomConnectionRead:
    return service.connection(principal)


@router.post("/oauth/start", response_model=ClassroomAuthorizationStart)
def start_authorization(
    principal: Principal = Depends(get_principal),
    service: ClassroomOAuthService = Depends(get_classroom_oauth),
) -> ClassroomAuthorizationStart:
    return service.start(principal)


@router.post("/oauth/complete", response_model=ClassroomConnectionRead)
def complete_authorization(
    payload: ClassroomAuthorizationComplete,
    principal: Principal = Depends(get_principal),
    service: ClassroomOAuthService = Depends(get_classroom_oauth),
) -> ClassroomConnectionRead:
    return service.complete(principal, code=payload.code, state=payload.state)


@router.post("/sync", response_model=ClassroomSyncRead)
def sync_courses(
    principal: Principal = Depends(get_principal),
    service: ClassroomOAuthService = Depends(get_classroom_oauth),
) -> ClassroomSyncRead:
    return service.sync(principal)


@router.post("/disconnect", response_model=ClassroomDisconnectRead)
def disconnect(
    principal: Principal = Depends(get_principal),
    service: ClassroomOAuthService = Depends(get_classroom_oauth),
) -> ClassroomDisconnectRead:
    return service.disconnect(principal)
