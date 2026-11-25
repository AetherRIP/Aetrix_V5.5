"""Criterion-level verification against the approved mark scheme.

The model's reply is one account of a marking decision; the approved, versioned
mark scheme is a second, independent account.  This module compares the two
without asking a model anything:

* every awarded component must name a mark point the scheme defines
  (``UNKNOWN_CRITERION``);
* every mark point the scheme defines should have been considered when the reply
  enumerates components at all (``MISSING_MARK_POINT``);
* the award must fit inside the marks the scheme's criteria actually carry
  (``OVER_SCHEME_CAPACITY``);
* a labelled dependent criterion is awarded while the criterion it depends on
  was not (``UNMET_DEPENDENCY``).  A question often prints two ``M1`` points
  where the second depends on the first, so the requirement is a count of awards
  of that code, not membership of a set.  Only a dependent point the reply
  actually granted is judged: withholding the follow-through is not a dependency
  failure, and awarding nothing has nothing to follow through from;
* a documented alternative route (``M2`` for two method marks, ``B2``) is a mark
  point of the question too, so naming it is not an unknown criterion and using
  it is not ignoring the primary points it replaces;
* an accuracy mark the scheme prints as ``cao`` is earned by the printed answer
  only, so awarding it for an equal answer written another way is a contradiction
  (``SCHEME_ANSWER_NOT_CAO``) while withholding it for that form is not;
* where the scheme states a short, unambiguous expected answer, SymPy decides
  whether the student's final answer matches it, which is independent of the
  model's own answer check (``SCHEME_MATHEMATICAL``).

Nothing here rewrites an award.  A finding sends the question to a person with a
statement of what disagreed; the model's mark and the quoted evidence are kept.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import term_count
from .aetrix.verification import (
    equivalent_to_scheme,
    parse_expression,
    restore_printed_superscripts,
)
from .codes import _base_component_code, _normalise_code, resolve_code
from .findings import (
    CODE_AMBIGUOUS_CRITERION,
    CODE_ANSWER_DIFFERENT,
    CODE_ANSWER_NOT_CAO,
    CODE_ANSWER_WITHHELD,
    CODE_EXCESS_CRITERION_AWARD,
    CODE_MISSING_MARK_POINT,
    CODE_OVER_SCHEME_CAPACITY,
    CODE_ROUTE_CONFLICT,
    CODE_ROUTE_THRESHOLD_UNRECORDED,
    CODE_TERM_COUNT_NOT_MET,
    CODE_TERM_COUNT_UNVERIFIED,
    CODE_UNKNOWN_CRITERION,
    CODE_UNMET_DEPENDENCY,
    SEVERITY_DEFINITE,
    SEVERITY_POSSIBLE,
    SchemeFinding,
)

#: A scheme answer is accepted as a comparable expression only when it is short,
#: contains a digit, and every alphabetic token is a single-letter variable or a
#: function this build knows.  "M1 for expanding" therefore never becomes an
#: expression: "for" is an English word, not a variable.
_KNOWN_TOKENS = frozenset(
    {"sqrt", "pi", "sin", "cos", "tan", "log", "ln", "exp", "e", "x", "y", "z"}
)
_ALPHA_TOKEN = re.compile(r"[A-Za-z]+")
#: The printed instruction "correct answer only", which governs an accuracy mark.
_CAO = re.compile(r"\bcao\b", re.IGNORECASE)
#: Brackets left in a student's answer once the grouping ones are removed mean a
#: product the scheme prints expanded.
_BRACKETS = re.compile(r"[()[\]{}]")
#: What may sit on either side of a bracket that only groups a term instead of
#: multiplying one: ``(y^2 + 8y - 20)``, ``y^2 + 8y + (-20)``.  A bracket with a
#: factor in front of it (``2(5x + 11)``) or behind it (``(y + 10)(y - 2)``) is a
#: product, so it is not grouping and is never removed.
_GROUPING_BEFORE = frozenset({"", "+"})
_GROUPING_AFTER = frozenset({"", "+", "-"})
_MAX_EXPRESSION_CHARS = 60


def scheme_codes(criteria: Iterable[Any]) -> list[str]:
    return [str(criterion.code).strip() for criterion in criteria if str(criterion.code).strip()]


def scheme_capacity(criteria: Iterable[Any]) -> int:
    """The marks the scheme's own criteria carry for one question."""

    return sum(int(getattr(criterion, "marks", 0) or 0) for criterion in criteria)


def alternative_codes(criteria: Iterable[Any]) -> list[str]:
    """The codes of the alternative routes a scheme documents for a question.

    A question printed as ``M1 M1 A1`` may also be answerable through ``M2 A1``.
    The alternative is recorded beside the criterion it replaces, never as an
    extra row, so reading it changes which codes count as defined without
    changing the question's capacity.
    """

    codes: list[str] = []
    for criterion in criteria:
        for alternative in getattr(criterion, "alternatives", None) or []:
            if not isinstance(alternative, dict):
                continue
            code = str(alternative.get("code") or "").strip()
            if code and code not in codes:
                codes.append(code)
    return codes


@dataclass(frozen=True, slots=True)
class AlternativeRoute:
    """One documented alternative route, with the marks it replaces.

    ``replaces`` names the schedule codes the route stands in for.  It is approved
    data, not an inference: two routes can both carry two marks while replacing
    different criteria, and the engine must know which criteria it may not see
    awarded beside the route.
    """

    code: str
    marks: int
    host_code: str
    replaces: tuple[str, ...]
    term_count: dict[str, Any] | None = None

    @property
    def excluded(self) -> frozenset[str]:
        """Codes that cannot be awarded alongside this route."""

        return frozenset(self.replaces) | {self.host_code}


def alternative_routes(
    criteria: Iterable[Any], question_id: str | None = None
) -> dict[str, AlternativeRoute]:
    """``{resolved route code: route}``, independent of row and reply order."""

    routes: dict[str, AlternativeRoute] = {}
    for criterion in criteria:
        host = _normalise_code(getattr(criterion, "code", ""), question_id)
        for alternative in getattr(criterion, "alternatives", None) or []:
            if not isinstance(alternative, dict):
                continue
            raw = str(alternative.get("code") or "").strip()
            if not raw:
                continue
            code = _normalise_code(raw, question_id)
            replaces = tuple(
                _normalise_code(name, question_id)
                for name in (alternative.get("replaces") or [])
                if str(name).strip()
            )
            routes[code] = AlternativeRoute(
                code=code,
                marks=int(alternative.get("marks") or 0),
                host_code=host,
                replaces=replaces,
                term_count=alternative.get("term_count"),
            )
    return routes


def dependency_requirements(criteria: Iterable[Any]) -> dict[str, int]:
    """How many awards of each code the scheme's dependent marks require.

    A mark point that depends on ``M1`` needs one ``M1`` to have been awarded.  A
    dependent point whose own code is ``M1`` needs two: the one it is, and the
    earlier one it follows through from.  That distinction is invisible to a set
    of codes, which is why the check counts awards.
    """

    requirements: dict[str, int] = {}
    for criterion in criteria:
        code = str(getattr(criterion, "code", "")).strip().upper()
        for raw in getattr(criterion, "dependencies", None) or []:
            name = str(raw).strip().upper()
            if not name:
                continue
            needed = 2 if name == code else 1
            requirements[name] = max(requirements.get(name, 0), needed)
    return requirements


def awarded_codes(
    components: Iterable[Any], criteria: Iterable[Any], question_id: str | None = None
) -> set[str]:
    """The scheme points the reply actually awarded, with codes resolved."""

    known = [_normalise_code(code, question_id) for code in scheme_codes(criteria)]
    known += [
        code
        for code in (
            _normalise_code(alternative, question_id) for alternative in alternative_codes(criteria)
        )
        if code not in known
    ]
    return {
        resolve_code(component.code, known, question_id)
        for component in components
        if getattr(component, "awarded", False)
    }


def _dependencies(criterion: Any) -> list[str]:
    """The mark point codes a criterion says it depends on."""

    return [
        str(raw).strip().upper()
        for raw in getattr(criterion, "dependencies", None) or []
        if str(raw).strip()
    ]


def _criterion_marks(criterion: Any) -> int:
    return int(getattr(criterion, "marks", 0) or 1)


def _alternative_host(code: str, codes: list[str], criteria: list[Any]) -> str | None:
    """The scheme mark point a documented alternative route stands in for.

    An alternative is recorded beside the criterion it replaces, never as a row
    of its own.  Taking it therefore earns the marks of that mark point, which is
    what a dependent point printed later in the same question follows through
    from: ``M2 A1`` where the scheme prints ``M1 M1 A1`` is not missing the mark
    the accuracy mark depends on.
    """

    for index, criterion in enumerate(criteria):
        for alternative in getattr(criterion, "alternatives", None) or []:
            if not isinstance(alternative, dict):
                continue
            if str(alternative.get("code") or "").strip().upper() == code:
                return codes[index]
    return None


def _awarded_criteria(
    criteria: list[Any],
    codes: list[str],
    parts: Iterable[Any],
    defined: Iterable[str],
    question_id: str | None,
) -> tuple[list[int], Counter[str]]:
    """Marks credited to each criterion, and marks earned for each mark point.

    The scheme repeats codes (``M1 M1 A1``) and a reply names only the code, so an
    award is matched to the rows of its code in the order the scheme prints them:
    the first ``M1`` earns the first method mark, a second earns the follow-through
    one, and one component printed as two marks earns both.  A code the reply
    decorates as a follow-through (``M1FT``) is evidence of the dependent row
    itself, which is the only way a reply that awarded the follow-through alone can
    be seen to have skipped the mark it follows.
    """

    credits = [0] * len(criteria)
    plain: Counter[str] = Counter()
    pinned: Counter[str] = Counter()
    earned: Counter[str] = Counter()
    rows: dict[str, list[int]] = {}
    for index, code in enumerate(codes):
        rows.setdefault(code, []).append(index)

    for component in parts:
        if not getattr(component, "awarded", False):
            continue
        marks = int(getattr(component, "marks", 0) or 1)
        code = resolve_code(component.code, defined, question_id)
        host = _alternative_host(code, codes, criteria)
        if host is not None:
            earned[host] += marks
            continue
        earned[code] += marks
        decorated = _normalise_code(component.code, question_id) != code
        dependent_rows = [index for index in rows.get(code, []) if _dependencies(criteria[index])]
        if decorated and dependent_rows:
            pinned[code] += marks
        else:
            plain[code] += marks

    for code, indexes in rows.items():
        remaining = plain.get(code, 0)
        for index in indexes:
            if remaining <= 0:
                break
            take = min(remaining, _criterion_marks(criteria[index]))
            credits[index] = min(credits[index] + take, _criterion_marks(criteria[index]))
            remaining -= take
        remaining = pinned.get(code, 0)
        for index in indexes:
            if remaining <= 0:
                break
            if not _dependencies(criteria[index]):
                continue
            take = min(remaining, _criterion_marks(criteria[index]))
            credits[index] = min(credits[index] + take, _criterion_marks(criteria[index]))
            remaining -= take

    return credits, earned


def _dependency_findings(
    criteria: list[Any], codes: list[str], credits: list[int], earned: Counter[str]
) -> list[SchemeFinding]:
    """Report a dependent point the reply awarded without the marks it needs.

    Only an awarded criterion is judged.  Awarding the first method mark and
    stopping, or awarding nothing at all, leaves every dependent point unwon, and
    a prerequisite cannot be missing from an award that was never made.
    """

    findings: list[SchemeFinding] = []
    reported: set[str] = set()
    for index, criterion in enumerate(criteria):
        names = _dependencies(criterion)
        if not names or credits[index] <= 0:
            continue
        for name in names:
            # A point that follows through from its own code needs the earlier
            # award as well as itself, so it needs two.
            needed = 2 if name == codes[index] else 1
            have = earned.get(name, 0)
            if have >= needed:
                continue
            if needed > 1:
                message = (
                    f"A follow-through mark point that depends on {name!r} was awarded while "
                    f"only {have} of the {needed} {name!r} marks it needs was awarded; the "
                    "scheme requires the earlier mark first."
                )
            else:
                message = (
                    f"A mark point that depends on {name!r} was awarded while no {name!r} "
                    "mark was awarded."
                )
            if message in reported:
                continue
            reported.add(message)
            findings.append(SchemeFinding(CODE_UNMET_DEPENDENCY, message, SEVERITY_DEFINITE))
    return findings


def check_against_scheme(
    *,
    awarded: int,
    components: Iterable[Any],
    criteria: Iterable[Any],
    question_id: str | None = None,
    max_marks: int | None = None,
) -> list[SchemeFinding]:
    """Compare one parsed mark with the scheme criteria for its question."""

    scheme = list(criteria)
    if not scheme:
        # No criterion detail is stored for this question, so there is nothing
        # independent to compare against.  Silence here is honest: the other
        # integrity checks still run.
        return []
    parts = list(components)
    known = [_normalise_code(code, question_id) for code in scheme_codes(scheme)]
    # Indexed against the scheme's rows, so a code repeated in the scheme stays a
    # separate mark point when awards are matched to it.
    criterion_codes = [
        _normalise_code(getattr(criterion, "code", ""), question_id) for criterion in scheme
    ]
    alternative = [
        _normalise_code(code, question_id) for code in alternative_codes(scheme)
    ]
    # A documented alternative is a mark point of this question, so naming it is
    # not an unknown criterion.  It carries no capacity of its own: the printed
    # alternative replaces marks the criteria already count.
    defined = known + [code for code in alternative if code not in known]
    capacity = scheme_capacity(scheme)
    findings: list[SchemeFinding] = []

    claimed = {
        _normalise_code(component.code, question_id)
        for component in parts
        if getattr(component, "awarded", False)
    }
    granted = {resolve_code(code, defined, question_id) for code in claimed}
    used_alternative = bool(granted & set(alternative))
    if parts:
        for code in sorted(granted):
            if code not in defined:
                findings.append(
                    SchemeFinding(
                        CODE_UNKNOWN_CRITERION,
                        f"The award relies on mark point {code!r}, which the approved "
                        f"scheme does not define for this question ({', '.join(known) or 'none'}).",
                        SEVERITY_POSSIBLE,
                    )
                )
        present = {
            resolve_code(component.code, defined, question_id) for component in parts
        }
        # An unnamed mark point only matters when marks were left on the table:
        # a reply that already awarded the scheme's whole capacity cannot have
        # withheld a point by not naming it, and a reply that awarded nothing
        # withheld nothing — an unattempted question is a confirmed zero, not a
        # question for a person because the criteria were not recited.  A reply
        # that took a documented alternative route is not expected to name the
        # points that route replaces either, so its silence about them is not
        # evidence of omission.
        missing = (
            [code for code in known if code not in present]
            if 0 < awarded < capacity and not used_alternative
            else []
        )
        if missing:
            findings.append(
                SchemeFinding(
                    CODE_MISSING_MARK_POINT,
                    "The reply does not consider the scheme's mark point(s) "
                    f"{', '.join(missing)}, so those marks were decided without being "
                    "named.",
                    SEVERITY_POSSIBLE,
                )
            )

    if capacity and awarded > capacity:
        # The criteria stored for this question carry fewer marks than the
        # question itself.  That is evidence the scheme record is incomplete, not
        # evidence the award is wrong: a reply can fit the question's maximum and
        # still exceed what was recorded for it.  A definite mismatch therefore
        # needs the scheme's marks to cover the question; otherwise the finding is
        # a reason to look, never a contradiction.
        complete = max_marks is None or capacity >= max_marks
        findings.append(
            SchemeFinding(
                CODE_OVER_SCHEME_CAPACITY,
                f"The award {awarded} exceeds the {capacity} mark(s) the scheme's criteria "
                "carry for this question."
                + (
                    ""
                    if complete
                    else f" The criteria do not cover the question's {max_marks} mark(s), "
                    "so the stored scheme may be incomplete."
                ),
                SEVERITY_DEFINITE if complete else SEVERITY_POSSIBLE,
            )
        )

    # Each dependent point is judged on its own award, never on the question as a
    # whole: a reply that withheld the follow-through, or awarded nothing, has no
    # dependent award to check.  A documented alternative route is handled by
    # what it stands in for, not by suppressing the question's dependency check.
    if parts:
        credits, earned = _awarded_criteria(
            scheme, criterion_codes, parts, defined, question_id
        )
        findings.extend(_dependency_findings(scheme, criterion_codes, credits, earned))
        findings.extend(
            _route_findings(scheme, parts, granted, question_id=question_id)
        )
        findings.extend(
            _identity_findings(scheme, criterion_codes, parts, defined, question_id)
        )

    return findings


def _route_findings(
    scheme: list[Any],
    parts: list[Any],
    granted: set[str],
    *,
    question_id: str | None,
) -> list[SchemeFinding]:
    """Reject an award that mixes routes, or that counts a code more than it exists.

    These are the two ways an award can look plausible and still be impossible:

    * a reply awards a documented alternative route and also a criterion that
      route replaces (the student cannot have expanded in one stage and in two),
      or awards two alternative routes at once;
    * a reply awards more marks against a code than the scheme's rows of that code
      carry (three ``M1`` awards where the paper prints two).

    Both are definite contradictions with the approved scheme, and both are
    invisible to a capacity check alone: two ``M1`` plus an ``M2`` can total
    exactly the question's marks while double-counting one method.
    """

    findings: list[SchemeFinding] = []
    routes = alternative_routes(scheme, question_id)
    granted_routes = sorted(code for code in granted if code in routes)
    if len(granted_routes) > 1:
        findings.append(
            SchemeFinding(
                CODE_ROUTE_CONFLICT,
                "The award takes more than one documented alternative route "
                f"({', '.join(granted_routes)}); the scheme presents them as "
                "alternative routes for the same marks.",
                SEVERITY_DEFINITE,
            )
        )
    elif granted_routes:
        route = routes[granted_routes[0]]
        clashes = sorted(
            code
            for code in granted
            if code in route.excluded and code != route.code
        )
        if clashes:
            findings.append(
                SchemeFinding(
                    CODE_ROUTE_CONFLICT,
                    f"The award takes the documented {route.code} route and also awards "
                    f"{', '.join(clashes)}, the mark point(s) that route replaces. "
                    "The two routes cannot both be earned for the same method.",
                    SEVERITY_DEFINITE,
                )
            )

    scheme_marks: Counter[str] = Counter()
    for criterion in scheme:
        scheme_marks[_normalise_code(getattr(criterion, "code", ""), question_id)] += (
            _criterion_marks(criterion)
        )
    awarded_marks: Counter[str] = Counter()
    for component in parts:
        if not getattr(component, "awarded", False):
            continue
        code = resolve_code(
            component.code,
            list(scheme_marks) + list(routes),
            question_id,
        )
        if code in routes:
            # A route's marks are judged against the question's capacity, not
            # against the single schedule code it is recorded beside.
            continue
        awarded_marks[code] += int(getattr(component, "marks", 0) or 0)
    for code, marks in sorted(awarded_marks.items()):
        available = scheme_marks.get(code)
        if available is None or marks <= available:
            continue
        findings.append(
            SchemeFinding(
                CODE_EXCESS_CRITERION_AWARD,
                f"The award claims {marks} mark(s) against {code}, but the scheme "
                f"defines only {available} for that mark point in this question.",
                SEVERITY_DEFINITE,
            )
        )
    return findings


def _shared_code_is_ordered(
    criteria: list[Any], codes: list[str], indexes: list[int]
) -> bool:
    """Whether the rows sharing one code form a follow-through chain.

    ``M1`` followed by a second ``M1`` that depends on ``M1`` is ordered: the
    later point cannot be earned without the earlier one, so a single award of
    that code can only be the earlier point.  Two independent points that merely
    share a code — Q6's two expansions, Q13's two bracket pairs — are not
    ordered, and one award of that code names neither of them.
    """

    for position, index in enumerate(indexes):
        if position == 0:
            continue
        earlier = {codes[indexes[earlier_index]] for earlier_index in range(position)}
        if not set(_dependencies(criteria[index])) & earlier:
            return False
    return True


def _identity_findings(
    scheme: list[Any],
    codes: list[str],
    parts: list[Any],
    defined: Iterable[str],
    question_id: str | None,
) -> list[SchemeFinding]:
    """Report an award that cannot be attributed to one of the points it names.

    A reply names codes, not rows.  Where the scheme prints two independent mark
    points under one code, a single award of that code does not say which was
    earned: the engine reads it against the printed order so the award is
    deterministic, but the attribution is not *known*.  Deterministic is not the
    same as correct, so the question is sent to a person.

    Rows that form a follow-through chain are not ambiguous: the dependent point
    cannot be earned without the earlier one, so one award of that code can only
    be the earlier point.  A decorated code (``M1FT``) is an explicit identity and
    is judged by the dependency check, not here.
    """

    groups: dict[str, list[int]] = {}
    for index, code in enumerate(codes):
        groups.setdefault(code, []).append(index)
    # A reply that names the printed position of a point (``M1#2``) has said
    # which row it means, so nothing is left for a person to disambiguate.  The
    # reference is the engine's own stable identity, exposed by the prompt; a
    # reply that ignores it still gets the ambiguity report below.
    referenced = {
        _normalise_code(
            _base_component_code(str(getattr(component, "reference", "") or "").split("#")[0]),
            question_id,
        )
        for component in parts
        if str(getattr(component, "reference", "") or "").strip()
    }
    findings: list[SchemeFinding] = []
    for code, indexes in groups.items():
        if len(indexes) < 2 or _shared_code_is_ordered(scheme, codes, indexes):
            continue
        if code in referenced:
            continue
        available = sum(_criterion_marks(scheme[index]) for index in indexes)
        claimed = 0
        for component in parts:
            if not getattr(component, "awarded", False):
                continue
            # Read the engine's own disambiguation suffix off before attribution:
            # ``M1`` and ``M1-2`` are two awards of the code the scheme prints.
            base = _base_component_code(str(getattr(component, "code", "")))
            if resolve_code(base, defined, question_id) != code:
                continue
            if _normalise_code(base, question_id) != code:
                continue
            claimed += int(getattr(component, "marks", 0) or 0)
        if claimed <= 0 or claimed >= available:
            continue
        findings.append(
            SchemeFinding(
                CODE_AMBIGUOUS_CRITERION,
                f"The scheme prints {len(indexes)} separate mark points coded {code!r} "
                f"for this question and the reply awarded {claimed} mark(s) against "
                "that code, which does not say which of them was earned. The award is "
                "read against the order the scheme prints; a person has to confirm "
                "which point the marks were for.",
                SEVERITY_POSSIBLE,
            )
        )
    return findings


def term_count_findings(
    *,
    components: Iterable[Any],
    criteria: Iterable[Any],
    student_expression: str | None,
    question_id: str | None = None,
) -> list[SchemeFinding]:
    """Check an awarded alternative route against its printed term threshold.

    Only a route that was actually awarded is judged.  A route whose threshold is
    recorded as data is evaluated deterministically: fewer matching terms than the
    route requires is a definite contradiction, and a form the check cannot read is
    a possible one that a person decides.  A route whose printed threshold was
    never recorded cannot be checked at all, which is reported rather than
    assumed satisfied.
    """

    scheme = list(criteria)
    routes = alternative_routes(scheme, question_id)
    if not routes:
        return []
    known = [_normalise_code(code, question_id) for code in scheme_codes(scheme)]
    defined = known + [code for code in routes if code not in known]
    granted = {
        resolve_code(component.code, defined, question_id)
        for component in components
        if getattr(component, "awarded", False)
    }
    findings: list[SchemeFinding] = []
    for code in sorted(granted & set(routes)):
        route = routes[code]
        if route.term_count is None:
            findings.append(
                SchemeFinding(
                    CODE_ROUTE_THRESHOLD_UNRECORDED,
                    f"The award uses the documented {code} route. Its printed threshold "
                    "is not recorded as data, so it could not be checked against the "
                    "student's answer.",
                    SEVERITY_POSSIBLE,
                )
            )
            continue
        status, detail, _matched, _of = term_count.evaluate(
            student_expression, route.term_count
        )
        if status == term_count.NOT_SATISFIED:
            findings.append(
                SchemeFinding(
                    CODE_TERM_COUNT_NOT_MET,
                    f"The {code} route was awarded, but the answer does not meet its "
                    f"recorded threshold: {detail}.",
                    SEVERITY_DEFINITE,
                )
            )
        elif status == term_count.UNKNOWN:
            findings.append(
                SchemeFinding(
                    CODE_TERM_COUNT_UNVERIFIED,
                    f"The {code} route's term threshold could not be checked: {detail}.",
                    SEVERITY_POSSIBLE,
                )
            )
    return findings


def _looks_like_answer(text: str) -> bool:
    value = text.strip()
    if not value or len(value) > _MAX_EXPRESSION_CHARS or not any(ch.isdigit() for ch in value):
        return False
    tokens = [token.lower() for token in _ALPHA_TOKEN.findall(value)]
    return all(len(token) == 1 or token in _KNOWN_TOKENS for token in tokens)


def scheme_expected_expression(criteria: Iterable[Any]) -> tuple[str, str] | None:
    """A single unambiguous expected answer stated by the scheme, if there is one.

    The criterion's ``expected_answer`` is read as well as its description and
    award conditions.  ``expected_answer`` is the field that exists to state the
    answer, and a scheme whose description is prose ("a correct expansion")
    states nothing comparable without it: the mathematical check would report
    ``SKIPPED`` on exactly the questions the scheme most clearly answers.  Two
    *different* candidate answers are still ambiguous, so nothing is returned and
    no check runs.
    """

    candidates: dict[str, tuple[str, str]] = {}
    for criterion in criteria:
        code = str(criterion.code).strip()
        for field in ("description", "award_conditions", "expected_answer"):
            text = getattr(criterion, field, None)
            if not isinstance(text, str) or not _looks_like_answer(text):
                continue
            restored = restore_printed_superscripts(text)
            if parse_expression(text) is None and parse_expression(restored) is None:
                continue
            # The approved rows state the same answer in two places, written
            # differently: a description with a real superscript (``12x^3``) and
            # an ``expected_answer`` whose superscript was flattened when the
            # page was transcribed (``12x3``).  One key for both notations keeps
            # that pair from reading as two answers, which would look ambiguous
            # and switch the check off.
            candidates.setdefault(" ".join(restored.split()).casefold(), (text.strip(), code))
    if len(candidates) != 1:
        return None
    expression, code = next(iter(candidates.values()))
    return expression, code


@dataclass(frozen=True, slots=True)
class SchemeMathCheck:
    status: str
    expected_expression: str | None = None
    expected_criterion: str | None = None
    student_expression: str | None = None
    #: The accuracy mark is printed ``cao``, so only the printed form earns it.
    correct_answer_only: bool = False
    #: The student wrote that form, rather than something merely equal to it.
    printed_form: bool = False


def correct_answer_only(criteria: Iterable[Any], code: str | None) -> bool:
    """Whether the scheme prints ``cao`` for the accuracy mark ``code``.

    ``cao`` is a printed instruction, not decoration: the accuracy mark is earned
    by the answer the scheme prints, not by any expression that happens to equal
    it.  Reading it is what lets the verifier tell an award made for a different
    form from a correct withholding for a different form.
    """

    if not code:
        return False
    target = str(code).strip().upper()
    for criterion in criteria:
        if str(getattr(criterion, "code", "")).strip().upper() != target:
            continue
        for field in ("award_conditions", "description"):
            text = getattr(criterion, field, None)
            if isinstance(text, str) and _CAO.search(text):
                return True
    return False


def prints_allowance(criteria: Iterable[Any], code: str | None) -> bool:
    """Whether the accuracy mark's own cell prints a further accepted form."""

    if not code:
        return False
    target = str(code).strip().upper()
    for criterion in criteria:
        if str(getattr(criterion, "code", "")).strip().upper() != target:
            continue
        text = getattr(criterion, "award_conditions", None)
        if isinstance(text, str) and "allow" in text.lower():
            return True
    return False


def _closing_bracket(text: str, start: int) -> int | None:
    """The index that closes the bracket at ``start``, if it is closed at all."""

    depth = 0
    for position in range(start, len(text)):
        character = text[position]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth == 0:
                return position
    return None


def _is_single_term(text: str) -> bool:
    """Whether ``text`` is one term, so a sign in front of it only negates it."""

    body = text.strip()
    if not body:
        return False
    depth = 0
    for position, character in enumerate(body):
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif depth == 0 and character in "+-*/^":
            if position == 0 and character in "+-":
                continue  # a leading sign belongs to the term itself
            return False
    return True


def _strip_one_grouping_bracket(text: str) -> str:
    """Remove the first bracket that only groups a term, when there is one.

    A bracket groups rather than multiplies when nothing or a plus sign precedes
    it and nothing or a sign follows it.  That is what makes ``(y^2 + 8y - 20)``
    and ``(11p + 6)`` the printed answers with harmless padding, while leaving
    ``2(5x + 11)`` and ``(y + 10)(y - 2)`` alone: there a factor multiplies the
    bracket, so the brackets are structure, not spacing.  A minus sign in front of
    a bracket that holds a single term is the same kind of padding — ``-(20)`` is
    ``-20`` — but a sum or difference inside would change the expression, so it is
    left in place.
    """

    position = 0
    while position < len(text):
        if text[position] not in "([{":
            position += 1
            continue
        close = _closing_bracket(text, position)
        if close is None:
            return text
        before = text[:position].rstrip()[-1:]
        after = text[close + 1 :].lstrip()[:1]
        groups = before in _GROUPING_BEFORE and after in _GROUPING_AFTER
        negated_term = (
            before == "-"
            and after in _GROUPING_AFTER
            and _is_single_term(text[position + 1 : close])
        )
        if groups or negated_term:
            return text[:position] + text[position + 1 : close] + text[close + 1 :]
        position = close + 1
    return text


def _without_grouping_brackets(text: str) -> str:
    """``text`` with every bracket that only groups a term removed."""

    current = text
    while True:
        stripped = _strip_one_grouping_bracket(current)
        if stripped == current:
            return current
        current = stripped


def answer_is_printed_form(
    student_expression: str | None, expected_expression: str | None
) -> bool:
    """Whether the student wrote the scheme's answer in the form it prints.

    Order and spacing do not matter: ``8y + y^2 - 20`` is the printed answer
    reordered, and brackets that only group a term are padding, so
    ``(y^2 + 8y - 20)`` is the answer the scheme prints.  An unexpanded product
    does matter: ``(y + 10)(y - 2)`` and ``2(5x + 11)`` are equal to the answers
    the scheme prints for their expansions and are not those answers, which is
    exactly what ``cao`` distinguishes.
    """

    student = (student_expression or "").strip()
    expected = (expected_expression or "").strip()
    if not student or not expected:
        return False
    form = _without_grouping_brackets(student)
    if _BRACKETS.search(form):
        # What is left multiplies, so it is not the expanded form the scheme prints.
        return False
    return equivalent_to_scheme(form, expected) is True


def check_answer_against_scheme(
    *, student_expression: str | None, criteria: Iterable[Any]
) -> SchemeMathCheck:
    """Decide whether the student's final answer matches the scheme's answer."""

    scheme = list(criteria)
    expected = scheme_expected_expression(scheme)
    student = (student_expression or "").strip()
    if expected is None or not student:
        return SchemeMathCheck(status="SKIPPED", student_expression=student or None)
    expression, code = expected
    # The scheme's answer is plain text transcribed from a printed page, so a
    # superscript may have arrived as a digit.  The comparison reads that
    # artefact on the scheme side only; the script's own expression is read as
    # written.
    decision = equivalent_to_scheme(student, expression)
    status = "EQUIVALENT" if decision is True else "DIFFERENT" if decision is False else "UNKNOWN"
    return SchemeMathCheck(
        status=status,
        expected_expression=expression,
        expected_criterion=code,
        student_expression=student,
        correct_answer_only=correct_answer_only(scheme, code),
        printed_form=(
            answer_is_printed_form(student, expression) if status == "EQUIVALENT" else False
        ),
    )


def scheme_math_findings(
    check: SchemeMathCheck,
    *,
    awarded: int,
    max_marks: int,
    components: Iterable[Any] = (),
    criteria: Iterable[Any] = (),
    question_id: str | None = None,
) -> list[SchemeFinding]:
    """Turn a scheme/answer decision into findings, attributed to the mark points.

    A different final answer proves an error only where the accuracy mark itself
    was awarded (or every available mark was).  A reply that awarded method marks
    and withheld the accuracy mark is not contradicted by a wrong answer — that is
    exactly the correct marking, which is why the earlier unattributed rule flagged
    correct method-mark awards.

    The other direction is a real risk: if the answer is provably equivalent to the
    scheme's and the accuracy mark was withheld, the reply may have under-awarded.
    That is a possible mismatch, not a definite one, because a printed scheme can
    require a particular form.
    """

    scheme = list(criteria)
    capacity = scheme_capacity(scheme) or max_marks
    answer_code = (
        _normalise_code(check.expected_criterion, question_id)
        if check.expected_criterion
        else None
    )
    granted = (
        awarded_codes(components, scheme, question_id) if scheme else set()
    )

    if check.status == "DIFFERENT" and awarded > 0:
        if (answer_code is not None and answer_code in granted) or (
            capacity > 0 and awarded >= capacity
        ):
            return [
                SchemeFinding(
                    CODE_ANSWER_DIFFERENT,
                    "The student's final answer is not equivalent to the answer the scheme "
                    f"states for {check.expected_criterion!r} "
                    f"({check.expected_expression!r}), yet the accuracy mark was awarded "
                    f"({awarded} of {max_marks}).",
                    SEVERITY_DEFINITE,
                )
            ]
        return []
    if check.status == "EQUIVALENT" and check.correct_answer_only and not check.printed_form:
        # The scheme prints ``cao``: its answer earns the mark, not every expression
        # equal to it.  A reply that awarded the mark for another form has
        # contradicted that instruction; a reply that withheld it for another form
        # is doing what the instruction asks, so it is not flagged at all.
        if (answer_code is not None and answer_code in granted) or (
            capacity > 0 and awarded >= capacity
        ):
            return [
                SchemeFinding(
                    CODE_ANSWER_NOT_CAO,
                    "The scheme prints "
                    f"{check.expected_criterion!r} as cao (correct answer only) with the answer "
                    f"{check.expected_expression!r}, but the award of {awarded} of {max_marks} "
                    f"granted it for {check.student_expression!r}, which is equal to that answer "
                    "but not written in the form the scheme prints.",
                    SEVERITY_POSSIBLE
                    if prints_allowance(scheme, answer_code)
                    else SEVERITY_DEFINITE,
                )
            ]
        return []
    if (
        check.status == "EQUIVALENT"
        and max_marks > 0
        and answer_code is not None
        and answer_code not in granted
        and awarded < capacity
    ):
        return [
                SchemeFinding(
                    CODE_ANSWER_WITHHELD,
                    "The student's final answer is equivalent to the answer the scheme "
                    f"states ({check.expected_expression!r}), but the mark point that "
                    f"states it ({check.expected_criterion}) was not awarded "
                    f"({awarded} of {max_marks}).",
                    SEVERITY_POSSIBLE,
                )
            ]
    return []
