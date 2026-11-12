from __future__ import annotations

from app.correction.recovery import (
    DEFAULT_MAX_CHUNKS,
    MAX_QUESTIONS_PER_CHUNK,
    need_recovery,
    plan_recovery,
    unresolved_reason,
)


def test_a_small_gap_is_one_chunk() -> None:
    plan = plan_recovery(missing=["1", "2", "3"], scheme_questions=40)

    assert plan.blocked_reason is None
    assert [chunk.questions for chunk in plan.chunks] == [("1", "2", "3")]
    assert plan.deferred == ()


def test_a_gap_is_chunked_in_order() -> None:
    missing = [str(index) for index in range(1, 15)]

    plan = plan_recovery(missing=missing, scheme_questions=40)

    assert [len(chunk.questions) for chunk in plan.chunks] == [6, 6, 2]
    assert plan.questions == tuple(missing)
    assert [len(chunk.questions) for chunk in plan.chunks] == [
        MAX_QUESTIONS_PER_CHUNK,
        MAX_QUESTIONS_PER_CHUNK,
        2,
    ]


def test_the_chunk_budget_is_respected_across_restarts() -> None:
    missing = [str(index) for index in range(1, 60)]

    plan = plan_recovery(missing=missing, already_attempted=DEFAULT_MAX_CHUNKS)

    assert plan.chunks == ()
    assert plan.blocked_reason is not None
    assert "budget" in plan.blocked_reason


def test_a_partly_spent_budget_still_gets_the_remaining_chunks() -> None:
    missing = [str(index) for index in range(1, 20)]

    plan = plan_recovery(missing=missing, already_attempted=6)

    assert len(plan.chunks) == 2
    assert plan.deferred


def test_a_gap_covering_the_whole_paper_is_refused() -> None:
    missing = [str(index) for index in range(1, 10)]

    plan = plan_recovery(missing=missing, scheme_questions=10)

    assert plan.chunks == ()
    assert plan.deferred == tuple(missing)
    assert "whole paper" in (plan.blocked_reason or "")


def test_a_gap_just_under_the_whole_paper_threshold_is_retried() -> None:
    missing = [str(index) for index in range(1, 9)]

    plan = plan_recovery(missing=missing, scheme_questions=10)

    assert plan.chunks


def test_no_missing_questions_means_no_plan() -> None:
    plan = plan_recovery(missing=[])

    assert plan.chunks == ()
    assert plan.deferred == ()
    assert plan.blocked_reason is None


def test_recovery_rounds_stop_at_the_budget() -> None:
    allowed, _ = need_recovery(missing=["1"], already_attempted=0)
    assert allowed is True

    allowed, reason = need_recovery(missing=["1"], already_attempted=2)
    assert allowed is False
    assert reason is not None and "2 round" in reason


def test_no_gap_needs_no_round() -> None:
    allowed, reason = need_recovery(missing=[], already_attempted=0)
    assert allowed is False
    assert reason is None


def test_the_unresolved_reason_says_unmarked_not_zero() -> None:
    reason = unresolved_reason(chunks_run=1, questions_covered=6, recovered=4)

    assert "unmarked" in reason
    assert "not a confirmed zero" in reason
    assert "1 chunk" in reason
    assert "4" in reason


def test_the_unresolved_reason_carries_the_refusal() -> None:
    reason = unresolved_reason(blocked_reason="the budget is spent")

    assert "the budget is spent" in reason
