"""Manual-correction intake.

A manual correction is an ordinary correction job.  This module only assembles
the records the existing engine already requires — an exam, an approved scheme,
an approved blueprint and criteria, an assignment, a submission and its
documents — then asks :class:`JobService` to queue the job.  It never marks
anything itself and it has no fallback pipeline.

The intake is deliberately isolated from Classroom and from general exam
management.  Every object it creates is named as a manual-correction paper and
the job carries the ``manual:`` idempotency prefix, which is what the history
read uses to find these runs again.

An account of any workspace role may use this workspace tool.  The service
methods that normally require an exam manager are called under a scoped
operator principal whose user id is still the caller's.  That elevation is
confined to objects this request creates; it does not add a route that can
manage arbitrary exams, and the caller's real role is recorded on the audit
event.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import content_hash, sha256_hex
from ..core.security import Principal
from ..db.models import CorrectionJob
from ..db.repositories import JobRepository
from ..documents.blueprint_extraction import BlueprintExtractionService
from ..documents.service import DocumentService
from ..jobs.service import JobService
from ..prompts.registry import PromptRegistry
from ..schemas.api import (
    AssignmentCreate,
    CorrectionCreate,
    ExamCreate,
    SubmissionCreate,
)
from ..schemas.blueprint import BlueprintPut
from ..storage.base import Storage
from .exams import AssignmentService, BlueprintService, ExamService, SubmissionService
from .provider_calls import ProviderCallService
from .scheme_criteria import SchemeCriteriaService
from .schemes import SchemeService


@dataclass(frozen=True, slots=True)
class ManualCorrectionInput:
    student_ref: str
    board: str | None
    subject: str | None
    qualification: str | None
    paper_code: str | None
    marking_mode: str | None
    student_filename: str
    student_mime: str
    student_bytes: bytes
    scheme_filename: str
    scheme_mime: str
    scheme_bytes: bytes
    question_paper_filename: str | None = None
    question_paper_mime: str | None = None
    question_paper_bytes: bytes | None = None


class ManualCorrectionService:
    """Create the records one manual correction needs, through existing services."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        storage: Storage,
        registry: PromptRegistry,
        provider_calls: ProviderCallService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.registry = registry
        self.provider_calls = provider_calls
        self.jobs = JobRepository(session)
        self.audit = AuditService(session)

    def create(self, principal: Principal, payload: ManualCorrectionInput) -> CorrectionJob:
        if not payload.student_bytes:
            raise AppError(ErrorCode.VALIDATION_ERROR, "The student's work is empty.")
        if not payload.scheme_bytes:
            raise AppError(ErrorCode.VALIDATION_ERROR, "The mark scheme is empty.")

        key = self._idempotency_key(principal, payload)
        existing = self.jobs.find_by_idempotency(principal.tenant_id, key)
        if existing is not None:
            return existing

        operator = replace(principal, role="TEACHER")
        label = self._label(payload)

        exam_title = self._exam_title(label, payload)
        exam = ExamService(self.session).create(
            operator,
            ExamCreate(
                title=exam_title,
                board=self._clean(payload.board, 80),
                paper_code=self._clean(payload.paper_code, 80),
            ),
        )

        scheme_service = SchemeService(self.session, self.settings, self.storage)
        _scheme, scheme_version = scheme_service.upload(
            operator,
            exam.id,
            title=f"{exam_title} — mark scheme",
            filename=payload.scheme_filename,
            declared_mime=payload.scheme_mime,
            data=payload.scheme_bytes,
        )
        # The user supplied this scheme for this isolated paper.  The extraction
        # below is the review step: only a complete transcription is stored, and
        # the blueprint/approval gates still run in their normal order.
        scheme_service.approve(
            operator,
            scheme_version.id,
            "Manual correction setup: uploaded mark scheme accepted for this isolated paper.",
        )

        extracted = BlueprintExtractionService(
            self.session, self.settings, self.storage, self.registry, self.provider_calls
        ).extract(operator, exam.id, scheme_version.id)
        blueprint = BlueprintService(self.session).put(
            operator,
            exam.id,
            BlueprintPut(
                structure=extracted.blueprint.structure,
                approve=True,
                reason="Manual correction setup: extracted question structure accepted.",
            ),
        )

        criteria_service = SchemeCriteriaService(
            self.session, self.settings, self.storage, self.registry, self.provider_calls
        )
        criteria_service.extract(
            operator,
            scheme_version.id,
            blueprint_version_id=blueprint.id,
        )
        criteria_service.approve(
            operator,
            scheme_version.id,
            blueprint_version_id=blueprint.id,
            reason="Manual correction setup: transcribed mark points accepted for this paper.",
        )

        assignment = AssignmentService(self.session).create(
            operator,
            AssignmentCreate(
                exam_id=exam.id,
                blueprint_version_id=blueprint.id,
                scheme_version_id=scheme_version.id,
                name=f"Manual correction · {label}",
                review_mode=self._review_mode(payload.marking_mode),
            ),
            allow_unassigned=True,
        )

        student_hash = sha256_hex(payload.student_bytes)
        submission = SubmissionService(self.session).create(
            operator,
            SubmissionCreate(
                assignment_id=assignment.id,
                student_ref=label,
                content_hash=student_hash,
            ),
        )
        DocumentService(self.session, self.settings, self.storage).ingest_for_submission(
            operator,
            submission.id,
            filename=payload.student_filename,
            declared_mime=payload.student_mime,
            data=payload.student_bytes,
        )
        if payload.question_paper_bytes:
            DocumentService(self.session, self.settings, self.storage).ingest_for_exam(
                operator,
                exam.id,
                kind="QUESTION_PAPER",
                filename=payload.question_paper_filename or "question-paper",
                declared_mime=payload.question_paper_mime or "application/octet-stream",
                data=payload.question_paper_bytes,
            )

        creation = JobService(self.session, self.settings).create(
            operator,
            CorrectionCreate(
                assignment_id=assignment.id,
                submission_id=submission.id,
                idempotency_key=key,
                marking_mode=payload.marking_mode or None,
            ),
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="manual_correction.created",
            entity_type="correction_job",
            entity_id=creation.job.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "exam_id": str(exam.id),
                "assignment_id": str(assignment.id),
                "submission_id": str(submission.id),
                "caller_role": principal.role,
                "scoped_operator": operator.role,
                "idempotency_key": key,
            },
        )
        self.session.commit()
        return creation.job

    def list(self, tenant_id: uuid.UUID, *, limit: int = 50) -> list[CorrectionJob]:
        return list(
            self.session.scalars(
                select(CorrectionJob)
                .where(
                    CorrectionJob.tenant_id == tenant_id,
                    CorrectionJob.idempotency_key.like("manual:%"),
                )
                .order_by(CorrectionJob.created_at.desc())
                .limit(limit)
            )
        )

    @staticmethod
    def _clean(value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned[:limit] if cleaned else None

    @staticmethod
    def _label(payload: ManualCorrectionInput) -> str:
        cleaned = (payload.student_ref or "").strip()
        return (cleaned or "Unlabelled script")[:120]

    @staticmethod
    def _exam_title(label: str, payload: ManualCorrectionInput) -> str:
        parts = ["Manual correction", label]
        for value in (payload.subject, payload.qualification, payload.paper_code):
            cleaned = (value or "").strip()
            if cleaned:
                parts.append(cleaned[:80])
        return " · ".join(parts)[:300]

    @staticmethod
    def _review_mode(marking_mode: str | None) -> str:
        # The job's execution mode and the assignment's review mode are different
        # settings.  A manual paper defaults to the balanced review posture; the
        # explicit marking mode is passed to the job itself.
        if marking_mode == "ACCURACY":
            return "ACCURACY"
        if marking_mode == "ECONOMY":
            return "ECONOMY"
        return "BALANCED"

    def _idempotency_key(self, principal: Principal, payload: ManualCorrectionInput) -> str:
        digest = content_hash(
            "manual-correction",
            str(principal.tenant_id),
            payload.student_ref.strip(),
            (payload.board or "").strip(),
            (payload.subject or "").strip(),
            (payload.qualification or "").strip(),
            (payload.paper_code or "").strip(),
            payload.marking_mode or "",
            sha256_hex(payload.student_bytes),
            sha256_hex(payload.scheme_bytes),
            sha256_hex(payload.question_paper_bytes) if payload.question_paper_bytes else "",
        )
        return f"manual:{digest}"

