"""Google Classroom integration routes.

Two audiences, one integration:

``/admin/classroom``
    Platform administration.  It owns the single central Google authorisation,
    discovers courses and sees which workspace owns each one.  Every route is
    gated on the verified platform claim.

``/workspaces/{workspace_id}/classroom``
    A workspace's teachers.  A workspace id that is not the caller's is a 404,
    exactly like one that does not exist, and every service call filters on the
    verified tenant.  No route accepts a Google token or returns one.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.classroom_integration import (
    ApprovalRequest,
    ClassroomCourseRead,
    ClassroomSyncRunRead,
    CorrectionStartRead,
    CourseworkCreate,
    CourseworkRead,
    CourseworkUpdate,
    GradePublicationRead,
    GradePublishRequest,
    PublicationStatusRead,
    ReviewRead,
    RosterEntryRead,
    RosterLinkRequest,
    RosterSyncRead,
    SubmissionRead,
    SubmissionSyncRead,
    SubmissionSyncRequest,
    TeacherCourseRead,
)
from ...schemas.classroom_oauth import (
    ClassroomAuthorizationComplete,
    ClassroomAuthorizationStart,
    ClassroomConnectionRead,
    ClassroomDisconnectRead,
    ClassroomSyncRead,
)
from ...services.classroom_allocations import ClassroomAllocationService
from ...services.classroom_assignments import ClassroomCourseworkService
from ...services.classroom_grades import ClassroomGradeService
from ...services.classroom_oauth import ClassroomOAuthService
from ...services.classroom_roster import ClassroomRosterService
from ...services.classroom_submissions import ClassroomSubmissionService
from ...storage.base import Storage
from ..deps import get_principal, get_storage
from .admin_accounts import require_platform_admin

router = APIRouter(tags=["google classroom"])

ADMIN_BASE = "/admin/classroom"


def _oauth(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ClassroomOAuthService:
    return ClassroomOAuthService(session, settings)


def _roster(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ClassroomRosterService:
    return ClassroomRosterService(session, settings)


def _coursework(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ClassroomCourseworkService:
    return ClassroomCourseworkService(session, settings)


def _submissions(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> ClassroomSubmissionService:
    return ClassroomSubmissionService(session, settings, storage)


def _grades(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ClassroomGradeService:
    return ClassroomGradeService(session, settings)


def _workspace(principal: Principal, workspace_id: uuid.UUID) -> uuid.UUID:
    if workspace_id != principal.tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
    return workspace_id


# -- platform administration ----------------------------------------------


@router.get(f"{ADMIN_BASE}/connection", response_model=ClassroomConnectionRead)
def admin_connection(
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomOAuthService = Depends(_oauth),
) -> ClassroomConnectionRead:
    return service.connection(principal)


@router.post(
    f"{ADMIN_BASE}/oauth/start", response_model=ClassroomAuthorizationStart
)
def admin_start_authorization(
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomOAuthService = Depends(_oauth),
) -> ClassroomAuthorizationStart:
    return service.start(principal)


@router.post(
    f"{ADMIN_BASE}/oauth/complete", response_model=ClassroomConnectionRead
)
def admin_complete_authorization(
    payload: ClassroomAuthorizationComplete,
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomOAuthService = Depends(_oauth),
) -> ClassroomConnectionRead:
    return service.complete(principal, code=payload.code, state=payload.state)


@router.post(f"{ADMIN_BASE}/sync", response_model=ClassroomSyncRead)
def admin_sync_courses(
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomOAuthService = Depends(_oauth),
) -> ClassroomSyncRead:
    return service.sync(principal)


@router.post(f"{ADMIN_BASE}/disconnect", response_model=ClassroomDisconnectRead)
def admin_disconnect(
    principal: Principal = Depends(require_platform_admin),
    service: ClassroomOAuthService = Depends(_oauth),
) -> ClassroomDisconnectRead:
    return service.disconnect(principal)


@router.get(f"{ADMIN_BASE}/courses", response_model=list[ClassroomCourseRead])
def admin_courses(
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[ClassroomCourseRead]:
    return ClassroomAllocationService(session, settings).list_courses(
        principal, q=q, limit=limit, offset=offset
    )


@router.get(
    f"{ADMIN_BASE}/sync-runs", response_model=list[ClassroomSyncRunRead]
)
def admin_sync_runs(
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[ClassroomSyncRunRead]:
    return ClassroomAllocationService(session, settings).sync_runs(
        principal, limit=limit
    )


# -- teacher: courses and roster ------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/classroom/courses",
    response_model=list[TeacherCourseRead],
)
def workspace_courses(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomRosterService = Depends(_roster),
) -> list[TeacherCourseRead]:
    _workspace(principal, workspace_id)
    return service.courses(principal)


@router.get(
    "/workspaces/{workspace_id}/classroom/courses/{course_id}/roster",
    response_model=list[RosterEntryRead],
)
def workspace_roster(
    workspace_id: uuid.UUID,
    course_id: str,
    principal: Principal = Depends(get_principal),
    service: ClassroomRosterService = Depends(_roster),
) -> list[RosterEntryRead]:
    _workspace(principal, workspace_id)
    return service.roster(principal, course_id)


@router.post(
    "/workspaces/{workspace_id}/classroom/courses/{course_id}/sync-roster",
    response_model=RosterSyncRead,
)
def workspace_sync_roster(
    workspace_id: uuid.UUID,
    course_id: str,
    principal: Principal = Depends(get_principal),
    service: ClassroomRosterService = Depends(_roster),
) -> RosterSyncRead:
    _workspace(principal, workspace_id)
    return service.sync(principal, course_id)


@router.post(
    "/workspaces/{workspace_id}/classroom/courses/{course_id}/roster/link",
    response_model=RosterEntryRead,
)
def workspace_link_roster(
    workspace_id: uuid.UUID,
    course_id: str,
    payload: RosterLinkRequest,
    principal: Principal = Depends(get_principal),
    service: ClassroomRosterService = Depends(_roster),
) -> RosterEntryRead:
    _workspace(principal, workspace_id)
    return service.link(principal, course_id, payload)


# -- teacher: coursework --------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/classroom/coursework",
    response_model=list[CourseworkRead],
)
def workspace_coursework(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomCourseworkService = Depends(_coursework),
) -> list[CourseworkRead]:
    _workspace(principal, workspace_id)
    return service.list(principal)


@router.post(
    "/workspaces/{workspace_id}/classroom/coursework",
    response_model=CourseworkRead,
    status_code=status.HTTP_201_CREATED,
)
def workspace_create_coursework(
    workspace_id: uuid.UUID,
    payload: CourseworkCreate,
    principal: Principal = Depends(get_principal),
    service: ClassroomCourseworkService = Depends(_coursework),
) -> CourseworkRead:
    _workspace(principal, workspace_id)
    return service.create(principal, payload)


@router.post(
    "/workspaces/{workspace_id}/classroom/coursework/{link_id}/publish",
    response_model=CourseworkRead,
)
def workspace_publish_coursework(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomCourseworkService = Depends(_coursework),
) -> CourseworkRead:
    _workspace(principal, workspace_id)
    return service.publish(principal, link_id)


@router.patch(
    "/workspaces/{workspace_id}/classroom/coursework/{link_id}",
    response_model=CourseworkRead,
)
def workspace_update_coursework(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: CourseworkUpdate,
    principal: Principal = Depends(get_principal),
    service: ClassroomCourseworkService = Depends(_coursework),
) -> CourseworkRead:
    _workspace(principal, workspace_id)
    return service.update(principal, link_id, payload)


# -- teacher: submissions -------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/classroom/coursework/{link_id}/submissions/sync",
    response_model=SubmissionSyncRead,
)
def workspace_sync_submissions(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: SubmissionSyncRequest | None = None,
    principal: Principal = Depends(get_principal),
    service: ClassroomSubmissionService = Depends(_submissions),
) -> SubmissionSyncRead:
    _workspace(principal, workspace_id)
    request = payload or SubmissionSyncRequest(coursework_link_id=link_id)
    if request.coursework_link_id != link_id:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "The coursework link in the body does not match the path.",
        )
    return service.sync(principal, request)


@router.get(
    "/workspaces/{workspace_id}/classroom/coursework/{link_id}/submissions",
    response_model=list[SubmissionRead],
)
def workspace_submissions(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomSubmissionService = Depends(_submissions),
) -> list[SubmissionRead]:
    _workspace(principal, workspace_id)
    return service.list(principal, link_id)


@router.post(
    "/workspaces/{workspace_id}/classroom/submissions/{link_id}/ingest",
    response_model=SubmissionRead,
)
def workspace_ingest_submission(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomSubmissionService = Depends(_submissions),
) -> SubmissionRead:
    _workspace(principal, workspace_id)
    return service.ingest(principal, link_id)


@router.post(
    "/workspaces/{workspace_id}/classroom/submissions/{link_id}/correct",
    response_model=CorrectionStartRead,
)
def workspace_start_correction(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomSubmissionService = Depends(_submissions),
) -> CorrectionStartRead:
    _workspace(principal, workspace_id)
    return service.start_correction(principal, link_id)


# -- teacher: review, approval and publication ----------------------------


@router.get(
    "/workspaces/{workspace_id}/classroom/submissions/{link_id}/review",
    response_model=ReviewRead,
)
def workspace_review(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomGradeService = Depends(_grades),
) -> ReviewRead:
    _workspace(principal, workspace_id)
    return service.review(principal, link_id)


@router.post(
    "/workspaces/{workspace_id}/classroom/submissions/{link_id}/approve",
    response_model=ReviewRead,
)
def workspace_approve(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: ApprovalRequest,
    principal: Principal = Depends(get_principal),
    service: ClassroomGradeService = Depends(_grades),
) -> ReviewRead:
    _workspace(principal, workspace_id)
    return service.approve(principal, link_id, payload)


@router.get(
    "/workspaces/{workspace_id}/classroom/submissions/{link_id}/publication",
    response_model=PublicationStatusRead,
)
def workspace_publication_status(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    service: ClassroomGradeService = Depends(_grades),
) -> PublicationStatusRead:
    _workspace(principal, workspace_id)
    return service.status(principal, link_id)


@router.post(
    "/workspaces/{workspace_id}/classroom/submissions/{link_id}/publish-grade",
    response_model=GradePublicationRead,
)
def workspace_publish_grade(
    workspace_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: GradePublishRequest,
    principal: Principal = Depends(get_principal),
    service: ClassroomGradeService = Depends(_grades),
) -> GradePublicationRead:
    _workspace(principal, workspace_id)
    return service.publish(principal, link_id, payload)
