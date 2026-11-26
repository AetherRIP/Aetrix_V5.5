"""Reading the three sources behind a correction, without changing any of them.

A preview is assembled from records the marking run already produced:

* the student document, its pages and the stored question-to-page mapping;
* the reviewed marking criteria and the document they were printed in;
* the question rows, their archived reply, their verifications and concerns.

The service never reaches a provider and never writes.  Where a record is
missing it says so in the payload (``None`` or a warning) instead of filling the
gap, and every award shown comes from ``question_results`` as stored.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..correction.processing import effective_state
from ..db.models import (
    Assignment,
    CorrectionJob,
    CriterionResult,
    Document,
    DocumentPage,
    Exam,
    ExamBlueprintVersion,
    JobEvent,
    MarkingCriterion,
    MarkSchemeVersion,
    PageQuestionMapping,
    ProviderResponse,
    QuestionResult,
    Submission,
    VerificationResult,
)
from ..schemas.preview import (
    CorrectionPreviewRead,
    PreviewArchiveRead,
    PreviewCriterionRead,
    PreviewDecisionRead,
    PreviewDocumentRead,
    PreviewLocationRead,
    PreviewPaperRead,
    PreviewQuestionRead,
    PreviewSchemeDocumentRead,
    PreviewStudentRead,
    PreviewVerificationRead,
    PreviewWarningRead,
)
from ..schemas.results import JobResultsRead
from .results import ResultsService

#: The engine renames a repeated criterion code (``M1`` -> ``M1-2``) so both
#: awards survive validation.  The suffix belongs to the reply, not the scheme,
#: so it is stripped to find the printed point and read as its occurrence.
_DISAMBIGUATED = re.compile(r"^(.*)-(\d+)$")


def _base_code(code: str) -> tuple[str, int]:
    match = _DISAMBIGUATED.match(code.strip())
    if not match:
        return code.strip(), 0
    return match.group(1), max(0, int(match.group(2)) - 1)


def _natural_key(value: str) -> tuple[Any, ...]:
    """1a, 1d, 2, ... 16b, 17 — the order a paper is read in."""
    parts: list[Any] = []
    for chunk in re.split(r"(\d+)", value):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(chunk.lower())
    return tuple(parts)


def _flatten_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for question in questions:
        flat.append(question)
        flat.extend(_flatten_questions(question.get("subquestions") or []))
    return flat


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            items.append(entry.strip())
        elif isinstance(entry, dict):
            rendered = ", ".join(
                f"{key}: {item}"
                for key, item in entry.items()
                if isinstance(item, (str, int, float))
            )
            if rendered:
                items.append(rendered)
    return items


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


class CorrectionPreviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.results = ResultsService(session)

    # -- lookups ---------------------------------------------------------
    def _job(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> CorrectionJob:
        job = self.session.scalar(
            select(CorrectionJob).where(
                CorrectionJob.tenant_id == tenant_id, CorrectionJob.id == job_id
            )
        )
        if job is None:
            raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")
        return job

    def preview(self, principal: Principal, submission_id: uuid.UUID) -> CorrectionPreviewRead:
        submission = self.session.scalar(
            select(Submission).where(
                Submission.tenant_id == principal.tenant_id, Submission.id == submission_id
            )
        )
        if submission is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
        # The presented result is preferred.  When every run was refused, the
        # newest refused run is still readable as evidence — the results API
        # allows that read — and the preview says plainly that it is not the
        # submission's result.
        job = self.results.latest_job_for_submission(principal.tenant_id, submission.id)
        if job is None:
            job = self.results.newest_refused_job(principal.tenant_id, submission.id)
        if job is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "This submission has not been marked yet, so there is nothing to preview.",
            )
        base = self.results.job_results(principal, job.id)
        return self._build(principal, job, submission, base)

    # -- assembly --------------------------------------------------------
    def _build(
        self,
        principal: Principal,
        job: CorrectionJob,
        submission: Submission,
        base: JobResultsRead,
    ) -> CorrectionPreviewRead:
        tenant_id = principal.tenant_id
        assignment = self.session.scalar(
            select(Assignment).where(
                Assignment.tenant_id == tenant_id, Assignment.id == job.assignment_id
            )
        )
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        exam = self.session.scalar(
            select(Exam).where(Exam.tenant_id == tenant_id, Exam.id == assignment.exam_id)
        )
        if exam is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        blueprint = self.session.scalar(
            select(ExamBlueprintVersion).where(
                ExamBlueprintVersion.tenant_id == tenant_id,
                ExamBlueprintVersion.id == job.blueprint_version_id,
            )
        )
        scheme_version = self.session.scalar(
            select(MarkSchemeVersion).where(
                MarkSchemeVersion.tenant_id == tenant_id,
                MarkSchemeVersion.id == job.scheme_version_id,
            )
        )

        rows = list(
            self.session.scalars(
                select(QuestionResult).where(
                    QuestionResult.tenant_id == tenant_id,
                    QuestionResult.job_id == job.id,
                )
            )
        )
        rows.sort(key=lambda row: _natural_key(row.question_id))
        result_ids = [row.id for row in rows]

        persisted: dict[uuid.UUID, list[CriterionResult]] = defaultdict(list)
        if result_ids:
            for criterion in self.session.scalars(
                select(CriterionResult).where(
                    CriterionResult.tenant_id == tenant_id,
                    CriterionResult.question_result_id.in_(result_ids),
                )
            ):
                persisted[criterion.question_result_id].append(criterion)

        scheme_rows: dict[str, list[MarkingCriterion]] = defaultdict(list)
        if scheme_version is not None:
            for criterion in self.session.scalars(
                select(MarkingCriterion)
                .where(
                    MarkingCriterion.tenant_id == tenant_id,
                    MarkingCriterion.scheme_version_id == scheme_version.id,
                )
                .order_by(MarkingCriterion.ordinal)
            ):
                scheme_rows[criterion.question_id].append(criterion)

        verifications: dict[str, list[VerificationResult]] = defaultdict(list)
        for verification in self.session.scalars(
            select(VerificationResult).where(
                VerificationResult.tenant_id == tenant_id,
                VerificationResult.job_id == job.id,
            )
        ):
            verifications[verification.question_id].append(verification)

        student_document = self.session.scalar(
            select(Document)
            .where(
                Document.tenant_id == tenant_id,
                Document.submission_id == submission.id,
                Document.kind == "STUDENT",
            )
            .order_by(Document.created_at)
        )
        pages_by_id: dict[uuid.UUID, DocumentPage] = {}
        pages: list[DocumentPage] = []
        mappings: dict[str, list[PageQuestionMapping]] = defaultdict(list)
        if student_document is not None:
            pages = list(
                self.session.scalars(
                    select(DocumentPage)
                    .where(DocumentPage.document_id == student_document.id)
                    .order_by(DocumentPage.page_index)
                )
            )
            pages_by_id = {page.id: page for page in pages}
            for mapping in self.session.scalars(
                select(PageQuestionMapping).where(
                    PageQuestionMapping.tenant_id == tenant_id,
                    PageQuestionMapping.document_id == student_document.id,
                )
            ):
                mappings[mapping.question_id].append(mapping)

        archives: dict[str, ProviderResponse] = {}
        archive_rows = list(
            self.session.scalars(
                select(ProviderResponse).where(
                    ProviderResponse.tenant_id == tenant_id,
                    ProviderResponse.job_id == job.id,
                )
            )
        )
        for archive in archive_rows:
            archives[archive.content_sha256] = archive

        blueprint_questions = (
            _flatten_questions(blueprint.structure.get("questions") or [])
            if blueprint is not None and isinstance(blueprint.structure, dict)
            else []
        )
        blueprint_by_id = {
            str(item.get("question_id")): item
            for item in blueprint_questions
            if item.get("question_id") is not None
        }

        questions: list[PreviewQuestionRead] = []
        for row in rows:
            blueprint_question = blueprint_by_id.get(row.question_id, {})
            archived_item = self._archived_item(row)
            criteria = self._merge(
                scheme_rows.get(row.question_id, []),
                persisted.get(row.id, []),
                archived_item,
            )
            component_total = self._component_total(archived_item)
            location, mapping_note = self._location(
                mappings.get(row.question_id, []), pages_by_id
            )
            archive = self._archive_for(row, archived_item, archives)
            concerns = _dict_list(row.scheme_concerns)
            review_reasons = self._review_reasons(row, concerns, archived_item)

            questions.append(
                PreviewQuestionRead(
                    question_id=row.question_id,
                    label=_text(blueprint_question.get("label")) or f"Question {row.question_id}",
                    question_text=_text(blueprint_question.get("question_text")),
                    special_instructions=_string_list(
                        blueprint_question.get("special_instructions")
                    ),
                    max_marks=row.max_marks,
                    awarded_marks=row.awarded_marks,
                    raw_awarded_marks=row.raw_awarded_marks,
                    status=row.status,
                    processing_state=effective_state(
                        row.status,
                        row.processing_state,
                        review_required=bool(row.review_required),
                    ),
                    review_required=bool(row.review_required),
                    student_answer=_text(row.student_answer)
                    or _text((archived_item or {}).get("student_answer")),
                    working_summary=_text(row.working_summary),
                    confidence=row.confidence,
                    answer_check=_text((archived_item or {}).get("answer_check")),
                    notes=_text((archived_item or {}).get("notes")),
                    response_source=row.response_source,
                    response_sequence=row.response_sequence,
                    prompt_version=row.prompt_version,
                    scheme_criteria=[
                        PreviewCriterionRead(
                            code=criterion.code,
                            ordinal=criterion.ordinal,
                            marks=criterion.marks,
                            description=criterion.description,
                            expected_answer=criterion.expected_answer,
                            required_evidence=criterion.required_evidence,
                            award_conditions=criterion.award_conditions,
                            withhold_conditions=criterion.withhold_conditions,
                            dependencies=_string_list(criterion.dependencies),
                            alternatives=_dict_list(criterion.alternatives),
                            source_page=criterion.source_page,
                            source_quote=criterion.source_quote,
                        )
                        for criterion in scheme_rows.get(row.question_id, [])
                    ],
                    criteria=criteria,
                    scheme_marks=sum(
                        criterion.marks for criterion in scheme_rows.get(row.question_id, [])
                    ),
                    component_total=component_total,
                    component_consistent=(
                        None if component_total is None else component_total == row.awarded_marks
                    ),
                    location=location,
                    mapping_note=mapping_note,
                    verifications=[
                        PreviewVerificationRead(
                            kind=verification.kind,
                            status=verification.status,
                            detail=verification.detail or {},
                        )
                        for verification in verifications.get(row.question_id, [])
                    ],
                    review_reasons=review_reasons,
                    concerns=concerns,
                    archive=archive,
                )
            )

        paper_awarded = sum(row.awarded_marks for row in rows)
        paper_total = sum(row.max_marks for row in rows)

        scheme_document, scheme_note = self._scheme_document(
            tenant_id, exam.id, scheme_version
        )
        guard_decision, guard_reason = self._guard_decision(tenant_id, job.id)

        warnings = self._warnings(
            student_document=student_document,
            pages=pages,
            mappings=mappings,
            questions=questions,
            rows=rows,
            verifications=base.verifications,
            scheme_note=scheme_note,
            refused=job.result_source == "AUTOMATED_REFUSED",
            guard_reason=guard_reason,
        )

        prompt_version = next(
            (row.prompt_version for row in rows if row.prompt_version), None
        )
        paper = PreviewPaperRead(
            exam_id=exam.id,
            exam_title=exam.title,
            board=exam.board,
            paper_code=exam.paper_code,
            assignment_id=assignment.id,
            assignment_name=assignment.name,
            blueprint_version_id=job.blueprint_version_id,
            scheme_version_id=job.scheme_version_id,
            blueprint_total_marks=blueprint.total_marks if blueprint is not None else paper_total,
            marking_mode=job.marking_mode,
            engine_name=job.engine_name,
            engine_version=job.engine_version,
            primary_model=job.primary_model,
            secondary_model=job.secondary_model,
            prompt_version=prompt_version,
            job_state=job.state,
            result_source=job.result_source,
            guard_decision=guard_decision,
            guard_reason=guard_reason,
            questions_reviewed=len(rows),
            attention=sum(1 for row in rows if row.review_required),
            paper_awarded=paper_awarded,
            paper_total=paper_total,
            decided_awarded=base.totals.awarded,
            decided_total=base.totals.total,
            decided=base.totals.decided,
            scoreable=base.totals.scoreable,
            undecided=base.totals.undecided,
            review_required=base.totals.review_required,
            approved=base.totals.approved,
            approved_at=base.approved_at,
            approved_by=base.approved_by,
        )

        exam_scheme_document = self._exam_scheme_document(tenant_id, exam.id)
        return CorrectionPreviewRead(
            job_id=job.id,
            submission_id=submission.id,
            student_ref=submission.student_ref,
            paper=paper,
            student_document=(
                PreviewDocumentRead(
                    id=student_document.id,
                    kind=student_document.kind,
                    original_filename=student_document.original_filename,
                    sha256=student_document.sha256,
                    size_bytes=student_document.size_bytes,
                    page_count=student_document.page_count,
                    ordering_status=student_document.ordering_status,
                    ordering_reasons=_dict_list(student_document.ordering_reasons),
                    mapping_status=student_document.mapping_status,
                    mapping_reasons=_dict_list(student_document.mapping_reasons),
                )
                if student_document is not None
                else None
            ),
            scheme_document=PreviewSchemeDocumentRead(
                document_id=scheme_document.id if scheme_document else None,
                original_filename=scheme_document.original_filename if scheme_document else None,
                page_count=scheme_document.page_count if scheme_document else 0,
                content_hash_matches=bool(
                    scheme_document is not None
                    and scheme_version is not None
                    and scheme_document.sha256 == scheme_version.content_hash
                ),
                exam_document_filename=(
                    exam_scheme_document.original_filename
                    if exam_scheme_document is not None
                    else None
                ),
                exam_document_size_bytes=(
                    exam_scheme_document.size_bytes
                    if exam_scheme_document is not None
                    else None
                ),
                note=scheme_note,
            ),
            students=self._students(principal, assignment.id, job.id),
            questions=questions,
            warnings=warnings,
        )

    # -- pieces ----------------------------------------------------------
    @staticmethod
    def _archived_item(row: QuestionResult) -> dict[str, Any] | None:
        raw = row.raw_response
        if not isinstance(raw, dict):
            return None
        item = raw.get("item")
        if isinstance(item, dict):
            return item
        if "components" in raw or "awarded_marks" in raw:
            return raw
        return None

    def _merge(
        self,
        scheme: list[MarkingCriterion],
        persisted: list[CriterionResult],
        archived_item: dict[str, Any] | None,
    ) -> list[PreviewDecisionRead]:
        components = archived_item.get("components") if archived_item else None
        awards: list[dict[str, Any]] = []

        if isinstance(components, list) and components:
            used: set[int] = set()
            for component in components:
                if not isinstance(component, dict):
                    continue
                code = str(component.get("code") or "?").strip()
                match_index = next(
                    (
                        index
                        for index, row in enumerate(persisted)
                        if index not in used and row.code.strip() == code
                    ),
                    None,
                )
                stored = persisted[match_index] if match_index is not None else None
                if match_index is not None:
                    used.add(match_index)
                evidence: list[str] = []
                for entry in (stored.evidence if stored else []) or []:
                    quote = entry.get("quote") if isinstance(entry, dict) else None
                    if isinstance(quote, str) and quote.strip() and quote.strip() not in evidence:
                        evidence.append(quote.strip())
                archived_quote = _text(component.get("evidence"))
                if archived_quote and archived_quote not in evidence:
                    evidence.append(archived_quote)
                awards.append(
                    {
                        "code": code,
                        "base": _base_code(code)[0],
                        "occurrence": _base_code(code)[1],
                        "awarded": bool(component.get("awarded")),
                        "marks": component.get("marks")
                        if isinstance(component.get("marks"), int)
                        else None,
                        "reason": _text(stored.reason) if stored else None,
                        "evidence": evidence,
                        "description": _text(component.get("description")),
                    }
                )
            # A persisted criterion the reply's components do not name is still
            # a stored assessment; it must not disappear from the preview.
            leftovers = [row for index, row in enumerate(persisted) if index not in used]
        else:
            leftovers = list(persisted)

        for row in leftovers:
            code = row.code.strip()
            evidence = [
                entry.get("quote").strip()
                for entry in (row.evidence or [])
                if isinstance(entry, dict)
                and isinstance(entry.get("quote"), str)
                and entry.get("quote").strip()
            ]
            awards.append(
                {
                    "code": code,
                    "base": _base_code(code)[0],
                    "occurrence": _base_code(code)[1],
                    "awarded": bool(row.awarded),
                    "marks": None,
                    "reason": _text(row.reason),
                    "evidence": evidence,
                    "description": None,
                }
            )

        # How many printed points share each code, and how many the reply named.
        scheme_by_code: dict[str, list[int]] = defaultdict(list)
        for criterion in scheme:
            scheme_by_code[criterion.code.strip()].append(criterion.ordinal)
        awards_by_code: dict[str, int] = defaultdict(int)
        for award in awards:
            awards_by_code[award["base"]] += 1

        used_awards: set[int] = set()
        decisions: list[PreviewDecisionRead] = []
        for criterion in scheme:
            code = criterion.code.strip()
            same_code = scheme_by_code[code]
            occurrence = same_code.index(criterion.ordinal)
            preferred = next(
                (
                    index
                    for index, award in enumerate(awards)
                    if index not in used_awards
                    and award["base"] == code
                    and award["occurrence"] == occurrence
                ),
                None,
            )
            if preferred is None:
                preferred = next(
                    (
                        index
                        for index, award in enumerate(awards)
                        if index not in used_awards and award["base"] == code
                    ),
                    None,
                )
            ambiguous = len(same_code) > 1 and awards_by_code[code] < len(same_code)
            note = None
            if ambiguous and preferred is not None:
                note = (
                    f"The scheme prints {len(same_code)} {code} points; the reply names "
                    f"{code} {awards_by_code[code]} time(s). The award is read against the "
                    "order the scheme prints, and the stored concern records that a person "
                    "has to confirm which point it was for."
                )
            if len(same_code) > 1 and preferred is not None and not ambiguous:
                note = f"Matched to {code} point {occurrence + 1} of {len(same_code)}."
            if preferred is None:
                decisions.append(
                    PreviewDecisionRead(
                        code=code,
                        scheme_ordinal=criterion.ordinal,
                        scheme_marks=criterion.marks,
                        awarded=None,
                        awarded_marks=None,
                        note="The archived reply recorded no separate assessment for this point.",
                    )
                )
                continue
            award = awards[preferred]
            used_awards.add(preferred)
            decisions.append(
                PreviewDecisionRead(
                    code=award["code"],
                    scheme_ordinal=criterion.ordinal,
                    scheme_marks=criterion.marks,
                    awarded=award["awarded"],
                    awarded_marks=award["marks"],
                    reason=award["reason"],
                    evidence=award["evidence"],
                    component_description=award["description"],
                    ambiguous=ambiguous,
                    note=note,
                )
            )

        for index, award in enumerate(awards):
            if index in used_awards:
                continue
            decisions.append(
                PreviewDecisionRead(
                    code=award["code"],
                    scheme_ordinal=None,
                    scheme_marks=None,
                    awarded=award["awarded"],
                    awarded_marks=award["marks"],
                    reason=award["reason"],
                    evidence=award["evidence"],
                    component_description=award["description"],
                    note="The reply names this code; the stored scheme has no matching point.",
                )
            )
            used_awards.add(index)
        return decisions

    @staticmethod
    def _component_total(archived_item: dict[str, Any] | None) -> int | None:
        if not archived_item:
            return None
        components = archived_item.get("components")
        if not isinstance(components, list) or not components:
            return None
        total = 0
        for component in components:
            if not isinstance(component, dict) or not component.get("awarded"):
                continue
            marks = component.get("marks")
            if isinstance(marks, int):
                total += marks
        return total

    @staticmethod
    def _location(
        mappings: list[PageQuestionMapping], pages_by_id: dict[uuid.UUID, DocumentPage]
    ) -> tuple[PreviewLocationRead | None, str | None]:
        candidates = [mapping for mapping in mappings if mapping.page_id in pages_by_id]
        if not candidates:
            return (
                None,
                "No stored question-to-page mapping for this question, so the full "
                "first page is shown rather than a crop.",
            )
        candidates.sort(key=lambda mapping: mapping.confidence, reverse=True)
        best = candidates[0]
        page = pages_by_id[best.page_id]
        pages = sorted({pages_by_id[mapping.page_id].page_index for mapping in candidates})
        note = None
        if len(pages) > 1:
            note = "The engine mapped this question to more than one stored page: " + ", ".join(
                f"page {index}" for index in pages
            )
        return (
            PreviewLocationRead(
                page_index=page.page_index,
                confidence=best.confidence,
                method=best.method,
                quality_status=page.quality_status,
                width=page.width,
                height=page.height,
            ),
            note,
        )

    @staticmethod
    def _archive_for(
        row: QuestionResult,
        archived_item: dict[str, Any] | None,
        archives: dict[str, ProviderResponse],
    ) -> PreviewArchiveRead | None:
        sha = _text((archived_item or {}).get("paper_sha256"))
        archive = archives.get(sha) if sha else None
        if archive is None and len(archives) == 1 and (row.response_source == "WHOLE_PAPER"):
            archive = next(iter(archives.values()))
        if archive is None:
            return None
        return PreviewArchiveRead(
            provider_response_id=archive.id,
            content_sha256=archive.content_sha256,
            model=archive.model,
            finish_reason=archive.finish_reason,
            response_source=archive.response_source,
            created_at=archive.created_at,
        )

    @staticmethod
    def _review_reasons(
        row: QuestionResult,
        concerns: list[dict[str, Any]],
        archived_item: dict[str, Any] | None,
    ) -> list[str]:
        messages: list[str] = []
        for concern in concerns:
            message = _text(concern.get("message"))
            if message and message not in messages:
                messages.append(message)
        for reason in _string_list((archived_item or {}).get("review_reasons")):
            if reason not in messages:
                messages.append(reason)
        if row.review_required and not messages:
            messages.append(
                "The engine flagged this question for review, but the stored row records no reason."
            )
        return messages

    def _exam_scheme_document(
        self, tenant_id: uuid.UUID, exam_id: uuid.UUID
    ) -> Document | None:
        return self.session.scalar(
            select(Document)
            .where(
                Document.tenant_id == tenant_id,
                Document.exam_id == exam_id,
                Document.kind == "MARK_SCHEME",
            )
            .order_by(Document.created_at.desc())
            .limit(1)
        )

    def _scheme_document(
        self,
        tenant_id: uuid.UUID,
        exam_id: uuid.UUID,
        scheme_version: MarkSchemeVersion | None,
    ) -> tuple[Document | None, str]:
        exam_document = self._exam_scheme_document(tenant_id, exam_id)
        if scheme_version is None:
            return (
                None,
                "The job records no scheme version, so no printed scheme pages can be matched.",
            )
        matching = list(
            self.session.scalars(
                select(Document)
                .where(
                    Document.tenant_id == tenant_id,
                    Document.kind == "MARK_SCHEME",
                    Document.sha256 == scheme_version.content_hash,
                )
                .order_by(Document.page_count.desc(), Document.created_at)
            )
        )
        chosen = matching[0] if matching else None
        if chosen is None:
            return (
                None,
                "No stored scheme document matches this scheme version's content hash "
                f"({scheme_version.content_hash[:12]}…), so only the structured criteria "
                "are shown.",
            )
        if exam_document is not None and chosen.id != exam_document.id:
            return (
                chosen,
                "The exam record points to a different document "
                f"({exam_document.original_filename}, {exam_document.size_bytes} bytes, "
                f"{exam_document.page_count} page(s)); it does not match this scheme "
                f"version's content. The pages shown come from {chosen.original_filename}, "
                "whose SHA-256 equals this scheme version's content hash.",
            )
        return (
            chosen,
            "The printed scheme pages come from the document recorded for this exam; its "
            "SHA-256 equals this scheme version's content hash.",
        )

    def _guard_decision(
        self, tenant_id: uuid.UUID, job_id: uuid.UUID
    ) -> tuple[str | None, str | None]:
        event = self.session.scalar(
            select(JobEvent)
            .where(JobEvent.tenant_id == tenant_id, JobEvent.job_id == job_id)
            .order_by(JobEvent.event_seq.desc())
            .limit(1)
        )
        if event is None or not isinstance(event.detail, dict):
            return None, None
        decision = event.detail.get("guard")
        reason = event.detail.get("guard_reason")
        return (
            decision if isinstance(decision, str) else None,
            reason if isinstance(reason, str) else None,
        )

    def _students(
        self, principal: Principal, assignment_id: uuid.UUID, current_job_id: uuid.UUID
    ) -> list[PreviewStudentRead]:
        students: list[PreviewStudentRead] = []
        submissions = list(
            self.session.scalars(
                select(Submission)
                .where(
                    Submission.tenant_id == principal.tenant_id,
                    Submission.assignment_id == assignment_id,
                )
                .order_by(Submission.student_ref)
            )
        )
        for submission in submissions:
            job = self.results.latest_job_for_submission(principal.tenant_id, submission.id)
            if job is None:
                job = self.results.newest_refused_job(principal.tenant_id, submission.id)
            if job is None:
                continue
            awarded, total, review = self.session.execute(
                select(
                    func.coalesce(func.sum(QuestionResult.awarded_marks), 0),
                    func.coalesce(func.sum(QuestionResult.max_marks), 0),
                    func.count()
                    .filter(QuestionResult.review_required.is_(True)),
                ).where(QuestionResult.job_id == job.id)
            ).one()
            students.append(
                PreviewStudentRead(
                    submission_id=submission.id,
                    job_id=job.id,
                    student_ref=submission.student_ref,
                    awarded_marks=int(awarded),
                    total_marks=int(total),
                    review_required=int(review),
                    job_state=job.state,
                    result_source=job.result_source,
                    current=job.id == current_job_id,
                )
            )
        return students

    def _warnings(
        self,
        *,
        student_document: Document | None,
        pages: list[DocumentPage],
        mappings: dict[str, list[PageQuestionMapping]],
        questions: list[PreviewQuestionRead],
        rows: list[QuestionResult],
        verifications: list[Any],
        scheme_note: str,
        refused: bool,
        guard_reason: str | None,
    ) -> list[PreviewWarningRead]:
        warnings: list[PreviewWarningRead] = []
        if refused:
            warnings.append(
                PreviewWarningRead(
                    code="RUN_REFUSED",
                    message=(
                        "This run was refused by the result guard and is not the "
                        "submission's presented result."
                        + (f" {guard_reason}" if guard_reason else "")
                        + " Its question rows are shown as evidence."
                    ),
                )
            )
        if student_document is None:
            warnings.append(
                PreviewWarningRead(
                    code="NO_STUDENT_DOCUMENT",
                    message=(
                        "This submission has no stored student document, so no page "
                        "can be shown."
                    ),
                )
            )
        else:
            if student_document.ordering_status != "ORDERED":
                warnings.append(
                    PreviewWarningRead(
                        code="PAGE_ORDERING",
                        message=(
                            f"Page order is {student_document.ordering_status}. The page shown "
                            "is the stored page number, not a verified printed page number."
                        ),
                    )
                )
            if student_document.mapping_status != "MAPPED":
                mapped_pages = {
                    mapping.page_id for group in mappings.values() for mapping in group
                }
                unmapped = [
                    page.page_index for page in pages if page.id not in mapped_pages
                ]
                detail = (
                    " Page(s) with no question mapping: "
                    + ", ".join(str(index) for index in unmapped)
                    + "."
                    if unmapped
                    else ""
                )
                warnings.append(
                    PreviewWarningRead(
                        code="PAGE_MAPPING",
                        message=(
                            f"Question-page mapping is {student_document.mapping_status}.{detail}"
                        ),
                    )
                )
            low = [
                question.question_id
                for question in questions
                if question.location is not None and question.location.confidence < 0.95
            ]
            if low:
                warnings.append(
                    PreviewWarningRead(
                        code="LOW_MAPPING_CONFIDENCE",
                        message=(
                            f"{len(low)} question(s) are mapped to a page below 0.95 confidence: "
                            + ", ".join(low)
                            + "."
                        ),
                    )
                )
        missing = sum(1 for row in rows if not _text(row.student_answer))
        if missing:
            warnings.append(
                PreviewWarningRead(
                    code="NO_TRANSCRIPTION",
                    message=(
                        f"The archived reply recorded no transcription for {missing} question(s). "
                        "Their student work is shown only as the scanned page."
                    ),
                )
            )
        different = [
            verification
            for verification in verifications
            if verification.kind == "SCHEME_MATHEMATICAL" and verification.status == "DIFFERENT"
        ]
        if different:
            warnings.append(
                PreviewWarningRead(
                    code="SCHEME_MATHEMATICAL",
                    message=(
                        f"SymPy found {len(different)} final answer(s) different from the "
                        "scheme's expected expression. Each is listed on its question; the "
                        "award still stands until a person decides."
                    ),
                )
            )
        warnings.append(PreviewWarningRead(code="SCHEME_SOURCE", message=scheme_note))
        return warnings
