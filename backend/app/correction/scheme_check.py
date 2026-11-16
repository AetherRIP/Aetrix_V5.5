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
* a labelled dependent criterion is not awarded while the criterion it depends
  on was not (``UNMET_DEPENDENCY``);
* where the scheme states a short, unambiguous expected answer, SymPy decides
  whether the student's final answer matches it, which is independent of the
  model's own answer check (``SCHEME_MATHEMATICAL``).

Nothing here rewrites an award.  A finding sends the question to a person with a
statement of what disagreed; the model's mark and the quoted evidence are kept.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .aetrix.verification import equivalent, parse_expression

CODE_UNKNOWN_CRITERION = "UNKNOWN_CRITERION"
CODE_MISSING_MARK_POINT = "MISSING_MARK_POINT"
CODE_OVER_SCHEME_CAPACITY = "OVER_SCHEME_CAPACITY"
CODE_UNMET_DEPENDENCY = "UNMET_DEPENDENCY"
CODE_ANSWER_DIFFERENT = "SCHEME_ANSWER_DIFFERENT"
CODE_ANSWER_WITHHELD = "SCHEME_ANSWER_WITHHELD"

#: What a finding is worth.  ``DEFINITE_MISMATCH`` is a contradiction with the
#: approved scheme that the stored evidence itself proves: an award above the
#: scheme's capacity, a dependent point without its prerequisite, or an accuracy
#: mark awarded for an answer the scheme says is different.  ``POSSIBLE_MISMATCH``
#: is a reason to look that does not prove an error on its own (notation the scheme
#: does not use, a scheme point nobody named, an accuracy mark withheld although the
#: answer matches).  ``VERIFIED`` means the comparison found nothing to dispute;
#: ``UNVERIFIABLE`` means this build could not compare, which is never a mismatch.
SEVERITY_DEFINITE = "DEFINITE_MISMATCH"
SEVERITY_POSSIBLE = "POSSIBLE_MISMATCH"
SEVERITY_VERIFIED = "VERIFIED"
SEVERITY_UNVERIFIABLE = "UNVERIFIABLE"

#: A scheme answer is accepted as a comparable expression only when it is short,
#: contains a digit, and every alphabetic token is a single-letter variable or a
#: function this build knows.  "M1 for expanding" therefore never becomes an
#: expression: "for" is an English word, not a variable.
_KNOWN_TOKENS = frozenset(
    {"sqrt", "pi", "sin", "cos", "tan", "log", "ln", "exp", "e", "x", "y", "z"}
)
_ALPHA_TOKEN = re.compile(r"[A-Za-z]+")
#: A printed mark point code: one or more letters followed by its number.
_LEADING_CODE = re.compile(r"^[A-Z]+\d+")
_MAX_EXPRESSION_CHARS = 60


@dataclass(frozen=True, slots=True)
class SchemeFinding:
    code: str
    message: str
    severity: str = SEVERITY_POSSIBLE

    @property
    def definite(self) -> bool:
        return self.severity == SEVERITY_DEFINITE


def scheme_codes(criteria: Iterable[Any]) -> list[str]:
    return [str(criterion.code).strip() for criterion in criteria if str(criterion.code).strip()]


def scheme_capacity(criteria: Iterable[Any]) -> int:
    """The marks the scheme's own criteria carry for one question."""

    return sum(int(getattr(criterion, "marks", 0) or 0) for criterion in criteria)


def _dependencies(criteria: Iterable[Any]) -> dict[str, list[str]]:
    dependencies: dict[str, list[str]] = {}
    for criterion in criteria:
        raw = getattr(criterion, "dependencies", None) or []
        codes = [str(item).strip() for item in raw if str(item).strip()]
        if codes:
            dependencies[str(criterion.code).strip()] = codes
    return dependencies


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


def resolve_code(code: Any, known: Iterable[str], question_id: str | None = None) -> str:
    """The scheme point a reply's component code names, if the scheme defines one."""

    value = _normalise_code(code, question_id)
    if value in set(known):
        return value
    for base in _base_codes(value):
        if base in set(known):
            return base
    return value


def awarded_codes(
    components: Iterable[Any], criteria: Iterable[Any], question_id: str | None = None
) -> set[str]:
    """The scheme points the reply actually awarded, with codes resolved."""

    known = [_normalise_code(code, question_id) for code in scheme_codes(criteria)]
    return {
        resolve_code(component.code, known, question_id)
        for component in components
        if getattr(component, "awarded", False)
    }


def _base_codes(value: str) -> list[str]:
    """The base mark points a decorated code could refer to (``M1FT`` → ``M1``)."""

    match = _LEADING_CODE.match(value)
    if match is None or match.group(0) == value:
        return []
    return [match.group(0)]


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
    capacity = scheme_capacity(scheme)
    findings: list[SchemeFinding] = []

    claimed = {
        _normalise_code(component.code, question_id)
        for component in parts
        if getattr(component, "awarded", False)
    }
    granted = {resolve_code(code, known, question_id) for code in claimed}
    if parts:
        for code in sorted(granted):
            if code not in known:
                findings.append(
                    SchemeFinding(
                        CODE_UNKNOWN_CRITERION,
                        f"The award relies on mark point {code!r}, which the approved "
                        f"scheme does not define for this question ({', '.join(known) or 'none'}).",
                        SEVERITY_POSSIBLE,
                    )
                )
        present = {
            resolve_code(component.code, known, question_id) for component in parts
        }
        # An unnamed mark point only matters when marks were left on the table:
        # a reply that already awarded the scheme's whole capacity cannot have
        # withheld a point by not naming it.
        missing = [code for code in known if code not in present] if awarded < capacity else []
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

    dependencies = {
        _normalise_code(code, question_id): [
            _normalise_code(item, question_id) for item in codes
        ]
        for code, codes in _dependencies(scheme).items()
    }
    for code in sorted(granted):
        for dependency in dependencies.get(code, []):
            if dependency not in granted:
                findings.append(
                    SchemeFinding(
                        CODE_UNMET_DEPENDENCY,
                        f"Mark point {code!r} was awarded while its stated prerequisite "
                        f"{dependency!r} was not.",
                        SEVERITY_DEFINITE,
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

    Only the criterion's description and award conditions are read: they are
    where a printed scheme states the answer a mark point is for.  Two different
    candidate answers are ambiguous, so nothing is returned and no check runs.
    """

    candidates: dict[str, str] = {}
    for criterion in criteria:
        code = str(criterion.code).strip()
        for field in ("description", "award_conditions"):
            text = getattr(criterion, field, None)
            if not isinstance(text, str) or not _looks_like_answer(text):
                continue
            if parse_expression(text) is None:
                continue
            candidates.setdefault(text.strip(), code)
    if len(candidates) != 1:
        return None
    expression, code = next(iter(candidates.items()))
    return expression, code


@dataclass(frozen=True, slots=True)
class SchemeMathCheck:
    status: str
    expected_expression: str | None = None
    expected_criterion: str | None = None
    student_expression: str | None = None


def check_answer_against_scheme(
    *, student_expression: str | None, criteria: Iterable[Any]
) -> SchemeMathCheck:
    """Decide whether the student's final answer matches the scheme's answer."""

    expected = scheme_expected_expression(criteria)
    student = (student_expression or "").strip()
    if expected is None or not student:
        return SchemeMathCheck(status="SKIPPED", student_expression=student or None)
    expression, code = expected
    decision = equivalent(student, expression)
    status = "EQUIVALENT" if decision is True else "DIFFERENT" if decision is False else "UNKNOWN"
    return SchemeMathCheck(
        status=status,
        expected_expression=expression,
        expected_criterion=code,
        student_expression=student,
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
