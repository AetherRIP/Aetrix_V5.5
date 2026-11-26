"""Transcribe, review and approve the mark points a scheme prints.

An uploaded scheme is a PDF; the engine can only award marks against stored
rows.  This module owns the missing middle: turning a printed scheme into rows a
person has reviewed, against one exact blueprint version.

The three steps mirror blueprint approval and keep its ordering:

* ``extract`` transcribes the printed mark points against an **approved**
  blueprint and refuses to store anything unless they cover the paper exactly;
* a person reads the stored rows;
* ``approve`` re-validates those rows against that exact blueprint version and
  records the rules digest, which is what the engine's readiness gate checks.

There is no path from extraction to approval, and no path from approval to
marking that skips :func:`app.correction.scheme_criteria.criteria_readiness`.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal, ensure_exam_manager
from ..correction.scheme_criteria import (
    REASON_CRITERIA_MISSING,
    CoverageReport,
    CriteriaReadiness,
    blueprint_leaves,
    criteria_readiness,
    criteria_rules_hash,
    iter_criteria,
    rows_as_document,
    validate,
)
from ..db.models import (
    ExamBlueprintVersion,
    MarkingCriterion,
    MarkScheme,
    MarkSchemeVersion,
)
from ..db.repositories import BlueprintRepository, MarkSchemeRepository
from ..documents.service import DocumentService
from ..prompts.registry import PromptRegistry
from ..providers.base import LLMInput
from ..providers.json import parse_json_text
from ..schemas.documents import SchemeCriterionCreate, SchemeCriterionUpdate
from ..storage.base import Storage
from .provider_calls import ProviderCallResult, ProviderCallService

PROMPT_ID = "scheme_criteria_extraction"
PURPOSE = "SCHEME_CRITERIA_EXTRACTION"

#: How many scheme pages are sent as images, matching blueprint extraction.  A
#: longer scheme still contributes its later pages as text.
MAX_IMAGE_PAGES = 24


def criteria_response_schema() -> dict[str, Any]:
    """The OpenAPI subset Gemini's ``responseSchema`` accepts for criteria."""

    alternative = {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "marks": {"type": "integer"},
            "rule": {"type": "string"},
            "replaces": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["code", "marks", "replaces"],
    }
    criterion = {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "marks": {"type": "integer"},
            "ordinal": {"type": "integer"},
            "description": {"type": "string"},
            "expected_answer": {"type": "string"},
            "required_evidence": {"type": "string"},
            "dependencies": {"type": "array", "items": {"type": "string"}},
            "alternatives": {"type": "array", "items": alternative},
            "award_conditions": {"type": "string"},
            "withhold_conditions": {"type": "string"},
            "source_page": {"type": "integer"},
            "source_quote": {"type": "string"},
        },
        "required": ["code", "marks", "description"],
    }
    question = {
        "type": "object",
        "properties": {
            "question_id": {"type": "string"},
            "source_ref": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "pdf_page": {"type": "integer"},
                },
            },
            "criteria": {"type": "array", "items": criterion},
        },
        "required": ["question_id", "criteria"],
    }
    return {
        "type": "object",
        "properties": {
            "questions": {"type": "array", "items": question},
            "total_marks": {"type": "integer"},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["questions", "total_marks"],
    }


def readiness_for(
    rows: list[Any],
    blueprint: ExamBlueprintVersion,
    version: MarkSchemeVersion,
) -> CriteriaReadiness:
    """The engine's own readiness verdict for stored criteria.

    A thin argument-shuffling wrapper so every caller — assignment creation,
    Classroom publication and the API — asks the identical question of the
    identical gate.  It decides nothing itself.
    """

    return criteria_readiness(
        rows,
        blueprint.structure,
        blueprint_version_id=blueprint.id,
        approved_against=version.criteria_blueprint_version_id,
        approved_at=version.criteria_approved_at,
        approved_rules_hash=version.criteria_rules_hash,
    )


def reconcile_max_points(blueprint_total: int, requested: Any) -> Decimal:
    """The coursework's maximum points, or a refusal naming the paper's total.

    Google stores one number, and it is what every published grade is scored
    against.  Letting it differ from the approved paper would put a mark out of
    91 beside a coursework worth 6, and a fractional value would make the
    coursework's denominator disagree with the blueprint's integer total.
    """

    total = Decimal(int(blueprint_total))
    if requested is None:
        return total
    try:
        value = Decimal(str(requested))
    except (InvalidOperation, ValueError) as error:
        raise AppError(
            ErrorCode.CONFLICT,
            f"The coursework's maximum points must be the paper's {total} marks.",
            details={"blueprint_total": int(blueprint_total)},
        ) from error
    if value != value.to_integral_value():
        raise AppError(
            ErrorCode.CONFLICT,
            f"The coursework's maximum points must be a whole number of marks "
            f"({total}); {value} cannot match an integer paper total.",
            details={"blueprint_total": int(blueprint_total)},
        )
    if value != total:
        raise AppError(
            ErrorCode.CONFLICT,
            f"This paper is worth {total} marks, so the coursework's maximum "
            f"points must be {total}, not {value}.",
            details={
                "blueprint_total": int(blueprint_total),
                "requested_max_points": str(value),
            },
        )
    return total


def readiness_of_assignment(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    blueprint_version_id: uuid.UUID | None,
    scheme_version_id: uuid.UUID | None,
) -> CriteriaReadiness:
    """Read an assignment's own configuration and ask the engine's gate.

    A missing blueprint or scheme is not an error to raise from here: it is a
    not-ready answer, so each caller can phrase its own refusal.
    """

    if blueprint_version_id is None or scheme_version_id is None:
        return CriteriaReadiness(
            ready=False,
            reason=REASON_CRITERIA_MISSING,
            problems=("the assignment has no blueprint or mark scheme attached",),
            questions=0,
            total_marks=0,
        )
    blueprint = session.get(ExamBlueprintVersion, blueprint_version_id)
    if blueprint is None or blueprint.tenant_id != tenant_id:
        return CriteriaReadiness(
            ready=False,
            reason=REASON_CRITERIA_MISSING,
            problems=("the assignment's blueprint version cannot be loaded",),
            questions=0,
            total_marks=0,
        )
    version = session.get(MarkSchemeVersion, scheme_version_id)
    if version is None or version.tenant_id != tenant_id:
        return CriteriaReadiness(
            ready=False,
            reason=REASON_CRITERIA_MISSING,
            problems=("the assignment's mark-scheme version cannot be loaded",),
            questions=0,
            total_marks=0,
        )
    rows = MarkSchemeRepository(session).list_criteria(tenant_id, version.id)
    return readiness_for(rows, blueprint, version)


@dataclass(frozen=True, slots=True)
class CriteriaExtractionResult:
    version: MarkSchemeVersion
    criteria: list[MarkingCriterion]
    coverage: CoverageReport
    provider: ProviderCallResult


class SchemeCriteriaService:
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
        self.schemes = MarkSchemeRepository(session)
        self.blueprints = BlueprintRepository(session)
        self.documents = DocumentService(session, settings, storage)
        self.audit = AuditService(session)

    # -- reads -----------------------------------------------------------
    def get_version(self, tenant_id: uuid.UUID, version_id: uuid.UUID) -> MarkSchemeVersion:
        version = self.schemes.get_version(tenant_id, version_id)
        if version is None:
            raise AppError(ErrorCode.NOT_FOUND, "Mark-scheme version not found.")
        return version

    def criteria(
        self, tenant_id: uuid.UUID, version_id: uuid.UUID
    ) -> list[MarkingCriterion]:
        return self.schemes.list_criteria(tenant_id, version_id)

    def readiness(
        self, tenant_id: uuid.UUID, version_id: uuid.UUID, blueprint_version_id: uuid.UUID
    ) -> CriteriaReadiness:
        version = self.get_version(tenant_id, version_id)
        scheme = self.schemes.get_scheme(tenant_id, version.mark_scheme_id)
        if scheme is None:
            raise AppError(ErrorCode.NOT_FOUND, "Mark scheme not found.")
        blueprint = self._approved_blueprint(tenant_id, scheme.exam_id, blueprint_version_id)
        return readiness_for(
            self.schemes.list_criteria(tenant_id, version.id), blueprint, version
        )

    # -- extraction ------------------------------------------------------
    def extract(
        self,
        principal: Principal,
        version_id: uuid.UUID,
        *,
        blueprint_version_id: uuid.UUID,
        prompt_version: int | None = None,
    ) -> CriteriaExtractionResult:
        ensure_exam_manager(principal)
        version, scheme = self._version_and_scheme(principal.tenant_id, version_id)
        if version.status == "SUPERSEDED":
            raise AppError(
                ErrorCode.CONFLICT,
                "A superseded mark scheme cannot be transcribed again.",
            )
        blueprint = self._approved_blueprint(
            principal.tenant_id, scheme.exam_id, blueprint_version_id
        )
        document = self._scheme_document(principal.tenant_id, scheme)

        inputs = self._inputs(document, blueprint)
        result = self.provider_calls.call(
            tenant_id=principal.tenant_id,
            purpose=PURPOSE,
            prompt_id=PROMPT_ID,
            inputs=tuple(inputs),
            prompt_version=prompt_version,
            response_schema=criteria_response_schema(),
            max_output_tokens=32768,
        )
        payload = self._parse(result)
        coverage = validate(payload, blueprint.structure)
        if not coverage.complete:
            # Nothing is written for a transcription that does not cover the
            # paper: a partial set would look like a scheme and mark with holes.
            raise AppError(
                ErrorCode.EXTRACTION_INVALID,
                "The transcribed criteria do not cover this paper exactly, so "
                "nothing was stored. Review the scheme pages and extract again.",
                details={
                    "usage_id": str(result.usage_id),
                    "problems": list(coverage.problems)[:40],
                    "shortfall": coverage.describe()["shortfall"][:40],
                },
            )

        rows = self._replace_rows(principal, version, blueprint, payload)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme_criteria.extracted",
            entity_type="mark_scheme_version",
            entity_id=version.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "blueprint_version_id": str(blueprint.id),
                "questions": len(coverage.lines),
                "criteria": len(rows),
                "total_marks": coverage.total_criteria,
                "usage_id": str(result.usage_id),
                "prompt_id": result.prompt.prompt_id,
                "prompt_version": result.prompt.version,
            },
        )
        self.session.commit()
        return CriteriaExtractionResult(
            version=version, criteria=rows, coverage=coverage, provider=result
        )

    # -- approval --------------------------------------------------------
    def approve(
        self,
        principal: Principal,
        version_id: uuid.UUID,
        *,
        blueprint_version_id: uuid.UUID,
        reason: str,
    ) -> MarkSchemeVersion:
        ensure_exam_manager(principal)
        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "A reason is required to approve marking criteria.",
            )
        version, scheme = self._version_and_scheme(principal.tenant_id, version_id)
        if version.status == "SUPERSEDED":
            raise AppError(
                ErrorCode.CONFLICT, "A superseded mark scheme cannot be approved."
            )
        blueprint = self._approved_blueprint(
            principal.tenant_id, scheme.exam_id, blueprint_version_id
        )
        rows = self.schemes.list_criteria(principal.tenant_id, version.id)
        if not rows:
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "This scheme version has no transcribed criteria, so there is "
                "nothing to approve. Extract them first.",
            )

        # The rows are re-checked, not the reply: this is the set that will mark.
        coverage = validate(rows_as_document(rows), blueprint.structure)
        if not coverage.complete:
            raise AppError(
                ErrorCode.CONFLICT,
                "The stored criteria do not cover this blueprint exactly, so "
                "they cannot be approved. Extract them again against this "
                "blueprint version.",
                details={
                    "problems": list(coverage.problems)[:40],
                    "shortfall": coverage.describe()["shortfall"][:40],
                },
            )

        version.criteria_blueprint_version_id = blueprint.id
        version.criteria_blueprint_hash = blueprint.content_hash
        version.criteria_rules_hash = criteria_rules_hash(rows, blueprint.structure)
        version.criteria_approved_at = utcnow()
        version.criteria_approved_by = principal.user_id
        version.criteria_approval_reason = clean_reason[:2000]
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme_criteria.approved",
            entity_type="mark_scheme_version",
            entity_id=version.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "blueprint_version_id": str(blueprint.id),
                "questions": len(coverage.lines),
                "total_marks": coverage.total_criteria,
                "rules_hash": version.criteria_rules_hash,
                "reason": clean_reason[:500],
            },
        )
        self.session.commit()
        return version

    # -- manual authoring ------------------------------------------------
    def add_criterion(
        self,
        principal: Principal,
        version_id: uuid.UUID,
        payload: SchemeCriterionCreate,
    ) -> MarkingCriterion:
        """Add one mark point a person typed, before any approval exists.

        The question must be a scoreable leaf of the blueprint this scheme is
        being written against, and the question's stored mark points may never
        exceed its maximum.  Nothing is invented: a missing question stays
        missing and the readiness gate keeps refusing the scheme.
        """

        ensure_exam_manager(principal)
        version, scheme = self._version_and_scheme(principal.tenant_id, version_id)
        self._writable(version)
        blueprint = self._approved_blueprint(
            principal.tenant_id, scheme.exam_id, payload.blueprint_version_id
        )
        question_id = payload.question_id.strip()
        leaves = blueprint_leaves(blueprint.structure)
        if question_id not in leaves:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"Question {question_id!r} is not a scoreable leaf of this blueprint.",
            )
        rows = self.schemes.list_criteria(principal.tenant_id, version.id)
        recorded = sum(row.marks for row in rows if row.question_id == question_id)
        remaining = leaves[question_id] - recorded
        if payload.marks > remaining:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"Question {question_id} has {remaining} mark(s) left; "
                f"a {payload.marks}-mark criterion would exceed its maximum.",
            )
        code = payload.code.strip().upper()
        if any(
            row.question_id == question_id
            and row.code.upper() == code
            and row.ordinal == payload.ordinal
            for row in rows
        ):
            raise AppError(
                ErrorCode.CONFLICT,
                f"Question {question_id} already has criterion {code} at that position.",
            )
        row = MarkingCriterion(
            tenant_id=principal.tenant_id,
            scheme_version_id=version.id,
            blueprint_version_id=blueprint.id,
            question_id=question_id,
            code=code,
            marks=payload.marks,
            ordinal=payload.ordinal,
            description=payload.description.strip(),
            expected_answer=(payload.expected_answer or "").strip() or None,
            award_conditions=(payload.award_conditions or "").strip() or None,
            withhold_conditions=(payload.withhold_conditions or "").strip() or None,
            dependencies=[],
            alternatives=[],
            source_ref={},
        )
        self.session.add(row)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme_criteria.manually_created",
            entity_type="marking_criterion",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "scheme_version_id": str(version.id),
                "blueprint_version_id": str(blueprint.id),
                "question_id": question_id,
                "code": code,
                "marks": payload.marks,
            },
        )
        self.session.commit()
        self.session.refresh(row)
        return row

    def update_criterion(
        self,
        principal: Principal,
        version_id: uuid.UUID,
        criterion_id: uuid.UUID,
        payload: SchemeCriterionUpdate,
    ) -> MarkingCriterion:
        ensure_exam_manager(principal)
        version, scheme = self._version_and_scheme(principal.tenant_id, version_id)
        self._writable(version)
        row = self._criterion_row(principal.tenant_id, version.id, criterion_id)
        blueprint_id = payload.blueprint_version_id or row.blueprint_version_id
        if blueprint_id is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "This criterion names no blueprint version; supply one to validate its marks.",
            )
        blueprint = self._approved_blueprint(
            principal.tenant_id, scheme.exam_id, blueprint_id
        )
        leaves = blueprint_leaves(blueprint.structure)
        if row.question_id not in leaves:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"Question {row.question_id!r} is not a scoreable leaf of this blueprint.",
            )
        if payload.marks is not None:
            rows = self.schemes.list_criteria(principal.tenant_id, version.id)
            recorded = sum(
                item.marks
                for item in rows
                if item.question_id == row.question_id and item.id != row.id
            )
            remaining = leaves[row.question_id] - recorded
            if payload.marks > remaining:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"Question {row.question_id} has {remaining} mark(s) left; "
                    f"a {payload.marks}-mark criterion would exceed its maximum.",
                )
        changes: dict[str, Any] = {}
        for field in (
            "marks",
            "description",
            "expected_answer",
            "award_conditions",
            "withhold_conditions",
        ):
            value = getattr(payload, field)
            if value is None:
                continue
            changes[field] = value.strip() if isinstance(value, str) else value
        if not changes:
            return row
        for field, value in changes.items():
            setattr(row, field, value)
        row.blueprint_version_id = blueprint.id
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme_criteria.manually_updated",
            entity_type="marking_criterion",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "scheme_version_id": str(version.id),
                "question_id": row.question_id,
                "code": row.code,
                "fields": sorted(changes),
            },
        )
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete_criterion(
        self,
        principal: Principal,
        version_id: uuid.UUID,
        criterion_id: uuid.UUID,
    ) -> None:
        ensure_exam_manager(principal)
        version, _scheme = self._version_and_scheme(principal.tenant_id, version_id)
        self._writable(version)
        row = self._criterion_row(principal.tenant_id, version.id, criterion_id)
        detail = {
            "scheme_version_id": str(version.id),
            "question_id": row.question_id,
            "code": row.code,
            "marks": row.marks,
        }
        self.session.delete(row)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme_criteria.manually_removed",
            entity_type="marking_criterion",
            entity_id=criterion_id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail=detail,
        )
        self.session.commit()

    def revise(
        self, principal: Principal, version_id: uuid.UUID
    ) -> MarkSchemeVersion:
        """Carry an approved scheme into a new, unapproved version.

        Approved rows are immutable, so a correction to them is a new version:
        the copies start with no approval trail and the engine keeps refusing
        them until a person approves the copy against a blueprint.
        """

        ensure_exam_manager(principal)
        version, scheme = self._version_and_scheme(principal.tenant_id, version_id)
        if version.criteria_approved_at is None:
            raise AppError(
                ErrorCode.CONFLICT,
                "This scheme has no approved criteria to revise; edit it directly.",
            )
        rows = self.schemes.list_criteria(principal.tenant_id, version.id)
        latest = self.session.scalar(
            select(func.max(MarkSchemeVersion.version)).where(
                MarkSchemeVersion.mark_scheme_id == scheme.id
            )
        )
        number = int(latest or version.version) + 1
        digest = hashlib.sha256(
            f"{version.content_hash}:manual-revision:{number}".encode()
        ).hexdigest()
        revised = MarkSchemeVersion(
            tenant_id=principal.tenant_id,
            mark_scheme_id=scheme.id,
            version=number,
            status="DRAFT",
            source="REVISION",
            content_hash=digest,
        )
        self.session.add(revised)
        self.session.flush()
        self.session.add_all(
            [
                MarkingCriterion(
                    tenant_id=principal.tenant_id,
                    scheme_version_id=revised.id,
                    blueprint_version_id=row.blueprint_version_id,
                    question_id=row.question_id,
                    code=row.code,
                    marks=row.marks,
                    ordinal=row.ordinal,
                    description=row.description,
                    required_evidence=row.required_evidence,
                    dependencies=list(row.dependencies or []),
                    alternatives=list(row.alternatives or []),
                    award_conditions=row.award_conditions,
                    withhold_conditions=row.withhold_conditions,
                    source_ref=dict(row.source_ref or {}),
                    question_text=row.question_text,
                    expected_answer=row.expected_answer,
                    source_page=row.source_page,
                    source_quote=row.source_quote,
                )
                for row in rows
            ]
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme_version.revised",
            entity_type="mark_scheme_version",
            entity_id=revised.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "source_version_id": str(version.id),
                "version": number,
                "criteria": len(rows),
            },
        )
        self.session.commit()
        self.session.refresh(revised)
        return revised

    def _writable(self, version: MarkSchemeVersion) -> None:
        if version.status == "SUPERSEDED":
            raise AppError(
                ErrorCode.CONFLICT, "A superseded mark scheme cannot be changed."
            )
        if version.criteria_approved_at is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "These criteria are approved and cannot be edited. "
                "Create a new scheme version first.",
            )

    def _criterion_row(
        self,
        tenant_id: uuid.UUID,
        version_id: uuid.UUID,
        criterion_id: uuid.UUID,
    ) -> MarkingCriterion:
        row = self.session.scalar(
            select(MarkingCriterion).where(
                MarkingCriterion.tenant_id == tenant_id,
                MarkingCriterion.scheme_version_id == version_id,
                MarkingCriterion.id == criterion_id,
            )
        )
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Marking criterion not found.")
        return row

    # -- helpers ---------------------------------------------------------
    def _version_and_scheme(
        self, tenant_id: uuid.UUID, version_id: uuid.UUID
    ) -> tuple[MarkSchemeVersion, MarkScheme]:
        version = self.get_version(tenant_id, version_id)
        scheme = self.schemes.get_scheme(tenant_id, version.mark_scheme_id)
        if scheme is None:
            raise AppError(ErrorCode.NOT_FOUND, "Mark scheme not found.")
        return version, scheme

    def _approved_blueprint(
        self,
        tenant_id: uuid.UUID,
        exam_id: uuid.UUID,
        blueprint_version_id: uuid.UUID,
    ) -> ExamBlueprintVersion:
        blueprint = self.blueprints.get(tenant_id, blueprint_version_id)
        if blueprint is None or blueprint.exam_id != exam_id:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "Blueprint version not found for this exam.",
            )
        if blueprint.status != "APPROVED":
            raise AppError(
                ErrorCode.BLUEPRINT_NOT_APPROVED,
                "Criteria are reviewed against an approved blueprint. Approve "
                f"blueprint version {blueprint.version} first, then extract.",
                details={"blueprint_status": blueprint.status},
            )
        return blueprint

    def _scheme_document(self, tenant_id: uuid.UUID, scheme: MarkScheme):
        if scheme.document_id is None:
            raise AppError(
                ErrorCode.CONFLICT,
                "This mark-scheme version has no uploaded document to transcribe.",
            )
        document = self.documents.get(tenant_id, scheme.document_id)
        if document.kind != "MARK_SCHEME" or document.status != "PROCESSED":
            raise AppError(
                ErrorCode.CONFLICT,
                "The mark-scheme document is not processed and available for "
                "transcription.",
            )
        return document

    def _inputs(self, document, blueprint: ExamBlueprintVersion) -> list[LLMInput]:
        expected = blueprint_leaves(blueprint.structure)
        listing = "\n".join(
            f"- {question_id}: {marks} mark(s)"
            for question_id, marks in expected.items()
        )
        inputs: list[LLMInput] = [
            LLMInput.text_part(
                "Blueprint leaves for this paper "
                f"({len(expected)} questions, {sum(expected.values())} marks):\n"
                f"{listing}\n\n"
                "Transcribe the printed mark points for exactly these question "
                "ids. Their marks must add up to the marks listed."
            )
        ]
        for index, (page, image) in enumerate(
            self.documents.page_images(blueprint.tenant_id, document.id)
        ):
            if index < MAX_IMAGE_PAGES:
                inputs.append(
                    LLMInput.text_part(f"\n--- scheme page {page.page_index} ---\n")
                )
                inputs.append(LLMInput.image_part(image, "image/png"))
            else:
                inputs.append(
                    LLMInput.text_part(
                        f"\n--- scheme page {page.page_index} (text only) ---\n"
                        f"{page.text_excerpt or ''}"
                    )
                )
        return inputs

    def _parse(self, result: ProviderCallResult) -> dict[str, Any]:
        try:
            payload = parse_json_text(result.response.text)
        except ValueError as error:
            raise AppError(
                ErrorCode.EXTRACTION_INVALID,
                "The model's criteria transcription was not valid JSON.",
                details={"usage_id": str(result.usage_id)},
            ) from error
        if not isinstance(payload, dict):
            raise AppError(
                ErrorCode.EXTRACTION_INVALID,
                "The model's criteria transcription was not a JSON object.",
                details={"usage_id": str(result.usage_id)},
            )
        return payload

    def _replace_rows(
        self,
        principal: Principal,
        version: MarkSchemeVersion,
        blueprint: ExamBlueprintVersion,
        payload: dict[str, Any],
    ) -> list[MarkingCriterion]:
        """Store the reviewed transcription as this version's only rows.

        Replacing the set is what keeps the stored rules equal to the rules a
        person last approved.  The approval trail is cleared in the same
        transaction: rows that changed are not the rows that were approved, and
        the engine's digest check must see that rather than a stale timestamp.
        """

        self.session.execute(
            delete(MarkingCriterion).where(
                MarkingCriterion.tenant_id == principal.tenant_id,
                MarkingCriterion.scheme_version_id == version.id,
            )
        )
        created = [
            MarkingCriterion(
                tenant_id=principal.tenant_id,
                scheme_version_id=version.id,
                blueprint_version_id=blueprint.id,
                question_id=row["question_id"],
                code=row["code"],
                marks=row["marks"],
                ordinal=row["ordinal"],
                description=row["description"] or row["code"],
                # The printed answer is part of the reviewed rules, not
                # decoration: the digest covers it and comparison marking reads
                # it, so it must be stored with the row it belongs to.
                expected_answer=row["expected_answer"],
                required_evidence=row["required_evidence"],
                dependencies=row["dependencies"],
                alternatives=row["alternatives"],
                award_conditions=row["award_conditions"],
                withhold_conditions=row["withhold_conditions"],
                source_ref=row["source_ref"],
                source_page=row["source_page"],
                source_quote=row["source_quote"],
            )
            for row in iter_criteria(payload)
        ]
        version.criteria_blueprint_version_id = None
        version.criteria_blueprint_hash = None
        version.criteria_rules_hash = None
        version.criteria_approved_at = None
        version.criteria_approved_by = None
        version.criteria_approval_reason = None
        self.session.add_all(created)
        self.session.flush()
        return created
