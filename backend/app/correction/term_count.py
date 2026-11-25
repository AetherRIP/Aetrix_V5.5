"""Deterministic term-count thresholds for printed alternative routes.

An approved scheme sometimes states a route as a count of correct terms
("3 out of a maximum of 4 terms correct") rather than as an answer the engine can
compare.  Such a condition is checkable only when the approved rules name the
expression whose terms are counted and the threshold, so both are stored beside
the alternative route.  The check counts the student's written terms against the
terms of that expression.

It is deliberately narrow:

* the expression must be written as a sum of terms, so a product, a power of a
  sum or anything unreadable is ``UNKNOWN``;
* the recorded ``count`` must equal the terms the expression actually has;
* a term is matched by mathematical equality, and a match is consumed, so
  repeating a correct term cannot satisfy a higher threshold.

``UNKNOWN`` is never treated as satisfied.  Nothing here awards or removes a
mark; the caller turns a result into a review signal.
"""

from __future__ import annotations

import sympy

SATISFIED = "SATISFIED"
NOT_SATISFIED = "NOT_SATISFIED"
UNKNOWN = "UNKNOWN"


def _parse_expression(text: str) -> sympy.Expr | None:
    """The engine's expression parser, imported lazily.

    ``aetrix.verification`` is reachable only through the ``aetrix`` package,
    whose ``__init__`` imports the pipeline, which imports the scheme gate that
    imports this module.  Importing the parser at module scope closes that cycle;
    resolving it at call time keeps the module dependency-free and the parser the
    single implementation the whole engine uses.
    """

    from .aetrix.verification import parse_expression

    return parse_expression(text)


def _written_terms(expression: sympy.Expr) -> list[sympy.Expr] | None:
    """The expression's terms as written, or ``None`` when it is not a sum.

    ``3x^3 + 34x^2 + 84x - 72`` is four written terms.  ``(x + 1)(x + 2)`` and
    ``(x + 1)^2`` are not: expanding them would invent a form the student did not
    write, and a threshold stated for written terms cannot judge it.
    """

    if expression.is_Add:
        return list(expression.args)
    if any(getattr(argument, "is_Add", False) for argument in expression.args):
        return None
    return [expression]


def _equal(left: sympy.Expr, right: sympy.Expr) -> bool | None:
    try:
        return bool(sympy.expand(sympy.simplify(left - right)) == 0)
    except Exception:  # a comparison SymPy cannot settle is not a mismatch
        return None


def validate_spec(spec: object) -> str | None:
    """Why a recorded threshold cannot be used, or ``None`` when it can.

    Used by the scheme importer, so a threshold that does not describe its own
    expression is a data error a person must fix rather than a silent ``UNKNOWN``
    discovered while marking.
    """

    if not isinstance(spec, dict):
        return "term_count is not an object"
    try:
        required = int(spec["required"])
        count = int(spec["count"])
    except (KeyError, TypeError, ValueError):
        return "term_count needs an integer required and count"
    if required <= 0 or count <= 0 or required > count:
        return f"term_count {required} of {count} is not a usable threshold"
    expression = spec.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return "term_count names no expression"
    parsed = _parse_expression(expression)
    if parsed is None:
        return f"term_count expression {expression!r} cannot be read as mathematics"
    terms = _written_terms(parsed)
    if terms is None:
        return f"term_count expression {expression!r} is not written as a sum of terms"
    if len(terms) != count:
        return (
            f"term_count expression {expression!r} has {len(terms)} written term(s), "
            f"not the recorded {count}"
        )
    return None


def evaluate(expression: str | None, threshold: object) -> tuple[str, str, int | None, int | None]:
    """``(status, detail, matched, of)`` for one answer against one threshold.

    ``status`` is ``SATISFIED`` only when the number of matching terms reaches the
    recorded requirement.  Every form the check cannot read is ``UNKNOWN``.
    """

    problem = validate_spec(threshold)
    if problem is not None:
        return UNKNOWN, problem, None, None
    assert isinstance(threshold, dict)  # validate_spec guarantees the shape
    required = int(threshold["required"])
    expected = _parse_expression(str(threshold["expression"]))
    assert expected is not None
    expected_terms = _written_terms(expected) or []
    student_text = (expression or "").strip()
    if not student_text:
        return UNKNOWN, "the reply states no final answer to count", None, len(expected_terms)
    student = _parse_expression(student_text)
    if student is None:
        return UNKNOWN, f"{student_text!r} cannot be read as mathematics", None, len(expected_terms)
    student_terms = _written_terms(student)
    if student_terms is None:
        return (
            UNKNOWN,
            f"{student_text!r} is not written as a sum of terms, so a written-term "
            "threshold cannot judge it",
            None,
            len(expected_terms),
        )

    remaining = list(expected_terms)
    matched = 0
    for term in student_terms:
        for index, candidate in enumerate(remaining):
            decision = _equal(term, candidate)
            if decision is None:
                return (
                    UNKNOWN,
                    f"the term {term} could not be compared with {candidate}",
                    matched,
                    len(expected_terms),
                )
            if decision:
                matched += 1
                remaining.pop(index)
                break
    detail = (
        f"{matched} of {len(expected_terms)} written term(s) match; "
        f"{required} required"
    )
    if matched >= required:
        return SATISFIED, detail, matched, len(expected_terms)
    return NOT_SATISFIED, detail, matched, len(expected_terms)
