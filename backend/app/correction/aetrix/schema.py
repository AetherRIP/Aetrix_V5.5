"""Strict parsing of the marking model's response.

The model is an untrusted input.  A response that does not satisfy this contract
is a typed failure for that question — it never becomes a mark.  Parsing is
deliberately intolerant of missing reasoning: an award without a quote is not
evidence an examiner can check.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...providers.json import parse_json_text

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


#: Supporting text is clipped, never rejected.  A model that writes a long
#: quotation, reason or note has still marked the question; discarding that mark
#: over a size limit would turn a real decision into an unmarked question.  The
#: unclipped reply is retained in ``raw_response``, so nothing is lost.
MAX_DESCRIPTION_CHARS = 500
MAX_REASON_CHARS = 2000
MAX_EVIDENCE_CHARS = 2000
MAX_NOTES_CHARS = 2000
MAX_ANSWER_CHARS = 4000
MAX_REVIEW_REASONS = 20
MAX_REVIEW_REASON_CHARS = 500

#: An award at or above this is a parsing failure, not a mark: no question in an
#: examination paper is worth more, and the blueprint maximum is enforced later.
AWARD_RESPONSE_CEILING = 200

_TEXT_LIMITS = {
    "description": MAX_DESCRIPTION_CHARS,
    "reason": MAX_REASON_CHARS,
    "evidence": MAX_EVIDENCE_CHARS,
}


def _clip(value: Any, limit: int) -> Any:
    """Keep a supporting string within its documented limit."""

    if value is None or not isinstance(value, str):
        return value
    return value if len(value) <= limit else value[:limit]


class MarkComponent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=20)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    marks: int = Field(ge=0, le=AWARD_RESPONSE_CEILING)
    awarded: bool = False
    reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)
    evidence: str | None = Field(default=None, max_length=MAX_EVIDENCE_CHARS)

    @field_validator("code")
    @classmethod
    def _code_shape(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a component code cannot be blank")
        return value

    @field_validator("description", "reason", "evidence", mode="before")
    @classmethod
    def _clip_supporting_text(cls, value: Any, info: Any) -> Any:
        return _clip(value, _TEXT_LIMITS[str(info.field_name)])

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
    student_answer: str | None = Field(default=None, max_length=MAX_ANSWER_CHARS)
    awarded_marks: int = Field(ge=0, le=AWARD_RESPONSE_CEILING)
    components: list[MarkComponent] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    review_reasons: list[str] = Field(default_factory=list)
    answer_check: AnswerCheck | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTES_CHARS)

    @field_validator("student_answer", "notes", mode="before")
    @classmethod
    def _clip_answer_text(cls, value: Any, info: Any) -> Any:
        limit = MAX_ANSWER_CHARS if str(info.field_name) == "student_answer" else MAX_NOTES_CHARS
        return _clip(value, limit)

    @field_validator("review_reasons", mode="before")
    @classmethod
    def _bound_review_reasons(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        reasons = [_clip(reason, MAX_REVIEW_REASON_CHARS) for reason in value]
        return [reason for reason in reasons if isinstance(reason, str)][:MAX_REVIEW_REASONS]

    @field_validator("answer_check", mode="before")
    @classmethod
    def _optional_answer_check(cls, value: Any) -> Any:
        """The mathematical check is advisory; it must not void the award.

        A check this build cannot read (an empty side, an expression beyond the
        length limit) is dropped.  The marking decision is still fully subject
        to the integrity checks and is recorded with no mathematical verdict,
        which is honest: an unreadable check proved nothing.
        """

        if value is None:
            return None
        if isinstance(value, dict):
            # A blank side is not a check: comparing nothing to something can
            # only produce "unknown", which would send a good mark to review for
            # a field the model filled in badly.
            cleaned = dict(value)
            for key in ("student_expression", "expected_expression"):
                raw = cleaned.get(key)
                if isinstance(raw, str):
                    cleaned[key] = raw.strip()
            if not cleaned.get("student_expression") or not cleaned.get(
                "expected_expression"
            ):
                return None
            value = cleaned
        try:
            return AnswerCheck.model_validate(value)
        except ValidationError:
            return None

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


def _disambiguate_component_codes(components: list[MarkComponent]) -> None:
    """Make repeated component codes unique instead of discarding the answer.

    A scheme genuinely reuses a label — two ``M1`` stages in one question are
    ordinary — and refusing the response threw away an answer that could be
    marked.  Each repeat is renamed deterministically (``M1``, ``M1-2``) so the
    components, their awards and their evidence are kept exactly as stated;
    only the label that collided changes.
    """

    seen: dict[str, int] = {}
    for component in components:
        base = component.code
        seen[base] = seen.get(base, 0) + 1
        if seen[base] == 1:
            continue
        suffix = f"-{seen[base]}"
        component.code = f"{base[: 20 - len(suffix)]}{suffix}"


def parse_question_mark(text: str, *, question_id: str) -> QuestionMark:
    import json  # noqa: F401 - re-exported for callers that assemble replies

    raw = _strip_fence(text)
    if not raw:
        raise MarkingResponseInvalid("The model returned an empty response.")
    # A reply wrapped in prose or a fence is still a reply: the provider helper
    # extracts the balanced JSON object, and the contract below validates its
    # shape.  This does not repair malformed JSON and does not accept a partial
    # object.
    try:
        payload = parse_json_text(raw)
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
    _disambiguate_component_codes(mark.components)
    return mark
