"""Correction job endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.security import Principal
from ...db.session import get_db_session
from ...jobs.service import JobService
from ...schemas.api import (
    CorrectionCreate,
    JobDetailRead,
    JobEventRead,
    JobRead,
)
from ..deps import get_principal

router = APIRouter(prefix="/corrections", tags=["corrections"])


def _service(session: Session, settings: Settings) -> JobService:
    return JobService(session, settings)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_correction(
    payload: CorrectionCreate,
    response: Response,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JobRead:
    creation = _service(session, settings).create(principal, payload)
    if not creation.created:
        response.status_code = status.HTTP_200_OK
    return JobRead.model_validate(creation.job)


@router.get("", response_model=list[JobRead])
def list_corrections(
    state: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[JobRead]:
    jobs = _service(session, settings).list(principal.tenant_id, state=state, limit=limit)
    return [JobRead.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=JobDetailRead)
def get_correction(
    job_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JobDetailRead:
    job, events = _service(session, settings).get_with_events(principal.tenant_id, job_id)
    base = JobRead.model_validate(job)
    return JobDetailRead(
        **base.model_dump(),
        events=[JobEventRead.model_validate(event) for event in events],
    )


@router.post("/{job_id}/cancel", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def cancel_correction(
    job_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JobRead:
    job = _service(session, settings).cancel(principal, job_id)
    return JobRead.model_validate(job)


@router.post("/{job_id}/retry", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def retry_correction(
    job_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JobRead:
    job = _service(session, settings).retry(principal, job_id)
    return JobRead.model_validate(job)
