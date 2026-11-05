"""Canonical paper blueprint.

The blueprint is the marking contract.  Validation here is intentionally
stricter than "does it parse": identifiers must be unique, sub-question marks
must sum to their parent, and the declared total must equal the sum of the
non-excluded questions.  A blueprint that fails these checks cannot become an
approved version, so the engine never marks against an internally inconsistent
paper.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BlueprintSubQuestion(BaseModel):
    question_id: str = Field(min_length=1, max_length=40)
    label: str | None = Field(default=None, max_length=120)
    max_marks: int = Field(ge=0, le=200)
    answer_type: str | None = Field(default=None, max_length=60)
    excluded: bool = False
    exclusion_reason: str | None = Field(default=None, max_length=500)
    special_instructions: list[str] = Field(default_factory=list)
    criteria_refs: list[str] = Field(default_factory=list)

    @field_validator("question_id")
    @classmethod
    def _identifier_shape(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question_id cannot be blank")
        return value

    @model_validator(mode="after")
    def _exclusion_needs_reason(self) -> BlueprintSubQuestion:
        if self.excluded and not (self.exclusion_reason or "").strip():
            raise ValueError("an excluded sub-question needs an exclusion_reason")
        return self


class BlueprintQuestion(BaseModel):
    question_id: str = Field(min_length=1, max_length=40)
    label: str | None = Field(default=None, max_length=120)
    max_marks: int = Field(ge=0, le=200)
    answer_type: str | None = Field(default=None, max_length=60)
    excluded: bool = False
    exclusion_reason: str | None = Field(default=None, max_length=500)
    subquestions: list[BlueprintSubQuestion] = Field(default_factory=list)
    special_instructions: list[str] = Field(default_factory=list)
    criteria_refs: list[str] = Field(default_factory=list)

    @field_validator("question_id")
    @classmethod
    def _identifier_shape(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question_id cannot be blank")
        return value

    @model_validator(mode="after")
    def _exclusion_and_subquestion_consistency(self) -> BlueprintQuestion:
        if self.excluded and not (self.exclusion_reason or "").strip():
            raise ValueError("an excluded question needs an exclusion_reason")
        if self.subquestions:
            included = sum(sub.max_marks for sub in self.subquestions if not sub.excluded)
            if not self.excluded and included != self.max_marks:
                raise ValueError(
                    f"question {self.question_id}: sub-question marks ({included}) "
                    f"do not sum to max_marks ({self.max_marks})"
                )
        return self


class BlueprintStructure(BaseModel):
    paper_code: str | None = Field(default=None, max_length=80)
    questions: list[BlueprintQuestion] = Field(min_length=1)
    total_marks: int = Field(ge=0, le=1000)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _identifiers_and_total(self) -> BlueprintStructure:
        seen: set[str] = set()

        def register(identifier: str) -> None:
            normalized = identifier.strip().casefold()
            if normalized in seen:
                raise ValueError(f"duplicate question identifier: {identifier}")
            seen.add(normalized)

        for question in self.questions:
            register(question.question_id)
            for sub in question.subquestions:
                register(sub.question_id)

        included = sum(q.max_marks for q in self.questions if not q.excluded)
        if included != self.total_marks:
            raise ValueError(
                f"declared total_marks ({self.total_marks}) does not equal the sum of "
                f"included question marks ({included})"
            )
        if not any(not q.excluded for q in self.questions):
            raise ValueError("a blueprint needs at least one non-excluded question")
        return self

    @property
    def scoreable_question_ids(self) -> list[str]:
        return [q.question_id for q in self.questions if not q.excluded]


class BlueprintPut(BaseModel):
    structure: BlueprintStructure
    approve: bool = False
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _approval_needs_reason(self) -> BlueprintPut:
        if self.approve and not (self.reason or "").strip():
            raise ValueError("approving a blueprint requires a reason")
        return self


class BlueprintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exam_id: UUID
    version: int
    status: str
    structure: BlueprintStructure
    total_marks: int
    content_hash: str
    source: str
    extraction_metadata: dict
    approved_at: datetime | None
    approval_reason: str | None
    created_at: datetime
