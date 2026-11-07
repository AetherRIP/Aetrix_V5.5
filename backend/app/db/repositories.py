"""Repositories.

Every read and write for a tenant-owned entity takes the tenant identifier
explicitly.  A caller cannot obtain another workspace's row by guessing a UUID:
``get`` returns ``None`` and the service turns that into a 404.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..jobs.states import RUNNABLE_STATES, JobState, ensure_transition, progress_for
from .models import (
    Assignment,
    AuditEvent,
    BlueprintOverride,
    CorrectionJob,
    Document,
    DocumentPage,
    Exam,
    ExamBlueprintVersion,
    JobEvent,
    MarkingCriterion,
    MarkScheme,
    MarkSchemeVersion,
    PageQuestionMapping,
    PromptVersion,
    ProviderContributor,
    ProviderCredential,
    ProviderProjectCooldown,
    ProviderQuotaReservation,
    ProviderUsage,
    Submission,
    Tenant,
    User,
)


class TenantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return self.session.get(Tenant, tenant_id)

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self.session.scalar(select(Tenant).where(Tenant.slug == slug))

    def create(self, *, name: str, slug: str) -> Tenant:
        tenant = Tenant(name=name, slug=slug)
        self.session.add(tenant)
        self.session.flush()
        return tenant


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        return self.session.scalar(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )

    def get_by_subject(self, tenant_id: uuid.UUID, subject: str) -> User | None:
        return self.session.scalar(
            select(User).where(User.tenant_id == tenant_id, User.subject == subject)
        )

    def find_by_subject_any_tenant(self, subject: str) -> list[User]:
        return list(self.session.scalars(select(User).where(User.subject == subject).limit(2)))

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        subject: str,
        role: str = "TEACHER",
        email: str | None = None,
        display_name: str | None = None,
    ) -> User:
        user = User(
            tenant_id=tenant_id,
            subject=subject,
            role=role,
            email=email,
            display_name=display_name,
        )
        self.session.add(user)
        self.session.flush()
        return user


class ExamRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> Exam | None:
        return self.session.scalar(
            select(Exam).where(Exam.id == exam_id, Exam.tenant_id == tenant_id)
        )

    def list(self, tenant_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Exam]:
        return list(
            self.session.scalars(
                select(Exam)
                .where(Exam.tenant_id == tenant_id)
                .order_by(Exam.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        title: str,
        created_by: uuid.UUID | None,
        board: str | None = None,
        paper_code: str | None = None,
    ) -> Exam:
        exam = Exam(
            tenant_id=tenant_id,
            title=title,
            board=board,
            paper_code=paper_code,
            created_by=created_by,
        )
        self.session.add(exam)
        self.session.flush()
        return exam


class BlueprintRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, blueprint_id: uuid.UUID) -> ExamBlueprintVersion | None:
        return self.session.scalar(
            select(ExamBlueprintVersion).where(
                ExamBlueprintVersion.id == blueprint_id,
                ExamBlueprintVersion.tenant_id == tenant_id,
            )
        )

    def latest(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> ExamBlueprintVersion | None:
        return self.session.scalar(
            select(ExamBlueprintVersion)
            .where(
                ExamBlueprintVersion.tenant_id == tenant_id,
                ExamBlueprintVersion.exam_id == exam_id,
            )
            .order_by(ExamBlueprintVersion.version.desc())
            .limit(1)
        )

    def latest_approved(
        self, tenant_id: uuid.UUID, exam_id: uuid.UUID
    ) -> ExamBlueprintVersion | None:
        return self.session.scalar(
            select(ExamBlueprintVersion)
            .where(
                ExamBlueprintVersion.tenant_id == tenant_id,
                ExamBlueprintVersion.exam_id == exam_id,
                ExamBlueprintVersion.status == "APPROVED",
            )
            .order_by(ExamBlueprintVersion.version.desc())
            .limit(1)
        )

    def next_version(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> int:
        current = self.session.scalar(
            select(func.max(ExamBlueprintVersion.version)).where(
                ExamBlueprintVersion.tenant_id == tenant_id,
                ExamBlueprintVersion.exam_id == exam_id,
            )
        )
        return int(current or 0) + 1

    def create_version(
        self,
        *,
        tenant_id: uuid.UUID,
        exam_id: uuid.UUID,
        structure: dict[str, Any],
        total_marks: int,
        content_hash: str,
        created_by: uuid.UUID | None,
        status: str = "DRAFT",
        approval_reason: str | None = None,
        source: str = "MANUAL",
        source_document_id: uuid.UUID | None = None,
        extraction_metadata: dict[str, Any] | None = None,
    ) -> ExamBlueprintVersion:
        version = self.next_version(tenant_id, exam_id)
        approved_at = None
        approved_by = None
        if status == "APPROVED":
            self._supersede_approved(tenant_id, exam_id)
            approved_at = utcnow()
            approved_by = created_by
        blueprint = ExamBlueprintVersion(
            tenant_id=tenant_id,
            exam_id=exam_id,
            version=version,
            status=status,
            structure=structure,
            total_marks=total_marks,
            content_hash=content_hash,
            source=source,
            source_document_id=source_document_id,
            extraction_metadata=extraction_metadata or {},
            created_by=created_by,
            approved_by=approved_by,
            approved_at=approved_at,
            approval_reason=approval_reason,
        )
        self.session.add(blueprint)
        self.session.flush()
        return blueprint

    def approve(
        self,
        blueprint: ExamBlueprintVersion,
        *,
        actor_id: uuid.UUID,
        reason: str,
    ) -> ExamBlueprintVersion:
        if blueprint.status == "SUPERSEDED":
            raise AppError(ErrorCode.CONFLICT, "A superseded blueprint cannot be approved again.")
        if blueprint.status == "APPROVED":
            return blueprint
        self._supersede_approved(blueprint.tenant_id, blueprint.exam_id, keep=blueprint.id)
        blueprint.status = "APPROVED"
        blueprint.approved_by = actor_id
        blueprint.approved_at = utcnow()
        blueprint.approval_reason = reason
        self.session.flush()
        return blueprint

    def _supersede_approved(
        self, tenant_id: uuid.UUID, exam_id: uuid.UUID, *, keep: uuid.UUID | None = None
    ) -> None:
        statement = (
            update(ExamBlueprintVersion)
            .where(
                ExamBlueprintVersion.tenant_id == tenant_id,
                ExamBlueprintVersion.exam_id == exam_id,
                ExamBlueprintVersion.status == "APPROVED",
            )
            .values(status="SUPERSEDED")
        )
        if keep is not None:
            statement = statement.where(ExamBlueprintVersion.id != keep)
        self.session.execute(statement)


class MarkSchemeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_version(self, tenant_id: uuid.UUID, version_id: uuid.UUID) -> MarkSchemeVersion | None:
        return self.session.scalar(
            select(MarkSchemeVersion).where(
                MarkSchemeVersion.id == version_id,
                MarkSchemeVersion.tenant_id == tenant_id,
            )
        )

    def get_scheme(self, tenant_id: uuid.UUID, mark_scheme_id: uuid.UUID) -> MarkScheme | None:
        return self.session.scalar(
            select(MarkScheme).where(
                MarkScheme.id == mark_scheme_id, MarkScheme.tenant_id == tenant_id
            )
        )

    def create_scheme(
        self,
        *,
        tenant_id: uuid.UUID,
        exam_id: uuid.UUID,
        title: str,
        document_id: uuid.UUID | None = None,
    ) -> MarkScheme:
        scheme = MarkScheme(
            tenant_id=tenant_id, exam_id=exam_id, title=title, document_id=document_id
        )
        self.session.add(scheme)
        self.session.flush()
        return scheme

    def create_version(
        self,
        *,
        tenant_id: uuid.UUID,
        mark_scheme_id: uuid.UUID,
        content_hash: str,
        status: str = "DRAFT",
        source: str = "UPLOAD",
    ) -> MarkSchemeVersion:
        current = self.session.scalar(
            select(func.max(MarkSchemeVersion.version)).where(
                MarkSchemeVersion.tenant_id == tenant_id,
                MarkSchemeVersion.mark_scheme_id == mark_scheme_id,
            )
        )
        version = MarkSchemeVersion(
            tenant_id=tenant_id,
            mark_scheme_id=mark_scheme_id,
            version=int(current or 0) + 1,
            status=status,
            source=source,
            content_hash=content_hash,
            approved_at=utcnow() if status == "APPROVED" else None,
        )
        self.session.add(version)
        self.session.flush()
        return version

    def approve_version(self, version: MarkSchemeVersion) -> MarkSchemeVersion:
        if version.status == "APPROVED":
            return version
        if version.status == "SUPERSEDED":
            raise AppError(ErrorCode.CONFLICT, "A superseded mark scheme cannot be approved again.")
        self.session.execute(
            update(MarkSchemeVersion)
            .where(
                MarkSchemeVersion.tenant_id == version.tenant_id,
                MarkSchemeVersion.mark_scheme_id == version.mark_scheme_id,
                MarkSchemeVersion.status == "APPROVED",
            )
            .values(status="SUPERSEDED")
        )
        version.status = "APPROVED"
        version.approved_at = utcnow()
        self.session.flush()
        return version

    def list_versions(
        self, tenant_id: uuid.UUID, mark_scheme_id: uuid.UUID
    ) -> list[MarkSchemeVersion]:
        return list(
            self.session.scalars(
                select(MarkSchemeVersion)
                .where(
                    MarkSchemeVersion.tenant_id == tenant_id,
                    MarkSchemeVersion.mark_scheme_id == mark_scheme_id,
                )
                .order_by(MarkSchemeVersion.version.desc())
            )
        )

    def list_criteria(
        self, tenant_id: uuid.UUID, scheme_version_id: uuid.UUID
    ) -> list[MarkingCriterion]:
        return list(
            self.session.scalars(
                select(MarkingCriterion)
                .where(
                    MarkingCriterion.tenant_id == tenant_id,
                    MarkingCriterion.scheme_version_id == scheme_version_id,
                )
                .order_by(MarkingCriterion.question_id, MarkingCriterion.ordinal)
            )
        )


class AssignmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, assignment_id: uuid.UUID) -> Assignment | None:
        return self.session.scalar(
            select(Assignment).where(
                Assignment.id == assignment_id, Assignment.tenant_id == tenant_id
            )
        )

    def list(self, tenant_id: uuid.UUID) -> list[Assignment]:
        return list(
            self.session.scalars(
                select(Assignment)
                .where(Assignment.tenant_id == tenant_id)
                .order_by(Assignment.created_at.desc())
            )
        )

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        exam_id: uuid.UUID,
        blueprint_version_id: uuid.UUID,
        scheme_version_id: uuid.UUID,
        name: str,
        completion_threshold: float,
        review_mode: str,
        created_by: uuid.UUID | None,
    ) -> Assignment:
        assignment = Assignment(
            tenant_id=tenant_id,
            exam_id=exam_id,
            blueprint_version_id=blueprint_version_id,
            scheme_version_id=scheme_version_id,
            name=name,
            completion_threshold=completion_threshold,
            review_mode=review_mode,
            created_by=created_by,
        )
        self.session.add(assignment)
        self.session.flush()
        return assignment


class SubmissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, submission_id: uuid.UUID) -> Submission | None:
        return self.session.scalar(
            select(Submission).where(
                Submission.id == submission_id, Submission.tenant_id == tenant_id
            )
        )

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        student_ref: str,
        content_hash: str,
        status: str = "REGISTERED",
    ) -> Submission:
        submission = Submission(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            student_ref=student_ref,
            content_hash=content_hash,
            status=status,
        )
        self.session.add(submission)
        self.session.flush()
        return submission


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, tenant_id: uuid.UUID, job_id: uuid.UUID, *, for_update: bool = False
    ) -> CorrectionJob | None:
        statement: Select[tuple[CorrectionJob]] = select(CorrectionJob).where(
            CorrectionJob.id == job_id, CorrectionJob.tenant_id == tenant_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def find_by_idempotency(
        self, tenant_id: uuid.UUID, idempotency_key: str
    ) -> CorrectionJob | None:
        return self.session.scalar(
            select(CorrectionJob).where(
                CorrectionJob.tenant_id == tenant_id,
                CorrectionJob.idempotency_key == idempotency_key,
            )
        )

    def list(
        self,
        tenant_id: uuid.UUID,
        *,
        state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CorrectionJob]:
        statement = select(CorrectionJob).where(CorrectionJob.tenant_id == tenant_id)
        if state:
            statement = statement.where(CorrectionJob.state == state)
        return list(
            self.session.scalars(
                statement.order_by(CorrectionJob.created_at.desc()).limit(limit).offset(offset)
            )
        )

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        submission_id: uuid.UUID,
        blueprint_version_id: uuid.UUID,
        scheme_version_id: uuid.UUID,
        idempotency_key: str,
        request_hash: str,
        max_attempts: int,
    ) -> CorrectionJob:
        job = CorrectionJob(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            submission_id=submission_id,
            blueprint_version_id=blueprint_version_id,
            scheme_version_id=scheme_version_id,
            state=JobState.CREATED,
            progress=progress_for(JobState.CREATED),
            attempts=0,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def events(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> list[JobEvent]:
        return list(
            self.session.scalars(
                select(JobEvent)
                .where(JobEvent.tenant_id == tenant_id, JobEvent.job_id == job_id)
                .order_by(JobEvent.event_seq)
            )
        )

    def next_event_seq(self, job_id: uuid.UUID) -> int:
        current = self.session.scalar(
            select(func.coalesce(func.max(JobEvent.event_seq), 0)).where(JobEvent.job_id == job_id)
        )
        return int(current or 0) + 1

    def add_event(
        self,
        job: CorrectionJob,
        *,
        from_state: str | None,
        to_state: str,
        detail: dict[str, Any],
        actor: str,
    ) -> JobEvent:
        event = JobEvent(
            tenant_id=job.tenant_id,
            job_id=job.id,
            event_seq=self.next_event_seq(job.id),
            from_state=from_state,
            to_state=to_state,
            detail=detail,
            actor=actor,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def transition(
        self,
        job: CorrectionJob,
        target: JobState,
        *,
        detail: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> CorrectionJob:
        current = JobState(job.state)
        ensure_transition(current, target)
        job.state = target
        job.progress = progress_for(target)
        job.record_version += 1
        if target in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
            job.finished_at = utcnow()
        self.add_event(
            job,
            from_state=current.value,
            to_state=target.value,
            detail=detail or {},
            actor=actor,
        )
        self.session.flush()
        return job

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> CorrectionJob | None:
        """Claim one runnable job with ``FOR UPDATE SKIP LOCKED``.

        The lease is the crash-recovery mechanism: a worker that dies stops
        heartbeating, the lease expires, and another worker may reclaim the job.
        ``attempts`` counts claims, so a job that repeatedly kills workers
        eventually becomes ``FAILED`` rather than looping forever.
        """
        now = utcnow()
        runnable = [state.value for state in RUNNABLE_STATES]
        statement = (
            select(CorrectionJob)
            .where(
                CorrectionJob.state.in_(runnable),
                or_(
                    CorrectionJob.lease_expires_at.is_(None),
                    CorrectionJob.lease_expires_at < now,
                ),
            )
            .order_by(CorrectionJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = self.session.scalar(statement)
        if job is None:
            self.session.rollback()
            return None

        if job.cancel_requested:
            self.transition(
                job,
                JobState.CANCELLED,
                detail={"reason": "cancelled before execution"},
                actor="system",
            )
            self.session.commit()
            return None

        if job.attempts >= job.max_attempts:
            job.error_code = "MAX_ATTEMPTS_EXHAUSTED"
            job.error_message = "The job exhausted its attempt budget before being claimed."
            job.retryable = False
            self.transition(
                job,
                JobState.FAILED,
                detail={"reason": "max attempts exhausted"},
                actor="system",
            )
            self.session.commit()
            return None

        job.attempts += 1
        job.lease_owner = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        if job.started_at is None:
            job.started_at = now
        if JobState(job.state) is JobState.CREATED:
            self.transition(
                job,
                JobState.VALIDATING,
                detail={"worker": worker_id, "attempt": job.attempts},
                actor=f"worker:{worker_id}",
            )
        else:
            job.record_version += 1
            self.add_event(
                job,
                from_state=job.state,
                to_state=job.state,
                detail={"event": "lease_acquired", "worker": worker_id},
                actor=f"worker:{worker_id}",
            )
        self.session.commit()
        return job

    def heartbeat(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        result = self.session.execute(
            update(CorrectionJob)
            .where(
                CorrectionJob.id == job_id,
                CorrectionJob.lease_owner == worker_id,
            )
            .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
        )
        self.session.commit()
        return bool(result.rowcount)

    def release(self, job: CorrectionJob, *, worker_id: str) -> None:
        if job.lease_owner == worker_id:
            job.lease_owner = None
            job.lease_expires_at = None
            self.session.flush()

    def reap_expired(self, *, max_attempts: int) -> int:
        """Fail or release jobs whose worker disappeared.

        Called on worker start and periodically.  A job with attempts left is
        released so it can be claimed again; a job with no attempts left is
        failed with a terminal error instead of being silently retried.
        """
        now = utcnow()
        jobs = list(
            self.session.scalars(
                select(CorrectionJob)
                .where(
                    CorrectionJob.lease_owner.is_not(None),
                    CorrectionJob.lease_expires_at.is_not(None),
                    CorrectionJob.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        )
        count = 0
        for job in jobs:
            if job.attempts >= min(job.max_attempts, max_attempts):
                job.error_code = "LEASE_EXPIRED"
                job.error_message = "The worker lease expired and the attempt budget is exhausted."
                job.retryable = False
                self.transition(
                    job,
                    JobState.FAILED,
                    detail={"reason": "lease_expired", "attempts": job.attempts},
                    actor="system",
                )
            else:
                job.lease_owner = None
                job.lease_expires_at = None
                job.record_version += 1
                self.add_event(
                    job,
                    from_state=job.state,
                    to_state=job.state,
                    detail={"event": "lease_expired", "attempts": job.attempts},
                    actor="system",
                )
            count += 1
        if count:
            self.session.commit()
        return count

    def set_error(
        self,
        job: CorrectionJob,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        job.error_code = code
        job.error_message = message[:2000]
        job.retryable = retryable
        self.session.flush()


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        return self.session.scalar(
            select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
        )

    def pages(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> list[DocumentPage]:
        return list(
            self.session.scalars(
                select(DocumentPage)
                .where(
                    DocumentPage.tenant_id == tenant_id,
                    DocumentPage.document_id == document_id,
                )
                .order_by(DocumentPage.page_index)
            )
        )

    def list_for_submission(self, tenant_id: uuid.UUID, submission_id: uuid.UUID) -> list[Document]:
        return list(
            self.session.scalars(
                select(Document)
                .where(
                    Document.tenant_id == tenant_id,
                    Document.submission_id == submission_id,
                )
                .order_by(Document.created_at)
            )
        )


class PageMappingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_document(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> list[PageQuestionMapping]:
        return list(
            self.session.scalars(
                select(PageQuestionMapping)
                .where(
                    PageQuestionMapping.tenant_id == tenant_id,
                    PageQuestionMapping.document_id == document_id,
                )
                .order_by(PageQuestionMapping.question_id)
            )
        )

    def replace_for_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        blueprint_version_id: uuid.UUID,
        mappings: list[dict[str, Any]],
    ) -> list[PageQuestionMapping]:
        self.session.execute(
            select(PageQuestionMapping)
            .where(
                PageQuestionMapping.tenant_id == tenant_id,
                PageQuestionMapping.document_id == document_id,
                PageQuestionMapping.blueprint_version_id == blueprint_version_id,
            )
            .with_for_update()
        )
        from sqlalchemy import delete

        self.session.execute(
            delete(PageQuestionMapping).where(
                PageQuestionMapping.tenant_id == tenant_id,
                PageQuestionMapping.document_id == document_id,
                PageQuestionMapping.blueprint_version_id == blueprint_version_id,
            )
        )
        rows: list[PageQuestionMapping] = []
        for item in mappings:
            row = PageQuestionMapping(
                tenant_id=tenant_id,
                document_id=document_id,
                page_id=item["page_id"],
                blueprint_version_id=blueprint_version_id,
                question_id=item["question_id"],
                confidence=item.get("confidence", 0.0),
                method=item.get("method", "TEXT_MATCH"),
                source_ref=item.get("source_ref", {}),
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows


class BlueprintOverrideRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        exam_id: uuid.UUID,
        base_version_id: uuid.UUID,
        result_version_id: uuid.UUID,
        author_id: uuid.UUID,
        rationale: str,
        patch: list[dict[str, Any]],
    ) -> BlueprintOverride:
        row = BlueprintOverride(
            tenant_id=tenant_id,
            exam_id=exam_id,
            base_version_id=base_version_id,
            result_version_id=result_version_id,
            author_id=author_id,
            rationale=rationale,
            patch=patch,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_exam(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> list[BlueprintOverride]:
        return list(
            self.session.scalars(
                select(BlueprintOverride)
                .where(
                    BlueprintOverride.tenant_id == tenant_id,
                    BlueprintOverride.exam_id == exam_id,
                )
                .order_by(BlueprintOverride.created_at.desc())
            )
        )


class PromptVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(
        self,
        *,
        prompt_id: str,
        version: int,
        content_hash: str,
        path: str,
        model_role: str,
    ) -> PromptVersion:
        existing = self.session.scalar(
            select(PromptVersion).where(
                PromptVersion.prompt_id == prompt_id, PromptVersion.version == version
            )
        )
        if existing is not None:
            if existing.content_hash != content_hash:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "A prompt asset changed without incrementing its version.",
                    details={"prompt_id": prompt_id, "version": version},
                )
            return existing
        row = PromptVersion(
            prompt_id=prompt_id,
            version=version,
            content_hash=content_hash,
            path=path,
            model_role=model_role,
        )
        self.session.add(row)
        self.session.flush()
        return row


class CredentialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_tenant(self, tenant_id: uuid.UUID) -> list[ProviderCredential]:
        return list(
            self.session.scalars(
                select(ProviderCredential)
                .where(
                    or_(
                        ProviderCredential.tenant_id == tenant_id,
                        ProviderCredential.tenant_id.is_(None),
                    )
                )
                .order_by(ProviderCredential.account_label)
            )
        )

    def get(self, credential_id: uuid.UUID) -> ProviderCredential | None:
        return self.session.get(ProviderCredential, credential_id)

    def create(
        self,
        *,
        tenant_id: uuid.UUID | None,
        project_id: str,
        account_label: str,
        key_fingerprint: str,
        encrypted_secret: str,
        model_access: list[str],
        auth_type: str = "api_key",
        tier: str = "UNKNOWN",
        health: str = "UNKNOWN",
        contributor_id: uuid.UUID | None = None,
    ) -> ProviderCredential:
        credential = ProviderCredential(
            tenant_id=tenant_id,
            contributor_id=contributor_id,
            project_id=project_id,
            account_label=account_label,
            key_fingerprint=key_fingerprint,
            encrypted_secret=encrypted_secret,
            model_access=model_access,
            auth_type=auth_type,
            tier=tier,
            health=health,
        )
        self.session.add(credential)
        self.session.flush()
        return credential

    def get_by_fingerprint(self, key_fingerprint: str) -> ProviderCredential | None:
        return self.session.scalar(
            select(ProviderCredential).where(
                ProviderCredential.key_fingerprint == key_fingerprint
            )
        )

    def fleet(
        self,
        *,
        project_id: str | None = None,
        health: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ProviderCredential], int]:
        """Every key on the platform, not only the caller's tenant.

        Fleet administration is a platform capability: keys are provisioned by
        the operator and leased across workspaces, so filtering by tenant here
        would hide most of the fleet.
        """

        conditions = []
        if project_id:
            conditions.append(ProviderCredential.project_id == project_id)
        if health:
            conditions.append(ProviderCredential.health == health)
        if search:
            pattern = f"%{search.lower()}%"
            conditions.append(
                or_(
                    func.lower(ProviderCredential.account_label).like(pattern),
                    func.lower(ProviderCredential.project_id).like(pattern),
                    func.lower(ProviderCredential.key_fingerprint).like(pattern),
                )
            )

        total = int(
            self.session.scalar(
                select(func.count(ProviderCredential.id)).where(*conditions)
            )
            or 0
        )
        rows = list(
            self.session.scalars(
                select(ProviderCredential)
                .where(*conditions)
                .order_by(
                    ProviderCredential.project_id,
                    ProviderCredential.account_label,
                    ProviderCredential.id,
                )
                .limit(limit)
                .offset(offset)
            )
        )
        return rows, total

    def all_credentials(self) -> list[ProviderCredential]:
        return list(
            self.session.scalars(
                select(ProviderCredential).order_by(ProviderCredential.project_id)
            )
        )

    def project_ids(self) -> list[str]:
        return list(
            self.session.scalars(
                select(ProviderCredential.project_id).distinct().order_by(
                    ProviderCredential.project_id
                )
            )
        )

    def delete(self, credential: ProviderCredential) -> None:
        self.session.delete(credential)
        self.session.flush()

    def for_contributor(self, contributor_id: uuid.UUID) -> list[ProviderCredential]:
        return list(
            self.session.scalars(
                select(ProviderCredential)
                .where(ProviderCredential.contributor_id == contributor_id)
                .order_by(ProviderCredential.project_id, ProviderCredential.account_label)
            )
        )

    def claim_candidates(
        self, tenant_id: uuid.UUID, model: str, excluded: set[uuid.UUID]
    ) -> list[ProviderCredential]:
        """Credentials a request may be leased on.

        Eligibility is decided by the contributor's status as well as the key's
        own health: a suspended or withdrawn contributor must stop receiving
        traffic even if an earlier health update left the row looking healthy.
        Platform-owned keys (``contributor_id IS NULL``) are always eligible.
        """

        statement = (
            select(ProviderCredential)
            .outerjoin(
                ProviderContributor,
                ProviderContributor.id == ProviderCredential.contributor_id,
            )
            .where(
                or_(
                    ProviderCredential.tenant_id == tenant_id,
                    ProviderCredential.tenant_id.is_(None),
                ),
                ProviderCredential.health.not_in(["INVALID", "DISABLED"]),
                ProviderCredential.revoked_at.is_(None),
                or_(
                    ProviderCredential.contributor_id.is_(None),
                    ProviderContributor.status == "ACTIVE",
                ),
                or_(
                    ProviderCredential.cooldown_until.is_(None),
                    ProviderCredential.cooldown_until <= utcnow(),
                ),
            )
            .order_by(ProviderCredential.last_success_at.desc().nullslast())
            .with_for_update(skip_locked=True)
        )
        rows = list(self.session.scalars(statement))
        result: list[ProviderCredential] = []
        for row in rows:
            if row.id in excluded:
                continue
            access = row.model_access or []
            if access and model not in access:
                continue
            result.append(row)
        return result


class ContributorRepository:
    """Contributors are platform-level, so these reads never filter by tenant."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, contributor_id: uuid.UUID) -> ProviderContributor | None:
        return self.session.get(ProviderContributor, contributor_id)

    def get_for_user(self, user_id: uuid.UUID) -> ProviderContributor | None:
        return self.session.scalar(
            select(ProviderContributor).where(ProviderContributor.user_id == user_id)
        )

    def list(self, status: str | None = None) -> list[ProviderContributor]:
        statement = select(ProviderContributor).order_by(ProviderContributor.display_name)
        if status:
            statement = statement.where(ProviderContributor.status == status)
        return list(self.session.scalars(statement))

    def create(
        self,
        *,
        display_name: str,
        consent_version: str,
        contact_email: str | None = None,
        user_id: uuid.UUID | None = None,
        consent_reference: str | None = None,
        consent_at: Any | None = None,
    ) -> ProviderContributor:
        contributor = ProviderContributor(
            user_id=user_id,
            display_name=display_name,
            contact_email=contact_email,
            consent_version=consent_version,
            consent_at=consent_at or utcnow(),
            consent_reference=consent_reference,
            status="ACTIVE",
        )
        self.session.add(contributor)
        self.session.flush()
        return contributor


class QuotaReservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count_since(self, credential_id: uuid.UUID, since: Any, now: Any) -> int:
        return int(
            self.session.scalar(
                select(func.count(ProviderQuotaReservation.id)).where(
                    ProviderQuotaReservation.credential_id == credential_id,
                    ProviderQuotaReservation.created_at >= since,
                    or_(
                        ProviderQuotaReservation.status == "CONSUMED",
                        (ProviderQuotaReservation.status == "RESERVED")
                        & (ProviderQuotaReservation.expires_at > now),
                    ),
                )
            )
            or 0
        )

    def count_since_project(self, project_id: str, since: Any, now: Any) -> int:
        """Reservations for every credential in one Google Cloud project.

        This is the number that matters: quota is shared per project, so adding
        keys must not add capacity.
        """

        return int(
            self.session.scalar(
                select(func.count(ProviderQuotaReservation.id))
                .join(
                    ProviderCredential,
                    ProviderCredential.id == ProviderQuotaReservation.credential_id,
                )
                .where(
                    ProviderCredential.project_id == project_id,
                    ProviderQuotaReservation.created_at >= since,
                    or_(
                        ProviderQuotaReservation.status == "CONSUMED",
                        (ProviderQuotaReservation.status == "RESERVED")
                        & (ProviderQuotaReservation.expires_at > now),
                    ),
                )
            )
            or 0
        )

    def project_cooldown(self, project_id: str) -> ProviderProjectCooldown | None:
        return self.session.get(ProviderProjectCooldown, project_id)

    def set_project_cooldown(
        self, *, project_id: str, reason: str, cooldown_until: Any
    ) -> ProviderProjectCooldown:
        row = self.session.get(ProviderProjectCooldown, project_id)
        if row is None:
            row = ProviderProjectCooldown(
                project_id=project_id,
                reason=reason[:300],
                cooldown_until=cooldown_until,
                updated_at=utcnow(),
            )
            self.session.add(row)
        else:
            row.reason = reason[:300]
            row.cooldown_until = cooldown_until
            row.updated_at = utcnow()
        self.session.flush()
        return row

    def clear_project_cooldown(self, project_id: str) -> None:
        row = self.session.get(ProviderProjectCooldown, project_id)
        if row is not None:
            self.session.delete(row)
            self.session.flush()

    def active_project_cooldowns(self, now: Any) -> list[ProviderProjectCooldown]:
        return list(
            self.session.scalars(
                select(ProviderProjectCooldown).where(
                    ProviderProjectCooldown.cooldown_until > now
                )
            )
        )

    def reserve(
        self, *, tenant_id: uuid.UUID, credential_id: uuid.UUID, purpose: str, ttl_seconds: int
    ) -> ProviderQuotaReservation:
        now = utcnow()
        row = ProviderQuotaReservation(
            tenant_id=tenant_id,
            credential_id=credential_id,
            purpose=purpose,
            status="RESERVED",
            expires_at=now + timedelta(seconds=ttl_seconds),
            created_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, reservation_id: uuid.UUID) -> ProviderQuotaReservation | None:
        return self.session.get(ProviderQuotaReservation, reservation_id)


class UsageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        tenant_id: uuid.UUID | None,
        credential_id: uuid.UUID | None,
        job_id: uuid.UUID | None,
        provider: str,
        model: str,
        purpose: str,
        prompt_version_id: uuid.UUID | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cached_tokens: int | None,
        cost_usd: Decimal | None,
        reported: bool,
        success: bool,
        request_id: str | None,
        latency_ms: int | None,
        http_status: int | None,
        error_class: str | None,
        project_id: str = "",
        retry_count: int = 0,
        contributor_id: uuid.UUID | None = None,
    ) -> ProviderUsage:
        row = ProviderUsage(
            tenant_id=tenant_id,
            contributor_id=contributor_id,
            credential_id=credential_id,
            job_id=job_id,
            project_id=project_id or "",
            provider=provider,
            model=model,
            purpose=purpose,
            retry_count=retry_count,
            prompt_version_id=prompt_version_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
            reported=reported,
            success=success,
            request_id=request_id,
            latency_ms=latency_ms,
            http_status=http_status,
            error_class=error_class,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def summary(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        rows = self.session.execute(
            select(
                ProviderUsage.model,
                func.count(ProviderUsage.id),
                func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.cached_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.cost_usd), 0),
            )
            .where(ProviderUsage.tenant_id == tenant_id)
            .group_by(ProviderUsage.model)
        ).all()
        requests = 0
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        cost = Decimal("0")
        by_model: dict[str, int] = {}
        for model, count, input_sum, output_sum, cached_sum, cost_sum in rows:
            requests += int(count)
            input_tokens += int(input_sum)
            output_tokens += int(output_sum)
            cached_tokens += int(cached_sum)
            cost += Decimal(cost_sum or 0)
            by_model[model] = int(count)
        return {
            "tenant_id": tenant_id,
            "requests": requests,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "cost_usd": float(cost),
            "by_model": by_model,
        }

    # ── fleet aggregation ───────────────────────────────────────────────────

    def window_stats(self, since: Any, *, project_id: str | None = None) -> dict[str, Any]:
        """Requests, tokens and failures since ``since``.

        Failures are split by class so a 429 (quota) cannot be confused with a
        500 (provider outage) in an alert or a rate calculation.
        """

        conditions = [ProviderUsage.created_at >= since]
        if project_id is not None:
            conditions.append(ProviderUsage.project_id == project_id)

        row = self.session.execute(
            select(
                func.count(ProviderUsage.id),
                func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
                func.count(ProviderUsage.id).filter(ProviderUsage.success.is_(False)),
                func.count(ProviderUsage.id).filter(
                    ProviderUsage.error_class == "ProviderQuotaError"
                ),
                func.count(ProviderUsage.id).filter(
                    ProviderUsage.error_class == "ProviderAuthenticationError"
                ),
            ).where(*conditions)
        ).one()
        requests, input_tokens, output_tokens, failures, quota_failures, auth_failures = row
        return {
            "requests": int(requests or 0),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "failures": int(failures or 0),
            "quota_failures": int(quota_failures or 0),
            "auth_failures": int(auth_failures or 0),
        }

    def model_window_stats(self, since: Any) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(
                ProviderUsage.model,
                func.count(ProviderUsage.id),
                func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
                func.count(ProviderUsage.id).filter(ProviderUsage.success.is_(False)),
            )
            .where(ProviderUsage.created_at >= since)
            .group_by(ProviderUsage.model)
            .order_by(ProviderUsage.model)
        ).all()
        return [
            {
                "model": model,
                "requests": int(count),
                "input_tokens": int(input_sum or 0),
                "output_tokens": int(output_sum or 0),
                "failures": int(failures or 0),
            }
            for model, count, input_sum, output_sum, failures in rows
        ]

    def project_window_stats(self, since: Any) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(
                ProviderUsage.project_id,
                func.count(ProviderUsage.id),
                func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
                func.count(ProviderUsage.id).filter(ProviderUsage.success.is_(False)),
                func.count(ProviderUsage.id).filter(
                    ProviderUsage.error_class == "ProviderQuotaError"
                ),
            )
            .where(ProviderUsage.created_at >= since)
            .group_by(ProviderUsage.project_id)
            .order_by(ProviderUsage.project_id)
        ).all()
        return [
            {
                "project_id": project,
                "requests": int(count),
                "input_tokens": int(input_sum or 0),
                "output_tokens": int(output_sum or 0),
                "failures": int(failures or 0),
                "quota_failures": int(quota_failures or 0),
            }
            for project, count, input_sum, output_sum, failures, quota_failures in rows
        ]

    def contributor_window_stats(self, since: Any) -> dict[uuid.UUID, dict[str, Any]]:
        """Contribution statistics per contributor.

        Grouped by the ledger's denormalised ``contributor_id``, so a key that
        was retired keeps counting toward the person who lent it.
        """

        rows = self.session.execute(
            select(
                ProviderUsage.contributor_id,
                func.count(ProviderUsage.id),
                func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
                func.count(ProviderUsage.id).filter(ProviderUsage.success.is_(False)),
                func.count(ProviderUsage.id).filter(
                    ProviderUsage.error_class == "ProviderQuotaError"
                ),
                func.max(ProviderUsage.created_at).filter(ProviderUsage.success.is_(True)),
            )
            .where(
                ProviderUsage.created_at >= since,
                ProviderUsage.contributor_id.is_not(None),
            )
            .group_by(ProviderUsage.contributor_id)
        ).all()
        return {
            contributor_id: {
                "requests": int(count or 0),
                "input_tokens": int(input_sum or 0),
                "output_tokens": int(output_sum or 0),
                "failures": int(failures or 0),
                "quota_failures": int(quota_failures or 0),
                "last_success_at": last_success,
            }
            for (
                contributor_id,
                count,
                input_sum,
                output_sum,
                failures,
                quota_failures,
                last_success,
            ) in rows
            if contributor_id is not None
        }

    def key_window_stats(self, since: Any) -> dict[uuid.UUID, dict[str, Any]]:
        rows = self.session.execute(
            select(
                ProviderUsage.credential_id,
                func.count(ProviderUsage.id),
                func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
                func.count(ProviderUsage.id).filter(ProviderUsage.success.is_(False)),
                func.count(ProviderUsage.id).filter(
                    ProviderUsage.error_class == "ProviderQuotaError"
                ),
                func.max(ProviderUsage.created_at).filter(ProviderUsage.success.is_(True)),
                func.max(ProviderUsage.created_at).filter(ProviderUsage.success.is_(False)),
            )
            .where(
                ProviderUsage.created_at >= since,
                ProviderUsage.credential_id.is_not(None),
            )
            .group_by(ProviderUsage.credential_id)
        ).all()
        return {
            credential_id: {
                "requests": int(count or 0),
                "input_tokens": int(input_sum or 0),
                "output_tokens": int(output_sum or 0),
                "failures": int(failures or 0),
                "quota_failures": int(quota_failures or 0),
                "last_success_at": last_success,
                "last_failure_at": last_failure,
            }
            for (
                credential_id,
                count,
                input_sum,
                output_sum,
                failures,
                quota_failures,
                last_success,
                last_failure,
            ) in rows
            if credential_id is not None
        }

    def daily(self, since: Any) -> list[dict[str, Any]]:
        day = func.date_trunc("day", ProviderUsage.created_at).label("day")
        rows = self.session.execute(
            select(
                day,
                func.count(ProviderUsage.id),
                func.coalesce(func.sum(ProviderUsage.input_tokens), 0),
                func.coalesce(func.sum(ProviderUsage.output_tokens), 0),
                func.count(ProviderUsage.id).filter(ProviderUsage.success.is_(False)),
            )
            .where(ProviderUsage.created_at >= since)
            .group_by(day)
            .order_by(day)
        ).all()
        return [
            {
                "day": day_value,
                "requests": int(count),
                "input_tokens": int(input_sum or 0),
                "output_tokens": int(output_sum or 0),
                "failures": int(failures or 0),
            }
            for day_value, count, input_sum, output_sum, failures in rows
        ]

    def recent_failures(self, limit: int = 20) -> list[ProviderUsage]:
        return list(
            self.session.scalars(
                select(ProviderUsage)
                .where(ProviderUsage.success.is_(False))
                .order_by(ProviderUsage.created_at.desc())
                .limit(limit)
            )
        )


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        tenant_id: uuid.UUID | None,
        actor_type: str,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str,
        detail: dict[str, Any],
        before_hash: str | None = None,
        after_hash: str | None = None,
        request_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            before_hash=before_hash,
            after_hash=after_hash,
            request_id=request_id,
        )
        self.session.add(event)
        self.session.flush()
        return event
