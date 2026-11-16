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
    Assignment,
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
from ...providers.json import parse_json_text
from ...schemas.blueprint import BlueprintQuestion, BlueprintStructure
from ...services.provider_calls import ProviderCallService
from ...storage import build_storage
from ...storage.base import Storage, StorageError
from .. import evidence, page_coverage, recovery, runs, sampling, scheme_check, transcription
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
from .verification import VerificationOutcome, VerificationRecord, verify_question

MAX_PAGES_PER_QUESTION = 6
#: The prompt assets this engine uses.  The double check is a separate asset with
#: its own model role, so the second opinion is not the same request repeated.
PROMPT_MARKING = "aetrix_v5_5_marking"
PROMPT_DOUBLE_CHECK = "aetrix_v5_5_double_check"
PROMPT_TRANSCRIPTION = "aetrix_v5_5_transcription"

#: The transcription reply is small and fixed-shape; asking for a marking-sized
#: response would pay for tokens it cannot use.
TRANSCRIPTION_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "question_id": {"type": "STRING"},
        "transcript": {"type": "STRING", "nullable": True},
        "confidence": {"type": "NUMBER"},
        "review_reasons": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["question_id", "transcript", "confidence"],
}
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
    policy: sampling.ReviewPolicy
    prompt_version: str | None = None
    integrity_findings: list[str] = field(default_factory=list)
    scheme_findings: list[str] = field(default_factory=list)
    coverage_messages: list[str] = field(default_factory=list)
    leaf_by_question: dict[str, tuple[str, int, str | None, str]] = field(default_factory=dict)

    # -- helpers ---------------------------------------------------------
    def _mapped_pages(self, question_id: str) -> list[DocumentPage] | None:
        """The pages explicitly mapped to this question, or ``None`` when none are.

        ``None`` is not the same as an empty list: it means the approved mapping
        says nothing about this question, so the request falls back to the whole
        script and may be truncated.  ``withheld_pages`` reports that.
        """

        tenant_id = self.job.tenant_id
        document_ids = {
            document.id
            for document in DocumentRepository(self.session).list_for_submission(
                tenant_id, self.job.submission_id
            )
        }
        if not document_ids:
            return None
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
        if not mapped:
            return None
        selected = [page for page in self.readable if page.id in mapped]
        return selected or None

    def _question_pages(self, question_id: str) -> list[DocumentPage]:
        mapped = self._mapped_pages(question_id)
        return mapped if mapped is not None else self.readable

    def withheld_pages(self, question_id: str) -> int:
        """How many of this question's pages its request cannot carry.

        A request is capped at ``MAX_PAGES_PER_QUESTION``.  When the pages this
        question needs — its mapped pages, or the whole script when the mapping
        says nothing about it — exceed that cap, the model reads a partial script,
        which is exactly how an answer that is present gets recorded as absent.
        The award is kept as evidence, but it is never presented without a person.
        """

        return max(0, len(self._question_pages(question_id)) - MAX_PAGES_PER_QUESTION)

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
        inputs.extend(self._page_inputs(question_pages))

        if self.criteria_by_question.get(question_id):
            described = "\n".join(
                f"- {criterion.code} ({criterion.marks} mark(s)): {criterion.description}"
                for criterion in self.criteria_by_question[question_id]
            )
            inputs.append(
                LLMInput.text_part("Mark scheme criteria for this question:\n" + described)
            )
        return tuple(inputs)

    def _page_inputs(self, pages: list[DocumentPage]) -> tuple[LLMInput, ...]:
        inputs: list[LLMInput] = []
        for page in pages[:MAX_PAGES_PER_QUESTION]:
            try:
                image = self.storage.read(page.storage_key)
            except StorageError as error:
                raise AppError(
                    ErrorCode.SERVICE_NOT_READY,
                    f"A rendered page is missing from storage (page {page.page_index}).",
                ) from error
            inputs.append(LLMInput.image_part(image, "image/png"))
        return tuple(inputs)

    def _transcription_inputs(
        self, leaf: tuple[str, int, str | None, str]
    ) -> tuple[LLMInput, ...]:
        """Pages and the question only — no scheme, no award, no expected answer.

        The transcription reader must not be able to agree with the marking pass by
        seeing what it concluded.  It gets the same pages and the question text,
        which is all a second reader would have.
        """

        question_id, max_marks, answer_type, parent_id = leaf
        blueprint_question = self._blueprint_question(parent_id, question_id)
        return (
            LLMInput.text_part(
                _question_context(question_id, max_marks, answer_type, blueprint_question)
            ),
            *self._page_inputs(self._question_pages(question_id)),
        )

    def call_model(
        self,
        leaf: tuple[str, int, str | None, str],
        *,
        prompt_id: str,
        purpose: str,
        inputs: tuple[LLMInput, ...] | None = None,
        response_schema: dict | None = None,
        max_output_tokens: int = 8192,
    ):
        """One audited provider call for this question.

        A provider outage becomes ``RetryablePipelineError`` so the runner parks
        the job; a refusal the provider would repeat is raised unchanged.
        """

        try:
            call = self.calls.call(
                tenant_id=self.job.tenant_id,
                purpose=purpose,
                prompt_id=prompt_id,
                inputs=inputs if inputs is not None else self._inputs(leaf),
                job_id=self.job.id,
                response_schema=response_schema or MARKING_RESPONSE_SCHEMA,
                max_output_tokens=max_output_tokens,
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
            withheld_pages=self.withheld_pages(question_id),
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
        withheld_pages: int = 0,
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

        # The approved scheme is independent of the model's reply.  Comparing the
        # two catches an award built on a mark point the scheme does not define, a
        # mark point never considered, an award larger than the scheme's capacity,
        # a dependent mark without its prerequisite, and a final answer that the
        # scheme's stated answer contradicts.
        criteria = self.criteria_by_question.get(mark.question_id, [])
        scheme_findings = scheme_check.check_against_scheme(
            awarded=awarded,
            components=mark.components,
            criteria=criteria,
            question_id=mark.question_id,
            max_marks=max_marks,
        )
        scheme_math = scheme_check.check_answer_against_scheme(
            student_expression=(
                mark.answer_check.student_expression
                if mark.answer_check is not None
                else mark.student_answer
            ),
            criteria=criteria,
        )
        scheme_findings.extend(
            scheme_check.scheme_math_findings(
                scheme_math,
                awarded=awarded,
                max_marks=max_marks,
                components=mark.components,
                criteria=criteria,
                question_id=mark.question_id,
            )
        )
        scheme_records: list[VerificationRecord] = []
        if scheme_math.status != "SKIPPED":
            scheme_records.append(
                VerificationRecord(
                    kind="SCHEME_MATHEMATICAL",
                    status=scheme_math.status,
                    detail={
                        "student_expression": scheme_math.student_expression,
                        "expected_expression": scheme_math.expected_expression,
                        "expected_criterion": scheme_math.expected_criterion,
                        "awarded_marks": awarded,
                        "max_marks": max_marks,
                    },
                )
            )
        # A definite mismatch is a contradiction with the approved scheme and is
        # always reviewed.  A possible mismatch costs an operator's attention, so
        # ECONOMY records it as evidence without stopping the paper; the wider
        # modes act on it.
        reviewable = [
            finding
            for finding in scheme_findings
            if finding.definite or self.policy.mode != sampling.MODE_ECONOMY
        ]
        for finding in reviewable:
            concerns.append(f"{finding.code}: {finding.message}")
        for finding in scheme_findings:
            self.scheme_findings.append(
                f"{mark.question_id}: {finding.code} ({finding.severity})"
            )
        recorded_only = [finding for finding in scheme_findings if finding not in reviewable]
        for message in self.coverage_messages:
            concerns.append(f"PAGE_COVERAGE: {message}")
        if normalised.anomaly == evidence.OVER_MAX_AWARD:
            # The model's claim is kept in raw_awarded_marks; the stored award is
            # zero and a person decides.  Clamping would invent a mark.
            concerns.append(
                f"The model awarded {normalised.raw} of {max_marks}; the award was not applied."
            )
        for finding in findings:
            concerns.append(f"{finding.code}: {finding.message}")
            self.integrity_findings.append(f"{mark.question_id}: {finding.code}")
        if withheld_pages:
            # The model read a partial script for this question.  Its award is
            # kept as evidence, but it must not be presented as if the whole
            # script had been read.
            concerns.append(
                f"PAGE_LIMIT_TRUNCATED: {withheld_pages} page(s) belonging to this "
                f"question were not supplied because a request carries at most "
                f"{MAX_PAGES_PER_QUESTION}. The award covers only the pages read, so a "
                "person decides it."
            )

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
        ] + [
            {
                "code": finding.code,
                "message": finding.message,
                "severity": finding.severity,
            }
            for finding in recorded_only
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

        self._persist_verifications(mark.question_id, verification, scheme_records)
        self.session.commit()
        return row

    def _persist_verifications(
        self,
        question_id: str,
        verification: VerificationOutcome,
        extra: list[VerificationRecord] | None = None,
    ) -> None:
        for record in list(verification.records) + list(extra or []):
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

        # The review mode is a property of the assignment, so the job reads it
        # from the tenant-scoped row rather than from a request body.
        assignment = session.get(Assignment, current.assignment_id)
        if assignment is not None and assignment.tenant_id != tenant_id:
            raise RuntimeError("the job references an assignment from another workspace")
        # The assignment is the authority; the configured mode is the fallback
        # for a submission whose assignment row predates review modes.  Without
        # this, `settings.marking.review_mode` would be a second, dead source of
        # truth that silently disagreed with the row.
        policy = sampling.policy_for(
            getattr(assignment, "review_mode", None) or settings.marking.review_mode,
            settings=settings,
        )

        submission_documents = DocumentRepository(session).list_for_submission(
            tenant_id, current.submission_id
        )
        processed_documents = [
            document for document in submission_documents if document.status == "PROCESSED"
        ]
        # A document that failed or never finished processing is not part of the
        # marked script at all.  Reading only the processed pages would turn its
        # answers into apparent blanks, so it is a blocking coverage gap.
        unprocessed_documents = [
            document for document in submission_documents if document.status != "PROCESSED"
        ]
        document_ids = [document.id for document in processed_documents]
        mapping_rows = (
            list(
                session.scalars(
                    select(PageQuestionMapping).where(
                        PageQuestionMapping.tenant_id == tenant_id,
                        PageQuestionMapping.document_id.in_(document_ids),
                        PageQuestionMapping.blueprint_version_id
                        == current.blueprint_version_id,
                    )
                )
            )
            if document_ids
            else []
        )
        coverage = page_coverage.assess_coverage(
            documents=processed_documents,
            pages=pages,
            mappings=mapping_rows,
            question_ids=[leaf[0] for leaf in leaves],
            page_cap=MAX_PAGES_PER_QUESTION,
            unprocessed_documents=unprocessed_documents,
        )
        blocking_coverage = [finding for finding in coverage if finding.blocking]
        # A review-worthy coverage finding is attached to every stored question:
        # the award is kept as evidence, but it is never presented as if the whole
        # script had been read.
        coverage_messages = [finding.message for finding in coverage if finding.review]
        if blocking_coverage:
            # A page the document declares but storage does not hold may carry the
            # answer to a question.  Marking the pages that did arrive would turn a
            # missing page into an apparent blank, so nothing is marked and nothing
            # is charged to the provider.
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_MARKING,
                outcome=runs.OUTCOME_REVIEW,
                detail={
                    "review_mode": policy.mode,
                    "blocked": blocking_coverage[0].code,
                    "messages": [finding.message for finding in blocking_coverage][:10],
                },
            )
            session.commit()
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": "PAGE_COVERAGE_INCOMPLETE",
                    "review_mode": policy.mode,
                    "review_reasons": [
                        finding.message for finding in blocking_coverage
                    ][:10],
                    "page_coverage": [
                        {"code": finding.code, "blocking": finding.blocking}
                        for finding in coverage
                    ],
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
            policy=policy,
            coverage_messages=coverage_messages,
            leaf_by_question={leaf[0]: leaf for leaf in leaves},
        )

        current.scheme_hash = _content_hash(scheme)
        current.submission_hash = self._submission_hash(session, tenant_id, current.submission_id)
        session.commit()

        created: list[uuid.UUID] = []
        unresolved: list[tuple[str, int, str | None, str]] = []

        for index, leaf in enumerate(leaves):
            if self._cancelled(session, current.id):
                self._discard(session, current.id, created)
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
                "review_mode": policy.mode,
                "integrity_findings": list(dict.fromkeys(working.integrity_findings))[:20],
                "scheme_findings": list(dict.fromkeys(working.scheme_findings))[:20],
                "page_coverage": [
                    {"code": finding.code, "blocking": finding.blocking}
                    for finding in coverage
                ],
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
            outcome=(
                runs.OUTCOME_REVIEW
                if working.integrity_findings
                or working.scheme_findings
                or working.coverage_messages
                else runs.OUTCOME_OK
            ),
            prompt_version=working.prompt_version,
            detail={
                "count": len(working.integrity_findings),
                "findings": list(dict.fromkeys(working.integrity_findings))[:20],
                "scheme_findings": list(dict.fromkeys(working.scheme_findings))[:20],
                "page_coverage": [
                    {"code": finding.code, "blocking": finding.blocking}
                    for finding in coverage
                ],
            },
        )
        session.commit()

        if self._cancelled(session, current.id):
            self._discard(session, current.id, created)
            return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled during marking"})

        rows = results.list_for_job(tenant_id, current.id)
        transcription_detail = self._transcribe(working, rows)
        if transcription_detail is not None:
            rows = results.list_for_job(tenant_id, current.id)
        # Cancellation must be observed between verification stages too: a
        # cancelled job may not keep spending requests, and the rows it produced
        # are discarded exactly as they are during marking.
        if self._cancelled(session, current.id):
            self._discard(session, current.id, created)
            return PipelineOutcome(
                JobState.CANCELLED, {"reason": "cancelled during verification"}
            )
        double_check = self._double_check(working, rows)
        if self._cancelled(session, current.id):
            self._discard(session, current.id, created)
            return PipelineOutcome(
                JobState.CANCELLED, {"reason": "cancelled during verification"}
            )
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
            "review_mode": policy.mode,
            "review_reasons": review_reasons[:20],
            "scheme_findings": list(dict.fromkeys(working.scheme_findings))[:20],
            "transcription": transcription_detail,
            "double_check": double_check,
            "page_coverage": [
                {"code": finding.code, "blocking": finding.blocking}
                for finding in coverage
            ],
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
            missing=missing,
            already_attempted=current.recovery_rounds,
            max_rounds=working.policy.recovery_rounds,
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
    def _transcribe(
        self, working: _MarkingRun, rows: list[QuestionResult]
    ) -> dict[str, Any] | None:
        """A blind second reading of selected answers.  It never re-marks.

        The reader sees the pages and the question, not the award, the scheme or
        the answer the first pass extracted.  A difference is evidence that the
        extraction is unproven; the award stays as recorded and a person decides.
        """

        settings = working.settings
        policy = working.policy
        if not settings.marking.transcription_enabled or policy.transcription_budget <= 0:
            return None
        session = working.session
        current = working.job
        existing = set(
            session.scalars(
                select(VerificationResult.question_id).where(
                    VerificationResult.job_id == current.id,
                    VerificationResult.kind == "TRANSCRIPTION",
                )
            )
        )
        targets = transcription.transcribe_targets(
            rows, budget=policy.transcription_budget, skip=existing, seed=str(current.id)
        )
        if not targets:
            return {
                "enabled": True,
                "checked": 0,
                "agreements": 0,
                "differences": 0,
                "absent": 0,
                "unverifiable": 0,
            }

        counts = {"agreements": 0, "differences": 0, "absent": 0, "unverifiable": 0}
        prompt_version: str | None = None
        by_id = {row.question_id: row for row in rows}
        for target in targets:
            if self._cancelled(session, current.id):
                break
            row = by_id.get(target.question_id)
            leaf = working.leaf_by_question.get(target.question_id)
            if row is None or leaf is None:
                continue
            call = working.call_model(
                leaf,
                prompt_id=PROMPT_TRANSCRIPTION,
                purpose="transcription",
                inputs=working._transcription_inputs(leaf),
                response_schema=TRANSCRIPTION_RESPONSE_SCHEMA,
                max_output_tokens=2048,
            )
            if prompt_version is None:
                version = getattr(call.prompt, "version", None)
                prompt_version = (
                    f"{PROMPT_TRANSCRIPTION}:v{version}"
                    if version is not None
                    else PROMPT_TRANSCRIPTION
                )
            transcript: str | None = None
            confidence: float | None = None
            try:
                payload = parse_json_text(call.response.text)
                if not isinstance(payload, dict):
                    raise ValueError("the transcription reply is not a JSON object")
                raw = payload.get("transcript")
                if raw is not None and not isinstance(raw, str):
                    raise ValueError("the transcription reply's transcript is not text")
                transcript = raw
                confidence = float(payload.get("confidence") or 0.0)
                status = transcription.compare_transcripts(row.student_answer, transcript)
            except (TypeError, ValueError):
                status = transcription.STATUS_UNVERIFIABLE
            working._persist_verifications(
                row.question_id,
                VerificationOutcome(review_required=False, reasons=[], records=[]),
                [
                    VerificationRecord(
                        kind="TRANSCRIPTION",
                        status=status,
                        detail={
                            "original_answer": row.student_answer,
                            "transcript": transcript,
                            "confidence": confidence,
                            "comparison": status,
                            "selection": list(target.reasons),
                            "model": call.response.model,
                            "prompt_version": prompt_version,
                        },
                    )
                ],
            )
            if status == transcription.STATUS_AGREES:
                counts["agreements"] += 1
            elif status == transcription.STATUS_ABSENT:
                counts["absent"] += 1
            elif status == transcription.STATUS_DIFFERS:
                counts["differences"] += 1
                concerns = [
                    concern
                    for concern in (row.scheme_concerns or [])
                    if concern.get("code") != "TRANSCRIPTION_DIFFERS"
                ]
                concerns.append(
                    {
                        "code": "TRANSCRIPTION_DIFFERS",
                        "severity": "POSSIBLE_MISMATCH",
                        "message": (
                            f"A blind second reading transcribed {transcript!r} where this "
                            f"run recorded {row.student_answer!r}. The award was not "
                            "changed; a person decides which reading the mark rests on."
                        ),
                    }
                )
                row.scheme_concerns = concerns
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
            else:
                counts["unverifiable"] += 1
            # One verdict, one durable record: a crash after this point must not
            # make the next execution pay for the same reading again.
            session.commit()

        session.flush()
        runs.record_run(
            session=session,
            job=current,
            stage=runs.STAGE_TRANSCRIPTION,
            outcome=(
                runs.OUTCOME_REVIEW if counts["differences"] else runs.OUTCOME_OK
            ),
            prompt_version=prompt_version,
            detail={
                **policy.describe(),
                "candidates": len(targets),
                **counts,
                "selection": {
                    target.question_id: list(target.reasons) for target in targets
                },
            },
        )
        session.commit()
        return {"enabled": True, "checked": len(targets), **counts}

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
            return {
                "enabled": False,
                "checked": 0,
                "already_checked": 0,
                "disagreements": 0,
            }

        policy = working.policy
        if policy.double_check_budget <= 0:
            # The assignment asked for economy: no second opinion is bought, and
            # the stage says so rather than looking like it found nothing.
            current.double_check_status = "NOT_REQUIRED"
            runs.record_run(
                session=session,
                job=current,
                stage=runs.STAGE_DOUBLE_CHECK,
                outcome=runs.OUTCOME_SKIPPED,
                detail={
                    "reason": f"review mode {policy.mode} takes no second opinion",
                    **policy.describe(),
                },
            )
            session.commit()
            return {
                "enabled": True,
                "checked": 0,
                "already_checked": 0,
                "disagreements": 0,
                "unverifiable": 0,
            }

        threshold = policy.double_check_threshold
        # A question that already has a second opinion is not asked again.  A
        # resumed execution must not spend another request to re-litigate a
        # verdict that is already recorded, and a human decision that followed
        # it must not be quietly reopened by a retry.
        existing_verdicts = {
            verdict.question_id
            for verdict in session.scalars(
                select(VerificationResult).where(
                    VerificationResult.job_id == current.id,
                    VerificationResult.kind == "DOUBLE_CHECK",
                )
            )
        }
        history = ResultRepository(session).double_check_disagreements(
            current.tenant_id,
            [row.question_id for row in rows],
            exclude_job_id=current.id,
        )
        markable = {
            row.question_id: row
            for row in rows
            if row.processing_state == ProcessingState.MARKED.value
        }
        targets = sampling.select_targets(
            markable.values(),
            policy=policy,
            skip=existing_verdicts,
            history=history,
            seed=str(current.id),
        )
        already_checked = [
            question_id
            for question_id in existing_verdicts
            if question_id in markable
        ]
        selected = [
            (markable[item.question_id], item)
            for item in targets
            if item.question_id in markable
        ]

        checked = 0
        disagreements = 0
        unverifiable = 0
        prompt_version: str | None = None
        for row, suspicion in selected:
            if self._cancelled(session, current.id):
                break
            leaf = working.leaf_by_question.get(row.question_id)
            if leaf is None:
                continue
            call = working.call_model(
                leaf, prompt_id=PROMPT_DOUBLE_CHECK, purpose="double_check"
            )
            if prompt_version is None:
                # Provenance: the verdict names the prompt that produced it, so a
                # later prompt change does not rewrite an old verdict's identity.
                prompt_version = f"{PROMPT_DOUBLE_CHECK}:v{call.prompt.version}"
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
                session.commit()
                continue
            second_award = evidence.normalise_award(
                second.awarded_marks, max_marks=row.max_marks
            )
            if second_award.anomaly is not None:
                # The second examiner returned a value that is not an awardable
                # mark at all.  That is an unusable second opinion, not a
                # legitimate disagreement over a mark between 0 and the maximum.
                unverifiable += 1
                self._record_double_check(
                    session,
                    row,
                    status="UNVERIFIABLE",
                    detail={
                        "error": (
                            f"the second marking returned {second.awarded_marks} of "
                            f"{row.max_marks}, which is not an awardable mark"
                        ),
                        "second_awarded": second.awarded_marks,
                        "max_marks": row.max_marks,
                        "raw_response": captured.value,
                        "raw_response_truncated": captured.truncated,
                    },
                )
                session.commit()
                continue
            checked += 1
            detail = {
                "first_awarded": row.awarded_marks,
                "second_awarded": second_award.normalised,
                "max_marks": row.max_marks,
                "second_confidence": second.confidence,
                "selection": list(suspicion.reasons),
                "raw_response": captured.value,
                "raw_response_truncated": captured.truncated,
            }
            if second_award.normalised == row.awarded_marks:
                self._record_double_check(session, row, status="AGREES", detail=detail)
                session.commit()
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
                        f"{second_award.normalised} of {row.max_marks} where this run "
                        f"awarded {row.awarded_marks}. A person decides which award stands."
                    ),
                }
            )
            row.scheme_concerns = concerns
            row.review_required = True
            row.status = status_for(ProcessingState.NEEDS_REVIEW)
            row.processing_state = ProcessingState.NEEDS_REVIEW.value
            session.commit()

        session.flush()
        if checked or unverifiable:
            current.double_check_status = "COMPLETED"
            current.disagreement_status = "DISAGREEMENTS" if disagreements else "NONE"
        elif already_checked:
            # The second opinion was taken by an earlier execution of this job.
            # Its recorded status stands; reporting NOT_REQUIRED would erase it.
            current.double_check_status = current.double_check_status or "COMPLETED"
        else:
            current.double_check_status = "NOT_REQUIRED"
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
            prompt_version=prompt_version,
            detail={
                **policy.describe(),
                "threshold": threshold,
                "candidates": len(selected),
                "already_checked": len(already_checked),
                "checked": checked,
                "disagreements": disagreements,
                "unverifiable": unverifiable,
                "selection": {
                    item.question_id: list(item.reasons) for item in targets
                },
            },
        )
        session.commit()
        return {
            "enabled": True,
            "checked": checked,
            "already_checked": len(already_checked),
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

    def _discard(
        self, session: Session, job_id: uuid.UUID, question_result_ids: list[uuid.UUID]
    ) -> None:
        """A cancelled job must not leave a half-marked paper behind.

        The verification records go with their rows.  Leaving them behind would be
        worse than untidy: the next execution treats a stored verdict as already
        taken, so it would skip a question whose award had been discarded.
        """

        if not question_result_ids:
            return
        question_ids = list(
            session.scalars(
                select(QuestionResult.question_id).where(
                    QuestionResult.id.in_(question_result_ids)
                )
            )
        )
        if question_ids:
            session.query(VerificationResult).filter(
                VerificationResult.job_id == job_id,
                VerificationResult.question_id.in_(question_ids),
            ).delete(synchronize_session=False)
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
