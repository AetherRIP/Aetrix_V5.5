"""Extract a draft blueprint from an uploaded mark scheme.

The result always goes through ``BlueprintService.create_extracted_draft``:
status ``DRAFT``, a content hash, provenance and an audit event.  There is no
code path from extraction to ``APPROVED``; a teacher must use the existing
save-then-approve gate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.security import Principal, ensure_exam_manager
from ..db.models import ExamBlueprintVersion
from ..db.repositories import MarkSchemeRepository
from ..prompts.registry import PromptRegistry
from ..providers.base import LLMInput
from ..providers.json import parse_json_text
from ..schemas.blueprint import BlueprintStructure
from ..services.exams import BlueprintService
from ..services.provider_calls import ProviderCallResult, ProviderCallService
from ..storage.base import Storage
from .service import DocumentService

#: How many scheme pages are sent as images.  A 21-page scanned scheme is
#: comfortably inside this, and the provider accepts far more image input.
MAX_IMAGE_PAGES = 24


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    blueprint: ExamBlueprintVersion
    provider: ProviderCallResult


def blueprint_response_schema() -> dict[str, Any]:
    """A small OpenAPI-subset schema accepted by Gemini's responseSchema field."""
    subquestion = {
        "type": "object",
        "properties": {
            "question_id": {"type": "string"},
            "label": {"type": "string"},
            "max_marks": {"type": "integer"},
            "answer_type": {"type": "string"},
            "excluded": {"type": "boolean"},
            "exclusion_reason": {"type": "string"},
            "special_instructions": {"type": "array", "items": {"type": "string"}},
            "criteria_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question_id", "max_marks"],
    }
    question = {
        "type": "object",
        "properties": {
            "question_id": {"type": "string"},
            "label": {"type": "string"},
            "max_marks": {"type": "integer"},
            "answer_type": {"type": "string"},
            "excluded": {"type": "boolean"},
            "exclusion_reason": {"type": "string"},
            "subquestions": {"type": "array", "items": subquestion},
            "special_instructions": {"type": "array", "items": {"type": "string"}},
            "criteria_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question_id", "max_marks"],
    }
    return {
        "type": "object",
        "properties": {
            "paper_code": {"type": "string"},
            "questions": {"type": "array", "items": question},
            "total_marks": {"type": "integer"},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["questions", "total_marks"],
    }


def _repair_total(payload: dict[str, Any]) -> dict[str, Any]:
    """Derive ``total_marks`` from the extracted questions.

    The total is arithmetic over the questions, and a model's own sum drifts on
    long scanned schemes (61 vs 63, then 83 vs 91 on the same paper).  Trusting
    that number would reject usable extractions; deriving it keeps the strict
    schema check intact and records what the model declared, so a reviewer can
    see the correction on the draft.
    """
    questions = payload.get("questions")
    if not isinstance(questions, list):
        return payload
    total = 0
    for question in questions:
        if not isinstance(question, dict) or question.get("excluded") is True:
            continue
        marks = question.get("max_marks")
        if not isinstance(marks, int) or isinstance(marks, bool):
            return payload
        total += marks
    declared = payload.get("total_marks")
    if declared == total:
        return payload
    notes = payload.get("notes")
    notes = list(notes) if isinstance(notes, list) else []
    notes.append(
        f"The model declared total_marks={declared}, but its extracted questions "
        f"sum to {total}; the total was derived from the questions."
    )
    return {**payload, "total_marks": total, "notes": notes}


class BlueprintExtractionService:
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
        self.documents = DocumentService(session, settings, storage)

    def extract(
        self,
        principal: Principal,
        exam_id: uuid.UUID,
        scheme_version_id: uuid.UUID,
        *,
        prompt_version: int | None = None,
    ) -> ExtractionResult:
        ensure_exam_manager(principal)
        version = self.schemes.get_version(principal.tenant_id, scheme_version_id)
        if version is None:
            raise AppError(ErrorCode.NOT_FOUND, "Mark-scheme version not found.")
        scheme = self.schemes.get_scheme(principal.tenant_id, version.mark_scheme_id)
        if scheme is None or scheme.exam_id != exam_id:
            raise AppError(ErrorCode.NOT_FOUND, "Mark-scheme version not found for this exam.")
        if version.status == "SUPERSEDED":
            raise AppError(ErrorCode.CONFLICT, "A superseded mark scheme cannot be extracted.")
        if scheme.document_id is None:
            raise AppError(
                ErrorCode.CONFLICT,
                "This mark-scheme version has no uploaded document to extract from.",
            )
        document = self.documents.get(principal.tenant_id, scheme.document_id)
        if document.kind != "MARK_SCHEME" or document.status != "PROCESSED":
            raise AppError(
                ErrorCode.CONFLICT,
                "The mark-scheme document is not processed and available for extraction.",
            )
        images = self.documents.page_images(principal.tenant_id, document.id)
        inputs: list[LLMInput] = []
        for index, (page, image) in enumerate(images):
            # A scanned scheme has no text layer, so a page sent as text alone is
            # invisible to the model.  Every page therefore goes in as an image
            # up to the cap; a scheme longer than the cap is still extraction
            # input for its later pages, but those pages are stated as text.
            if index < MAX_IMAGE_PAGES:
                inputs.append(LLMInput.text_part(f"\n--- page {page.page_index} ---\n"))
                inputs.append(LLMInput.image_part(image, "image/png"))
            else:
                inputs.append(
                    LLMInput.text_part(
                        f"\n--- page {page.page_index} (text only) ---\n{page.text_excerpt or ''}"
                    )
                )
        result = self.provider_calls.call(
            tenant_id=principal.tenant_id,
            purpose="BLUEPRINT_EXTRACTION",
            prompt_id="blueprint_extraction",
            inputs=tuple(inputs),
            prompt_version=prompt_version,
            response_schema=blueprint_response_schema(),
            max_output_tokens=16384,
        )
        try:
            payload = parse_json_text(result.response.text)
        except ValueError as error:
            raise AppError(
                ErrorCode.EXTRACTION_INVALID,
                "The model's blueprint extraction was not valid JSON.",
                details={"usage_id": str(result.usage_id)},
            ) from error
        if not isinstance(payload, dict):
            raise AppError(
                ErrorCode.EXTRACTION_INVALID,
                "The model's blueprint extraction was not a JSON object.",
                details={"usage_id": str(result.usage_id)},
            )
        payload = _repair_total(payload)
        try:
            structure = BlueprintStructure.model_validate(payload)
        except ValidationError as error:
            problems = [
                {"location": list(item.get("loc", ())), "message": str(item.get("msg", ""))}
                for item in error.errors()
            ]
            raise AppError(
                ErrorCode.EXTRACTION_INVALID,
                "The extracted blueprint did not satisfy the canonical structure.",
                details={"usage_id": str(result.usage_id), "problems": problems},
            ) from error

        blueprint = BlueprintService(self.session).create_extracted_draft(
            principal,
            exam_id,
            structure,
            source_document_id=document.id,
            extraction_metadata={
                "provider": result.response.model,
                "prompt_id": result.prompt.prompt_id,
                "prompt_version": result.prompt.version,
                "prompt_hash": result.prompt.content_hash,
                "usage_id": str(result.usage_id),
                "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
            },
        )
        return ExtractionResult(blueprint=blueprint, provider=result)
