"""Read-only correction progress from persisted rows.

The job row owns the percentage; the engine's ``engine_runs`` own the stage
history; ``question_results`` own the per-question answer.  This service never
advances any of them and never fills a gap with an estimate.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..correction import verification_status as verification_completeness
from ..correction.processing import effective_state, is_scoreable
from ..db.models import CorrectionJob, EngineRun, ExamBlueprintVersion
from ..db.repositories import (
    DocumentRepository,
    JobRepository,
    ResultRepository,
    SubmissionRepository,
)
from ..schemas.blueprint import BlueprintStructure
from ..schemas.progress import (
    JobProgressRead,
    ProgressEventRead,
    ProgressQuestionRead,
    ProgressStageRead,
)
from .classroom_job_access import require_job_access


class ProgressService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.jobs = JobRepository(session)
        self.results = ResultRepository(session)
        self.submissions = SubmissionRepository(session)
        self.documents = DocumentRepository(session)

    def job_progress(self, principal: Principal, job_id: uuid.UUID) -> JobProgressRead:
        job = self.jobs.get(principal.tenant_id, job_id)
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")
        require_job_access(self.session, principal, job)
        return self._build(job)

    def _build(self, job: CorrectionJob) -> JobProgressRead:
        blueprint = self.session.get(ExamBlueprintVersion, job.blueprint_version_id)
        if blueprint is None or blueprint.tenant_id != job.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "The job's blueprint is unavailable.")
        try:
            structure = BlueprintStructure.model_validate(blueprint.structure)
        except ValueError as error:
            raise AppError(
                ErrorCode.RESULT_NOT_READY,
                "The job's approved blueprint cannot be read, so progress cannot be described.",
            ) from error

        leaves = structure.scoreable_leaf_ids
        max_by_question = self._leaf_marks(structure)
        rows = self.results.list_for_job(job.tenant_id, job.id)
        row_by_question = {str(row.question_id): row for row in rows}

        verification_rows = self.results.verifications(job.id)
        paper_verification = verification_completeness.summarise(
            rows, verification_completeness.records_from_rows(verification_rows)
        )

        questions: list[ProgressQuestionRead] = []
        completed = review = failed = 0
        awarded = 0
        for question_id in leaves:
            row = row_by_question.get(question_id)
            if row is None:
                questions.append(
                    ProgressQuestionRead(
                        question_id=question_id,
                        max_marks=max_by_question.get(question_id, 0),
                        status="PENDING",
                    )
                )
                continue
            state = effective_state(
                row.status,
                row.processing_state,
                review_required=bool(row.review_required),
            )
            if is_scoreable(state):
                completed += 1
                awarded += row.awarded_marks
            if row.review_required or row.status == "REVIEW_REQUIRED":
                review += 1
            verification = paper_verification.question(question_id)
            questions.append(
                ProgressQuestionRead(
                    question_id=question_id,
                    max_marks=row.max_marks,
                    status=row.status,
                    processing_state=row.processing_state,
                    awarded_marks=row.awarded_marks if is_scoreable(state) else None,
                    confidence=row.confidence,
                    review_required=bool(row.review_required),
                    verification_status=(
                        verification.status if verification is not None else None
                    ),
                    result_id=row.id,
                )
            )

        events = self.jobs.events(job.tenant_id, job.id)
        stages = list(
            self.session.scalars(
                select(EngineRun)
                .where(EngineRun.tenant_id == job.tenant_id, EngineRun.job_id == job.id)
                .order_by(EngineRun.created_at.asc())
            )
        )
        documents = self.documents.list_for_submission(job.tenant_id, job.submission_id)

        timestamps: list[datetime] = [job.updated_at]
        if events:
            timestamps.append(max(event.created_at for event in events))
        if stages:
            timestamps.append(max(stage.created_at for stage in stages))
        if rows:
            timestamps.append(max(row.updated_at for row in rows))
        last_updated = max(timestamps)

        return JobProgressRead(
            job_id=job.id,
            submission_id=job.submission_id,
            assignment_id=job.assignment_id,
            state=job.state,
            progress=job.progress,
            started_at=job.started_at,
            finished_at=job.finished_at,
            updated_at=job.updated_at,
            last_updated_at=last_updated,
            elapsed_seconds=self._elapsed(job),
            total_questions=len(leaves),
            completed_questions=completed,
            processing_questions=0,
            review_questions=review,
            failed_questions=failed,
            pending_questions=max(0, len(leaves) - len(rows)),
            awarded_marks=awarded,
            available_marks=sum(max_by_question.get(question_id, 0) for question_id in leaves),
            estimated_remaining_seconds=None,
            questions=questions,
            stages=[
                ProgressStageRead(
                    stage=row.stage,
                    outcome=row.outcome,
                    at=row.created_at,
                    prompt_version=row.prompt_version,
                    detail=row.detail,
                )
                for row in stages
            ],
            events=[
                ProgressEventRead(
                    seq=event.event_seq,
                    from_state=event.from_state,
                    state=event.to_state,
                    detail=event.detail,
                    actor=event.actor,
                    at=event.created_at,
                )
                for event in events
            ],
            documents=[
                {
                    "id": str(document.id),
                    "kind": document.kind,
                    "filename": document.original_filename,
                    "status": document.status,
                    "pages": document.page_count,
                    "error_code": document.error_code,
                }
                for document in documents
            ],
            error_code=job.error_code,
            error_message=job.error_message,
            retryable=job.retryable,
            result_source=job.result_source,
            verification_status=job.verification_status,
        )

    @staticmethod
    def _leaf_marks(structure: BlueprintStructure) -> dict[str, int]:
        marks: dict[str, int] = {}
        for question in structure.questions:
            if question.excluded:
                continue
            if question.subquestions:
                for sub in question.subquestions:
                    if not sub.excluded:
                        marks[sub.question_id] = sub.max_marks
                continue
            marks[question.question_id] = question.max_marks
        return marks

    @staticmethod
    def _elapsed(job: CorrectionJob) -> int | None:
        start = job.started_at or job.created_at
        end = job.finished_at
        if start is None:
            return None
        if end is None:
            from ..core.ids import utcnow

            end = utcnow()
        return max(0, int((end - start).total_seconds()))
