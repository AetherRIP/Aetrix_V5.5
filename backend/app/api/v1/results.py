"""Result reads, overrides, approvals and tenant-checked page serving."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.results import (
    JobApprovalRequest,
    JobResultsRead,
    MarkOverride,
    PageRead,
    QuestionReviewRequest,
)
from ...services.results import ResultsService
from ...storage.base import Storage
from ..deps import get_principal, get_storage

router = APIRouter(tags=["results"])


@router.get("/corrections/{job_id}/results", response_model=JobResultsRead)
def get_job_results(
    job_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> JobResultsRead:
    return ResultsService(session).job_results(principal, job_id)


@router.get("/submissions/{submission_id}/results", response_model=JobResultsRead)
def get_submission_results(
    submission_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> JobResultsRead:
    results = ResultsService(session).submission_results(principal, submission_id)
    if results is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "This submission has not been marked yet, so it has no results.",
        )
    return results


@router.post("/results/{question_result_id}/override", response_model=JobResultsRead)
def override_result(
    question_result_id: uuid.UUID,
    payload: MarkOverride,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> JobResultsRead:
    return ResultsService(session).override(principal, question_result_id, payload)


@router.post(
    "/corrections/{job_id}/reviews/{question_id}", response_model=JobResultsRead
)
def review_question(
    job_id: uuid.UUID,
    question_id: str,
    payload: QuestionReviewRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> JobResultsRead:
    return ResultsService(session).review_question(principal, job_id, question_id, payload)


@router.post("/corrections/{job_id}/approve", response_model=JobResultsRead)
def approve_job(
    job_id: uuid.UUID,
    payload: JobApprovalRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> JobResultsRead:
    return ResultsService(session).approve(principal, job_id, payload)


@router.get("/submissions/{submission_id}/pages", response_model=list[PageRead])
def list_pages(
    submission_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[PageRead]:
    return ResultsService(session).pages(principal, submission_id)


@router.get("/submissions/{submission_id}/pages/{page_index}")
def get_page_image(
    submission_id: uuid.UUID,
    page_index: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> Response:
    if page_index < 1:
        raise AppError(ErrorCode.NOT_FOUND, "Page not found.")
    image = ResultsService(session).page_image(
        principal, submission_id, page_index, storage
    )
    return Response(
        content=image,
        media_type="image/png",
        headers={
            "Cache-Control": f"private, max-age={settings.security.signed_url_ttl_seconds}",
            "Content-Disposition": "inline",
        },
    )
