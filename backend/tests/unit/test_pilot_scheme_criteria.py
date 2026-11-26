"""The pilot's transcribed criteria must cover the paper exactly, or not ship.

The payload in ``seed/`` is what the marking engine will be given instead of
reopening the scanned scheme.  These tests pin it to the paper it was transcribed
from: 39 scoreable questions, 89 marks, no invented mark point, and an answer the
SymPy scheme check can read wherever the scheme states one unambiguously.
"""

from __future__ import annotations

import copy
import json
import pathlib
from types import SimpleNamespace

import pytest
from app.correction import scheme_check
from app.correction.scheme_criteria import (
    blueprint_leaves,
    children_by_parent,
    iter_criteria,
    validate,
)

BACKEND = pathlib.Path(__file__).resolve().parents[2]
PAYLOAD = BACKEND / "seed" / "pilot_scheme_v1_criteria.json"

#: The blueprint's scoreable leaves and their marks, restated here on purpose: a
#: transcription error must fail against a second, independent statement of the
#: paper rather than only against itself.
EXPECTED_LEAVES: dict[str, tuple[str, ...] | None] = {
    "1": ("1a", "1d"),
    "2": None,
    "3": None,
    "4": None,
    "5": None,
    "6": None,
    "7": None,
    "8": None,
    "9": None,
    "10": None,
    "11": None,
    "12": None,
    "13": None,
    "14": None,
    "15": None,
    "16": ("16b",),
    "17": None,
    "18": None,
    "19": None,
    "20": None,
    "21": None,
    "22": None,
    "23": None,
    "24": None,
    "25": None,
    "26": None,
    "27": None,
    "28": None,
    "29": None,
    "30": None,
    "31": None,
    "32": None,
    "33": None,
    "34": None,
    "35": None,
    "36": None,
    "37": ("37a", "37b"),
}

LEAF_MARKS = {
    "1a": 1,
    "1d": 2,
    "2": 1,
    "3": 2,
    "4": 2,
    "5": 1,
    "6": 3,
    "7": 2,
    "8": 2,
    "9": 2,
    "10": 2,
    "11": 3,
    "12": 2,
    "13": 3,
    "14": 2,
    "15": 1,
    "16b": 1,
    "17": 2,
    "18": 3,
    "19": 2,
    "20": 2,
    "21": 2,
    "22": 2,
    "23": 3,
    "24": 2,
    "25": 2,
    "26": 3,
    "27": 3,
    "28": 3,
    "29": 2,
    "30": 3,
    "31": 3,
    "32": 3,
    "33": 2,
    "34": 3,
    "35": 3,
    "36": 3,
    "37a": 3,
    "37b": 3,
}


def _payload() -> dict:
    return json.loads(PAYLOAD.read_text(encoding="utf-8"))


def _structure() -> dict:
    questions = []
    for parent, subquestions in EXPECTED_LEAVES.items():
        if subquestions:
            questions.append(
                {
                    "question_id": parent,
                    "max_marks": sum(LEAF_MARKS[sub] for sub in subquestions),
                    "excluded": False,
                    "subquestions": [
                        {
                            "question_id": sub,
                            "max_marks": LEAF_MARKS[sub],
                            "excluded": False,
                        }
                        for sub in subquestions
                    ],
                }
            )
            continue
        questions.append(
            {
                "question_id": parent,
                "max_marks": LEAF_MARKS[parent],
                "excluded": False,
                "subquestions": [],
            }
        )
    return {"questions": questions, "total_marks": sum(LEAF_MARKS.values())}


def test_the_paper_is_thirty_nine_leaves_and_eighty_nine_marks() -> None:
    leaves = blueprint_leaves(_structure())

    assert len(leaves) == 39
    assert sum(leaves.values()) == 89


def test_the_payload_covers_every_leaf_with_exactly_the_paper_marks() -> None:
    report = validate(_payload(), _structure())

    assert report.complete, report.problems
    assert len(report.lines) == 39
    assert report.total_expected == 89
    assert report.total_criteria == 89


def test_the_payload_names_only_scoreable_leaves_and_the_paper_total() -> None:
    payload = _payload()

    assert payload["total_marks"] == 89
    assert {entry["question_id"] for entry in payload["questions"]} == set(LEAF_MARKS)
    for entry in payload["questions"]:
        assert entry["max_marks"] == LEAF_MARKS[entry["question_id"]]


def test_every_leaf_carries_the_mark_points_the_scheme_prints() -> None:
    payload = _payload()

    for entry in payload["questions"]:
        criteria = entry["criteria"]
        assert criteria, entry["question_id"]
        assert sum(item["marks"] for item in criteria) == entry["max_marks"], entry["question_id"]
        # The printed codes are B, M and A points only; nothing invented.
        assert {item["code"][0] for item in criteria} <= {"B", "M", "A"}
        assert all(item["description"].strip() for item in criteria)
        assert all(item["source_quote"].strip() for item in criteria)


def test_an_alternative_scheme_never_doubles_the_marks() -> None:
    payload = _payload()

    for entry in payload["questions"]:
        for item in entry["criteria"]:
            for alternative in item["alternatives"]:
                assert alternative.get("marks", 0) <= entry["max_marks"], entry["question_id"]


def test_a_dropped_mark_point_is_reported_rather_than_accepted() -> None:
    payload = _payload()
    damaged = copy.deepcopy(payload)
    entry = next(item for item in damaged["questions"] if item["question_id"] == "1d")
    entry["criteria"].pop()

    report = validate(damaged, _structure())

    assert not report.complete
    assert any("'1d'" in problem and "blueprint" in problem for problem in report.problems)


def test_a_question_left_with_no_mark_points_is_reported() -> None:
    payload = _payload()
    damaged = copy.deepcopy(payload)
    next(item for item in damaged["questions"] if item["question_id"] == "2")["criteria"] = []

    report = validate(damaged, _structure())

    assert not report.complete
    assert any("'2'" in problem and "no mark points" in problem for problem in report.problems)


def test_a_missing_question_is_reported() -> None:
    payload = _payload()
    damaged = copy.deepcopy(payload)
    damaged["questions"] = [
        entry for entry in damaged["questions"] if entry["question_id"] != "16b"
    ]

    report = validate(damaged, _structure())

    assert not report.complete
    assert any("16b" in problem for problem in report.problems)


def test_the_importer_numbers_mark_points_positionally_and_keeps_the_source() -> None:
    rows = list(iter_criteria(_payload()))

    assert len(rows) == 89
    for question_id in {row["question_id"] for row in rows}:
        ordinals = [row["ordinal"] for row in rows if row["question_id"] == question_id]
        assert ordinals == list(range(len(ordinals))), question_id
    assert all(1 <= row["source_page"] <= 21 for row in rows)
    assert all(row["source_ref"]["item"] for row in rows)


def test_the_sympy_scheme_check_can_read_the_answer_for_every_question_it_can() -> None:
    """38 of 39 answers are single-letter algebra this build can compare.

    Q19's answer contains the product ``5xy``, which the parser reads as one
    symbol, so a comparison there would be wrong rather than silent.  It is left
    unreadable on purpose: the check is skipped, never guessed.
    """

    by_question: dict[str, list[SimpleNamespace]] = {}
    for row in iter_criteria(_payload()):
        by_question.setdefault(row["question_id"], []).append(
            SimpleNamespace(
                code=row["code"],
                marks=row["marks"],
                description=row["description"],
                award_conditions=row["award_conditions"],
            )
        )

    readable, unreadable = [], []
    for question_id, criteria in by_question.items():
        found = scheme_check.scheme_expected_expression(criteria)
        (readable if found else unreadable).append(question_id)

    assert unreadable == ["19"]
    assert len(readable) == 38
    assert by_question.get("16b")


def test_the_scheme_check_accepts_the_printed_answer_and_rejects_another() -> None:
    criteria = [
        SimpleNamespace(
            code="A1",
            marks=1,
            description=row["description"],
            award_conditions=row["award_conditions"],
        )
        for row in iter_criteria(_payload())
        if row["question_id"] == "29"
    ]

    agreed = scheme_check.check_answer_against_scheme(
        student_expression="2x^2 + 29x", criteria=criteria
    )
    disagreed = scheme_check.check_answer_against_scheme(
        student_expression="2x^2 + 28x", criteria=criteria
    )

    assert agreed.status == "EQUIVALENT"
    assert disagreed.status == "DIFFERENT"
    assert agreed.expected_criterion == "A1"


def test_a_parent_question_names_the_leaves_its_pages_belong_to() -> None:
    parents = children_by_parent(_structure())

    assert parents == {"1": ["1a", "1d"], "16": ["16b"], "37": ["37a", "37b"]}


def test_every_question_page_is_inside_the_scanned_scheme() -> None:
    payload = _payload()

    pages = {entry["source_ref"]["pdf_page"] for entry in payload["questions"]}
    assert min(pages) >= 2  # page 1 is the cover
    assert max(pages) <= payload["source"]["pages"]


def test_the_payload_records_the_scheme_it_was_read_from() -> None:
    payload = _payload()

    assert payload["scheme_version_id"] == "93eece22-864a-4de1-90e8-e37500ff2392"
    assert payload["blueprint_version_id"] == "c371be84-d4a0-46de-a81d-38effccc2d15"
    assert payload["source"]["sha256"].startswith("bb89f80b")


def test_the_coverage_report_names_the_shortfall_when_a_question_is_short() -> None:
    payload = _payload()
    damaged = copy.deepcopy(payload)
    entry = next(item for item in damaged["questions"] if item["question_id"] == "6")
    entry["criteria"] = entry["criteria"][:2]

    report = validate(damaged, _structure())

    assert not report.complete
    shortfall = {line["question_id"]: line for line in report.describe()["shortfall"]}
    assert shortfall["6"]["expected"] == 3
    assert shortfall["6"]["recorded"] == 2
    assert report.total_criteria == 88


def test_every_printed_depends_on_condition_is_recorded_as_a_dependency() -> None:
    """A printed ``dep (ft)`` is data, not prose the verifier has to guess at."""

    payload = _payload()
    dependent = {
        entry["question_id"]
        for entry in payload["questions"]
        if any(item["dependencies"] for item in entry["criteria"])
    }

    assert dependent == {
        "18",
        "23",
        "26",
        "27",
        "30",
        "31",
        "32",
        "34",
        "35",
        "36",
        "37a",
    }
    for entry in payload["questions"]:
        codes = {item["code"] for item in entry["criteria"]}
        for item in entry["criteria"]:
            assert set(item["dependencies"]) <= codes, entry["question_id"]
            if item["description"].startswith("Depends"):
                assert item["dependencies"] == ["M1"], entry["question_id"]


def test_a_dependency_on_an_undefined_code_is_refused() -> None:
    payload = _payload()
    damaged = copy.deepcopy(payload)
    entry = next(item for item in damaged["questions"] if item["question_id"] == "18")
    entry["criteria"][1]["dependencies"] = ["M9"]

    report = validate(damaged, _structure())

    assert not report.complete
    assert any("M9" in problem for problem in report.problems)


def test_an_alternative_m2_route_is_understood_by_the_scheme_check() -> None:
    """Question 18 prints ``M1 M1 A1`` and also allows ``M2 A1``."""

    criteria = [
        SimpleNamespace(
            code=row["code"],
            marks=row["marks"],
            description=row["description"],
            award_conditions=row["award_conditions"],
            dependencies=row["dependencies"],
            alternatives=row["alternatives"],
        )
        for row in iter_criteria(_payload())
        if row["question_id"] == "18"
    ]

    assert scheme_check.scheme_capacity(criteria) == 3
    assert scheme_check.alternative_codes(criteria) == ["M2"]

    findings = scheme_check.check_against_scheme(
        awarded=3,
        components=[
            SimpleNamespace(code="M2", awarded=True, marks=2),
            SimpleNamespace(code="A1", awarded=True, marks=1),
        ],
        criteria=criteria,
        question_id="18",
        max_marks=3,
    )

    assert findings == []


@pytest.mark.parametrize("question_id", sorted(LEAF_MARKS))
def test_each_leaf_has_a_printed_reference(question_id: str) -> None:
    payload = _payload()
    entry = next(item for item in payload["questions"] if item["question_id"] == question_id)

    assert entry["source_ref"]["item"].split(".")[0].strip()
    assert isinstance(entry["source_ref"]["pdf_page"], int)


# -- the corrections an independent audit of the printed pages required ----------
#
# Each test below pins one printed cell of the scheme against the payload, so the
# same fault cannot come back: a tolerance the scheme does not print may not be
# added, and one it does print may not be dropped.
REVIEW = BACKEND / "seed" / "pilot_scheme_v1_review.md"


def _entry(question_id: str) -> dict:
    return next(item for item in _payload()["questions"] if item["question_id"] == question_id)


def _mark_point(question_id: str, index: int) -> dict:
    return _entry(question_id)["criteria"][index]


def test_q4_records_only_the_tolerances_the_scheme_prints() -> None:
    """The scheme prints three correct terms, or four with signs excepted. Nothing else."""

    description = _mark_point("4", 0)["description"]

    assert description == (
        "Any three of the four product terms of (t - 4)(t + 5) correct, "
        "or all four terms correct except for signs"
    )
    assert "partial simplification" not in description
    assert "t^2 + t + k" not in description


def test_q13_second_method_mark_keeps_both_printed_tolerances() -> None:
    """Both the ignoring-signs route and the ``allow`` form are printed."""

    mark_point = _mark_point("13", 1)
    description = mark_point["description"]

    assert "all four terms correct ignoring signs" in description
    assert "-2x^2 - 7x - 15" in description
    assert "subtraction" not in description
    assert "ignoring signs" in mark_point["source_quote"]


def test_q6_second_method_mark_is_the_printed_negative_sign_point() -> None:
    """The scheme prints no alternative method for Q6, so none may be recorded."""

    mark_point = _mark_point("6", 1)

    assert mark_point["description"] == (
        "For dealing correctly with the negative sign, "
        "eg (2x + 3 + 2x - 3)(2x + 3 - 2x + 3)"
    )
    assert mark_point["alternatives"] == []
    assert "difference of two squares" not in json.dumps(_payload())


def test_q1d_accuracy_mark_keeps_the_printed_cao() -> None:
    assert _mark_point("1d", 1)["award_conditions"] == "cao"


def test_q34_second_method_mark_keeps_the_bracket_first_routes() -> None:
    """The printed cell gives the bracket-first order and its 2-out-of-3 tolerance."""

    description = _mark_point("34", 1)["description"]

    assert "product of (2x - 5) and (2x - 5) multiplied by 3x" in description
    assert "3 of 4 or 2 of 3 terms correct" in description
    assert "12x^3 - 60x^2 ... / ... - 60x^2 + 75x" in description


def test_q27_second_method_mark_keeps_the_two_out_of_three_tolerance() -> None:
    assert "3 of 4 or 2 of 3 terms correct" in _mark_point("27", 1)["description"]


def test_q19_keeps_the_non_zero_requirement_for_c_and_for_d() -> None:
    description = _mark_point("19", 0)["description"]

    assert "for any non-zero c" in description
    assert "for any non-zero d" in description


def test_q16b_names_only_the_question_it_represents() -> None:
    assert _entry("16b")["source_ref"]["item"] == "16. Jan 18/4H/Q10 b"


def test_the_extraction_notes_explain_why_the_pilot_totals_eighty_nine() -> None:
    """89 is the paper's scoreable total; the scheme prints 91 because of Q16d."""

    notes = " ".join(_payload()["extraction"]["notes"])

    assert "16(d)" in notes
    assert "91" in notes
    assert "excluded_scheme_entries.csv" in notes


def test_the_extraction_notes_record_the_two_printed_typos() -> None:
    notes = " ".join(_payload()["extraction"]["notes"])

    assert "Q5" in notes
    assert "Q14" in notes
    assert "x2 + 2x" in notes


def test_the_review_documents_the_exclusion_and_no_longer_claims_a_q6_alternative() -> None:
    text = REVIEW.read_text(encoding="utf-8")

    assert "difference of two squares" not in text
    assert "Q13 carries a printed prose alternative" in text
    assert "91 printed" in text


def test_the_pilots_cao_is_enforced_rather_than_only_stored() -> None:
    """Q1d prints ``cao``: the verifier must act on it, not merely display it."""

    criteria = [
        SimpleNamespace(
            code=row["code"],
            marks=row["marks"],
            description=row["description"],
            award_conditions=row["award_conditions"],
        )
        for row in iter_criteria(_payload())
        if row["question_id"] == "1d"
    ]

    printed = scheme_check.check_answer_against_scheme(
        student_expression="y^2 + 8y - 20", criteria=criteria
    )
    factorised = scheme_check.check_answer_against_scheme(
        student_expression="(y + 10)(y - 2)", criteria=criteria
    )

    assert printed.correct_answer_only
    assert printed.printed_form
    assert factorised.status == "EQUIVALENT"
    assert not factorised.printed_form

    findings = scheme_check.scheme_math_findings(
        factorised,
        awarded=2,
        max_marks=2,
        components=[
            SimpleNamespace(code="M1", awarded=True, marks=1),
            SimpleNamespace(code="A1", awarded=True, marks=1),
        ],
        criteria=criteria,
        question_id="1d",
    )

    assert [finding.code for finding in findings] == ["SCHEME_ANSWER_NOT_CAO"]
    assert findings[0].definite


# -- the alternative routes the scheme prints beside its primary points ---------
#
# The review that corrected seven transcription faults found three printed routes
# still unregistered: Q34's one-stage M2 and the B2 a no-working answer earns on
# Q36 and Q37a.  An unregistered route made the verifier call a valid award an
# unknown mark point and an unmet dependency, so each is pinned here.


def _scheme_criteria(question_id: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            code=row["code"],
            marks=row["marks"],
            description=row["description"],
            award_conditions=row["award_conditions"],
            dependencies=row["dependencies"],
            alternatives=row["alternatives"],
        )
        for row in iter_criteria(_payload())
        if row["question_id"] == question_id
    ]


def _awarded(code: str, marks: int = 1) -> SimpleNamespace:
    return SimpleNamespace(code=code, awarded=True, marks=marks)


def _withheld(code: str, marks: int = 1) -> SimpleNamespace:
    return SimpleNamespace(code=code, awarded=False, marks=marks)


def test_q34_registers_the_printed_one_stage_m2_route() -> None:
    """The cell prints ``award M2 for 3 out of 4 terms correct`` in one stage."""

    criteria = _scheme_criteria("34")
    mark_point = _mark_point("34", 1)

    assert scheme_check.alternative_codes(criteria) == ["M2"]
    assert mark_point["alternatives"] == [
        {
            "code": "M2",
            "marks": 2,
            "rule": "expansion in one stage without firstly expanding two factors: "
            "3 out of 4 terms correct (M1 for 2 out of 4 terms correct)",
            # The one-stage route stands in for the two printed method marks, so
            # the two-stage method marks cannot be awarded beside it.
            "replaces": ["M1"],
        }
    ]
    assert scheme_check.scheme_capacity(criteria) == 3
    assert "Expansion in one stage will lead to 12x3 - 30x2 - 30x2 + 75x" in (
        mark_point["source_quote"]
    )

    findings = scheme_check.check_against_scheme(
        awarded=3,
        components=[_awarded("M2", 2), _awarded("A1")],
        criteria=criteria,
        question_id="34",
        max_marks=3,
    )

    assert findings == []


def test_q36_registers_the_printed_no_working_b2_route() -> None:
    """``If no working shown then award B2 for 3 out of a maximum of 4 terms``."""

    criteria = _scheme_criteria("36")

    # The 8-term expansion route (M2) is printed beside the method marks; the B2
    # no-working route is printed inside the accuracy mark's own cell.
    assert scheme_check.alternative_codes(criteria) == ["M2", "B2"]
    assert _mark_point("36", 2)["alternatives"][0]["code"] == "B2"
    assert _mark_point("36", 2)["alternatives"][0]["marks"] == 2
    assert "award B2 for 3 out of a maximum of 4 terms correct" in (
        _mark_point("36", 2)["source_quote"]
    )

    findings = scheme_check.check_against_scheme(
        awarded=2,
        components=[_awarded("B2", 2)],
        criteria=criteria,
        question_id="36",
        max_marks=3,
    )

    assert findings == []


def test_q37a_registers_the_printed_no_working_b2_route() -> None:
    criteria = _scheme_criteria("37a")

    assert scheme_check.alternative_codes(criteria) == ["B2"]
    assert _mark_point("37a", 2)["alternatives"][0]["code"] == "B2"
    assert _mark_point("37a", 2)["alternatives"][0]["marks"] == 2
    assert "oe but must be simplified eg 22x - 3x3 - 7x2 + 8" in (
        _mark_point("37a", 2)["source_quote"]
    )
    assert "award B2 for 3 out of a maximum of 4 terms correct" in (
        _mark_point("37a", 2)["source_quote"]
    )

    findings = scheme_check.check_against_scheme(
        awarded=2,
        components=[_awarded("B2", 2)],
        criteria=criteria,
        question_id="37a",
        max_marks=3,
    )

    assert findings == []


def test_registering_an_alternative_does_not_stop_the_dependency_check() -> None:
    """Q36's follow-through mark still needs the first method mark."""

    criteria = _scheme_criteria("36")
    findings = scheme_check.check_against_scheme(
        awarded=1,
        components=[_awarded("M1FT")],
        criteria=criteria,
        question_id="36",
        max_marks=3,
    )

    unmet = [finding for finding in findings if finding.code == "UNMET_DEPENDENCY"]
    assert len(unmet) == 1
    assert unmet[0].definite


def test_the_primary_route_of_a_question_with_an_alternative_still_passes() -> None:
    criteria = _scheme_criteria("36")
    findings = scheme_check.check_against_scheme(
        awarded=3,
        components=[_awarded("M1"), _awarded("M1"), _awarded("A1")],
        criteria=criteria,
        question_id="36",
        max_marks=3,
    )

    assert findings == []


# -- a dependent point is judged on its own award --------------------------------
#
# The pilot prints a follow-through mark in eleven questions.  Checking the whole
# question's earned marks against the requirement meant a reply that awarded the
# first method mark and stopped was told it had failed a prerequisite it never
# claimed.  These tests pin the check to the dependent award itself.
DEPENDENT_LEAVES = (
    "18",
    "23",
    "26",
    "27",
    "30",
    "31",
    "32",
    "34",
    "35",
    "36",
    "37a",
)


@pytest.mark.parametrize("question_id", DEPENDENT_LEAVES)
def test_nothing_awarded_is_never_an_unmet_dependency(question_id: str) -> None:
    """A zero award that lists the criteria withheld every point, including the
    dependent one, so there is no award to test against its prerequisite."""

    findings = scheme_check.check_against_scheme(
        awarded=0,
        components=[_withheld("M1"), _withheld("M1"), _withheld("A1")],
        criteria=_scheme_criteria(question_id),
        question_id=question_id,
        max_marks=3,
    )

    assert findings == []


@pytest.mark.parametrize("question_id", DEPENDENT_LEAVES)
def test_the_first_method_mark_alone_has_no_follow_through_to_judge(
    question_id: str,
) -> None:
    """One ``M1`` and the accuracy mark: the follow-through was withheld."""

    findings = scheme_check.check_against_scheme(
        awarded=2,
        components=[_awarded("M1"), _awarded("A1")],
        criteria=_scheme_criteria(question_id),
        question_id=question_id,
        max_marks=3,
    )

    assert findings == []


@pytest.mark.parametrize("question_id", DEPENDENT_LEAVES)
def test_a_follow_through_without_its_prerequisite_is_a_definite_mismatch(
    question_id: str,
) -> None:
    """``M1FT`` is the dependent point itself, awarded without the mark it follows."""

    findings = scheme_check.check_against_scheme(
        awarded=1,
        components=[_awarded("M1FT")],
        criteria=_scheme_criteria(question_id),
        question_id=question_id,
        max_marks=3,
    )

    unmet = [finding for finding in findings if finding.code == "UNMET_DEPENDENCY"]
    assert len(unmet) == 1
    assert unmet[0].definite


@pytest.mark.parametrize("question_id", DEPENDENT_LEAVES)
def test_the_primary_route_passes_every_dependent_leaf(question_id: str) -> None:
    findings = scheme_check.check_against_scheme(
        awarded=3,
        components=[_awarded("M1"), _awarded("M1"), _awarded("A1")],
        criteria=_scheme_criteria(question_id),
        question_id=question_id,
        max_marks=3,
    )

    assert findings == []


def test_a_no_working_route_cannot_be_awarded_with_a_follow_through() -> None:
    """Q36's ``B2`` is the no-working route: it stands in for the method marks.

    The route is printed in the accuracy cell, but it answers the question with no
    working shown, so no method mark — and no follow-through — can be earned
    beside it.  Both contradictions are reported: the dependent mark has no
    prerequisite, and the route conflicts with the marks it replaces.
    """

    findings = scheme_check.check_against_scheme(
        awarded=3,
        components=[_awarded("B2", 2), _awarded("M1FT")],
        criteria=_scheme_criteria("36"),
        question_id="36",
        max_marks=3,
    )

    assert [finding.code for finding in findings] == [
        "UNMET_DEPENDENCY",
        "ROUTE_CONFLICT",
    ]


def test_an_alternative_route_supplies_the_marks_a_later_point_depends_on() -> None:
    """Q34's ``M2`` is the printed two-method-mark route, so its ``A1`` still stands."""

    criteria = _scheme_criteria("34")
    findings = scheme_check.check_against_scheme(
        awarded=3,
        components=[_awarded("M2", 2), _awarded("A1")],
        criteria=criteria,
        question_id="34",
        max_marks=3,
    )

    assert findings == []


def test_an_alternative_route_does_not_add_capacity() -> None:
    """Every printed route stays inside the question's three marks."""

    for question_id, code in (("34", "M2"), ("36", "M2"), ("36", "B2"), ("37a", "B2")):
        criteria = _scheme_criteria(question_id)
        assert scheme_check.scheme_capacity(criteria) == 3
        over = scheme_check.check_against_scheme(
            awarded=4,
            components=[_awarded(code, 2), _awarded("M1"), _awarded("A1")],
            criteria=criteria,
            question_id=question_id,
            max_marks=3,
        )
        assert "OVER_SCHEME_CAPACITY" in [finding.code for finding in over]
