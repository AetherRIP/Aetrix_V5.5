"""Contracts for ingestion, mapping, extraction and teacher overrides."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .blueprint import BlueprintRead


class DocumentPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    page_index: int
    width: int | None
    height: int | None
    quality_status: str
    quality_reasons: list[dict[str, Any]]
    ordering_reasons: list[dict[str, Any]]
    printed_page_number: int | None
    rotation_degrees: int
    duplicate_of_page_id: UUID | None
    text_excerpt: str | None
    checksum: str


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    submission_id: UUID | None
    exam_id: UUID | None
    kind: str
    original_filename: str
    mime_type: str
    size_bytes: int
    page_count: int
    status: str
    sha256: str
    validation_errors: list[dict[str, Any]]
    ordering_status: str
    ordering_reasons: list[dict[str, Any]]
    mapping_status: str
    mapping_reasons: list[dict[str, Any]]
    error_code: str | None
    created_at: datetime
    pages: list[DocumentPageRead] = Field(default_factory=list)


class SchemeVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mark_scheme_id: UUID
    version: int
    status: str
    source: str
    content_hash: str
    approved_at: datetime | None
    created_at: datetime


class SchemeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exam_id: UUID
    document_id: UUID | None
    title: str
    created_at: datetime


class SchemeUploadRead(BaseModel):
    scheme: SchemeRead
    version: SchemeVersionRead


class SchemeApprove(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class PageMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    page_id: UUID
    blueprint_version_id: UUID
    question_id: str
    confidence: float
    method: str
    source_ref: dict[str, Any]


class DocumentMappingRequest(BaseModel):
    blueprint_version_id: UUID


class DocumentMappingRead(BaseModel):
    document_id: UUID
    blueprint_version_id: UUID
    status: str
    reasons: list[dict[str, Any]]
    mappings: list[PageMappingRead]


class BlueprintExtractionRequest(BaseModel):
    scheme_version_id: UUID
    prompt_version: int | None = Field(default=None, ge=1)


class ProviderCallSummary(BaseModel):
    usage_id: UUID
    provider: str
    model: str
    prompt_id: str
    prompt_version: int
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    cost_usd: float | None
    latency_ms: int | None


class BlueprintExtractionRead(BaseModel):
    blueprint: BlueprintRead
    provider: ProviderCallSummary


class BlueprintOverrideOperation(BaseModel):
    op: Literal[
        "set_question_marks",
        "exclude_question",
        "include_question",
        "add_note",
        "set_special_instruction",
        "set_criteria_refs",
    ]
    question_id: str | None = Field(default=None, max_length=40)
    max_marks: int | None = Field(default=None, ge=0, le=200)
    reason: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=1000)
    refs: list[str] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _operation_fields(self) -> BlueprintOverrideOperation:
        if (
            self.op
            in {
                "set_question_marks",
                "exclude_question",
                "include_question",
                "set_special_instruction",
                "set_criteria_refs",
            }
            and not (self.question_id or "").strip()
        ):
            raise ValueError(f"{self.op} requires question_id")
        if self.op == "set_question_marks" and self.max_marks is None:
            raise ValueError("set_question_marks requires max_marks")
        if self.op == "exclude_question" and not (self.reason or "").strip():
            raise ValueError("exclude_question requires reason")
        if self.op == "add_note" and not (self.text or "").strip():
            raise ValueError("add_note requires text")
        if self.op == "set_special_instruction" and not (self.text or "").strip():
            raise ValueError("set_special_instruction requires text")
        if self.op == "set_criteria_refs" and self.refs is None:
            raise ValueError("set_criteria_refs requires refs")
        return self


class BlueprintOverrideCreate(BaseModel):
    base_version_id: UUID
    rationale: str = Field(min_length=1, max_length=2000)
    operations: list[BlueprintOverrideOperation] = Field(min_length=1, max_length=100)


class BlueprintOverrideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exam_id: UUID
    base_version_id: UUID
    result_version_id: UUID
    author_id: UUID | None
    rationale: str
    patch: list[dict[str, Any]]
    created_at: datetime
    base_version: BlueprintRead | None = None
    result_version: BlueprintRead | None = None
