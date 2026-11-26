"""The verification policy: which questions the checkers must examine.

Checking is expensive, so the policy decides attention deterministically.  These
tests pin the properties that matter: a known over-awarded question is always
checked, risk always escalates to REQUIRED, required checks are never dropped to
fit a budget, and an unavailable checker is reported rather than skipped.
"""

from __future__ import annotations

from app.core.verification_policy import (
    EVIDENCE,
    KNOWN_OVER_AWARD_QUESTIONS,
    TRANSCRIPTION,
    QuestionFacts,
    Reason,
    Severity,
    plan,
    unavailable_checkers,
)


def _facts(question_id: str = "1a", **overrides) -> QuestionFacts:
    base = {"question_id": question_id, "awarded_marks": 1, "max_marks": 3}
    base.update(overrides)
    return QuestionFacts(**base)


def test_a_clean_low_mark_question_is_not_checked_without_sampling():
    result = plan([_facts("1a", awarded_marks=1, max_marks=4)], job_key="job-1")
    assert result.decisions[0].severity is Severity.SAMPLE
    assert result.decisions[0].checkers == ()
    assert result.required_questions == ()


def test_a_known_over_awarded_question_is_always_required():
    """The historical Ch2 L3 failures are standing regressions, not anecdotes."""

    for question_id in sorted(KNOWN_OVER_AWARD_QUESTIONS):
        result = plan([_facts(question_id, awarded_marks=0, max_marks=4)], job_key="j")
        decision = result.decisions[0]
        assert decision.severity is Severity.REQUIRED, question_id
        assert Reason.HISTORICAL_OVER_AWARD.value in decision.reasons
        assert set(decision.checkers) == {TRANSCRIPTION, EVIDENCE}


def test_high_marks_require_an_evidence_check():
    result = plan([_facts("2", awarded_marks=3, max_marks=3)], job_key="j")
    decision = result.decisions[0]
    assert decision.required
    assert Reason.HIGH_MARKS.value in decision.reasons
    assert EVIDENCE in decision.checkers


def test_transcription_disagreement_requires_both_checkers():
    result = plan([_facts("3", transcription_status="DIFFERS")], job_key="j")
    assert set(result.decisions[0].checkers) == {TRANSCRIPTION, EVIDENCE}


def test_unverifiable_evidence_requires_a_blind_rereading():
    result = plan([_facts("4", transcription_status="UNVERIFIABLE")], job_key="j")
    decision = result.decisions[0]
    assert decision.required
    assert decision.checkers == (TRANSCRIPTION,)


def test_a_mathematical_failure_requires_evidence_review():
    result = plan([_facts("5", mathematical_status="FAIL")], job_key="j")
    assert Reason.MATHEMATICAL_FAILURE.value in result.decisions[0].reasons
    assert EVIDENCE in result.decisions[0].checkers


def test_low_confidence_reading_requires_a_blind_rereading():
    result = plan([_facts("6", confidence=0.4)], job_key="j")
    assert Reason.TRANSCRIPTION_AMBIGUOUS.value in result.decisions[0].reasons
    assert result.decisions[0].checkers == (TRANSCRIPTION,)


def test_criterion_disagreement_and_unsupported_steps_require_evidence():
    for facts, reason in (
        (_facts("7", criterion_disagreement=True), Reason.CRITERION_DISAGREEMENT),
        (_facts("8", unsupported_steps=2), Reason.UNUSUAL_ANSWER),
    ):
        decision = plan([facts], job_key="j").decisions[0]
        assert decision.required
        assert reason.value in decision.reasons
        assert EVIDENCE in decision.checkers


def test_sampling_is_stable_for_the_same_paper():
    """A re-run must not check a different set and look better by chance."""

    facts = [_facts(str(index), awarded_marks=0, max_marks=3) for index in range(40)]
    first = plan(facts, job_key="job-a", sample_rate=0.5, request_budget=100)
    second = plan(facts, job_key="job-a", sample_rate=0.5, request_budget=100)
    other = plan(facts, job_key="job-b", sample_rate=0.5, request_budget=100)
    assert first.as_report() == second.as_report()
    sampled_first = {d.question_id for d in first.decisions if d.checkers}
    sampled_other = {d.question_id for d in other.decisions if d.checkers}
    assert sampled_first != sampled_other


def test_full_sample_rate_checks_every_question():
    facts = [_facts(str(index), awarded_marks=0, max_marks=3) for index in range(5)]
    result = plan(facts, job_key="j", sample_rate=1.0)
    assert len(result.decisions) == 5
    assert all(d.checkers == (TRANSCRIPTION,) for d in result.decisions)


def test_required_checks_survive_a_budget_that_only_covers_samples():
    """The budget trims samples, never a required check."""

    facts = [_facts("13", awarded_marks=0, max_marks=3)]  # required
    facts += [_facts(str(index), awarded_marks=0, max_marks=3) for index in range(10)]
    result = plan(facts, job_key="j", sample_rate=1.0, request_budget=1)
    assert "13" in result.required_questions
    assert result.dropped_samples
    assert sum(len(d.checkers) for d in result.decisions) <= 2


def test_an_unavailable_checker_is_reported_not_skipped():
    facts = [_facts("13")]
    result = plan(facts, job_key="j")
    missing = unavailable_checkers(
        result, transcription_available=True, evidence_available=False
    )
    assert missing == ("13:evidence",)
    assert "13" in result.required_questions


def test_an_unchecked_question_is_not_reported_as_verified():
    facts = [_facts("1a", awarded_marks=0, max_marks=3)]
    result = plan(facts, job_key="j")
    assert result.checkers_for("1a") == ()
    assert result.checkers_for("missing-question") == ()
    report = result.as_report()
    assert report["checking_requests"] == 0
    assert report["required_questions"] == []
