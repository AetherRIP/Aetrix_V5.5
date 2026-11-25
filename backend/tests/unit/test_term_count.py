"""A printed term threshold is evaluated, or it is unknown — never assumed.

The pilot prints two routes as "3 out of a maximum of 4 terms correct" (Q36 and
Q37a, both the no-working ``B2`` route).  The approved data now records the
expression and the threshold beside the route, so the engine can count terms
deterministically.  These tests pin both directions:

* a term count the mathematics settles is reported as met or not met;
* every form the check cannot read — a product, a fraction, unreadable text, a
  threshold that does not describe its own expression — is ``UNKNOWN`` and
  therefore a review signal, never a satisfied condition.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest
from app.correction import scheme_check, term_count

BACKEND = pathlib.Path(__file__).resolve().parents[2]
PAYLOAD = BACKEND / "seed" / "pilot_scheme_v1_criteria.json"

Q36 = {"expression": "3x^3 + 34x^2 + 84x - 72", "count": 4, "required": 3}


def _criteria(question_id: str) -> list[SimpleNamespace]:
    document = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    for question in document["questions"]:
        if question["question_id"] == question_id:
            return [SimpleNamespace(**criterion) for criterion in question["criteria"]]
    raise AssertionError(question_id)


def _component(code: str, marks: int = 1) -> SimpleNamespace:
    return SimpleNamespace(code=code, marks=marks, awarded=True)


# -- the evaluator ---------------------------------------------------------


def test_a_fully_correct_answer_meets_the_threshold() -> None:
    status, detail, matched, of = term_count.evaluate("3x^3 + 34x^2 + 84x - 72", Q36)

    assert status == term_count.SATISFIED
    assert (matched, of) == (4, 4)
    assert "3 required" in detail


def test_three_correct_terms_of_four_meet_the_printed_threshold() -> None:
    status, _detail, matched, _ = term_count.evaluate("-72 + 84x + 34x^2 + 9x^3", Q36)

    assert status == term_count.SATISFIED
    assert matched == 3


def test_two_correct_terms_do_not_meet_the_threshold() -> None:
    status, detail, matched, _ = term_count.evaluate("3x^3 + 34x^2", Q36)

    assert status == term_count.NOT_SATISFIED
    assert matched == 2
    assert "3 required" in detail


def test_a_wrong_sign_is_not_a_matching_term() -> None:
    spec = {"expression": "3x^3 - 34x^2 + 84x - 72", "count": 4, "required": 3}
    status, _, matched, _ = term_count.evaluate("3x^3 + 34x^2 + 84x - 72", spec)

    assert status == term_count.SATISFIED  # 3 of 4 match, which is the threshold
    assert matched == 3


def test_repeating_a_correct_term_cannot_meet_the_threshold() -> None:
    """A term written twice is one collected term, not two matches."""

    status, _, matched, _ = term_count.evaluate("3x^3 + 3x^3 + 84x", Q36)

    assert status == term_count.NOT_SATISFIED
    assert matched == 1


def test_a_factored_answer_is_unknown_not_satisfied() -> None:
    status, detail, matched, _ = term_count.evaluate("(x + 2)(3x^2 + 28x - 36)", Q36)

    assert status == term_count.UNKNOWN
    assert matched is None
    assert "not written as a sum of terms" in detail


@pytest.mark.parametrize("answer", ["", "   ", None, "not mathematics at all"])
def test_an_unreadable_answer_is_unknown(answer) -> None:
    assert term_count.evaluate(answer, Q36)[0] == term_count.UNKNOWN


def test_a_missing_threshold_is_unknown() -> None:
    status, detail, _, _ = term_count.evaluate("3x^3 + 34x^2 + 84x - 72", None)

    assert status == term_count.UNKNOWN
    assert "term_count is not an object" in detail


def test_a_threshold_that_miscounts_its_expression_is_unknown() -> None:
    spec = {"expression": "3x^3 + 34x^2 + 84x - 72", "count": 5, "required": 3}
    status, detail, _, _ = term_count.evaluate("3x^3 + 34x^2 + 84x - 72", spec)

    assert status == term_count.UNKNOWN
    assert "not the recorded 5" in detail


def test_an_impossible_threshold_is_refused_by_validation() -> None:
    assert term_count.validate_spec({"expression": "x + 1", "count": 2, "required": 3})
    assert term_count.validate_spec({"expression": "(x + 1)(x + 2)", "count": 1, "required": 1})
    assert term_count.validate_spec({"expression": "x + 1", "count": 2, "required": 1}) is None


# -- the approved data and the finding ------------------------------------


def test_the_pilot_records_a_threshold_for_the_two_no_working_routes() -> None:
    for question_id in ("36", "37a"):
        routes = scheme_check.alternative_routes(_criteria(question_id), question_id)
        spec = routes["B2"].term_count

        assert spec is not None, question_id
        assert term_count.validate_spec(spec) is None
        assert spec["count"] == 4
        assert spec["required"] == 3


def test_a_satisfied_route_produces_no_finding() -> None:
    findings = scheme_check.term_count_findings(
        components=[_component("B2", 2)],
        criteria=_criteria("36"),
        student_expression="3x^3 + 34x^2 + 84x - 72",
        question_id="36",
    )

    assert findings == []


def test_a_route_awarded_below_its_threshold_is_a_definite_finding() -> None:
    findings = scheme_check.term_count_findings(
        components=[_component("B2", 2)],
        criteria=_criteria("36"),
        student_expression="3x^3 + 34x^2",
        question_id="36",
    )

    assert [finding.code for finding in findings] == ["TERM_COUNT_NOT_MET"]
    assert findings[0].definite


def test_a_route_whose_answer_cannot_be_counted_is_a_possible_finding() -> None:
    findings = scheme_check.term_count_findings(
        components=[_component("B2", 2)],
        criteria=_criteria("36"),
        student_expression="(x + 2)(3x^2 + 28x - 36)",
        question_id="36",
    )

    assert [finding.code for finding in findings] == ["TERM_COUNT_UNVERIFIED"]
    assert not findings[0].definite


def test_a_route_without_a_recorded_threshold_is_reported_not_assumed() -> None:
    """Q34's one-stage route has no machine-readable threshold yet."""

    findings = scheme_check.term_count_findings(
        components=[_component("M2", 2), _component("A1")],
        criteria=_criteria("34"),
        student_expression="12x^3 - 60x^2 + 75x",
        question_id="34",
    )

    assert [finding.code for finding in findings] == ["ROUTE_THRESHOLD_UNRECORDED"]
    assert not findings[0].definite


def test_an_unawarded_route_is_not_judged_at_all() -> None:
    findings = scheme_check.term_count_findings(
        components=[_component("B2", 2), _component("A1")],
        criteria=_criteria("37a"),
        student_expression="nothing to count",
        question_id="37a",
    )

    assert [finding.code for finding in findings] == ["TERM_COUNT_UNVERIFIED"]


# -- the structure the count must respect --------------------------------
#
# The threshold is about the mathematics, not about how many fragments a string
# happens to contain.  These pin each way the two can differ.


def test_an_unrelated_extra_term_does_not_break_the_threshold() -> None:
    status, _detail, matched, of = term_count.evaluate(
        "3x^3 + 34x^2 + 84x - 72 + z", Q36
    )

    assert status == term_count.SATISFIED
    assert (matched, of) == (4, 4)


def test_extra_like_terms_change_the_coefficients_and_stop_matching() -> None:
    """``+ 100 + x`` collects into the answer's own terms, so they no longer match.

    A textual fragment count would still see the four correct fragments here; the
    mathematics says the answer is a different polynomial.
    """

    status, _detail, matched, _ = term_count.evaluate(
        "3x^3 + 34x^2 + 84x - 72 + 100 + x", Q36
    )

    assert status == term_count.NOT_SATISFIED
    assert matched == 2


def test_an_extra_wrong_term_is_written_but_never_matches() -> None:
    status, _detail, matched, _ = term_count.evaluate("3x^3 + 34x^2 + 84x + 5", Q36)

    assert status == term_count.SATISFIED
    assert matched == 3


def test_a_wrong_coefficient_is_not_a_matching_term() -> None:
    spec = {"expression": "4x^3 + 34x^2 + 84x - 72", "count": 4, "required": 3}
    status, _detail, matched, _ = term_count.evaluate(
        "3x^3 + 34x^2 + 84x - 72", spec
    )

    assert status == term_count.SATISFIED
    assert matched == 3


def test_a_wrong_power_is_not_a_matching_term() -> None:
    # ``3x^2 + 34x^2`` collects to ``37x^2``: one written term, and not the one
    # the scheme prints.
    _status, _detail, matched, _ = term_count.evaluate(
        "3x^2 + 34x^2 + 84x - 72", Q36
    )

    assert matched == 2


def test_a_product_of_sums_is_unknown_while_its_sum_is_counted() -> None:
    product = term_count.evaluate("(x + 2)(3x^2 + 28x - 36)", Q36)
    summed = term_count.evaluate("3x^3 + 34x^2 + 84x - 72", Q36)

    assert product[0] == term_count.UNKNOWN
    assert summed[0] == term_count.SATISFIED


def test_a_product_of_monomials_is_one_term_that_matches_nothing() -> None:
    """A product of monomials is a single term, not a sum — but it is countable."""

    status, _detail, matched, _ = term_count.evaluate("3x^3*34x^2*84x*-72", Q36)

    assert status == term_count.NOT_SATISFIED
    assert matched == 0


@pytest.mark.parametrize("answer", ["3x^3 + 34x^^2 - 72", "3x^3 + 34x^2 +", "=3x^3"])
def test_a_malformed_answer_is_unknown(answer: str) -> None:
    assert term_count.evaluate(answer, Q36)[0] == term_count.UNKNOWN


def test_ordering_and_grouping_brackets_do_not_change_the_count() -> None:
    for answer in (
        "-72 + 84x + 34x^2 + 3x^3",
        "(3x^3 + 34x^2 + 84x - 72)",
        "3x^3+34x^2+84x-72",
    ):
        status, _detail, matched, _ = term_count.evaluate(answer, Q36)
        assert status == term_count.SATISFIED, answer
        assert matched == 4, answer


def test_the_q34_threshold_cannot_be_recorded_as_a_written_term_count() -> None:
    """The scheme counts Q34's four *uncollected* terms; SymPy collects them.

    ``12x^3 - 30x^2 - 30x^2 + 75x`` is how the scheme prints the one-stage
    expansion, and ``3 out of 4 terms`` counts it that way.  The evaluator counts
    the collected form, so recording that spec would be refused — which is why
    Q34's route stays ``ROUTE_THRESHOLD_UNRECORDED`` (review) rather than being
    given a threshold that does not describe it.
    """

    spec = {"expression": "12x^3 - 30x^2 - 30x^2 + 75x", "count": 4, "required": 3}

    problem = term_count.validate_spec(spec)

    assert problem is not None
    assert "written term(s)" in problem
