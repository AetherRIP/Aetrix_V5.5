"""Page-to-question mapping against an approved blueprint.

Text labels are tried first because they are deterministic and cheap.  When a
page has no usable text label, the model may map it from the rendered image; its
answer is validated against the approved identifier set.  Every unmapped page
gets a typed reason.  A model failure never silently produces an empty map.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..db.models import Document, DocumentPage, PageQuestionMapping
from ..db.repositories import (
    BlueprintRepository,
    DocumentRepository,
    PageMappingRepository,
)
from ..providers.json import parse_json_text
from ..schemas.blueprint import BlueprintStructure
from ..services.provider_calls import ProviderCallService
from ..storage.base import Storage, StorageError
from .service import DocumentService
from .types import MappingStatus, reason


@dataclass(frozen=True, slots=True)
class MappingResult:
    document: Document
    blueprint_version_id: uuid.UUID
    status: str
    reasons: list[dict[str, str]]
    mappings: list[PageQuestionMapping]


def _identifier_pattern(identifier: str) -> str:
    text = identifier.strip()
    # "1a" also appears as "1 (a)" or "1(a)"; keep the base identifier exact
    # and allow the common printed variants.
    match = re.fullmatch(r"(\d+)\s*([A-Za-z])", text)
    if match:
        return rf"{re.escape(match.group(1))}\s*[\(\.]?\s*{re.escape(match.group(2))}\s*[\)]?"
    return re.escape(text)


def _all_question_ids(structure: BlueprintStructure) -> list[str]:
    identifiers: list[str] = []
    for question in structure.questions:
        identifiers.append(question.question_id)
        identifiers.extend(sub.question_id for sub in question.subquestions)
    return identifiers


def question_ids_on_page(text: str, structure: BlueprintStructure) -> list[str]:
    if not text.strip():
        return []
    found: list[str] = []
    for identifier in _all_question_ids(structure):
        pattern = re.compile(
            rf"(?:^|[\n\r])\s*(?:q(?:uestion)?\s*)?(?:{_identifier_pattern(identifier)})"
            r"(?![0-9A-Za-z])",
            re.IGNORECASE | re.MULTILINE,
        )
        if pattern.search(text):
            found.append(identifier)
        else:
            # A label such as "Question 1" can precede the number on its own
            # line; the same expression covers it.  Accept a bold-fenced table
            # cell "Q1" too.
            if re.search(
                rf"\bq\s*{_identifier_pattern(identifier)}(?![0-9A-Za-z])",
                text,
                re.IGNORECASE,
            ):
                found.append(identifier)
    return found


def _mapping_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "question_ids": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["question_ids", "confidence"],
    }


class PageQuestionMapper:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        storage: Storage,
        *,
        provider_calls: ProviderCallService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.documents = DocumentRepository(session)
        self.blueprints = BlueprintRepository(session)
        self.mappings = PageMappingRepository(session)
        self.document_service = DocumentService(session, settings, storage)
        self.provider_calls = provider_calls
        self.audit = AuditService(session)

    def _load(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> tuple[Document, list[DocumentPage]]:
        document = self.documents.get(tenant_id, document_id)
        if document is None:
            raise AppError(ErrorCode.NOT_FOUND, "Document not found.")
        pages = self.documents.pages(tenant_id, document_id)
        if not pages:
            raise AppError(ErrorCode.CONFLICT, "The document has no rendered pages.")
        return document, pages

    def _model_map(
        self,
        *,
        tenant_id: uuid.UUID,
        page: DocumentPage,
        structure: BlueprintStructure,
        page_image: bytes,
    ) -> tuple[list[str], float, dict[str, Any]]:
        if self.provider_calls is None:
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "No provider is available for image-based page mapping.",
            )
        identifiers = _all_question_ids(structure)
        prompt = (
            "Approved question identifiers: "
            + ", ".join(identifiers)
            + "\nMap this page. Return JSON only."
        )
        from ..providers.base import LLMInput

        result = self.provider_calls.call(
            tenant_id=tenant_id,
            purpose="PAGE_MAPPING",
            prompt_id="page_question_mapping",
            inputs=(
                LLMInput.text_part(prompt),
                LLMInput.image_part(page_image, "image/png"),
            ),
            response_schema=_mapping_schema(),
            max_output_tokens=1024,
        )
        try:
            payload = parse_json_text(result.response.text)
        except ValueError as error:
            raise AppError(
                ErrorCode.EXTRACTION_INVALID,
                "The model's page mapping was not valid JSON.",
            ) from error
        if not isinstance(payload, dict):
            raise AppError(
                ErrorCode.EXTRACTION_INVALID, "The model's page mapping was not an object."
            )
        raw_ids = payload.get("question_ids")
        if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
            raise AppError(ErrorCode.EXTRACTION_INVALID, "The model did not return question_ids.")
        allowed = {item.casefold(): item for item in identifiers}
        chosen = [allowed[item.casefold()] for item in raw_ids if item.casefold() in allowed]
        confidence = payload.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        return (
            chosen,
            max(0.0, min(1.0, float(confidence))),
            {
                "provider_usage_id": str(result.usage_id),
                "prompt": f"{result.prompt.prompt_id}@v{result.prompt.version}",
            },
        )

    def map(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        blueprint_version_id: uuid.UUID,
    ) -> MappingResult:
        document, pages = self._load(tenant_id, document_id)
        blueprint = self.blueprints.get(tenant_id, blueprint_version_id)
        if blueprint is None or blueprint.exam_id != document.exam_id:
            raise AppError(ErrorCode.NOT_FOUND, "Blueprint version not found for this document.")
        if blueprint.status != "APPROVED":
            raise AppError(
                ErrorCode.MAPPING_REQUIRES_APPROVED_BLUEPRINT,
                "Page mapping requires an approved blueprint version.",
            )
        try:
            structure = BlueprintStructure.model_validate(blueprint.structure)
        except ValidationError as error:
            raise AppError(
                ErrorCode.CONFLICT,
                "The approved blueprint is not internally valid.",
            ) from error

        rows: list[dict[str, Any]] = []
        reasons: list[dict[str, str]] = []
        mapped_pages = 0
        for page in pages:
            found = question_ids_on_page(page.text_excerpt or "", structure)
            method = "TEXT_MATCH"
            confidence = 0.9 if found else 0.0
            source_ref: dict[str, Any] = {"page_index": page.page_index}
            if not found and self.provider_calls is not None:
                try:
                    image = self.storage.read(page.storage_key)
                    found, confidence, source_ref = self._model_map(
                        tenant_id=tenant_id,
                        page=page,
                        structure=structure,
                        page_image=image,
                    )
                    method = "MODEL"
                except AppError as error:
                    if error.code not in {
                        ErrorCode.PROVIDER_UNAVAILABLE,
                        ErrorCode.EXTRACTION_INVALID,
                        ErrorCode.CONFIGURATION_ERROR,
                    }:
                        raise
                    reasons.append(
                        reason(
                            "MODEL_MAPPING_UNAVAILABLE",
                            f"Page {page.page_index} had no readable question label and the "
                            f"image mapper was unavailable: {error.message}",
                        )
                    )
                except StorageError as error:
                    raise AppError(
                        ErrorCode.SERVICE_NOT_READY,
                        f"Page {page.page_index} is missing from storage.",
                    ) from error
            if found:
                mapped_pages += 1
                for identifier in found:
                    rows.append(
                        {
                            "page_id": page.id,
                            "question_id": identifier,
                            "confidence": confidence,
                            "method": method,
                            "source_ref": source_ref,
                        }
                    )
            else:
                reasons.append(
                    reason(
                        "NO_QUESTION_MATCH",
                        f"Page {page.page_index} could not be mapped to a blueprint question.",
                    )
                )

        persisted = self.mappings.replace_for_document(
            tenant_id=tenant_id,
            document_id=document.id,
            blueprint_version_id=blueprint.id,
            mappings=rows,
        )
        if mapped_pages == len(pages):
            status = MappingStatus.MAPPED.value
        elif mapped_pages:
            status = MappingStatus.PARTIAL.value
        else:
            status = MappingStatus.UNVERIFIED.value
        document.mapping_status = status
        document.mapping_reasons = reasons
        self.audit.record(
            tenant_id=tenant_id,
            action="document.questions_mapped",
            entity_type="document",
            entity_id=document.id,
            actor_type="SYSTEM",
            detail={
                "blueprint_version_id": str(blueprint.id),
                "status": status,
                "mapped_pages": mapped_pages,
                "page_count": len(pages),
                "reasons": reasons,
            },
        )
        self.session.commit()
        return MappingResult(
            document=document,
            blueprint_version_id=blueprint.id,
            status=status,
            reasons=reasons,
            mappings=persisted,
        )
