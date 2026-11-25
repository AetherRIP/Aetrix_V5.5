"""Reading a mark-scheme code the way a reply writes it.

A reply decorates the code the scheme prints: it may qualify it with the
question it belongs to (``1a_B1`` where the scheme says ``B1``), append scheme
notation (``M1FT`` for follow-through), or carry the engine's own duplicate
suffix (``M1-2``).  None of those is a different mark point.  This module is the
single place that reads them, so the scheme comparison and the criterion
identity resolver cannot disagree about what a reply wrote.

It is dependency-free on purpose: both of those modules import it, and neither
may import the other.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: A code the engine disambiguated: ``M1`` repeated becomes ``M1-2``.
_DISAMBIGUATED_CODE = re.compile(r"^(.*)-(\d+)$")
#: A printed mark point code: one or more letters followed by its number.
_LEADING_CODE = re.compile(r"^[A-Z]+\d+")


def _normalise_code(code: Any, question_id: str | None) -> str:
    """Compare mark points by their code, not by how a reply decorates it.

    A reply may qualify a mark point with the question it belongs to
    (``1a_B1`` where the scheme says ``B1``) and may append a scheme notation
    (``M1FT`` for follow-through, ``M1_DEP`` for a dependent mark).  Neither is a
    different mark point, so the question prefix is removed here and a variant is
    resolved to its base code when the scheme defines that base.
    """

    value = str(code).strip()
    if question_id:
        for separator in (":", ".", "-", "_"):
            prefix = f"{question_id}{separator}"
            if len(value) > len(prefix) and value.upper().startswith(prefix.upper()):
                value = value[len(prefix) :]
                break
    return value.strip().upper()


def _base_codes(value: str) -> list[str]:
    """The base mark points a decorated code could refer to (``M1FT`` → ``M1``)."""

    match = _LEADING_CODE.match(value)
    if match is None or match.group(0) == value:
        return []
    return [match.group(0)]


def resolve_code(code: Any, known: Iterable[str], question_id: str | None = None) -> str:
    """The scheme point a reply's component code names, if the scheme defines one."""

    value = _normalise_code(code, question_id)
    if value in set(known):
        return value
    for base in _base_codes(value):
        if base in set(known):
            return base
    return value


def _base_component_code(code: str) -> str:
    """The scheme code a reply component names.

    ``_disambiguate_component_codes`` renames the second and later award of a
    repeated code (``M1`` -> ``M1-2``) so both awards survive validation.  The
    suffix is the engine's own label, not the scheme's, so attribution must read
    the base code: otherwise a question whose duplicate points were *all* awarded
    looks like a single award against an ambiguous code and is sent to a person
    for a reason the reply already answered.
    """

    match = _DISAMBIGUATED_CODE.match(code.strip())
    return match.group(1) if match else code.strip()
