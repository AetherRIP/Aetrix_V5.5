"""The real question-level marking pipeline.

One job marks one submission against one approved blueprint.  The pipeline:

1. re-loads the job in its own session and refuses to touch a cancelled one;
2. proves it has renderable pages, an approved blueprint and an approved scheme;
3. marks each *leaf* question (a sub-question where the paper has them, the
   question itself otherwise) through the audited provider-call service;
4. persists a question result, its components and its quoted evidence;
5. verifies each award and records uncertainty;
6. stops at ``REVIEW_REQUIRED`` when anything is unproven, otherwise
   ``FINALIZING`` so the runner can complete the job.

Nothing here invents a mark.  A malformed model response, a missing page, an
inconsistent award or a failed mathematical check produces a review item, not a
zero.  A provider outage raises ``RetryablePipelineError`` so the runner parks
the job with a truthful reason.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..db.models import (
    CorrectionJob,
    CriterionResult,
    DocumentPage,
    ExamBlueprintVersion,
    MarkingEvidence,
    MarkSchemeVersion,
    PageQuestionMapping,
    QuestionResult,
    VerificationResult,
)
from ..db.repositories import DocumentRepository, MarkSchemeRepository, ResultRepository
from ..jobs.pipeline import CorrectionPipeline, PipelineOutcome, RetryablePipelineError
from ..jobs.states import JobState
from ..prompts.registry import PromptRegistry
from ..providers.base import LLMInput, LLMProvider
from ..providers.factory import build_provider
from ..schemas.blueprint import BlueprintQuestion, BlueprintStructure
from ..services.provider_calls import ProviderCallService
from ..storage import build_storage
from ..storage.base import Storage, StorageError
from .schema import (
    MARKING_RESPONSE_SCHEMA,
    MarkingResponseInvalid,
    QuestionMark,
    parse_question_mark,
)
from .verification import VerificationOutcome, verify_question

MAX_PAGES_PER_QUESTION = 6
_RETRYABLE = {
    ErrorCode.PROVIDER_UNAVAILABLE,
    ErrorCode.SERVICE_NOT_READY,
    ErrorCode.CONFIGURATION_ERROR,
}


def _leaf_questions(structure: BlueprintStructure) -> list[tuple[str, int, str | None, str]]:
    """Return (question_id, max_marks, answer_type, parent_id) for scoreable leaves."""

    leaves: list[tuple[str, int, str | None, str]] = []
    for question in structure.questions:
        if question.excluded:
            continue
        if question.subquestions:
            for sub in question.subquestions:
                if sub.excluded:
                    continue
                leaves.append(
                    (sub.question_id, sub.max_marks, sub.answer_type, question.question_id)
                )
            continue
        leaves.append(
            (question.question_id, question.max_marks, question.answer_type, question.question_id)
        )
    return leaves


def _question_context(
    question_id: str,
    max_marks: int,
    answer_type: str | None,
    blueprint_question: BlueprintQuestion | None,
) -> str:
    lines = [
        f"Question: {question_id}",
        f"Maximum marks: {max_marks}",
        f"Answer type: {answer_type or 'not specified'}",
    ]
    if blueprint_question is not None:
        if blueprint_question.special_instructions:
            lines.append("Special instructions:")
            lines.extend(f"- {item}" for item in blueprint_question.special_instructions)
        if blueprint_question.criteria_refs:
            lines.append(f"Scheme references: {', '.join(blueprint_question.criteria_refs)}")
    return "\n".join(lines)


class QuestionMarkingPipeline(CorrectionPipeline):
    name = "question-marking-v1"

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        registry: PromptRegistry | None = None,
        storage: Storage | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._storage = storage

    # -- entry point -----------------------------------------------------
    def run(
        self, job: CorrectionJob, session: Session, settings: Settings
    ) -> PipelineOutcome:
        current = session.get(CorrectionJob, job.id)
        if current is None:
            raise RuntimeError("the claimed job disappeared before marking started")
        if current.cancel_requested:
            return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled before marking"})

        tenant_id = current.tenant_id
        blueprint = session.get(ExamBlueprintVersion, current.blueprint_version_id)
        scheme = session.get(MarkSchemeVersion, current.scheme_version_id)
        if blueprint is None or scheme is None:
            raise RuntimeError("the job references a missing blueprint or scheme version")
        if blueprint.tenant_id != tenant_id or scheme.tenant_id != tenant_id:
            raise RuntimeError("the job references a version from another workspace")
        if blueprint.status != "APPROVED":
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {"reason": "BLUEPRINT_NOT_APPROVED", "blueprint_status": blueprint.status},
            )
        if scheme.status != "APPROVED":
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {"reason": "SCHEME_NOT_APPROVED", "scheme_status": scheme.status},
            )

        structure = BlueprintStructure.model_validate(blueprint.structure)
        pages = self._pages(session, tenant_id, current.submission_id)
        readable = [
            page for page in pages if page.quality_status not in {"UNREADABLE", "EMPTY"}
        ]
        if not readable:
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": "NO_RENDERABLE_PAGES",
                    "page_count": len(pages),
                    "message": "No page of this submission can be read, so nothing was marked.",
                },
            )

        storage = self._storage or build_storage(settings)
        calls = ProviderCallService(
            session,
            settings,
            self._provider or build_provider(settings),
            self._registry or PromptRegistry(settings.provider.prompt_root),
        )
        scheme_criteria = MarkSchemeRepository(session).list_criteria(tenant_id, scheme.id)
        criteria_by_question: dict[str, list[Any]] = defaultdict(list)
        for criterion in scheme_criteria:
            criteria_by_question[criterion.question_id].append(criterion)

        results = ResultRepository(session)
        created: list[uuid.UUID] = []
        review_reasons: list[str] = []
        quality = [page.quality_status for page in pages]

        leaves = _leaf_questions(structure)
        if not leaves:
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": "NO_SCOREABLE_QUESTIONS",
                    "message": "The blueprint has no scoreable questions.",
                },
            )

        for index, (question_id, max_marks, answer_type, parent_id) in enumerate(leaves):
            if self._cancelled(session, current.id):
                self._discard(session, created)
                return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled during marking"})

            if results.get_question(current.id, question_id) is not None:
                # A reclaimed job reuses the work already committed for this
                # question: the (job, question) pair is the idempotency key.
                continue

            question_pages = self._question_pages(
                session, tenant_id, current.submission_id, blueprint.id, question_id, readable
            )
            blueprint_question = self._blueprint_question(
                structure, parent_id, question_id
            )
            inputs: list[LLMInput] = [
                LLMInput.text_part(
                    _question_context(question_id, max_marks, answer_type, blueprint_question)
                )
            ]
            for page in question_pages[:MAX_PAGES_PER_QUESTION]:
                try:
                    image = storage.read(page.storage_key)
                except StorageError as error:
                    raise AppError(
                        ErrorCode.SERVICE_NOT_READY,
                        f"A rendered page is missing from storage (page {page.page_index}).",
                    ) from error
                inputs.append(LLMInput.image_part(image, "image/png"))

            if criteria_by_question.get(question_id):
                described = "\n".join(
                    f"- {criterion.code} ({criterion.marks} mark(s)): "
                    f"{criterion.description}"
                    for criterion in criteria_by_question[question_id]
                )
                inputs.append(
                    LLMInput.text_part(
                        "Mark scheme criteria for this question:\n" + described
                    )
                )

            try:
                call = calls.call(
                    tenant_id=tenant_id,
                    purpose="marking",
                    prompt_id="question_marking",
                    inputs=tuple(inputs),
                    job_id=current.id,
                    response_schema=MARKING_RESPONSE_SCHEMA,
                    max_output_tokens=8192,
                )
            except AppError as error:
                if error.code in _RETRYABLE:
                    raise RetryablePipelineError(str(error)) from error
                raise

            try:
                mark = parse_question_mark(call.response.text, question_id=question_id)
            except MarkingResponseInvalid as error:
                row = self._persist_invalid(
                    session, current, question_id, max_marks, str(error)
                )
                created.append(row)
                review_reasons.append(
                    f"Question {question_id}: the marking response was not usable "
                    f"({error})."
                )
                continue

            row = self._persist_mark(
                session,
                current,
                mark,
                max_marks=max_marks,
                quality=quality,
                settings=settings,
            )
            created.append(row.id)
            if row.review_required:
                review_reasons.extend(
                    f"Question {question_id}: {reason}" for reason in row.scheme_concerns
                )

            current.progress = min(0.9, 0.55 + (index + 1) / max(len(leaves), 1) * 0.35)
            session.commit()

        if not created:
            # Every question was already marked by a previous attempt; the job
            # can be finalised without another provider call.
            review_reasons = [
                f"Question {row.question_id}: {concern}"
                for row in results.list_for_job(tenant_id, current.id)
                for concern in (row.scheme_concerns or [])
            ]

        if self._cancelled(session, current.id):
            self._discard(session, created)
            return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled during marking"})

        detail = {
            "questions": len(leaves),
            "marked": len(created),
            "review_reasons": list(dict.fromkeys(review_reasons))[:20],
        }
        if review_reasons:
            return PipelineOutcome(JobState.REVIEW_REQUIRED, detail)
        return PipelineOutcome(JobState.FINALIZING, detail)

    # -- helpers ---------------------------------------------------------
    def _pages(
        self, session: Session, tenant_id: uuid.UUID, submission_id: uuid.UUID
    ) -> list[DocumentPage]:
        documents = DocumentRepository(session).list_for_submission(tenant_id, submission_id)
        pages: list[DocumentPage] = []
        for document in documents:
            if document.status != "PROCESSED":
                continue
            pages.extend(DocumentRepository(session).pages(tenant_id, document.id))
        return pages

    def _question_pages(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        submission_id: uuid.UUID,
        blueprint_version_id: uuid.UUID,
        question_id: str,
        readable: list[DocumentPage],
    ) -> list[DocumentPage]:
        document_ids = {
            document.id
            for document in DocumentRepository(session).list_for_submission(
                tenant_id, submission_id
            )
        }
        if not document_ids:
            return readable
        mapped = set(
            session.scalars(
                select(PageQuestionMapping.page_id).where(
                    PageQuestionMapping.tenant_id == tenant_id,
                    PageQuestionMapping.document_id.in_(document_ids),
                    PageQuestionMapping.blueprint_version_id == blueprint_version_id,
                    PageQuestionMapping.question_id == question_id,
                )
            )
        )
        if mapped:
            selected = [page for page in readable if page.id in mapped]
            if selected:
                return selected
        return readable

    def _blueprint_question(
        self, structure: BlueprintStructure, parent_id: str, question_id: str
    ) -> BlueprintQuestion | None:
        for question in structure.questions:
            if question.question_id == question_id:
                return question
            if question.question_id == parent_id:
                for sub in question.subquestions:
                    if sub.question_id == question_id:
                        return BlueprintQuestion(
                            question_id=sub.question_id,
                            label=sub.label,
                            max_marks=sub.max_marks,
                            answer_type=sub.answer_type,
                            special_instructions=sub.special_instructions,
                            criteria_refs=sub.criteria_refs,
                        )
        return None

    def _cancelled(self, session: Session, job_id: uuid.UUID) -> bool:
        session.expire_all()
        job = session.get(CorrectionJob, job_id)
        return bool(job and job.cancel_requested)

    def _persist_invalid(
        self,
        session: Session,
        job: CorrectionJob,
        question_id: str,
        max_marks: int,
        message: str,
    ) -> uuid.UUID:
        row = QuestionResult(
            tenant_id=job.tenant_id,
            job_id=job.id,
            question_id=question_id,
            max_marks=max_marks,
            awarded_marks=0,
            status="REVIEW_REQUIRED",
            confidence=None,
            review_required=True,
            scheme_concerns=[{"code": "MODEL_RESPONSE_INVALID", "message": message}],
        )
        session.add(row)
        session.flush()
        session.commit()
        return row.id

    def _persist_mark(
        self,
        session: Session,
        job: CorrectionJob,
        mark: QuestionMark,
        *,
        max_marks: int,
        quality: list[str],
        settings: Settings,
    ) -> QuestionResult:
        verification = verify_question(
            mark,
            max_marks=max_marks,
            min_confidence=settings.marking.min_confidence,
            page_quality=quality,
        )
        concerns = list(verification.reasons)
        awarded = mark.awarded_marks
        status = "AWARDED" if awarded > 0 else "ZERO"
        if awarded > max_marks:
            # The database would reject this, and clamping would quietly change
            # the model's claim.  Record it as unmarked and require a person.
            concerns.append(
                f"The model awarded {awarded} of {max_marks}; the award was not applied."
            )
            awarded = 0
            status = "REVIEW_REQUIRED"
        elif verification.review_required:
            status = "REVIEW_REQUIRED"

        row = QuestionResult(
            tenant_id=job.tenant_id,
            job_id=job.id,
            question_id=mark.question_id,
            max_marks=max_marks,
            awarded_marks=awarded,
            status=status,
            student_answer=mark.student_answer,
            working_summary=mark.notes,
            confidence=mark.confidence,
            review_required=verification.review_required or status == "REVIEW_REQUIRED",
            scheme_concerns=[{"code": "REVIEW", "message": reason} for reason in concerns],
        )
        session.add(row)
        session.flush()

        for component in mark.components:
            session.add(
                CriterionResult(
                    tenant_id=job.tenant_id,
                    question_result_id=row.id,
                    criterion_id=None,
                    code=component.code,
                    awarded=component.awarded,
                    reason=component.reason,
                    evidence=(
                        [{"quote": component.evidence}]
                        if (component.evidence or "").strip()
                        else []
                    ),
                )
            )
            if (component.evidence or "").strip():
                session.add(
                    MarkingEvidence(
                        tenant_id=job.tenant_id,
                        question_result_id=row.id,
                        page_id=None,
                        kind="QUOTE",
                        quote=component.evidence,
                    )
                )

        self._persist_verifications(session, job, mark.question_id, verification)
        session.commit()
        return row

    def _persist_verifications(
        self,
        session: Session,
        job: CorrectionJob,
        question_id: str,
        verification: VerificationOutcome,
    ) -> None:
        for record in verification.records:
            existing = session.scalar(
                select(VerificationResult).where(
                    VerificationResult.job_id == job.id,
                    VerificationResult.question_id == question_id,
                    VerificationResult.kind == record.kind,
                )
            )
            if existing is not None:
                existing.status = record.status
                existing.detail = record.detail
                continue
            session.add(
                VerificationResult(
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    question_id=question_id,
                    kind=record.kind,
                    status=record.status,
                    detail=record.detail,
                )
            )

    def _discard(self, session: Session, question_result_ids: list[uuid.UUID]) -> None:
        """A cancelled job must not leave a half-marked paper behind."""

        if not question_result_ids:
            return
        for model in (CriterionResult, MarkingEvidence):
            session.query(model).filter(
                model.question_result_id.in_(question_result_ids)
            ).delete(synchronize_session=False)
        session.query(QuestionResult).filter(
            QuestionResult.id.in_(question_result_ids)
        ).delete(synchronize_session=False)
        session.commit()
