"""Reading, overriding and approving marked results.

Three separate acts are modelled here and they must not be conflated:

* **reading** a result — available to any member of the workspace;
* **overriding** one question — a reviewer act, requiring a stated reason and
  preserving the original award in the learning record;
* **approving** a job's totals — a teacher act, refused while any question still
  needs review.

Approval is stored, not inferred from a job state, so "provisional" and
"approved" are facts the gradebook can report.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal, ensure_reviewer
from ..db.models import (
    CorrectionJob,
    JobApproval,
    LearningFeedback,
    ReviewDecision,
    Submission,
)
from ..db.repositories import (
    DocumentRepository,
    JobRepository,
    ResultRepository,
    SubmissionRepository,
    UserRepository,
)
from ..jobs.states import JobState
from ..schemas.results import (
    CriterionResultRead,
    EvidenceRead,
    JobApprovalRequest,
    JobResultsRead,
    MarkOverride,
    PageRead,
    QuestionResultRead,
    QuestionReviewRequest,
    ResultTotals,
    ReviewDecisionRead,
    VerificationRead,
)
from ..storage.base import Storage, StorageError

_APPROVERS = frozenset({"OWNER", "ADMIN", "TEACHER", "PLATFORM_OWNER"})


def ensure_approver(principal: Principal) -> None:
    if principal.role not in _APPROVERS:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Approving results requires a teacher, administrator or owner role.",
        )


class ResultsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.results = ResultRepository(session)
        self.jobs = JobRepository(session)
        self.submissions = SubmissionRepository(session)
        self.documents = DocumentRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    # -- reads -----------------------------------------------------------
    def _job(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> CorrectionJob:
        job = self.jobs.get(tenant_id, job_id)
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")
        return job

    def _submission(self, tenant_id: uuid.UUID, submission_id: uuid.UUID) -> Submission:
        submission = self.submissions.get(tenant_id, submission_id)
        if submission is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
        return submission

    def latest_job_for_submission(
        self, tenant_id: uuid.UUID, submission_id: uuid.UUID
    ) -> CorrectionJob | None:
        return self.session.scalar(
            select(CorrectionJob)
            .where(
                CorrectionJob.tenant_id == tenant_id,
                CorrectionJob.submission_id == submission_id,
            )
            .order_by(CorrectionJob.created_at.desc())
            .limit(1)
        )

    def job_results(self, principal: Principal, job_id: uuid.UUID) -> JobResultsRead:
        job = self._job(principal.tenant_id, job_id)
        return self._build(job)

    def submission_results(
        self, principal: Principal, submission_id: uuid.UUID
    ) -> JobResultsRead | None:
        submission = self._submission(principal.tenant_id, submission_id)
        job = self.latest_job_for_submission(principal.tenant_id, submission.id)
        if job is None:
            return None
        return self._build(job)

    def _build(self, job: CorrectionJob) -> JobResultsRead:
        submission = self._submission(job.tenant_id, job.submission_id)
        rows = self.results.list_for_job(job.tenant_id, job.id)
        ids = [row.id for row in rows]
        criteria = self.results.criteria(ids)
        evidence = self.results.evidence(ids)
        criteria_by_result: dict[uuid.UUID, list[CriterionResultRead]] = {}
        for row in criteria:
            criteria_by_result.setdefault(row.question_result_id, []).append(
                CriterionResultRead.model_validate(row)
            )
        evidence_by_result: dict[uuid.UUID, list[EvidenceRead]] = {}
        for row in evidence:
            evidence_by_result.setdefault(row.question_result_id, []).append(
                EvidenceRead.model_validate(row)
            )

        questions = [
            QuestionResultRead.model_validate(row).model_copy(
                update={
                    "criteria": criteria_by_result.get(row.id, []),
                    "evidence": evidence_by_result.get(row.id, []),
                }
            )
            for row in rows
        ]
        approval = self.session.scalar(
            select(JobApproval).where(JobApproval.job_id == job.id)
        )
        awarded = sum(row.awarded_marks for row in rows)
        total = sum(row.max_marks for row in rows)
        totals = ResultTotals(
            awarded=awarded,
            total=total,
            questions=len(rows),
            unanswered=sum(1 for row in rows if row.status == "UNMARKED"),
            review_required=sum(1 for row in rows if row.review_required),
            approved=approval is not None,
            state=job.state,
        )
        return JobResultsRead(
            job_id=job.id,
            submission_id=submission.id,
            assignment_id=job.assignment_id,
            student_ref=submission.student_ref,
            job_state=job.state,
            questions=questions,
            verifications=[
                VerificationRead.model_validate(row)
                for row in self.results.verifications(job.id)
            ],
            reviews=[
                ReviewDecisionRead.model_validate(row) for row in self.results.reviews(job.id)
            ],
            totals=totals,
            approved_at=approval.approved_at if approval else None,
            approved_by=approval.approved_by_label if approval else None,
            record_version=job.record_version,
        )

    # -- review ----------------------------------------------------------
    def override(
        self, principal: Principal, question_result_id: uuid.UUID, payload: MarkOverride
    ) -> JobResultsRead:
        ensure_reviewer(principal)
        result = self.results.get(principal.tenant_id, question_result_id)
        if result is None:
            raise AppError(ErrorCode.NOT_FOUND, "Question result not found.")
        job = self._job(principal.tenant_id, result.job_id)
        if JobState(job.state) is JobState.CANCELLED:
            raise AppError(ErrorCode.CONFLICT, "A cancelled job's results cannot be changed.")
        if payload.awarded_marks > result.max_marks:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"A mark cannot exceed the question maximum ({result.max_marks}).",
                details={"max_marks": result.max_marks},
            )
        if (
            payload.expected_record_version is not None
            and payload.expected_record_version != job.record_version
        ):
            raise AppError(
                ErrorCode.CONFLICT,
                "Someone else changed this result first. Reload it before overriding.",
                details={"record_version": job.record_version},
            )
        approval = self.session.scalar(
            select(JobApproval).where(JobApproval.job_id == job.id)
        )
        if approval is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "An approved result cannot be changed. Reopen the job first.",
            )

        previous = result.awarded_marks
        result.awarded_marks = payload.awarded_marks
        result.status = "AWARDED" if payload.awarded_marks > 0 else "ZERO"
        result.review_required = False
        kept_concerns = [
            concern
            for concern in (result.scheme_concerns or [])
            if concern.get("code") != "REVIEW"
        ]
        result.scheme_concerns = [
            *kept_concerns,
            {"code": "TEACHER_OVERRIDE", "message": payload.reason},
        ]
        job.record_version += 1
        approver = self.users.get(principal.tenant_id, principal.user_id)
        actor_label = (
            (approver.display_name or approver.email) if approver is not None else None
        )
        self.session.add(
            ReviewDecision(
                tenant_id=principal.tenant_id,
                job_id=job.id,
                question_id=result.question_id,
                requested_reason=payload.reason,
                mode="TEACHER_OVERRIDE",
                independent=False,
                first_award=previous,
                second_award=payload.awarded_marks,
                outcome="OVERRIDE",
                decided_by=actor_label or f"user:{principal.user_id}",
                decided_at=utcnow(),
            )
        )
        self.session.add(
            LearningFeedback(
                tenant_id=principal.tenant_id,
                job_id=job.id,
                question_id=result.question_id,
                criterion_id=None,
                original_mark=previous,
                revised_mark=payload.awarded_marks,
                original_explanation=None,
                teacher_explanation=payload.reason,
                engine_version="v5.5",
                model_version=None,
                approved=False,
                approved_by=principal.user_id,
            )
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="result.overridden",
            entity_type="question_result",
            entity_id=result.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "job_id": str(job.id),
                "question_id": result.question_id,
                "previous_mark": previous,
                "awarded_marks": payload.awarded_marks,
                "reason": payload.reason,
            },
            before={"awarded_marks": previous},
            after={"awarded_marks": payload.awarded_marks},
        )
        self.session.commit()
        return self._build(job)

    def review_question(
        self,
        principal: Principal,
        job_id: uuid.UUID,
        question_id: str,
        payload: QuestionReviewRequest,
    ) -> JobResultsRead:
        """Record the decision a reviewer made about one flagged question.

        This is the audit trail of the human step, not a second model call: an
        independent second pass is recorded with the mark that pass produced.
        """

        ensure_reviewer(principal)
        job = self._job(principal.tenant_id, job_id)
        if JobState(job.state) is JobState.CANCELLED:
            raise AppError(ErrorCode.CONFLICT, "A cancelled job's results cannot be reviewed.")
        approval = self.session.scalar(
            select(JobApproval).where(JobApproval.job_id == job.id)
        )
        if approval is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "An approved result cannot be reviewed again. Reopen the job first.",
            )

        result = self.results.get_question(job.id, question_id)
        if result is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "That question has no result on this job.",
                details={"question_id": question_id},
            )
        if payload.awarded_marks is not None and payload.awarded_marks > result.max_marks:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"A mark cannot exceed the question maximum ({result.max_marks}).",
                details={"max_marks": result.max_marks},
            )

        previous = result.awarded_marks
        award = previous if payload.decision == "UPHOLD" else payload.awarded_marks
        if award is not None and award != previous:
            result.awarded_marks = award
            result.status = "AWARDED" if award > 0 else "ZERO"
            result.review_required = False
            kept_concerns = [
                concern
                for concern in (result.scheme_concerns or [])
                if concern.get("code") != "REVIEW"
            ]
            result.scheme_concerns = [
                *kept_concerns,
                {"code": "REVIEW_DECISION", "message": payload.reason},
            ]
        else:
            result.review_required = False

        job.record_version += 1
        reviewer = self.users.get(principal.tenant_id, principal.user_id)
        actor_label = (reviewer.display_name or reviewer.email) if reviewer is not None else None
        outcome = {
            "UPHOLD": "UPHELD",
            "CHANGE": "CHANGED",
            "INDEPENDENT": "SECOND_PASS",
        }[payload.decision]
        self.session.add(
            ReviewDecision(
                tenant_id=principal.tenant_id,
                job_id=job.id,
                question_id=question_id,
                requested_reason=payload.reason,
                mode=payload.decision,
                independent=payload.decision == "INDEPENDENT",
                first_award=previous,
                second_award=result.awarded_marks,
                outcome=outcome,
                decided_by=actor_label or f"user:{principal.user_id}",
                decided_at=utcnow(),
            )
        )
        if result.awarded_marks != previous:
            self.session.add(
                LearningFeedback(
                    tenant_id=principal.tenant_id,
                    job_id=job.id,
                    question_id=question_id,
                    criterion_id=None,
                    original_mark=previous,
                    revised_mark=result.awarded_marks,
                    original_explanation=None,
                    teacher_explanation=payload.reason,
                    engine_version="v5.5",
                    model_version=None,
                    approved=False,
                    approved_by=principal.user_id,
                )
            )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="result.reviewed",
            entity_type="question_result",
            entity_id=result.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "job_id": str(job.id),
                "question_id": question_id,
                "decision": payload.decision,
                "previous_mark": previous,
                "awarded_marks": result.awarded_marks,
                "reason": payload.reason,
            },
            before={"awarded_marks": previous},
            after={"awarded_marks": result.awarded_marks},
        )
        self.session.commit()
        return self._build(job)

    def approve(
        self, principal: Principal, job_id: uuid.UUID, payload: JobApprovalRequest
    ) -> JobResultsRead:
        ensure_approver(principal)
        job = self._job(principal.tenant_id, job_id)
        if JobState(job.state) is JobState.CANCELLED:
            raise AppError(ErrorCode.CONFLICT, "A cancelled job cannot be approved.")
        if (
            payload.expected_record_version is not None
            and payload.expected_record_version != job.record_version
        ):
            raise AppError(
                ErrorCode.CONFLICT,
                "Someone else changed this result first. Reload it before approving.",
                details={"record_version": job.record_version},
            )

        rows = self.results.list_for_job(principal.tenant_id, job.id)
        if not rows:
            raise AppError(
                ErrorCode.RESULT_NOT_READY,
                "This job has produced no question results yet, so there is nothing to approve.",
            )
        unresolved = [row.question_id for row in rows if row.review_required]
        if unresolved:
            raise AppError(
                ErrorCode.CONFLICT,
                "Resolve every question that needs review before approving.",
                details={"questions": unresolved[:50]},
            )

        existing = self.session.scalar(
            select(JobApproval).where(JobApproval.job_id == job.id)
        )
        if existing is not None:
            return self._build(job)

        state = JobState(job.state)
        if state is not JobState.COMPLETED:
            if state is JobState.REVIEW_REQUIRED:
                self.jobs.transition(
                    job,
                    JobState.FINALIZING,
                    detail={"event": "human_review_complete"},
                    actor=f"user:{principal.user_id}",
                )
                self.jobs.transition(
                    job,
                    JobState.COMPLETED,
                    detail={"event": "approved"},
                    actor=f"user:{principal.user_id}",
                )
            else:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "The engine has not finished this job, so its marks are not ready to approve.",
                    details={"state": job.state},
                )

        approver = self.users.get(principal.tenant_id, principal.user_id)
        # Attribution must never be blank: when the account has no name yet, the
        # user identifier is the honest label rather than a missing approver.
        label = (
            (approver.display_name or approver.email or str(approver.id))
            if approver
            else str(principal.user_id)
        )
        approved_marks = sum(row.awarded_marks for row in rows)
        total_marks = sum(row.max_marks for row in rows)
        job.record_version += 1
        self.session.add(
            JobApproval(
                tenant_id=principal.tenant_id,
                job_id=job.id,
                approved_by=principal.user_id,
                approved_by_label=label,
                approved_at=utcnow(),
                approved_marks=approved_marks,
                total_marks=total_marks,
                note=payload.note,
                record_version=job.record_version,
            )
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="result.approved",
            entity_type="correction_job",
            entity_id=job.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "approved_marks": approved_marks,
                "total_marks": total_marks,
                "questions": len(rows),
                "note": payload.note,
            },
        )
        self.session.commit()
        return self._build(job)

    # -- page serving ----------------------------------------------------
    def pages(self, principal: Principal, submission_id: uuid.UUID) -> list[PageRead]:
        submission = self._submission(principal.tenant_id, submission_id)
        pages: list[PageRead] = []
        for document in self.documents.list_for_submission(
            principal.tenant_id, submission.id
        ):
            for page in self.documents.pages(principal.tenant_id, document.id):
                pages.append(
                    PageRead(
                        page_index=page.page_index,
                        document_id=document.id,
                        quality_status=page.quality_status,
                        width=page.width,
                        height=page.height,
                    )
                )
        return pages

    def page_image(
        self,
        principal: Principal,
        submission_id: uuid.UUID,
        page_index: int,
        storage: Storage,
    ) -> bytes:
        submission = self._submission(principal.tenant_id, submission_id)
        for document in self.documents.list_for_submission(
            principal.tenant_id, submission.id
        ):
            for page in self.documents.pages(principal.tenant_id, document.id):
                if page.page_index == page_index:
                    try:
                        return storage.read(page.storage_key)
                    except StorageError as error:
                        raise AppError(
                            ErrorCode.SERVICE_NOT_READY,
                            "This page is missing from storage.",
                        ) from error
        raise AppError(ErrorCode.NOT_FOUND, "Page not found.")
