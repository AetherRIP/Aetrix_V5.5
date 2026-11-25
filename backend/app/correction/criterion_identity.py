"""Which approved mark point a reply's component actually means.

A mark scheme prints codes, and a code is not an identity.  The pilot paper
prints ``M1 M1 A1`` for a question: two method marks share one code, and a reply
that writes ``M1`` twice has said *which code* it awarded but not *which of the
two printed points*.  The engine used to resolve that by position — the first
``M1`` is the first printed row — which is deterministic but not knowledge, and
on Q6/Q37b it presented a guess as an attribution.

This module gives every approved criterion a stable, printable identity:
``CODE#n``, where ``n`` is the criterion's position in the question (its stored
``ordinal``), and resolves a reply against it:

* an explicit reference (``M1#2``) resolves to exactly that row, or to nothing;
* a bare code resolves only when exactly one approved row carries it;
* a bare code shared by two independent rows is **ambiguous** and resolves to
  nothing — never to the first match;
* a decorated follow-through (``M1FT``) is an explicit identity and resolves to
  the dependent row, which is the only row it can name.

Nothing here rewrites a mark.  An unresolvable component keeps ``criterion_id``
NULL, and the caller turns that into a review reason.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .codes import _base_codes, _base_component_code, _normalise_code
from .findings import (
    CODE_COMPONENT_ABOVE_CRITERION_MAX,
    CODE_CRITERION_NOT_IN_APPROVED_SCHEME,
    CODE_CRITERION_NOT_IN_QUESTION,
    CODE_CRITERION_REFERENCE_INVALID,
    CODE_DUPLICATE_CRITERION_AWARD,
    SEVERITY_DEFINITE,
    SchemeFinding,
)

#: The separator between a printed code and its position.  ``#`` is not used by
#: any mark-scheme notation, so a reference can never be confused with a
#: decorated code such as ``M1FT``.
REF_SEPARATOR = "#"

STATUS_RESOLVED = "RESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_UNKNOWN = "UNKNOWN"
#: The reply named a real mark point of another scheme version, or of another
#: question.  Neither may decide a mark in this paper, so it is refused with its
#: own reason rather than reported as an invented code.
STATUS_FOREIGN_VERSION = "FOREIGN_VERSION"
STATUS_OTHER_QUESTION = "OTHER_QUESTION"

#: A reference as the prompt prints it: a printed code and a 1-based position.
_REFERENCE = re.compile(r"^(?P<code>[A-Za-z]+\d+)\s*#\s*(?P<position>\d+)$")


def criterion_reference(code: str, ordinal: int) -> str:
    """The stable identity printed for one approved criterion."""

    return f"{str(code).strip().upper()}{REF_SEPARATOR}{int(ordinal) + 1}"


def split_reference(value: str | None) -> tuple[str, str | None]:
    """Split ``M1#2`` into ``("M1", "M1#2")``; leave a bare code alone.

    The reference is normalised (upper-case code, integer position) so a reply
    that writes ``m1 # 2`` names the same point as ``M1#2``.
    """

    raw = str(value or "").strip()
    if REF_SEPARATOR not in raw:
        return raw, None
    match = _REFERENCE.match(raw)
    if match is None:
        return raw, None
    code = match.group("code").upper()
    position = int(match.group("position"))
    if position < 1:
        return raw, None
    return code, f"{code}{REF_SEPARATOR}{position}"


@dataclass(frozen=True, slots=True)
class CriterionReference:
    """One approved criterion and the identity the prompt shows for it."""

    criterion: Any
    reference: str
    code: str
    ordinal: int

    @property
    def criterion_id(self) -> Any:
        return getattr(self.criterion, "id", None)


@dataclass(frozen=True, slots=True)
class Resolution:
    """What one reply component could be attributed to."""

    code: str
    reference: str | None
    status: str
    criterion: Any | None = None
    #: The component named a documented alternative route, so its marks are
    #: judged against the route, not against the single row it is recorded on.
    via_route: bool = False
    reason: str | None = None

    @property
    def criterion_id(self) -> Any:
        return getattr(self.criterion, "id", None) if self.criterion is not None else None

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED


def _ordinal(value: Any, position: int) -> int:
    """A criterion's printed position, defaulting to where it was listed."""

    if value is None:
        return position
    try:
        return int(value)
    except (TypeError, ValueError):
        return position


def references(criteria: Iterable[Any]) -> list[CriterionReference]:
    """Every approved criterion of one question, in printed order."""

    positioned = [
        (
            _ordinal(getattr(criterion, "ordinal", None), position),
            position,
            criterion,
        )
        for position, criterion in enumerate(criteria)
    ]
    positioned.sort(key=lambda item: (item[0], item[1]))
    return [
        CriterionReference(
            criterion=criterion,
            reference=criterion_reference(str(getattr(criterion, "code", "")), ordinal),
            code=str(getattr(criterion, "code", "")).strip().upper(),
            ordinal=ordinal,
        )
        for ordinal, _position, criterion in positioned
    ]


def reference_map(criteria: Iterable[Any]) -> dict[str, CriterionReference]:
    return {item.reference: item for item in references(criteria)}


def describe(criteria: Iterable[Any]) -> str:
    """A one-line statement of the identities a question accepts."""

    return ", ".join(item.reference for item in references(criteria))


def _route_host(criteria: list[Any], code: str, question_id: str | None) -> Any | None:
    """The criterion a documented alternative route is recorded beside."""

    for criterion in criteria:
        for alternative in getattr(criterion, "alternatives", None) or []:
            if not isinstance(alternative, dict):
                continue
            route = _normalise_code(alternative.get("code") or "", question_id)
            if route and route == code:
                return criterion
    return None


def _matching(criteria: list[Any], code: str, question_id: str | None) -> list[Any]:
    return [
        criterion
        for criterion in criteria
        if _normalise_code(getattr(criterion, "code", ""), question_id) == code
    ]


def resolve(
    *,
    code: str,
    reference: str | None = None,
    criteria: Iterable[Any],
    question_id: str | None = None,
    scheme_version_id: Any | None = None,
) -> Resolution:
    """Attribute one reply component to at most one approved criterion.

    ``scheme_version_id`` is the version the job is marking against.  A
    criterion from any other version can never be the answer to *this* paper,
    so it is refused rather than linked.
    """

    scheme = list(criteria)
    printed_code, tail = split_reference(code)
    explicit, explicit_tail = split_reference(reference)
    if explicit_tail is not None:
        tail = explicit_tail
        printed_code = explicit
    raw = printed_code.strip()
    if not raw:
        return Resolution(
            code=raw,
            reference=tail,
            status=STATUS_UNKNOWN,
            reason="the component names no mark point",
        )

    # The parser renames a repeated code (``M1`` -> ``M1-2``) so both awards
    # survive validation.  That suffix is the engine's label, not the reply's
    # statement, so it identifies nothing: it is read off, and the code is
    # resolved exactly as the bare code would be.
    stripped = _base_component_code(raw)
    engine_label = stripped != raw
    normalised = _normalise_code(stripped, question_id)
    known = reference_map(scheme)

    def _guarded(resolution: Resolution) -> Resolution:
        """Refuse a criterion that cannot belong to this question."""

        criterion = resolution.criterion
        if criterion is None:
            return resolution
        foreign_version = getattr(criterion, "scheme_version_id", None)
        if (
            scheme_version_id is not None
            and foreign_version is not None
            and foreign_version != scheme_version_id
        ):
            return Resolution(
                code=resolution.code,
                reference=resolution.reference,
                status=STATUS_FOREIGN_VERSION,
                reason=(
                    "the criterion belongs to a different scheme version, so it cannot "
                    "decide a mark in this paper"
                ),
            )
        criterion_question = getattr(criterion, "question_id", None)
        if (
            question_id is not None
            and criterion_question is not None
            and str(criterion_question) != str(question_id)
        ):
            return Resolution(
                code=resolution.code,
                reference=resolution.reference,
                status=STATUS_OTHER_QUESTION,
                reason=(
                    f"the criterion belongs to question {criterion_question!r}, not "
                    f"{question_id!r}"
                ),
            )
        return resolution

    if tail is not None:
        match = known.get(tail)
        if match is None:
            available = describe(scheme) or "none"
            return Resolution(
                code=normalised,
                reference=tail,
                status=STATUS_UNKNOWN,
                reason=(
                    f"the reply names mark point {tail!r}, which this question does "
                    f"not define (it defines {available})"
                ),
            )
        if _normalise_code(match.code, question_id) != normalised:
            # ``A1#2`` where reference position 2 is an ``M1``: the code and the
            # position disagree, so the reply does not name one mark point.
            return Resolution(
                code=normalised,
                reference=tail,
                status=STATUS_AMBIGUOUS,
                reason=(
                    f"the reply names mark point {tail!r}, whose code is "
                    f"{match.code!r}, while its own code is {normalised!r}"
                ),
            )
        return _guarded(
            Resolution(
                code=normalised,
                reference=tail,
                status=STATUS_RESOLVED,
                criterion=match.criterion,
            )
        )

    same = _matching(scheme, normalised, question_id)
    if len(same) == 1:
        return _guarded(
            Resolution(
                code=normalised,
                reference=criterion_reference(
                    str(getattr(same[0], "code", "")),
                    int(getattr(same[0], "ordinal", 0) or 0),
                ),
                status=STATUS_RESOLVED,
                criterion=same[0],
            )
        )
    if len(same) > 1:
        return Resolution(
            code=normalised,
            reference=None,
            status=STATUS_AMBIGUOUS,
            reason=(
                f"the scheme prints {len(same)} separate mark points coded "
                f"{normalised!r} for this question and the reply names only that "
                f"code; it must name one of {describe(same)}"
            ),
        )

    route_host = _route_host(scheme, normalised, question_id)
    if route_host is not None:
        return _guarded(
            Resolution(
                code=normalised,
                reference=criterion_reference(
                    str(getattr(route_host, "code", "")),
                    int(getattr(route_host, "ordinal", 0) or 0),
                ),
                status=STATUS_RESOLVED,
                criterion=route_host,
                via_route=True,
            )
        )

    # A decorated code is an explicit identity: ``M1FT`` can only be the
    # dependent row, and ``18_M1`` is the same point as ``M1``.  The engine's
    # own duplicate suffix is excluded: ``M1-2`` says only that this is the
    # second ``M1`` of the reply, which is not a statement about the scheme.
    decorated = [] if engine_label else _base_codes(normalised)
    for base in decorated:
        candidates = _matching(scheme, base, question_id)
        if len(candidates) == 1:
            return _guarded(
                Resolution(
                    code=base,
                    reference=criterion_reference(
                        str(getattr(candidates[0], "code", "")),
                        int(getattr(candidates[0], "ordinal", 0) or 0),
                    ),
                    status=STATUS_RESOLVED,
                    criterion=candidates[0],
                )
            )
        dependent = [
            criterion
            for criterion in candidates
            if getattr(criterion, "dependencies", None)
        ]
        if len(dependent) == 1:
            return _guarded(
                Resolution(
                    code=base,
                    reference=criterion_reference(
                        str(getattr(dependent[0], "code", "")),
                        int(getattr(dependent[0], "ordinal", 0) or 0),
                    ),
                    status=STATUS_RESOLVED,
                    criterion=dependent[0],
                )
            )
        if len(candidates) > 1:
            return Resolution(
                code=base,
                reference=None,
                status=STATUS_AMBIGUOUS,
                reason=(
                    f"{numerised(base)!r} could name {len(candidates)} mark points of "
                    "this question"
                ),
            )

    return Resolution(
        code=normalised,
        reference=None,
        status=STATUS_UNKNOWN,
        reason=(
            f"mark point {normalised!r} is not defined by this question "
            f"(it defines {describe(scheme) or 'none'})"
        ),
    )


def numerised(code: str) -> str:
    """Read a reply's component code back to the code the scheme prints.

    The parser renames a repeated code (``M1`` -> ``M1-2``) so both awards
    survive validation.  That suffix is the engine's own label and must never be
    treated as a different mark point.
    """

    return _base_component_code(code)


def check_components(
    *,
    components: Iterable[Any],
    criteria: Iterable[Any],
    question_id: str,
    scheme_version_id: Any | None = None,
) -> tuple[list[Resolution], list[SchemeFinding]]:
    """Resolve every component and report what could not be attributed.

    The findings are contradictions the stored evidence itself proves, so they
    are definite: an award larger than the mark point it names carries no mark
    to give, two awards against one mark point claim it twice, and a reference
    the question does not define names nothing at all.
    """

    scheme = list(criteria)
    resolutions: list[Resolution] = []
    findings: list[SchemeFinding] = []
    credited: dict[Any, str] = {}

    for component in components:
        code = str(getattr(component, "code", "") or "")
        reference = getattr(component, "reference", None)
        resolution = resolve(
            code=code,
            reference=reference if isinstance(reference, str) else None,
            criteria=scheme,
            question_id=question_id,
            scheme_version_id=scheme_version_id,
        )
        resolutions.append(resolution)
        if not resolution.criterion_id:
            if resolution.status == STATUS_FOREIGN_VERSION:
                findings.append(
                    SchemeFinding(
                        CODE_CRITERION_NOT_IN_APPROVED_SCHEME,
                        f"Mark point {resolution.code!r} belongs to a different scheme "
                        "version, so it cannot decide a mark in this paper.",
                        SEVERITY_DEFINITE,
                    )
                )
            elif resolution.status == STATUS_OTHER_QUESTION:
                findings.append(
                    SchemeFinding(
                        CODE_CRITERION_NOT_IN_QUESTION,
                        f"Mark point {resolution.code!r} belongs to another question of "
                        "this paper, so it cannot decide a mark here.",
                        SEVERITY_DEFINITE,
                    )
                )
            elif resolution.reference is not None and resolution.status == STATUS_UNKNOWN:
                findings.append(
                    SchemeFinding(
                        CODE_CRITERION_REFERENCE_INVALID,
                        f"The reply names mark point {resolution.reference!r}, which "
                        f"cannot be attributed to this question: {resolution.reason}.",
                        SEVERITY_DEFINITE,
                    )
                )
            continue

        criterion = resolution.criterion
        criterion_id = resolution.criterion_id
        if getattr(component, "awarded", False):
            if criterion_id in credited:
                findings.append(
                    SchemeFinding(
                        CODE_DUPLICATE_CRITERION_AWARD,
                        f"Mark point {getattr(criterion, 'code', '?')}"
                        f"#{int(getattr(criterion, 'ordinal', 0) or 0) + 1} is claimed "
                        f"for more than one awarded component "
                        f"({credited[criterion_id]!r} and {code!r}), so the same mark "
                        "point would be paid twice.",
                        SEVERITY_DEFINITE,
                    )
                )
            else:
                credited[criterion_id] = code
        if resolution.via_route:
            # A route's marks are judged against the question's capacity by the
            # scheme check; the single row it is recorded on carries fewer.
            continue
        marks = int(getattr(component, "marks", 0) or 0)
        available = int(getattr(criterion, "marks", 0) or 0)
        if marks > available:
            findings.append(
                SchemeFinding(
                    CODE_COMPONENT_ABOVE_CRITERION_MAX,
                    f"The reply credits {marks} mark(s) to mark point "
                    f"{getattr(criterion, 'code', '?')}"
                    f"#{int(getattr(criterion, 'ordinal', 0) or 0) + 1}, which the "
                    f"approved scheme prints as {available} mark(s).",
                    SEVERITY_DEFINITE,
                )
            )
        foreign_version = getattr(criterion, "scheme_version_id", None)
        if scheme_version_id is not None and foreign_version != scheme_version_id:
            findings.append(
                SchemeFinding(
                    CODE_CRITERION_NOT_IN_APPROVED_SCHEME,
                    "A criterion from another scheme version was resolved for this "
                    "question; only the approved version may decide a mark.",
                    SEVERITY_DEFINITE,
                )
            )
        criterion_question = getattr(criterion, "question_id", None)
        if question_id is not None and str(criterion_question) != str(question_id):
            findings.append(
                SchemeFinding(
                    CODE_CRITERION_NOT_IN_QUESTION,
                    f"Mark point {getattr(criterion, 'code', '?')} belongs to question "
                    f"{criterion_question!r}, not {question_id!r}.",
                    SEVERITY_DEFINITE,
                )
            )
    return resolutions, findings
