"""The prompt assets must demonstrate the contract the engine enforces.

A prompt is the instruction a model follows, and its example is the shape it
copies.  An example that violates the engine's own integrity rule — an award that
does not equal the sum of its awarded components — teaches the model to produce
responses that are sent to review for a reason the model was never told about.

These tests parse each marking prompt's example through the real parser and
assert the example is internally consistent.
"""

from __future__ import annotations

import json
import re

import pytest
from app.core.config import get_settings
from app.correction.aetrix.pipeline import PROMPT_DOUBLE_CHECK, PROMPT_MARKING
from app.correction.aetrix.schema import parse_question_mark
from app.prompts.registry import PromptRegistry

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _asset(prompt_id: str):
    return PromptRegistry(get_settings().provider.prompt_root).load(prompt_id)


def _example(prompt_id: str):
    asset = _asset(prompt_id)
    match = _JSON_BLOCK.search(asset.content)
    assert match is not None, f"{prompt_id} has no JSON example"
    return json.loads(match.group(1))


@pytest.mark.parametrize("prompt_id", [PROMPT_MARKING, PROMPT_DOUBLE_CHECK])
def test_the_example_response_parses_as_a_marking_response(prompt_id: str) -> None:
    example = _example(prompt_id)

    mark = parse_question_mark(json.dumps(example), question_id=example["question_id"])

    assert mark.question_id == example["question_id"]
    assert mark.awarded_marks == example["awarded_marks"]


@pytest.mark.parametrize("prompt_id", [PROMPT_MARKING, PROMPT_DOUBLE_CHECK])
def test_the_example_award_equals_the_sum_of_its_awarded_components(prompt_id: str) -> None:
    mark = parse_question_mark(
        json.dumps(_example(prompt_id)),
        question_id=_example(prompt_id)["question_id"],
    )

    assert mark.component_total == mark.awarded_marks, (
        "the prompt's example must not contradict the integrity rule that "
        "awarded component marks sum to the award"
    )


@pytest.mark.parametrize("prompt_id", [PROMPT_MARKING, PROMPT_DOUBLE_CHECK])
def test_the_example_quotes_evidence_for_every_awarded_component(prompt_id: str) -> None:
    mark = parse_question_mark(
        json.dumps(_example(prompt_id)),
        question_id=_example(prompt_id)["question_id"],
    )

    assert all(
        (component.evidence or "").strip()
        for component in mark.components
        if component.awarded
    )


@pytest.mark.parametrize("prompt_id", [PROMPT_MARKING, PROMPT_DOUBLE_CHECK])
def test_the_engine_loads_the_corrected_prompt_version(prompt_id: str) -> None:
    """The example fix ships as a new version; the registry must serve it."""

    assert _asset(prompt_id).version >= 2


@pytest.mark.parametrize(
    "phrase", ["cao", "isw", "oe", "method", "unit", "dependent", "negative marking"]
)
def test_the_marking_prompt_states_the_scheme_rules_it_is_judged_on(phrase: str) -> None:
    content = _asset(PROMPT_MARKING).content.lower()

    assert phrase in content, phrase
