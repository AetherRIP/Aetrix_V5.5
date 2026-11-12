"""The Aetrix V5.5 question-level marking pipeline.

One job marks one submission against one approved blueprint.  The pipeline:

1. re-loads the job in its own session and refuses to touch a cancelled one;
2. proves it has renderable pages, an approved blueprint and an approved scheme;
3. marks each *leaf* question (a sub-question where the paper has them, the
   question itself otherwise) through the audited provider-call service;
4. persists a question result, its components and its quoted evidence;
5. verifies each award and records uncertainty;
6. retries a bounded number of *unusable* responses, never re-running a question
   that already has a decision;
7. stops at ``REVIEW_REQUIRED`` when anything is unproven, otherwise
   ``FINALIZING`` so the runner can complete the job.

Nothing here invents a mark.  A malformed model response, a missing page, an
inconsistent award or a failed mathematical check produces a review item, not a
zero.  A provider outage raises ``RetryablePipelineError`` so the runner parks
the job with a truthful reason.

Three safeguards sit on top of the marking itself:

* every question records an explicit ``processing_state`` (marked, confirmed
  zero, unmarked, needs review) beside the status the API already exposes;
* the model's own award and raw reply are retained when normalisation changes
  anything, so the evidence survives the correction;
* before this run's marks could stand as the submission's result, the result
  guard compares them with the stored one and refuses to replace an approved or
  overridden result, or to replace a good total with a suspicious one.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...audit.service import AuditService
from ...core.config import CORRECTION_ENGINE_VERSION, Settings
from ...core.errors import AppError, ErrorCode
from ...core.ids import sha256_hex
from ...db.models import (
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
from ...db.repositories import DocumentRepository, MarkSchemeRepository, ResultRepository
from ...jobs.pipeline import CorrectionPipeline, PipelineOutcome, RetryablePipelineError
from ...jobs.states import JobState
from ...prompts.registry import PromptRegistry
from ...providers.base import LLMInput, LLMProvider
from ...providers.factory import build_provider
from ...schemas.blueprint import BlueprintQuestion, BlueprintStructure
from ...services.provider_calls import ProviderCallService
from ...storage import build_storage
from ...storage.base import Storage, StorageError
from .. import evidence, recovery, runs
from ..guard import (
    RESULT_SOURCE_AI,
    RESULT_SOURCE_REFUSED,
    PriorResult,
    evaluate_overwrite,
)
from ..integrity import check_mark
from ..processing import (
    ProcessingState,
    ensure_consistent,
    is_scoreable,
    state_for_mark,
    status_for,
)
from .schema import (
    MARKING_RESPONSE_SCHEMA,
    MarkingResponseInvalid,
    QuestionMark,
    parse_question_mark,
)
from .verification import VerificationOutcome, verify_question

MAX_PAGES_PER_QUESTION = 6
#: The prompt assets this engine uses.  The double check is a separate asset with
#: its own model role, so the second opinion is not the same request repeated.
PROMPT_MARKING = "aetrix_v5_5_marking"
PROMPT_DOUBLE_CHECK = "aetrix_v5_5_double_check"
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


def _content_hash(value: Any) -> str | None:
    raw = getattr(value, "content_hash", None)
    return str(raw) if raw else None


def validation_failed_for(
    rows: list[QuestionResult], integrity_findings: list[str]
) -> bool:
    """Whether this run's own validation rejected part of its output.

    A reply the pipeline could not parse, or an award that failed an integrity
    check, means the run did not validate.  The guard must see that instead of
    judging the run on aggregate marks alone.
    """

    if integrity_findings:
        return True
    return any(
        row.normalisation_anomaly == evidence.MODEL_RESPONSE_INVALID for row in rows
    )


def _retryable(row: QuestionResult) -> bool:
    """Whether a stored row is an unusable response worth another attempt.

    Only a row the engine itself recorded as unusable is retried.  A question
    that was marked, or sent to review for a reason about the student's work, is
    never re-run — that would replace a decision with a second opinion the
    teacher did not ask for.
    """

    if is_scoreable(row.processing_state):
        return False
    return row.normalisation_anomaly == evidence.MODEL_RESPONSE_INVALID


@dataclass
class _MarkingRun:
    """The state one execution needs, passed explicitly (the pipeline is shared)."""

    session: Session
    job: CorrectionJob
    settings: Settings
    structure: BlueprintStructure
    criteria_by_question: dict[str, list[Any]]
    readable: list[DocumentPage]
    calls: ProviderCallService
    storage: Storage
    quality: list[str]
    engine_version: str
    prompt_version: str | None = None
    integrity_findings: list[str] = field(default_factory=list)
    leaf_by_question: dict[str, tuple[str, int, str | None, str]] = field(default_factory=dict)

    # -- helpers ---------------------------------------------------------
    def _question_pages(self, question_id: str) -> list[DocumentPage]:
        tenant_id = self.job.tenant_id
        document_ids = {
            document.id
            for document in DocumentRepository(self.session).list_for_submission(
                tenant_id, self.job.submission_id
            )
        }
        if not document_ids:
            return self.readable
        mapped = set(
            self.session.scalars(
                select(PageQuestionMapping.page_id).where(
                    PageQuestionMapping.tenant_id == tenant_id,
                    PageQuestionMapping.document_id.in_(document_ids),
                    PageQuestionMapping.blueprint_version_id == self.job.blueprint_version_id,
                    PageQuestionMapping.question_id == question_id,
                )
            )
        )
        if mapped:
            selected = [page for page in self.readable if page.id in mapped]
            if selected:
                return selected
        return self.readable

    def _blueprint_question(
        self, parent_id: str, question_id: str
    ) -> BlueprintQuestion | None:
        for question in self.structure.questions:
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

    # -- model call ------------------------------------------------------
    def _inputs(self, leaf: tuple[str, int, str | None, str]) -> tuple[LLMInput, ...]:
        """The question, its pages and its scheme criteria, in one request."""

        question_id, max_marks, answer_type, parent_id = leaf
        question_pages = self._question_pages(question_id)
        blueprint_question = self._blueprint_question(parent_id, question_id)
        inputs: list[LLMInput] = [
            LLMInput.text_part(
                _question_context(question_id, max_marks, answer_type, blueprint_question)
            )
        ]
        for page in question_pages[:MAX_PAGES_PER_QUESTION]:
            try:
                image = self.storage.read(page.storage_key)
            except StorageError as error:
                raise AppError(
                    ErrorCode.SERVICE_NOT_READY,
                    f"A rendered page is missing from storage (page {page.page_index}).",
                ) from error
            inputs.append(LLMInput.image_part(image, "image/png"))

        if self.criteria_by_question.get(question_id):
            described = "\n".join(
                f"- {criterion.code} ({criterion.marks} mark(s)): {criterion.description}"
                for criterion in self.criteria_by_question[question_id]
            )
            inputs.append(
                LLMInput.text_part("Mark scheme criteria for this question:\n" + described)
            )
        return tuple(inputs)

    def call_model(self, leaf: tuple[str, int, str | None, str], *, prompt_id: str, purpose: str):
        """One audited provider call for this question.

        A provider outage becomes ``RetryablePipelineError`` so the runner parks
        the job; a refusal the provider would repeat is raised unchanged.
        """

        try:
            call = self.calls.call(
                tenant_id=self.job.tenant_id,
                purpose=purpose,
                prompt_id=prompt_id,
                inputs=self._inputs(leaf),
                job_id=self.job.id,
                response_schema=MARKING_RESPONSE_SCHEMA,
                max_output_tokens=8192,
            )
        except AppError as error:
            if error.code in _RETRYABLE:
                raise RetryablePipelineError(str(error)) from error
            raise
        if self.prompt_version is None:
            version = getattr(getattr(call, "prompt", None), "version", None)
            if version is not None:
                self.prompt_version = f"{prompt_id}:v{version}"
        return call

    # -- one question ----------------------------------------------------
    def mark(
        self,
        leaf: tuple[str, int, str | None, str],
        *,
        existing: QuestionResult | None = None,
    ) -> tuple[QuestionResult | None, str | None]:
        """Mark one leaf; return the row and, when the reply was unusable, why."""

        question_id = leaf[0]
        call = self.call_model(leaf, prompt_id=PROMPT_MARKING, purpose="marking")

        captured = evidence.capture_raw_response(call.response.text)
        try:
            mark = parse_question_mark(call.response.text, question_id=question_id)
        except MarkingResponseInvalid as error:
            row = self._persist_invalid(
                question_id, leaf[1], str(error), captured=captured, existing=existing
            )
            return row, str(error)

        row = self._persist_mark(
            mark,
            captured=captured,
            max_marks=leaf[1],
            existing=existing,
        )
        return row, None

    # -- persistence -----------------------------------------------------
    def _write_provenance(self, row: QuestionResult) -> None:
        row.engine_version = self.engine_version
        row.prompt_version = self.prompt_version

    def _persist_invalid(
        self,
        question_id: str,
        max_marks: int,
        message: str,
        *,
        captured: evidence.CapturedResponse,
        existing: QuestionResult | None,
    ) -> QuestionResult:
        row = existing or QuestionResult(
            tenant_id=self.job.tenant_id,
            job_id=self.job.id,
            question_id=question_id,
            max_marks=max_marks,
        )
        row.max_marks = max_marks
        row.awarded_marks = 0
        row.status = status_for(ProcessingState.NEEDS_REVIEW)
        row.processing_state = ProcessingState.NEEDS_REVIEW.value
        row.student_answer = None
        row.working_summary = None
        row.confidence = None
        row.review_required = True
        row.raw_awarded_marks = None
        row.normalised_awarded_marks = 0
        row.normalisation_anomaly = evidence.MODEL_RESPONSE_INVALID
        row.normalisation_detail = {"reason": message[:1000]}
        row.raw_response = captured.value
        row.raw_response_truncated = captured.truncated
        row.scheme_concerns = [{"code": "MODEL_RESPONSE_INVALID", "message": message}]
        self._write_provenance(row)
        if existing is None:
            self.session.add(row)
        self.session.flush()
        self.session.commit()
        return row

    def _persist_mark(
        self,
        mark: QuestionMark,
        *,
        captured: evidence.CapturedResponse,
        max_marks: int,
        existing: QuestionResult | None,
    ) -> QuestionResult:
        normalised = evidence.normalise_award(mark.awarded_marks, max_marks=max_marks)
        awarded = normalised.normalised
        findings = check_mark(
            awarded=awarded,
            max_marks=max_marks,
            components=mark.components,
            student_answer=mark.student_answer,
            confidence=mark.confidence,
        )
        verification = verify_question(
            mark,
            max_marks=max_marks,
            min_confidence=self.settings.marking.min_confidence,
            page_quality=self.quality,
        )
        concerns = list(verification.reasons)
        if normalised.anomaly == evidence.OVER_MAX_AWARD:
            # The model's claim is kept in raw_awarded_marks; the stored award is
            # zero and a person decides.  Clamping would invent a mark.
            concerns.append(
                f"The model awarded {normalised.raw} of {max_marks}; the award was not applied."
            )
        for finding in findings:
            concerns.append(f"{finding.code}: {finding.message}")
            self.integrity_findings.append(f"{mark.question_id}: {finding.code}")

        state = state_for_mark(
            awarded=awarded,
            review_required=bool(concerns),
            integrity_failed=bool(findings),
            confidence=mark.confidence,
            min_confidence=self.settings.marking.min_confidence,
        )
        status = status_for(state)
        ensure_consistent(status, state)

        row = existing or QuestionResult(
            tenant_id=self.job.tenant_id,
            job_id=self.job.id,
            question_id=mark.question_id,
            max_marks=max_marks,
        )
        if existing is not None:
            # Recovery replaces an unusable reply, never a decided question:
            # its dependent rows are cleared so the record has one story.
            self.session.query(CriterionResult).filter(
                CriterionResult.question_result_id == row.id
            ).delete(synchronize_session=False)
            self.session.query(MarkingEvidence).filter(
                MarkingEvidence.question_result_id == row.id
            ).delete(synchronize_session=False)

        row.question_id = mark.question_id
        row.max_marks = max_marks
        row.awarded_marks = awarded
        row.status = status
        row.processing_state = state.value
        row.student_answer = mark.student_answer
        row.working_summary = mark.notes
        row.confidence = mark.confidence
        row.review_required = state is ProcessingState.NEEDS_REVIEW
        row.raw_awarded_marks = normalised.raw
        row.normalised_awarded_marks = awarded
        row.normalisation_anomaly = normalised.anomaly
        row.normalisation_detail = normalised.detail
        row.raw_response = captured.value
        row.raw_response_truncated = captured.truncated
        row.scheme_concerns = [
            {"code": "REVIEW", "message": reason} for reason in concerns
        ]
        self._write_provenance(row)
        if existing is None:
            self.session.add(row)
        self.session.flush()

        for component in mark.components:
            self.session.add(
                CriterionResult(
                    tenant_id=self.job.tenant_id,
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
                self.session.add(
                    MarkingEvidence(
                        tenant_id=self.job.tenant_id,
                        question_result_id=row.id,
                        page_id=None,
                        kind="QUOTE",
                        quote=component.evidence,
                    )
                )

        self._persist_verifications(mark.question_id, verification)
        self.session.commit()
        return row

    def _persist_verifications(
        self, question_id: str, verification: VerificationOutcome
    ) -> None:
        for record in verification.records:
            existing = self.session.scalar(
                select(VerificationResult).where(
                    VerificationResult.job_id == self.job.id,
                    VerificationResult.question_id == question_id,
                    VerificationResult.kind == record.kind,
                )
            )
            if existing is not None:
                existing.status = record.status
                existing.detail = record.detail
                continue
            self.session.add(
                VerificationResult(
                    tenant_id=self.job.tenant_id,
                    job_id=self.job.id,
                    question_id=question_id,
                    kind=record.kind,
                    status=record.status,
                    detail=record.detail,
                )
            )


class AetrixPipeline(CorrectionPipeline):
    name = "aetrix_v5_5"

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

        leaves = _leaf_questions(structure)
        if not leaves:
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": "NO_SCOREABLE_QUESTIONS",
                    "message": "The blueprint has no scoreable questions.",
                },
            )

        results = ResultRepository(session)
        quality = [page.quality_status for page in pages]
        working = _MarkingRun(
            session=session,
            job=current,
            settings=settings,
            structure=structure,
            criteria_by_question=criteria_by_question,
            readable=readable,
            calls=calls,
            storage=storage,
            quality=quality,
            engine_version=current.engine_version or CORRECTION_ENGINE_VERSION,
            leaf_by_question={leaf[0]: leaf for leaf in leaves},
        )

        current.scheme_hash = _content_hash(scheme)
        current.submission_hash = self._submission_hash(session, tenant_id, current.submission_id)
        session.commit()

        created: list[uuid.UUID] = []
        unresolved: list[tuple[str, int, str | None, str]] = []

        for index, leaf in enumerate(leaves):
            if self._cancelled(session, current.id):
                self._discard(session, created)
                return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled during marking"})

            question_id = leaf[0]
            existing = results.get_question(current.id, question_id)
            if existing is not None and not _retryable(existing):
                # A question with a decision keeps it: the (job, question) pair
                # is the idempotency key, and re-marking a decided question
                # would replace a decision with a second opinion.
                continue

            row, failure = working.mark(leaf, existing=existing)
            if row is not None and row.id is not None:
                created.append(row.id)
            if failure is not None:
                unresolved.append(leaf)

            current.progress = min(0.9, 0.55 + (index + 1) / max(len(leaves), 1) * 0.35)
            session.commit()

        recovery_detail = self._recover(
            session=session,
            working=working,
            results=results,
            leaves=leaves,
            unresolved=unresolved,
        )

        runs.record_run(
            session,
            job=current,
            stage=runs.STAGE_MARKING,
            outcome=runs.OUTCOME_OK,
            prompt_version=working.prompt_version,
            detail={
                "questions": len(leaves),
                "marked_rows": len(created),
                "unresolved": len(unresolved),
                "integrity_findings": list(dict.fromkeys(working.integrity_findings))[:20],
            },
        )
        if recovery_detail is not None:
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_RECOVERY,
                outcome=(
                    runs.OUTCOME_OK
                    if recovery_detail["still_unresolved"] == 0
                    else runs.OUTCOME_REVIEW
                ),
                prompt_version=working.prompt_version,
                detail=recovery_detail,
            )
        session.commit()

        runs.record_run(
            session,
            job=current,
            stage=runs.STAGE_INTEGRITY,
            outcome=(runs.OUTCOME_REVIEW if working.integrity_findings else runs.OUTCOME_OK),
            prompt_version=working.prompt_version,
            detail={
                "count": len(working.integrity_findings),
                "findings": list(dict.fromkeys(working.integrity_findings))[:20],
            },
        )
        session.commit()

        if self._cancelled(session, current.id):
            self._discard(session, created)
            return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled during marking"})

        rows = results.list_for_job(tenant_id, current.id)
        double_check = self._double_check(working, rows)
        if double_check is not None:
            rows = results.list_for_job(tenant_id, current.id)
        review_reasons = [
            f"Question {row.question_id}: {concern.get('message') or concern.get('code')}"
            for row in rows
            if row.review_required
            for concern in (row.scheme_concerns or [])
        ]
        review_reasons = list(dict.fromkeys(review_reasons))

        marked = sum(1 for row in rows if is_scoreable(row.processing_state))
        detail = {
            "questions": len(leaves),
            "marked": marked,
            "unmarked": sum(1 for row in rows if not is_scoreable(row.processing_state)),
            "review_reasons": review_reasons[:20],
            "double_check": double_check,
        }

        # A reply the pipeline could not parse, or a mark that failed its
        # integrity check, means this run did not validate its own output.  The
        # guard must see that instead of judging the run on totals alone.
        validation_failed = validation_failed_for(rows, working.integrity_findings)
        guard = self._apply_guard(
            session=session,
            current=current,
            rows=rows,
            validation_failed=validation_failed,
        )
        if guard is not None:
            detail["guard"] = guard
            detail["guard_reason"] = guard_reason_summary(guard)
            return PipelineOutcome(JobState.REVIEW_REQUIRED, detail)

        if review_reasons:
            return PipelineOutcome(JobState.REVIEW_REQUIRED, detail)
        return PipelineOutcome(JobState.FINALIZING, detail)

    # -- stages ----------------------------------------------------------
    def _recover(
        self,
        *,
        session: Session,
        working: _MarkingRun,
        results: ResultRepository,
        leaves: list[tuple[str, int, str | None, str]],
        unresolved: list[tuple[str, int, str | None, str]],
    ) -> dict[str, Any] | None:
        """Retry unusable replies within a bounded, recorded budget."""

        if not unresolved:
            return None
        current = working.job
        missing = [leaf[0] for leaf in unresolved]
        allowed, refusal = recovery.need_recovery(
            missing=missing, already_attempted=current.recovery_rounds
        )
        plan = recovery.plan_recovery(
            missing=missing,
            already_attempted=current.recovery_rounds,
            scheme_questions=len(leaves),
        )
        blocked = refusal or plan.blocked_reason

        recovered = 0
        covered = 0
        chunks_run = 0
        last_error: str | None = None

        if allowed:
            for chunk in plan.chunks:
                if self._cancelled(session, current.id):
                    break
                current.recovery_rounds += 1
                chunks_run += 1
                covered += len(chunk.questions)
                for question_id in chunk.questions:
                    leaf = next(item for item in unresolved if item[0] == question_id)
                    existing = results.get_question(current.id, question_id)
                    try:
                        row, failure = working.mark(leaf, existing=existing)
                    except RetryablePipelineError:
                        # A provider outage during recovery is the same outage:
                        # the runner parks the job and the budget is intact.
                        raise
                    if failure is not None:
                        last_error = failure
                        continue
                    if row is not None and is_scoreable(row.processing_state):
                        recovered += 1
                session.commit()

        still_unresolved = 0
        for question_id in missing:
            row = results.get_question(current.id, question_id)
            if row is None or is_scoreable(row.processing_state):
                continue
            still_unresolved += 1
            reason = recovery.unresolved_reason(
                chunks_run=chunks_run,
                questions_covered=covered,
                recovered=recovered,
                blocked_reason=blocked,
                error=last_error,
            )
            concerns = [
                concern
                for concern in (row.scheme_concerns or [])
                if concern.get("code") != "RECOVERY_EXHAUSTED"
            ]
            concerns.append({"code": "RECOVERY_EXHAUSTED", "message": reason})
            row.scheme_concerns = concerns
            row.status = status_for(ProcessingState.NEEDS_REVIEW)
            row.processing_state = ProcessingState.NEEDS_REVIEW.value
            row.review_required = True
        session.flush()
        session.commit()

        return {
            "missing": len(missing),
            "chunks": chunks_run,
            "questions_covered": covered,
            "recovered": recovered,
            "still_unresolved": still_unresolved,
            "blocked_reason": blocked,
            "deferred": list(plan.deferred),
        }

    # -- independent double check -----------------------------------------
    def _double_check(
        self, working: _MarkingRun, rows: list[QuestionResult]
    ) -> dict[str, Any] | None:
        """Have a second, independent pass re-mark the least certain questions.

        It never replaces the first award.  Agreement is recorded, disagreement
        sends the question to a person with both awards stated, and a reply that
        cannot be parsed is recorded as unverifiable.  Nothing here may turn one
        mark into a different mark.
        """

        current = working.job
        settings = working.settings
        session = working.session
        if not settings.marking.double_check_enabled:
            current.double_check_status = "DISABLED"
            runs.record_run(
                session=session,
                job=current,
                stage=runs.STAGE_DOUBLE_CHECK,
                outcome=runs.OUTCOME_SKIPPED,
                detail={"reason": "double check is disabled by configuration"},
            )
            session.commit()
            return {"enabled": False, "checked": 0, "disagreements": 0}

        threshold = settings.marking.double_check_min_confidence
        limit = settings.marking.double_check_max_questions
        targets = [
            row
            for row in rows
            if row.processing_state == ProcessingState.MARKED.value
            and (row.confidence or 0.0) < threshold
        ][:limit]

        checked = 0
        disagreements = 0
        unverifiable = 0
        for row in targets:
            leaf = working.leaf_by_question.get(row.question_id)
            if leaf is None:
                continue
            call = working.call_model(
                leaf, prompt_id=PROMPT_DOUBLE_CHECK, purpose="double_check"
            )
            captured = evidence.capture_raw_response(call.response.text)
            try:
                second = parse_question_mark(call.response.text, question_id=row.question_id)
            except MarkingResponseInvalid as error:
                unverifiable += 1
                self._record_double_check(
                    session,
                    row,
                    status="UNVERIFIABLE",
                    detail={"error": str(error)[:300], "raw_response": captured.value},
                )
                continue
            checked += 1
            detail = {
                "first_awarded": row.awarded_marks,
                "second_awarded": second.awarded_marks,
                "max_marks": row.max_marks,
                "second_confidence": second.confidence,
                "raw_response": captured.value,
                "raw_response_truncated": captured.truncated,
            }
            if second.awarded_marks == row.awarded_marks:
                self._record_double_check(session, row, status="AGREES", detail=detail)
                continue
            disagreements += 1
            self._record_double_check(session, row, status="DISAGREES", detail=detail)
            concerns = [
                concern
                for concern in (row.scheme_concerns or [])
                if concern.get("code") != "DOUBLE_CHECK_DISAGREEMENT"
            ]
            concerns.append(
                {
                    "code": "DOUBLE_CHECK_DISAGREEMENT",
                    "message": (
                        "An independent second marking awarded "
                        f"{second.awarded_marks} of {row.max_marks} where this run awarded "
                        f"{row.awarded_marks}. A person decides which award stands."
                    ),
                }
            )
            row.scheme_concerns = concerns
            row.review_required = True
            row.status = status_for(ProcessingState.NEEDS_REVIEW)
            row.processing_state = ProcessingState.NEEDS_REVIEW.value

        session.flush()
        current.double_check_status = (
            "COMPLETED" if checked or unverifiable else "NOT_REQUIRED"
        )
        current.disagreement_status = (
            "DISAGREEMENTS" if disagreements else ("NONE" if checked else None)
        )
        runs.record_run(
            session=session,
            job=current,
            stage=runs.STAGE_DOUBLE_CHECK,
            outcome=(
                runs.OUTCOME_REVIEW
                if disagreements
                else runs.OUTCOME_FAILED
                if unverifiable and not checked
                else runs.OUTCOME_OK
            ),
            detail={
                "threshold": threshold,
                "candidates": len(targets),
                "checked": checked,
                "disagreements": disagreements,
                "unverifiable": unverifiable,
            },
        )
        session.commit()
        return {
            "enabled": True,
            "checked": checked,
            "disagreements": disagreements,
            "unverifiable": unverifiable,
        }

    def _record_double_check(
        self,
        session: Session,
        row: QuestionResult,
        *,
        status: str,
        detail: dict[str, Any],
    ) -> None:
        existing = session.scalar(
            select(VerificationResult).where(
                VerificationResult.job_id == row.job_id,
                VerificationResult.question_id == row.question_id,
                VerificationResult.kind == "DOUBLE_CHECK",
            )
        )
        if existing is not None:
            existing.status = status
            existing.detail = detail
            return
        session.add(
            VerificationResult(
                tenant_id=row.tenant_id,
                job_id=row.job_id,
                question_id=row.question_id,
                kind="DOUBLE_CHECK",
                status=status,
                detail=detail,
            )
        )

    def _apply_guard(
        self,
        *,
        session: Session,
        current: CorrectionJob,
        rows: list[QuestionResult],
        validation_failed: bool,
    ) -> str | None:
        """Decide whether this run's marks may stand as the stored result."""

        if not rows:
            return None
        prior_raw = ResultRepository(session).prior_job_totals(
            current.tenant_id, current.submission_id, exclude_job_id=current.id
        )
        prior = (
            PriorResult(
                job_id=prior_raw[0],
                earned=prior_raw[1],
                available=prior_raw[2],
                approved=prior_raw[3],
                teacher_override=prior_raw[4],
            )
            if prior_raw is not None
            else None
        )
        earned = sum(row.awarded_marks for row in rows)
        available = sum(row.max_marks for row in rows)
        decision = evaluate_overwrite(
            prior=prior,
            earned=earned,
            available=available,
            validation_failed=validation_failed,
        )

        runs.record_run(
            session,
            job=current,
            stage=runs.STAGE_GUARD,
            outcome=(
                runs.OUTCOME_BLOCKED
                if decision.action == "BLOCKED"
                else runs.OUTCOME_KEPT_EXISTING
                if decision.action == "KEEP_EXISTING"
                else runs.OUTCOME_OK
            ),
            detail={
                "action": decision.action,
                "confidence": decision.confidence,
                "earned": earned,
                "available": available,
                "prior_job_id": str(prior.job_id) if prior and prior.job_id else None,
                "validation_failed": validation_failed,
            },
        )
        session.commit()

        if decision.may_present:
            # This run may be presented.  A refusal recorded on this same job by
            # an earlier attempt must not keep hiding marks the guard now accepts.
            current.result_source = RESULT_SOURCE_AI
            session.commit()
            return None

        current.result_source = RESULT_SOURCE_REFUSED
        AuditService(session).record(
            tenant_id=current.tenant_id,
            action="result.overwrite_refused",
            entity_type="correction_job",
            entity_id=current.id,
            detail={
                "guard": decision.action,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "earned": earned,
                "available": available,
                "prior_job_id": str(prior.job_id) if prior and prior.job_id else None,
            },
        )
        session.commit()
        return decision.action

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

    def _submission_hash(
        self, session: Session, tenant_id: uuid.UUID, submission_id: uuid.UUID
    ) -> str | None:
        """A stable digest of the submitted documents, when they have one."""

        digests = sorted(
            str(document.sha256)
            for document in DocumentRepository(session).list_for_submission(
                tenant_id, submission_id
            )
            if getattr(document, "sha256", None)
        )
        return sha256_hex(",".join(digests)) if digests else None

    def _cancelled(self, session: Session, job_id: uuid.UUID) -> bool:
        session.expire_all()
        job = session.get(CorrectionJob, job_id)
        return bool(job and job.cancel_requested)

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


def guard_reason_summary(action: str | None) -> str | None:
    """The sentence the review screen shows for a refused automated result."""

    if action == "BLOCKED":
        return (
            "This run's marks were not presented: the stored result is approved or "
            "the run failed validation. Nothing was overwritten."
        )
    if action == "KEEP_EXISTING":
        return (
            "This run's marks were not presented: they differ from the stored result "
            "by more than the accepted margin, so the stored result was kept for review."
        )
    return None
