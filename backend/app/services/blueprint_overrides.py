"""Teacher overrides create new draft versions; approved versions stay immutable."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal, ensure_exam_manager
from ..db.models import BlueprintOverride, ExamBlueprintVersion
from ..db.repositories import BlueprintOverrideRepository, BlueprintRepository, ExamRepository
from ..schemas.blueprint import BlueprintStructure
from ..schemas.documents import BlueprintOverrideCreate, BlueprintOverrideOperation
from .exams import structure_hash


@dataclass(frozen=True, slots=True)
class OverrideResult:
    override: BlueprintOverride
    base: ExamBlueprintVersion
    result: ExamBlueprintVersion


def _find_question(
    payload: dict[str, Any], question_id: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    for question in payload.get("questions", []):
        if str(question.get("question_id", "")).casefold() == question_id.casefold():
            return question, None
        for sub in question.get("subquestions", []):
            if str(sub.get("question_id", "")).casefold() == question_id.casefold():
                return sub, question
    raise AppError(ErrorCode.NOT_FOUND, f"Question {question_id!r} is not in this blueprint.")


def apply_operations(
    structure: BlueprintStructure, operations: list[BlueprintOverrideOperation]
) -> BlueprintStructure:
    payload = copy.deepcopy(structure.model_dump(mode="json"))
    for operation in operations:
        if operation.op == "add_note":
            payload.setdefault("notes", []).append((operation.text or "").strip())
            continue
        question, parent = _find_question(payload, (operation.question_id or "").strip())
        if operation.op == "set_question_marks":
            if question.get("subquestions"):
                raise AppError(
                    ErrorCode.CONFLICT,
                    "Marks for a question with sub-questions must be set on the "
                    "sub-questions, not on the parent.",
                )
            question["max_marks"] = operation.max_marks
            if parent is not None:
                parent["max_marks"] = sum(
                    int(sub.get("max_marks", 0))
                    for sub in parent.get("subquestions", [])
                    if not sub.get("excluded")
                )
        elif operation.op == "exclude_question":
            if parent is not None:
                raise AppError(
                    ErrorCode.CONFLICT, "Exclude the parent question, not a sub-question."
                )
            question["excluded"] = True
            question["exclusion_reason"] = (operation.reason or "").strip()
        elif operation.op == "include_question":
            if parent is not None:
                raise AppError(
                    ErrorCode.CONFLICT, "Include the parent question, not a sub-question."
                )
            question["excluded"] = False
            question["exclusion_reason"] = None
        elif operation.op == "set_special_instruction":
            question["special_instructions"] = [(operation.text or "").strip()]
        elif operation.op == "set_criteria_refs":
            question["criteria_refs"] = list(operation.refs or [])
        else:  # pragma: no cover - the literal type closes this set
            raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown override operation.")

    payload["total_marks"] = sum(
        int(question.get("max_marks", 0))
        for question in payload.get("questions", [])
        if not question.get("excluded")
    )
    try:
        return BlueprintStructure.model_validate(payload)
    except ValidationError as error:
        problems = [
            {"location": list(item.get("loc", ())), "message": str(item.get("msg", ""))}
            for item in error.errors()
        ]
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "The override would make the blueprint invalid; no version was created.",
            details={"problems": problems},
        ) from error


class BlueprintOverrideService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.exams = ExamRepository(session)
        self.blueprints = BlueprintRepository(session)
        self.overrides = BlueprintOverrideRepository(session)
        self.audit = AuditService(session)

    def create(
        self, principal: Principal, exam_id: uuid.UUID, payload: BlueprintOverrideCreate
    ) -> OverrideResult:
        ensure_exam_manager(principal)
        if self.exams.get(principal.tenant_id, exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        base = self.blueprints.get(principal.tenant_id, payload.base_version_id)
        if base is None or base.exam_id != exam_id:
            raise AppError(ErrorCode.NOT_FOUND, "Blueprint version not found for this exam.")
        if base.status == "SUPERSEDED":
            raise AppError(
                ErrorCode.CONFLICT,
                "A superseded blueprint cannot be the base for a new override.",
            )
        try:
            structure = BlueprintStructure.model_validate(base.structure)
        except ValidationError as error:
            raise AppError(
                ErrorCode.CONFLICT,
                "The base blueprint is not internally valid.",
            ) from error
        updated = apply_operations(structure, payload.operations)
        digest = structure_hash(updated)
        result = self.blueprints.create_version(
            tenant_id=principal.tenant_id,
            exam_id=exam_id,
            structure=updated.model_dump(mode="json"),
            total_marks=updated.total_marks,
            content_hash=digest,
            created_by=principal.user_id,
            status="DRAFT",
            source="OVERRIDE",
            source_document_id=base.source_document_id,
            extraction_metadata={
                "override_of": str(base.id),
                "rationale": payload.rationale,
                "created_at": utcnow().isoformat(),
            },
        )
        override = self.overrides.create(
            tenant_id=principal.tenant_id,
            exam_id=exam_id,
            base_version_id=base.id,
            result_version_id=result.id,
            author_id=principal.user_id,
            rationale=payload.rationale,
            patch=[operation.model_dump(mode="json") for operation in payload.operations],
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="blueprint.override_created",
            entity_type="exam_blueprint_version",
            entity_id=result.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "base_version_id": str(base.id),
                "result_version_id": str(result.id),
                "override_id": str(override.id),
                "rationale": payload.rationale,
                "operations": len(payload.operations),
            },
        )
        self.session.commit()
        return OverrideResult(override=override, base=base, result=result)

    def list(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> list[BlueprintOverride]:
        return self.overrides.list_for_exam(tenant_id, exam_id)
