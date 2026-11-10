"""Exam, blueprint, assignment and submission endpoints.

Blueprint approval is a two-step operation on purpose: save a draft, then
approve the exact draft.  An approval request whose structure does not hash to
the stored draft is rejected, so an approved version always corresponds to
content a teacher actually saw.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.repositories import (
    AssignmentRepository,
    JobRepository,
    SubmissionRepository,
    TenantRepository,
)
from ...db.session import get_db_session
from ...schemas.api import (
    AssignmentCreate,
    AssignmentRead,
    ExamCreate,
    ExamRead,
    JobRead,
    SubmissionCreate,
    SubmissionRead,
    WorkspaceRead,
)
from ...schemas.blueprint import BlueprintPut, BlueprintRead
from ...services.exams import (
    AssignmentService,
    BlueprintService,
    ExamService,
    SubmissionService,
)
from ..deps import get_principal

router = APIRouter(tags=["exams"])


def _workspace_read(
    principal: Principal, session: Session, workspace_id: uuid.UUID
) -> WorkspaceRead:
    if workspace_id != principal.tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
    tenant = TenantRepository(session).get(principal.tenant_id)
    if tenant is None:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
    return WorkspaceRead(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        role=principal.role,
        is_demo=tenant.is_demo,
    )


@router.get("/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceRead]:
    return [_workspace_read(principal, session, principal.tenant_id)]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> WorkspaceRead:
    return _workspace_read(principal, session, workspace_id)


@router.get("/workspaces/{workspace_id}/assignments", response_model=list[AssignmentRead])
def list_workspace_assignments(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[AssignmentRead]:
    _workspace_read(principal, session, workspace_id)
    return [
        AssignmentRead.model_validate(row)
        for row in AssignmentRepository(session).list(principal.tenant_id)
    ]


@router.get("/assignments/{assignment_id}", response_model=AssignmentRead)
def get_assignment(
    assignment_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> AssignmentRead:
    assignment = AssignmentRepository(session).get(principal.tenant_id, assignment_id)
    if assignment is None:
        raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
    return AssignmentRead.model_validate(assignment)


@router.get(
    "/assignments/{assignment_id}/submissions", response_model=list[SubmissionRead]
)
def list_assignment_submissions(
    assignment_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[SubmissionRead]:
    if AssignmentRepository(session).get(principal.tenant_id, assignment_id) is None:
        raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
    return [
        SubmissionRead.model_validate(row)
        for row in SubmissionRepository(session).list_for_assignment(
            principal.tenant_id, assignment_id
        )
    ]


@router.get("/submissions/{submission_id}", response_model=SubmissionRead)
def get_submission(
    submission_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> SubmissionRead:
    submission = SubmissionRepository(session).get(principal.tenant_id, submission_id)
    if submission is None:
        raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
    return SubmissionRead.model_validate(submission)


@router.get("/submissions/{submission_id}/corrections", response_model=list[JobRead])
def list_submission_corrections(
    submission_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[JobRead]:
    if SubmissionRepository(session).get(principal.tenant_id, submission_id) is None:
        raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
    return [
        JobRead.model_validate(row)
        for row in JobRepository(session).list_for_submission(
            principal.tenant_id, submission_id
        )
    ]


@router.get("/workspaces/{workspace_id}/corrections", response_model=list[JobRead])
def list_workspace_corrections(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[JobRead]:
    _workspace_read(principal, session, workspace_id)
    return [
        JobRead.model_validate(row)
        for row in JobRepository(session).list(principal.tenant_id)
    ]


@router.post("/exams", response_model=ExamRead, status_code=status.HTTP_201_CREATED)
def create_exam(
    payload: ExamCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ExamRead:
    exam = ExamService(session).create(principal, payload)
    return ExamRead.model_validate(exam)


@router.get("/exams", response_model=list[ExamRead])
def list_exams(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[ExamRead]:
    return [
        ExamRead.model_validate(exam) for exam in ExamService(session).list(principal.tenant_id)
    ]


@router.get("/exams/{exam_id}/blueprint", response_model=BlueprintRead)
def get_blueprint(
    exam_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> BlueprintRead:
    blueprint = BlueprintService(session).get_latest(principal.tenant_id, exam_id)
    return BlueprintRead.model_validate(blueprint)


@router.put("/exams/{exam_id}/blueprint", response_model=BlueprintRead)
def put_blueprint(
    exam_id: uuid.UUID,
    payload: BlueprintPut,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> BlueprintRead:
    blueprint = BlueprintService(session).put(principal, exam_id, payload)
    return BlueprintRead.model_validate(blueprint)


@router.post("/assignments", response_model=AssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: AssignmentCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> AssignmentRead:
    assignment = AssignmentService(session).create(principal, payload)
    return AssignmentRead.model_validate(assignment)


@router.post("/submissions", response_model=SubmissionRead, status_code=status.HTTP_201_CREATED)
def register_submission(
    payload: SubmissionCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> SubmissionRead:
    submission = SubmissionService(session).create(principal, payload)
    return SubmissionRead.model_validate(submission)
