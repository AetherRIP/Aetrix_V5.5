"""Correction-job lifecycle.

This module owns the rules a job must obey:

* creation is idempotent per tenant and key, and a key cannot be reused for a
  different request;
* only an approved, immutable blueprint and an approved scheme can start a job;
* cancellation is terminal, but cancelling an in-flight job only records the
  request — the worker finalizes it at a safe boundary;
* retry is explicit and resets the attempt budget for a new run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import __version__
from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import content_hash, utcnow
from ..core.security import Principal
from ..db.models import CorrectionJob, ExamBlueprintVersion, MarkSchemeVersion
from ..db.repositories import (
    AssignmentRepository,
    BlueprintRepository,
    JobRepository,
    MarkSchemeRepository,
    SubmissionRepository,
)
from ..schemas.api import CorrectionCreate
from .states import JobState


@dataclass(frozen=True, slots=True)
class JobCreation:
    job: CorrectionJob
    created: bool


class JobService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.jobs = JobRepository(session)
        self.assignments = AssignmentRepository(session)
        self.submissions = SubmissionRepository(session)
        self.blueprints = BlueprintRepository(session)
        self.schemes = MarkSchemeRepository(session)
        self.audit = AuditService(session)

    def create(self, principal: Principal, payload: CorrectionCreate) -> JobCreation:
        assignment = self.assignments.get(principal.tenant_id, payload.assignment_id)
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        submission = self.submissions.get(principal.tenant_id, payload.submission_id)
        if submission is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
        if submission.assignment_id != assignment.id:
            raise AppError(ErrorCode.CONFLICT, "The submission does not belong to this assignment.")
        if assignment.blueprint_version_id is None or assignment.scheme_version_id is None:
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "The assignment has no blueprint or mark scheme attached.",
            )

        blueprint = self.blueprints.get(principal.tenant_id, assignment.blueprint_version_id)
        if blueprint is None:
            raise AppError(ErrorCode.ASSIGNMENT_NOT_READY, "The assignment blueprint is missing.")
        if self.settings.marking.blueprint_approval_required and blueprint.status != "APPROVED":
            raise AppError(
                ErrorCode.BLUEPRINT_NOT_APPROVED,
                "The assignment blueprint is not approved.",
            )
        scheme = self.schemes.get_version(principal.tenant_id, assignment.scheme_version_id)
        if scheme is None:
            raise AppError(ErrorCode.ASSIGNMENT_NOT_READY, "The assignment mark scheme is missing.")
        if scheme.status != "APPROVED":
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "The assignment mark scheme is not approved.",
            )

        request_hash = self._request_hash(submission.content_hash, blueprint, scheme)
        key = payload.idempotency_key or self._automatic_key(
            principal.tenant_id, assignment.id, submission.id, blueprint, scheme
        )

        existing = self.jobs.find_by_idempotency(principal.tenant_id, key)
        if existing is not None:
            return self._existing(existing, request_hash)

        try:
            job = self.jobs.create(
                tenant_id=principal.tenant_id,
                assignment_id=assignment.id,
                submission_id=submission.id,
                blueprint_version_id=blueprint.id,
                scheme_version_id=scheme.id,
                idempotency_key=key,
                request_hash=request_hash,
                max_attempts=self.settings.worker.max_attempts,
            )
            self.jobs.add_event(
                job,
                from_state=None,
                to_state=JobState.CREATED.value,
                detail={
                    "assignment_id": str(assignment.id),
                    "submission_id": str(submission.id),
                    "blueprint_version_id": str(blueprint.id),
                    "scheme_version_id": str(scheme.id),
                    "request_hash": request_hash,
                },
                actor=f"user:{principal.user_id}",
            )
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="job.created",
                entity_type="correction_job",
                entity_id=job.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "assignment_id": str(assignment.id),
                    "submission_id": str(submission.id),
                    "idempotency_key": key,
                },
            )
            self.session.commit()
            return JobCreation(job=job, created=True)
        except IntegrityError:
            self.session.rollback()
            existing = self.jobs.find_by_idempotency(principal.tenant_id, key)
            if existing is None:
                raise
            return self._existing(existing, request_hash)

    def _existing(self, job: CorrectionJob, request_hash: str) -> JobCreation:
        if job.request_hash != request_hash:
            raise AppError(
                ErrorCode.CONFLICT,
                "This idempotency key was already used for a different request.",
            )
        return JobCreation(job=job, created=False)

    def _request_hash(
        self,
        submission_hash: str,
        blueprint: ExamBlueprintVersion,
        scheme: MarkSchemeVersion,
    ) -> str:
        return content_hash(
            submission_hash,
            blueprint.content_hash,
            scheme.content_hash,
            __version__,
        )

    def _automatic_key(
        self,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        submission_id: uuid.UUID,
        blueprint: ExamBlueprintVersion,
        scheme: MarkSchemeVersion,
    ) -> str:
        return content_hash(
            "auto",
            str(tenant_id),
            str(assignment_id),
            str(submission_id),
            str(blueprint.id),
            str(scheme.id),
            __version__,
        )

    def get(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> CorrectionJob:
        job = self.jobs.get(tenant_id, job_id)
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")
        return job

    def get_with_events(
        self, tenant_id: uuid.UUID, job_id: uuid.UUID
    ) -> tuple[CorrectionJob, list]:
        job = self.get(tenant_id, job_id)
        return job, self.jobs.events(tenant_id, job_id)

    def cancel(self, principal: Principal, job_id: uuid.UUID) -> CorrectionJob:
        job = self.jobs.get(principal.tenant_id, job_id, for_update=True)
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")
        state = JobState(job.state)
        if state is JobState.CANCELLED:
            self.session.commit()
            return job
        if state in {JobState.COMPLETED, JobState.FAILED}:
            raise AppError(ErrorCode.JOB_NOT_CANCELLABLE, "A finished job cannot be cancelled.")

        # Cancellation is terminal.  The lease is cleared so the job cannot be
        # reclaimed; a worker already inside the pipeline may finish its current
        # call, but it must observe ``cancel_requested`` before persisting any
        # result.  Phase 5's pipeline checks that flag at every checkpoint.
        job.cancel_requested = True
        job.lease_owner = None
        job.lease_expires_at = None
        self.jobs.transition(
            job,
            JobState.CANCELLED,
            detail={"reason": "cancelled by user"},
            actor=f"user:{principal.user_id}",
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="job.cancelled",
            entity_type="correction_job",
            entity_id=job.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"state": job.state},
        )
        self.session.commit()
        return job

    def retry(self, principal: Principal, job_id: uuid.UUID) -> CorrectionJob:
        job = self.jobs.get(principal.tenant_id, job_id, for_update=True)
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")
        state = JobState(job.state)
        if state not in {JobState.FAILED, JobState.RETRY_SUSPENDED}:
            raise AppError(
                ErrorCode.JOB_NOT_RETRYABLE,
                "Only a failed or suspended job can be retried.",
            )

        job.attempts = 0
        job.cancel_requested = False
        job.error_code = None
        job.error_message = None
        job.retryable = None
        job.finished_at = None
        job.lease_owner = None
        job.lease_expires_at = None
        self.jobs.transition(
            job,
            JobState.VALIDATING,
            detail={"reason": "manual retry", "previous_state": state.value},
            actor=f"user:{principal.user_id}",
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="job.retried",
            entity_type="correction_job",
            entity_id=job.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"previous_state": state.value},
        )
        self.session.commit()
        return job

    def list(
        self, tenant_id: uuid.UUID, *, state: str | None = None, limit: int = 50
    ) -> list[CorrectionJob]:
        return self.jobs.list(tenant_id, state=state, limit=limit)

    def mark_failed(
        self,
        job: CorrectionJob,
        *,
        code: str,
        message: str,
        retryable: bool,
        actor: str = "system",
    ) -> CorrectionJob:
        target = (
            JobState.RETRY_SUSPENDED
            if retryable and job.attempts < job.max_attempts
            else JobState.FAILED
        )
        job.error_code = code
        job.error_message = message[:2000]
        job.retryable = retryable
        job.lease_owner = None
        job.lease_expires_at = None
        self.jobs.transition(
            job,
            target,
            detail={"code": code, "retryable": retryable},
            actor=actor,
        )
        self.session.commit()
        return job

    def finish(self, job: CorrectionJob, *, actor: str = "system") -> CorrectionJob:
        if JobState(job.state) is JobState.CANCELLED:
            return job
        if JobState(job.state) is not JobState.FINALIZING:
            self.jobs.transition(
                job,
                JobState.FINALIZING,
                detail={"event": "results_finalized"},
                actor=actor,
            )
        self.jobs.transition(
            job,
            JobState.COMPLETED,
            detail={"event": "completed"},
            actor=actor,
        )
        job.lease_owner = None
        job.lease_expires_at = None
        job.finished_at = utcnow()
        self.session.commit()
        return job
