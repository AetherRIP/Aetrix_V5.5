"""Small JSON helpers shared by provider-backed services."""

from __future__ import annotations

import json
from typing import Any


def _balanced_candidates(text: str):
    """Yield balanced JSON object/array substrings, ignoring braces in strings."""
    for start, first in enumerate(text):
        if first not in "{[":
            continue
        stack: list[str] = []
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
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
            elif char in "{[":
                stack.append(char)
            elif char in "}]":
                if not stack:
                    break
                opening = stack.pop()
                if (opening, char) not in {("{", "}"), ("[", "]")}:
                    break
                if not stack:
                    yield text[start : index + 1]
                    break


def parse_json_text(text: str) -> Any:
    """Parse JSON even when the model surrounds it with prose or a code fence.

    The caller still validates the decoded value against the canonical schema;
    this function only removes presentation noise.  It does not repair malformed
    JSON or accept a partial object.
    """
    value = text.strip().lstrip("\ufeff")
    if not value:
        raise ValueError("empty provider response")
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    for candidate in _balanced_candidates(value):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("provider response did not contain a complete JSON value")
