from __future__ import annotations

from types import SimpleNamespace

from app.correction.integrity import check_mark, duplicate_codes


def _component(code: str, marks: int, awarded: bool, evidence: str | None = None):
    return SimpleNamespace(code=code, marks=marks, awarded=awarded, evidence=evidence)


def _codes(findings) -> set[str]:
    return {finding.code for finding in findings}


def test_a_clean_mark_has_no_findings() -> None:
    findings = check_mark(
        awarded=2,
        max_marks=2,
        components=[
            _component("M1", 1, True, "4x^2 + 12x"),
            _component("A1", 1, True, "24x - 9"),
        ],
        student_answer="24x - 9",
        confidence=0.95,
    )

    assert findings == []


def test_a_negative_award_is_a_finding() -> None:
    findings = check_mark(
        awarded=-1, max_marks=3, components=[], student_answer="x", confidence=0.9
    )
    assert "NEGATIVE_AWARD" in _codes(findings)


def test_an_award_above_the_maximum_is_a_finding() -> None:
    findings = check_mark(
        awarded=5, max_marks=3, components=[], student_answer="x", confidence=0.9
    )
    assert "AWARD_ABOVE_MAXIMUM" in _codes(findings)


def test_a_component_total_that_contradicts_the_award_is_a_finding() -> None:
    findings = check_mark(
        awarded=2,
        max_marks=3,
        components=[_component("M1", 1, True, "2x^2"), _component("M1-2", 1, False)],
        student_answer="x",
        confidence=0.9,
    )
    assert "COMPONENT_TOTAL_MISMATCH" in _codes(findings)


def test_an_award_beyond_the_components_capacity_is_a_finding() -> None:
    findings = check_mark(
        awarded=3,
        max_marks=3,
        components=[_component("M1", 1, True, "2x^2"), _component("A1", 1, True, "3x")],
        student_answer="3x",
        confidence=0.9,
    )
    assert "AWARD_EXCEEDS_COMPONENT_CAPACITY" in _codes(findings)


def test_marks_for_a_blank_answer_without_evidence_are_a_finding() -> None:
    findings = check_mark(
        awarded=2,
        max_marks=2,
        components=[_component("M1", 1, True), _component("A1", 1, True)],
        student_answer=None,
        confidence=0.9,
    )
    assert "MARKS_FOR_BLANK_ANSWER" in _codes(findings)


def test_a_blank_answer_with_quoted_evidence_is_not_flagged() -> None:
    findings = check_mark(
        awarded=2,
        max_marks=2,
        components=[
            _component("M1", 1, True, "x^2 + 2x"),
            _component("A1", 1, True, "x(x + 2)"),
        ],
        student_answer="",
        confidence=0.9,
    )
    assert findings == []


def test_an_awarded_component_worth_no_marks_is_a_finding() -> None:
    findings = check_mark(
        awarded=0,
        max_marks=3,
        components=[_component("M1", 0, True, "some working")],
        student_answer="x",
        confidence=0.9,
    )
    assert "AWARDED_COMPONENT_WITH_NO_MARKS" in _codes(findings)


def test_duplicate_codes_are_reported_as_context() -> None:
    components = [
        _component("M1", 1, True, "a"),
        _component("M1", 1, True, "b"),
        _component("A1", 1, False),
    ]

    assert duplicate_codes(components) == ["M1"]
    assert duplicate_codes([_component("M1", 1, True, "a")]) == []
