"""Manual-correction intake and history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal, ensure_uploader
from ...db.models import CorrectionJob
from ...db.session import get_db_session
from ...prompts.registry import PromptRegistry
from ...schemas.api import JobRead
from ...services.manual_corrections import ManualCorrectionInput, ManualCorrectionService
from ...services.provider_calls import ProviderCallService
from ...storage.base import Storage
from ..deps import get_principal, get_prompt_registry, get_provider_calls, get_storage

router = APIRouter(prefix="/manual-corrections", tags=["manual-corrections"])


def _service(
    session: Session,
    settings: Settings,
    storage: Storage,
    registry: PromptRegistry,
    provider_calls: ProviderCallService,
) -> ManualCorrectionService:
    return ManualCorrectionService(session, settings, storage, registry, provider_calls)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_manual_correction(
    student_file: UploadFile = File(...),
    scheme_file: UploadFile = File(...),
    question_paper: UploadFile | None = File(default=None),
    student_ref: str = Form(default=""),
    board: str = Form(default=""),
    subject: str = Form(default=""),
    qualification: str = Form(default=""),
    paper_code: str = Form(default=""),
    marking_mode: str = Form(default=""),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    registry: PromptRegistry = Depends(get_prompt_registry),
    provider_calls: ProviderCallService = Depends(get_provider_calls),
) -> JobRead:
    ensure_uploader(principal)
    mode = (marking_mode or "").strip().upper() or None
    if mode is not None and mode not in {"PER_QUESTION", "WHOLE_PAPER", "PARALLEL"}:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "marking_mode must be PER_QUESTION, WHOLE_PAPER or PARALLEL.",
        )
    student_bytes = await student_file.read()
    scheme_bytes = await scheme_file.read()
    paper_bytes = await question_paper.read() if question_paper is not None else None
    payload = ManualCorrectionInput(
        student_ref=(student_ref or "").strip()[:120],
        board=(board or "").strip()[:80] or None,
        subject=(subject or "").strip()[:80] or None,
        qualification=(qualification or "").strip()[:80] or None,
        paper_code=(paper_code or "").strip()[:80] or None,
        marking_mode=mode,
        student_filename=student_file.filename or "student-work",
        student_mime=student_file.content_type or "",
        student_bytes=student_bytes,
        scheme_filename=scheme_file.filename or "mark-scheme",
        scheme_mime=scheme_file.content_type or "",
        scheme_bytes=scheme_bytes,
        question_paper_filename=(
            question_paper.filename or "question-paper" if question_paper is not None else None
        ),
        question_paper_mime=(
            question_paper.content_type or "" if question_paper is not None else None
        ),
        question_paper_bytes=paper_bytes,
    )
    job = _service(session, settings, storage, registry, provider_calls).create(
        principal, payload
    )
    return JobRead.model_validate(job)


@router.get("", response_model=list[JobRead])
def list_manual_corrections(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[JobRead]:
    jobs = session.scalars(
        select(CorrectionJob)
        .where(
            CorrectionJob.tenant_id == principal.tenant_id,
            CorrectionJob.idempotency_key.like("manual:%"),
        )
        .order_by(CorrectionJob.created_at.desc())
        .limit(50)
    )
    return [JobRead.model_validate(job) for job in jobs]
