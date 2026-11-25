"""The STUDENT_04 fresh correction's defects, reproduced from its own replies.

The audited job ``6dbc594b`` produced four refused questions, and each refusal
had a different cause.  These tests take the archived reply items — the exact
JSON the model returned — and run them through the real parsing, identity,
scheme and evidence code, so the defect classes stay fixed:

* **Q34** — every printed mark point is awarded, but the reply states a total of
  2 instead of 3.  The components are right and the total is wrong.
* **Q35** — the same arithmetic error, on a question where the approved scheme
  also carries one mark more than the paper prints.  The engine can prove the
  reply contradicts itself; it cannot see the printed maximum.
* **Q6 / Q37b** — the scheme prints two independent ``M1`` points.  A reply that
  writes ``M1`` twice has not said which point it awarded.
* **all 38 evidence rows** — quotations were stored with no page at all.

Nothing here calls a provider and nothing here edits a stored result.
"""

from __future__ import annotations

import copy
import json
import pathlib
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.correction import criterion_identity, integrity, provenance, scheme_check
from app.correction.aetrix.pipeline import omitted_leaves
from app.correction.aetrix.schema import (
    QuestionMark,
    _disambiguate_component_codes,
)
from app.correction.findings import (
    CODE_COMPONENT_ABOVE_CRITERION_MAX,
    CODE_CRITERION_NOT_IN_APPROVED_SCHEME,
    CODE_CRITERION_NOT_IN_QUESTION,
    CODE_CRITERION_REFERENCE_INVALID,
    CODE_DUPLICATE_CRITERION_AWARD,
    CODE_EVIDENCE_BBOX_INVALID,
    CODE_EVIDENCE_PAGE_INVALID,
    CODE_EVIDENCE_UNLOCATED,
    SEVERITY_DEFINITE,
)

BACKEND = pathlib.Path(__file__).resolve().parents[2]
SEED = BACKEND / "seed" / "pilot_scheme_v1_criteria.json"

#: The archived reply items, verbatim, for the four questions the audited run
#: refused.  Keeping them exact is the point: these are the inputs that produced
#: the findings a person saw.
ARCHIVED = {
    "34": {
        "question_id": "34",
        "awarded_marks": 2,
        "components": [
            {"code": "M1", "marks": 1, "awarded": True, "evidence": "4x^2 - 20x + 25"},
            {
                "code": "M1",
                "marks": 1,
                "awarded": True,
                "evidence": "3x(4x^2 - 20x + 25)",
            },
            {
                "code": "A1",
                "marks": 1,
                "awarded": True,
                "evidence": "12x^3 - 60x^2 + 75x",
            },
        ],
        "confidence": 1.0,
    },
    "35": {
        "question_id": "35",
        "awarded_marks": 2,
        "components": [
            {"code": "M1", "marks": 1, "awarded": True, "evidence": "6x^2 - 3x + 8x - 4"},
            {"code": "M1", "marks": 1, "awarded": True, "evidence": "5x(6x^2 + 5x - 4)"},
            {
                "code": "A1",
                "marks": 1,
                "awarded": True,
                "evidence": "30x^3 + 25x^2 - 20x",
            },
        ],
        "confidence": 1.0,
    },
    "6": {
        "question_id": "6",
        "awarded_marks": 1,
        "components": [
            {"code": "M1", "marks": 1, "awarded": True, "evidence": "4x^2 + 12x + 9"},
            {
                "code": "M1",
                "marks": 1,
                "awarded": False,
                "reason": "Failed to subtract the second bracket correctly (signs not handled).",
            },
            {"code": "A1", "marks": 1, "awarded": False, "reason": "Incorrect final answer."},
        ],
        "confidence": 1.0,
    },
    "37b": {
        "question_id": "37b",
        "awarded_marks": 1,
        "components": [
            {"code": "M1", "marks": 1, "awarded": True, "evidence": "a^6b^2 / a^18b^10"},
            {
                "code": "M1",
                "marks": 1,
                "awarded": False,
                "reason": "Incorrect simplification of powers.",
            },
            {"code": "A1", "marks": 1, "awarded": False, "reason": "Incorrect final answer."},
        ],
        "confidence": 1.0,
    },
}


def _scheme() -> dict[str, Any]:
    return json.loads(SEED.read_text(encoding="utf-8"))


def _criteria(question_id: str, *, scheme_version_id: Any | None = None) -> list[SimpleNamespace]:
    """The approved criteria for one question, with a stable id and ordinal.

    The seed payload is the real scheme; the ids are deterministic stand-ins for
    the database rows, because this suite does not touch a database.
    """

    document = _scheme()
    version = scheme_version_id or document["scheme_version_id"]
    for question in document["questions"]:
        if question["question_id"] == question_id:
            return [
                SimpleNamespace(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"{question_id}:{position}:{item['code']}"),
                    scheme_version_id=version,
                    question_id=question_id,
                    code=item["code"],
                    ordinal=position,
                    marks=item["marks"],
                    description=item["description"],
                    expected_answer=item.get("expected_answer"),
                    required_evidence=item.get("required_evidence"),
                    dependencies=item.get("dependencies") or [],
                    alternatives=item.get("alternatives") or [],
                    award_conditions=item.get("award_conditions"),
                    withhold_conditions=item.get("withhold_conditions"),
                )
                for position, item in enumerate(question["criteria"])
            ]
    raise AssertionError(f"question {question_id} is not in the seed payload")


def _mark(question_id: str, **overrides: Any) -> QuestionMark:
    """Parse one archived reply item exactly as the pipeline would."""

    item = copy.deepcopy(ARCHIVED[question_id])
    item.update(overrides)
    mark = QuestionMark.model_validate(item)
    _disambiguate_component_codes(mark.components)
    return mark


def _findings(question_id: str, mark: QuestionMark, max_marks: int) -> list[str]:
    criteria = _criteria(question_id)
    return [
        finding.code
        for finding in scheme_check.check_against_scheme(
            awarded=mark.awarded_marks,
            components=mark.components,
            criteria=criteria,
            question_id=question_id,
            max_marks=max_marks,
        )
    ]


def _identity(question_id: str, mark: QuestionMark):
    return criterion_identity.check_components(
        components=mark.components,
        criteria=_criteria(question_id),
        question_id=question_id,
        scheme_version_id=_scheme()["scheme_version_id"],
    )


def _statuses(resolutions) -> list[str]:
    return [resolution.status for resolution in resolutions]


# -- Q34 / Q35: the component total does not reconcile -------------------


@pytest.mark.parametrize("question_id", ["34", "35"])
def test_the_archived_reply_states_a_total_its_own_components_contradict(
    question_id: str,
) -> None:
    """Three awarded one-mark components, a stated award of 2.

    The refusal is correct: the reply's total is not the sum of the marks it
    says it awarded.  The components are the part that must survive, because a
    person needs them to see which number is wrong.
    """

    mark = _mark(question_id)

    findings = integrity.check_mark(
        awarded=mark.awarded_marks,
        max_marks=3,
        components=mark.components,
        student_answer=mark.student_answer,
        confidence=mark.confidence,
    )

    assert [finding.code for finding in findings] == ["COMPONENT_TOTAL_MISMATCH"]
    assert mark.component_total == 3
    assert mark.awarded_marks == 2


@pytest.mark.parametrize("question_id", ["34", "35"])
def test_a_pair_of_method_awards_is_not_silently_paired_with_printed_rows(
    question_id: str,
) -> None:
    """The reply awards two ``M1`` points; which row each belongs to is unknown.

    Both questions print ``M1 M1 A1``.  The reply awards both method points, so
    the *award* is not ambiguous and no ambiguity finding is raised — but the
    reply never says which printed row each component means, so neither is
    linked to one.  The parser's ``-2`` suffix is the engine's own label and is
    not treated as the reply naming the second row.

    The accuracy mark is printed once, so it does link, and that is the part of
    the reply whose provenance is provable.
    """

    mark = _mark(question_id)

    resolutions, findings = _identity(question_id, mark)

    assert _statuses(resolutions) == [
        criterion_identity.STATUS_AMBIGUOUS,
        criterion_identity.STATUS_AMBIGUOUS,
        criterion_identity.STATUS_RESOLVED,
    ]
    assert resolutions[0].criterion_id is None
    assert resolutions[1].criterion_id is None
    assert resolutions[2].criterion.ordinal == 2
    assert findings == [], "every printed point was named, so nothing is ambiguous"


@pytest.mark.parametrize("question_id", ["34", "35"])
def test_the_reply_is_not_scored_by_replacing_its_total_with_the_component_sum(
    question_id: str,
) -> None:
    """The engine refuses, and does not silently turn 2 into 3.

    Replacing the stated award with the component total would present a mark the
    model did not state.  The refusal is the whole point: the question is
    unmarked for a person, who can see three correct components and a wrong
    total.
    """

    mark = _mark(question_id)
    awarded = mark.awarded_marks

    findings = _findings(question_id, mark, max_marks=3)

    # Nothing about the scheme is wrong with this award: it fits the capacity,
    # names every point and satisfies every dependency.
    assert findings == []
    assert awarded == 2
    assert integrity.check_mark(
        awarded=awarded,
        max_marks=3,
        components=mark.components,
        student_answer=mark.student_answer,
        confidence=mark.confidence,
    ), "an unreconciled total must never be silently accepted"


def test_q35_carries_one_more_approved_mark_than_the_printed_paper_shows() -> None:
    """The upstream conflict the engine cannot see, pinned so it is not forgotten.

    The approved scheme gives Q35 three one-mark points (``M1 M1 A1``) and the
    blueprint gives it three marks; the scanned paper prints ``(2)`` beside the
    question.  Both numbers are approved data, so the disagreement is a scheme
    approval defect, not a marking defect.  The engine correctly refuses the
    reply, but it cannot name this cause: it would have to read the printed
    maximum off the page.
    """

    document = _scheme()
    question = next(item for item in document["questions"] if item["question_id"] == "35")

    assert question["max_marks"] == 3
    assert sum(item["marks"] for item in question["criteria"]) == 3
    assert [item["code"] for item in question["criteria"]] == ["M1", "M1", "A1"]


# -- Q6 / Q37b: an ambiguous code ----------------------------------------


@pytest.mark.parametrize("question_id", ["6", "37b"])
def test_a_bare_repeated_code_is_ambiguous_and_is_never_attributed(
    question_id: str,
) -> None:
    """The reply names ``M1`` twice without saying which printed point.

    One award and one withholding under one code cannot be matched to two rows:
    the engine must not read the printed order as if it were the answer.
    """

    mark = _mark(question_id)

    resolutions, _findings_from_identity = _identity(question_id, mark)

    assert resolutions[0].status == criterion_identity.STATUS_AMBIGUOUS
    assert resolutions[0].criterion is None
    assert resolutions[0].criterion_id is None
    assert resolutions[1].status == criterion_identity.STATUS_AMBIGUOUS
    # The accuracy mark has one printed point, so it is not ambiguous.
    assert resolutions[2].status == criterion_identity.STATUS_RESOLVED
    assert resolutions[2].criterion.ordinal == 2
    assert "AMBIGUOUS_CRITERION_CODE" in _findings(question_id, mark, max_marks=3)


@pytest.mark.parametrize("question_id", ["6", "37b"])
def test_naming_the_reference_resolves_the_ambiguity(question_id: str) -> None:
    """With the stable identity, the same reply is fully attributed."""

    item = copy.deepcopy(ARCHIVED[question_id])
    item["components"][0]["reference"] = "M1#1"
    item["components"][1]["reference"] = "M1#2"
    mark = QuestionMark.model_validate(item)
    _disambiguate_component_codes(mark.components)

    resolutions, findings = _identity(question_id, mark)

    assert _statuses(resolutions) == ["RESOLVED"] * 3
    assert [resolution.criterion.ordinal for resolution in resolutions] == [0, 1, 2]
    assert findings == []
    assert "AMBIGUOUS_CRITERION_CODE" not in _findings(question_id, mark, max_marks=3)


def test_a_reference_the_question_does_not_define_is_definite() -> None:
    """``M1#3`` names nothing: the question prints two method points."""

    item = copy.deepcopy(ARCHIVED["6"])
    item["components"][0]["reference"] = "M1#3"
    mark = QuestionMark.model_validate(item)

    resolutions, findings = _identity("6", mark)

    assert resolutions[0].status == criterion_identity.STATUS_UNKNOWN
    assert [finding.code for finding in findings] == [CODE_CRITERION_REFERENCE_INVALID]
    assert findings[0].severity == SEVERITY_DEFINITE


def test_an_invented_code_is_unknown_and_not_mapped_to_anything() -> None:
    item = copy.deepcopy(ARCHIVED["6"])
    item["components"] = [{"code": "Z9", "marks": 1, "awarded": True, "evidence": "x"}]
    item["awarded_marks"] = 1
    mark = QuestionMark.model_validate(item)

    resolutions, _ = _identity("6", mark)

    assert resolutions[0].status == criterion_identity.STATUS_UNKNOWN
    assert resolutions[0].criterion is None
    assert "UNKNOWN_CRITERION" in _findings("6", mark, max_marks=3)


def test_the_same_mark_point_cannot_be_awarded_twice() -> None:
    item = copy.deepcopy(ARCHIVED["6"])
    item["components"] = [
        {"code": "M1", "reference": "M1#1", "marks": 1, "awarded": True, "evidence": "a"},
        {"code": "M1", "reference": "M1#1", "marks": 1, "awarded": True, "evidence": "b"},
    ]
    item["awarded_marks"] = 2
    mark = QuestionMark.model_validate(item)

    _resolutions, findings = _identity("6", mark)

    codes = [finding.code for finding in findings]
    assert codes == [CODE_DUPLICATE_CRITERION_AWARD]
    assert findings[0].severity == SEVERITY_DEFINITE


def test_a_component_cannot_outscore_the_mark_point_it_names() -> None:
    item = copy.deepcopy(ARCHIVED["6"])
    item["components"] = [
        {"code": "A1", "reference": "A1#3", "marks": 2, "awarded": True, "evidence": "24x"}
    ]
    item["awarded_marks"] = 2
    mark = QuestionMark.model_validate(item)

    _resolutions, findings = _identity("6", mark)

    assert [finding.code for finding in findings] == [CODE_COMPONENT_ABOVE_CRITERION_MAX]
    assert findings[0].severity == SEVERITY_DEFINITE


def test_a_criterion_from_another_scheme_version_is_refused() -> None:
    """Only the approved version may decide a mark, whatever its rows say."""

    criteria = _criteria("6", scheme_version_id=uuid.uuid4())
    mark = _mark("6")

    resolutions, findings = criterion_identity.check_components(
        components=mark.components,
        criteria=criteria,
        question_id="6",
        scheme_version_id=_scheme()["scheme_version_id"],
    )

    assert all(resolution.criterion is None for resolution in resolutions)
    assert [finding.code for finding in findings] == [
        CODE_CRITERION_NOT_IN_APPROVED_SCHEME
    ]
    assert findings[0].severity == SEVERITY_DEFINITE


def test_a_criterion_from_another_question_is_refused() -> None:
    criteria = _criteria("6")
    for criterion in criteria:
        criterion.question_id = "34"
    mark = _mark("6")

    _resolutions, findings = criterion_identity.check_components(
        components=mark.components,
        criteria=criteria,
        question_id="6",
        scheme_version_id=_scheme()["scheme_version_id"],
    )

    assert [finding.code for finding in findings] == [CODE_CRITERION_NOT_IN_QUESTION]


# -- stored identity -----------------------------------------------------


def test_the_parser_reads_the_reference_from_either_field() -> None:
    """``M1#2`` in ``code`` is the same statement as ``reference: M1#2``."""

    in_code = QuestionMark.model_validate(
        {
            "question_id": "6",
            "awarded_marks": 1,
            "confidence": 0.9,
            "components": [
                {"code": "M1#2", "marks": 1, "awarded": True, "evidence": "x"}
            ],
        }
    )
    in_field = QuestionMark.model_validate(
        {
            "question_id": "6",
            "awarded_marks": 1,
            "confidence": 0.9,
            "components": [
                {
                    "code": "M1",
                    "reference": "M1#2",
                    "marks": 1,
                    "awarded": True,
                    "evidence": "x",
                }
            ],
        }
    )

    for mark in (in_code, in_field):
        assert mark.components[0].code == "M1"
        assert mark.components[0].reference == "M1#2"


def test_the_reference_is_normalised_and_kept_out_of_the_code() -> None:
    item = copy.deepcopy(ARCHIVED["6"])
    item["components"][0] = {
        "code": "m1 # 2",
        "marks": 1,
        "awarded": True,
        "evidence": "4x^2 + 12x + 9",
    }
    mark = QuestionMark.model_validate(item)

    component = mark.components[0]

    assert component.code == "m1"
    assert component.reference == "M1#2"


def test_a_referenced_component_keeps_the_code_the_scheme_prints() -> None:
    """A repeated code is not renamed when the reference already distinguishes it."""

    item = {
        "question_id": "6",
        "awarded_marks": 2,
        "confidence": 0.9,
        "components": [
            {"code": "M1", "reference": "M1#1", "marks": 1, "awarded": True, "evidence": "a"},
            {"code": "M1", "reference": "M1#2", "marks": 1, "awarded": True, "evidence": "b"},
        ],
    }
    mark = QuestionMark.model_validate(item)
    _disambiguate_component_codes(mark.components)

    assert [component.code for component in mark.components] == ["M1", "M1"]


def test_a_bare_repeated_code_is_still_disambiguated_for_storage() -> None:
    """The label a legacy-style reply gets is deterministic and preserved."""

    mark = _mark("34")

    assert [component.code for component in mark.components] == ["M1", "M1-2", "A1"]


# -- evidence provenance -------------------------------------------------


def _page(number: int, *, document_id: Any = "doc-1") -> SimpleNamespace:
    return SimpleNamespace(id=f"page-{number}", document_id=document_id, page_index=number)


def _index(*pages: SimpleNamespace, kind: str = "STUDENT") -> provenance.PageIndex:
    documents = [SimpleNamespace(id="doc-1", kind=kind)]
    return provenance.PageIndex.build(pages, documents)


def _evidence_components(**component: Any) -> list[SimpleNamespace]:
    base = {
        "code": "A1",
        "marks": 1,
        "awarded": True,
        "evidence": "24x",
        "page": None,
        "bbox": None,
    }
    base.update(component)
    return [SimpleNamespace(**base)]


def test_a_quotation_on_a_named_page_is_located() -> None:
    index = _index(_page(1), _page(2), _page(3))

    attributions, findings = provenance.attribute(
        components=_evidence_components(page=2), index=index
    )

    assert findings == []
    assert attributions[0].status == provenance.STATUS_LOCATED
    assert attributions[0].page_id == "page-2"
    assert attributions[0].page_number == 2
    assert attributions[0].document_id == "doc-1"


def test_a_quotation_with_no_page_is_unlocated_and_reported() -> None:
    """The prompt asked for a page, so a reply without one is refused."""

    index = _index(_page(1))

    attributions, findings = provenance.attribute(
        components=_evidence_components(page=None), index=index, require_page=True
    )

    assert attributions[0].page_id is None
    assert [finding.code for finding in findings] == [CODE_EVIDENCE_UNLOCATED]
    assert findings[0].severity != SEVERITY_DEFINITE, (
        "an unlocated quotation is a reason to look, not a proved contradiction"
    )


def test_a_reply_from_a_prompt_that_never_asked_for_a_page_is_not_refused() -> None:
    """An older prompt's reply is not judged against a field it never had.

    The quotation is still stored unlocated, which is a real gap — but refusing
    it would blame the model for a question the contract did not ask.
    """

    index = _index(_page(1))

    attributions, findings = provenance.attribute(
        components=_evidence_components(page=None), index=index
    )

    assert attributions[0].page_id is None
    assert findings == []


def test_a_page_the_script_does_not_have_is_a_definite_contradiction() -> None:
    index = _index(_page(1), _page(2))

    attributions, findings = provenance.attribute(
        components=_evidence_components(page=7), index=index
    )

    assert attributions[0].page_id is None
    assert attributions[0].claimed_page == 7
    assert [finding.code for finding in findings] == [CODE_EVIDENCE_PAGE_INVALID]
    assert findings[0].severity == SEVERITY_DEFINITE


def test_a_page_number_shared_by_two_documents_is_not_attributed() -> None:
    """A bare number identifies nothing when two scans both have a page 2."""

    documents = [
        SimpleNamespace(id="doc-1", kind="STUDENT"),
        SimpleNamespace(id="doc-2", kind="STUDENT"),
    ]
    index = provenance.PageIndex.build(
        [_page(2, document_id="doc-1"), _page(2, document_id="doc-2")], documents
    )

    location = index.locate(2)

    assert location.page_id is None
    assert location.status == provenance.STATUS_AMBIGUOUS_PAGE


def test_a_page_of_another_document_kind_is_not_the_students_script() -> None:
    index = _index(_page(1), kind="MARK_SCHEME")

    location = index.locate(1)

    assert location.page_id is None
    assert location.status == provenance.STATUS_NOT_STUDENT_DOCUMENT


@pytest.mark.parametrize(
    "box",
    [
        [0.0, 0.0, 1.2, 0.5],
        [0.6, 0.2, 0.4, 0.8],
        [0.1, 0.1, 0.2, 0.1],
        ["0.1", 0.2, 0.4, 0.8],
        [0.1, 0.2, 0.4],
        {"x0": 0.1, "y0": 0.2, "x1": 0.4},
    ],
)
def test_an_unusable_bounding_box_is_dropped_and_reported(box: Any) -> None:
    index = _index(_page(1))

    attributions, findings = provenance.attribute(
        components=_evidence_components(page=1, bbox=box), index=index
    )

    assert attributions[0].bbox is None, "an unreadable box is never repaired or stored"
    assert CODE_EVIDENCE_BBOX_INVALID in [finding.code for finding in findings]


def test_a_usable_bounding_box_is_kept() -> None:
    index = _index(_page(1))

    attributions, findings = provenance.attribute(
        components=_evidence_components(page=1, bbox=[0.1, 0.2, 0.4, 0.55]), index=index
    )

    assert findings == []
    assert attributions[0].bbox == [0.1, 0.2, 0.4, 0.55]


def test_a_withheld_component_is_not_judged_for_evidence() -> None:
    """No quotation means nothing to locate, so no finding either."""

    index = _index(_page(1))
    component = SimpleNamespace(
        code="M1", marks=1, awarded=False, evidence=None, page=None, bbox=None
    )

    attributions, findings = provenance.attribute(components=[component], index=index)

    assert findings == []
    assert attributions[0].page_id is None


# -- no scoreable leaf may be omitted ------------------------------------


def test_omitted_leaves_names_the_parts_of_the_paper_with_no_row() -> None:
    leaves = [("1a", 2, None, "1a"), ("1b", 3, None, "1b"), ("2", 5, None, "2")]
    rows = [SimpleNamespace(question_id="1a"), SimpleNamespace(question_id="2")]

    assert omitted_leaves(leaves, rows) == ["1b"]


def test_a_complete_paper_omits_nothing() -> None:
    leaves = [("1a", 1, None, "1a"), ("1b", 1, None, "1b")]
    rows = [SimpleNamespace(question_id="1a"), SimpleNamespace(question_id="1b")]

    assert omitted_leaves(leaves, rows) == []
