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

from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.api import (
    AssignmentCreate,
    AssignmentRead,
    ExamCreate,
    ExamRead,
    SubmissionCreate,
    SubmissionRead,
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
