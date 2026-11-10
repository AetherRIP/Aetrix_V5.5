"""Strict parsing of the marking model's response.

The model is an untrusted input.  A response that does not satisfy this contract
is a typed failure for that question — it never becomes a mark.  Parsing is
deliberately intolerant of missing reasoning: an award without a quote is not
evidence an examiner can check.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MARKING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question_id": {"type": "string"},
        "student_answer": {"type": ["string", "null"]},
        "awarded_marks": {"type": "integer", "minimum": 0},
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "description": {"type": "string"},
                    "marks": {"type": "integer", "minimum": 0},
                    "awarded": {"type": "boolean"},
                    "reason": {"type": ["string", "null"]},
                    "evidence": {"type": ["string", "null"]},
                },
                "required": ["code", "marks", "awarded"],
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "review_reasons": {"type": "array", "items": {"type": "string"}},
        "answer_check": {
            "type": ["object", "null"],
            "properties": {
                "student_expression": {"type": "string"},
                "expected_expression": {"type": "string"},
            },
        },
        "notes": {"type": ["string", "null"]},
    },
    "required": ["question_id", "awarded_marks", "components", "confidence"],
}


class MarkingResponseInvalid(RuntimeError):
    """The model's answer cannot be turned into a mark without inventing data."""


class MarkComponent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    marks: int = Field(ge=0, le=200)
    awarded: bool = False
    reason: str | None = Field(default=None, max_length=2000)
    evidence: str | None = Field(default=None, max_length=2000)

    @field_validator("code")
    @classmethod
    def _code_shape(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a component code cannot be blank")
        return value

    @field_validator("evidence")
    @classmethod
    def _award_needs_evidence(cls, value: str | None, info: Any) -> str | None:
        # Pydantic validates fields in declaration order, so ``awarded`` is
        # available here.  Evidence is not required for a mark that was not
        # given; it is required for one that was.
        awarded = info.data.get("awarded")
        if awarded and not (value or "").strip():
            raise ValueError("an awarded component needs quoted evidence")
        return value


class AnswerCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    student_expression: str = Field(min_length=1, max_length=200)
    expected_expression: str = Field(min_length=1, max_length=200)


class QuestionMark(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str = Field(min_length=1, max_length=40)
    student_answer: str | None = Field(default=None, max_length=4000)
    awarded_marks: int = Field(ge=0, le=200)
    components: list[MarkComponent] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    review_reasons: list[str] = Field(default_factory=list)
    answer_check: AnswerCheck | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @property
    def component_total(self) -> int | None:
        if not self.components:
            return None
        return sum(component.marks for component in self.components if component.awarded)


def _strip_fence(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_question_mark(text: str, *, question_id: str) -> QuestionMark:
    import json

    raw = _strip_fence(text)
    if not raw:
        raise MarkingResponseInvalid("The model returned an empty response.")
    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise MarkingResponseInvalid(
            f"The model response was not valid JSON: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise MarkingResponseInvalid("The model response was not a JSON object.")
    try:
        mark = QuestionMark.model_validate(payload)
    except ValidationError as error:
        raise MarkingResponseInvalid(
            "The model response did not satisfy the marking contract: "
            f"{error.error_count()} issue(s)."
        ) from error
    if mark.question_id.strip() != question_id:
        raise MarkingResponseInvalid(
            f"The model marked question {mark.question_id!r} while question "
            f"{question_id!r} was requested."
        )
    codes = [component.code for component in mark.components]
    if len(codes) != len(set(codes)):
        raise MarkingResponseInvalid("The model reused a component code within one question.")
    return mark
