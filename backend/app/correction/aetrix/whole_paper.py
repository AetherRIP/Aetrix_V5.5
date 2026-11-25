"""Whole-paper marking: one request per paper, one strictly validated reply.

The per-question engine asks the model 39 times and pays 39 times.  Whole-paper
marking asks once and receives every leaf's decision together, which is why the
reply is treated far more strictly than a single answer:

* the reply must be one JSON object holding a ``questions`` array;
* every item is validated through the same ``QuestionMark`` contract as a
  single-question reply, so an award without quoted evidence is still a
  failure — for that question only;
* supporting text is bounded (evidence and reason 200 characters, description
  120, at most six components), because an unbounded quotation per component
  makes a 39-question paper cost more output tokens than the model can emit;
* a truncated reply is salvaged object by object rather than discarded, so the
  questions the model finished are kept and only the rest fall back.

Nothing here decides a mark.  A question absent from, or invalid in, the reply
is reported as missing and is left to the retained per-question engine.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ...providers.json import parse_json_text
from .schema import QuestionMark, _disambiguate_component_codes

#: The sequential marking modes.  ``PARALLEL`` sends the same per-question
#: request and is named in ``parallel.MODE_PARALLEL``.
MODE_PER_QUESTION = "PER_QUESTION"
MODE_WHOLE_PAPER = "WHOLE_PAPER"

#: The most leaves one paper request may carry.  A blueprint above this is
#: marked per question: a request that asks for more answers than this cannot
#: return them inside the model's output budget.
MAX_WHOLE_PAPER_LEAVES = 80

#: Bounds on the whole-paper reply.  These are enforced on the reply after it
#: arrives, not as JSON-Schema constraints: Google refuses a schema whose bounded
#: strings and nested arrays produce too many decoding states (HTTP 400
#: ``INVALID_ARGUMENT``: "the specified schema produces a constraint that has too
#: many states for serving").  A ``maxLength`` on every string of 39 questions is
#: such a constraint, so the bounds live in the prompt and in ``_bound_item`` and
#: the schema keeps only the shape the parser needs.
MAX_WHOLE_PAPER_COMPONENTS = 6
MAX_WHOLE_PAPER_EVIDENCE_CHARS = 200
MAX_WHOLE_PAPER_REASON_CHARS = 200
MAX_WHOLE_PAPER_DESCRIPTION_CHARS = 120

_COMPONENT_BOUNDS = {
    "description": MAX_WHOLE_PAPER_DESCRIPTION_CHARS,
    "reason": MAX_WHOLE_PAPER_REASON_CHARS,
    "evidence": MAX_WHOLE_PAPER_EVIDENCE_CHARS,
}


def _component_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "reference": {"type": ["string", "null"]},
            "description": {"type": ["string", "null"]},
            "marks": {"type": "integer", "minimum": 0},
            "awarded": {"type": "boolean"},
            "reason": {"type": ["string", "null"]},
            "evidence": {"type": ["string", "null"]},
            "page": {"type": ["integer", "null"]},
            "bbox": {"type": "array", "items": {"type": "number"}},
        },
        "required": ["code", "marks", "awarded"],
    }


def _question_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "question_id": {"type": "string"},
            "student_answer": {"type": ["string", "null"]},
            "awarded_marks": {"type": "integer", "minimum": 0},
            "components": {
                "type": "array",
                "items": _component_schema(),
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "review_reasons": {
                "type": "array",
                "items": {"type": "string"},
            },
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


#: The response contract sent to the provider.  It is the single-question
#: contract wrapped in an array.  Shape only: the length and item limits that
#: make a reply cheap are enforced on the received reply, because a schema that
#: tries to enforce them is rejected before any marking happens.
WHOLE_PAPER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": _question_schema(),
        }
    },
    "required": ["questions"],
}


class WholePaperResponseInvalid(RuntimeError):
    """The reply cannot be read as a whole-paper marking at all."""


@dataclass(slots=True)
class WholePaperParse:
    """What one paper reply yielded, and what it did not."""

    marks: dict[str, QuestionMark] = field(default_factory=dict)
    #: Question id -> why that item was rejected.  Only that question falls back.
    invalid: dict[str, str] = field(default_factory=dict)
    #: Requested questions the reply did not mark.
    missing: list[str] = field(default_factory=list)
    #: Ids the reply marked that this blueprint does not contain.
    unknown_ids: list[str] = field(default_factory=list)
    #: Ids the reply marked more than once; the first reading is kept.
    duplicates: list[str] = field(default_factory=list)
    #: How many supporting strings had to be clipped to the whole-paper bounds.
    clipped_supporting_text: int = 0
    #: False when the reply was truncated or partly unreadable.
    complete: bool = True
    #: Items that were not objects at all (counted, not attributed).
    malformed_items: int = 0

    def describe(self) -> dict[str, Any]:
        return {
            "parsed": len(self.marks),
            "invalid": len(self.invalid),
            "missing": len(self.missing),
            "unknown": len(self.unknown_ids),
            "duplicates": len(self.duplicates),
            "malformed": self.malformed_items,
            "clipped_supporting_text": self.clipped_supporting_text,
            "complete": self.complete,
        }


def detect_truncation(finish_reason: str | None) -> bool:
    """Whether the provider stopped because it ran out of output tokens.

    A truncated reply is not an error the provider retries: the same prompt with
    the same cap would stop at the same place.  The caller salvages what the
    model finished and asks the per-question engine for the rest.
    """

    # Providers spell the same stop differently (``MAX_TOKENS``, ``max_tokens``),
    # so the comparison ignores separators and case.
    normalised = "".join(
        char for char in (finish_reason or "").upper() if char.isalnum()
    )
    return normalised == "MAXTOKENS"


def paper_sha256(text: str | None) -> str | None:
    """A digest of the received body, so a stored slice can name its source."""

    if text is None:
        return None
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _balanced_objects(text: str) -> list[str]:
    """Every outermost brace-balanced object in ``text``.

    A truncated array has no balanced root, so the scan resumes one character in
    and finds each complete item object.  Braces inside strings are ignored: a
    quoted answer must not be mistaken for structure.
    """

    found: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        start = text.find("{", index)
        if start < 0:
            break
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for position in range(start, length):
            char = text[position]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = position
                    break
        if end < 0:
            index = start + 1
            continue
        found.append(text[start : end + 1])
        index = end + 1
    return found


def _salvage_items(text: str) -> list[dict[str, Any]]:
    """Complete question objects recovered from a truncated reply."""

    items: list[dict[str, Any]] = []
    for candidate in _balanced_objects(text):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        questions = value.get("questions")
        if isinstance(questions, list):
            items.extend(item for item in questions if isinstance(item, dict))
            continue
        if "question_id" in value:
            items.append(value)
    return items


def _bound_item(item: dict[str, Any]) -> int:
    """Clip supporting text to the whole-paper bounds; return how many were cut.

    Clipping rather than rejecting follows the single-question contract: a model
    that writes a long quotation has still marked the question, and the unclipped
    reply is retained in the paper archive.  Components are not truncated — the
    award's arithmetic depends on every component the model stated.
    """

    clipped = 0
    components = item.get("components")
    if not isinstance(components, list):
        return clipped
    for component in components:
        if not isinstance(component, dict):
            continue
        for key, limit in _COMPONENT_BOUNDS.items():
            value = component.get(key)
            if isinstance(value, str) and len(value) > limit:
                component[key] = value[:limit]
                clipped += 1
    return clipped


def _accept(
    item: dict[str, Any],
    *,
    parse: WholePaperParse,
    expected: set[str],
    seen: set[str],
) -> None:
    raw_id = item.get("question_id")
    question_id = raw_id.strip() if isinstance(raw_id, str) else ""
    if not question_id:
        parse.malformed_items += 1
        return
    if question_id not in expected:
        parse.unknown_ids.append(question_id)
        return
    if question_id in seen:
        parse.duplicates.append(question_id)
        return
    parse.clipped_supporting_text += _bound_item(item)
    try:
        mark = QuestionMark.model_validate(item)
    except ValidationError as error:
        parse.invalid[question_id] = (
            "the item did not satisfy the marking contract: "
            f"{error.error_count()} issue(s)."
        )
        return
    _disambiguate_component_codes(mark.components)
    parse.marks[question_id] = mark
    seen.add(question_id)


def parse_whole_paper(
    text: str | None, *, expected_ids: Iterable[str], truncated: bool = False
) -> WholePaperParse:
    """Read one paper reply, isolating every failure to its own question.

    A reply that is not a whole-paper document at all raises
    ``WholePaperResponseInvalid``: there is nothing to attribute.  A reply that
    is a document but has bad, missing, duplicate or unknown items yields a
    parse report, and only the affected questions fall back.
    """

    expected = [str(question_id) for question_id in expected_ids]
    expected_set = set(expected)
    raw = (text or "").strip()
    if not raw:
        raise WholePaperResponseInvalid("The model returned an empty response.")

    parse = WholePaperParse(complete=not truncated)
    if truncated:
        items = _salvage_items(raw)
        if not items:
            raise WholePaperResponseInvalid(
                "The response was cut off before any complete question object "
                "was received."
            )
    else:
        try:
            payload = parse_json_text(raw)
        except ValueError as error:
            raise WholePaperResponseInvalid(
                f"The model response was not valid JSON: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise WholePaperResponseInvalid(
                "The model response was not a JSON object."
            )
        items = payload.get("questions")
        if not isinstance(items, list):
            raise WholePaperResponseInvalid(
                "The model response did not contain a 'questions' array."
            )
        if not items:
            raise WholePaperResponseInvalid(
                "The model response contained no question results."
            )

    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            parse.malformed_items += 1
            continue
        _accept(item, parse=parse, expected=expected_set, seen=seen)

    parse.missing = [question_id for question_id in expected if question_id not in parse.marks]
    return parse
