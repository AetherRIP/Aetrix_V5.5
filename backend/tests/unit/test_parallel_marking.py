"""Parallel correction: planning, bounded execution and deterministic totals.

These tests exercise the scheduler without a database or a provider.  They pin
the properties the mode exists for: independent questions really run at the same
time, dependent questions never overtake their prerequisite, a failed question
does not take the paper with it, persistence order is the paper's order, and a
paper that does not add up is reported incomplete rather than totalled.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from app.core.config import MarkingSettings
from app.correction.aetrix.parallel import (
    MODE_PARALLEL,
    STATUS_ACCEPTED,
    STATUS_BLOCKED,
    STATUS_FAILED,
    RequestFailure,
    TaskOutcome,
    aggregate,
    build_plan,
    execute,
)
from pydantic import ValidationError


def _leaf(question_id: str, parent_id: str, max_marks: int = 1):
    return (question_id, max_marks, None, parent_id)


def _row(
    question_id: str,
    *,
    awarded: int | None,
    max_marks: int = 1,
    state: str = "MARKED",
    review: bool = False,
):
    return SimpleNamespace(
        question_id=question_id,
        awarded_marks=awarded,
        max_marks=max_marks,
        processing_state=state,
        review_required=review,
    )


def _accept_ok(task, _reply) -> TaskOutcome:
    return TaskOutcome(task.question_id, STATUS_ACCEPTED, {})


def _accept_failure(task, reply) -> TaskOutcome:
    if isinstance(reply, RequestFailure):
        return TaskOutcome(
            task.question_id, STATUS_FAILED, {"reason": reply.error_class}
        )
    return TaskOutcome(task.question_id, STATUS_ACCEPTED, {})


# -- planning -----------------------------------------------------------


def test_the_plan_keeps_paper_order_and_chains_siblings() -> None:
    plan = build_plan(
        [_leaf("1b", "1"), _leaf("2", "2"), _leaf("1a", "1")]
    )

    # The plan follows the caller's blueprint order, not lexical order: 1b is
    # listed before 1a precisely so a reordering defect cannot hide.
    assert plan.question_ids == ("1b", "2", "1a")
    assert plan.task("2").depends_on == ()
    # Two leaves sharing parent 1 are chained in the order they arrive.
    assert plan.task("1a").depends_on == ("1b",)


def test_questions_without_siblings_do_not_depend_on_themselves() -> None:
    plan = build_plan([_leaf("1", "1"), _leaf("2", "2")])

    assert [task.depends_on for task in plan.tasks] == [(), ()]


def test_separate_parent_questions_share_the_first_wave() -> None:
    plan = build_plan([_leaf("1a", "1"), _leaf("2", "2"), _leaf("1b", "1")])

    assert [set(task.question_id for task in wave) for wave in plan.waves] == [
        {"1a", "2"},
        {"1b"},
    ]
    assert plan.describe()["wave_sizes"] == [2, 1]


def test_duplicate_identifiers_are_reported_not_deduplicated() -> None:
    plan = build_plan([_leaf("1a", "1"), _leaf("1a", "1")])

    assert plan.duplicates == ("1a",)
    # Both tasks remain: silently dropping one would hide a blueprint defect.
    assert len(plan.tasks) == 2


# -- execution ----------------------------------------------------------


def test_independent_questions_are_requested_concurrently() -> None:
    plan = build_plan([_leaf("1a", "1"), _leaf("2", "2"), _leaf("1b", "1")])
    # Both first-wave questions must be inside the provider call at once, or the
    # barrier times out.  A sequential implementation fails this test.
    gate = threading.Barrier(2, timeout=5.0)

    def request(task):
        gate.wait()
        return task.question_id

    execution = execute(
        plan,
        request=request,
        accept=_accept_ok,
        max_concurrency=3,
    )

    assert execution.peak_in_flight == 2
    assert execution.waves == 2
    assert set(execution.accepted()) == {"1a", "2", "1b"}


def test_a_failed_prerequisite_blocks_only_its_dependents() -> None:
    plan = build_plan([_leaf("1a", "1"), _leaf("2", "2"), _leaf("1b", "1")])
    requested: list[str] = []

    def request(task):
        requested.append(task.question_id)
        if task.question_id == "1a":
            raise RuntimeError("provider client defect")
        return task.question_id

    execution = execute(
        plan,
        request=request,
        accept=_accept_failure,
        max_concurrency=2,
    )

    assert "1b" not in requested
    assert execution.outcomes["1a"].status == STATUS_FAILED
    assert execution.outcomes["1b"].status == STATUS_BLOCKED
    assert execution.outcomes["2"].status == STATUS_ACCEPTED
    assert execution.outcomes["1b"].detail["depends_on"] == ["1a"]


def test_replies_are_accepted_in_paper_order_whatever_finishes_first() -> None:
    plan = build_plan([_leaf("1a", "1"), _leaf("2", "2")])
    accepted: list[str] = []

    def request(task):
        # The first question is deliberately the slower one.
        time.sleep(0.15 if task.question_id == "1a" else 0.0)
        return task.question_id

    def accept(task, _reply):
        accepted.append(task.question_id)
        return TaskOutcome(task.question_id, STATUS_ACCEPTED, {})

    execute(plan, request=request, accept=accept, max_concurrency=2)

    assert accepted == ["1a", "2"]


def test_cancellation_stops_before_the_next_wave() -> None:
    plan = build_plan([_leaf("1a", "1"), _leaf("2", "2"), _leaf("1b", "1")])
    calls = {"stop": 0}

    def should_stop() -> bool:
        calls["stop"] += 1
        return calls["stop"] > 1

    execution = execute(
        plan,
        request=lambda task: task.question_id,
        accept=_accept_ok,
        max_concurrency=2,
        should_stop=should_stop,
    )

    assert execution.cancelled is True
    assert execution.waves == 1
    assert "1b" not in execution.outcomes


def test_concurrency_below_one_is_refused() -> None:
    plan = build_plan([_leaf("1", "1")])

    with pytest.raises(ValueError):
        execute(plan, request=lambda task: None, accept=_accept_ok, max_concurrency=0)


# -- aggregation --------------------------------------------------------


def test_aggregation_totals_in_order_and_reports_missing() -> None:
    plan = build_plan([_leaf("1a", "1", 2), _leaf("1b", "1", 3), _leaf("2", "2", 5)])

    totals = aggregate(
        plan,
        [
            # Rows arrive in whatever order persistence finished; totals must not.
            _row("2", awarded=5, max_marks=5),
            _row("1a", awarded=2, max_marks=2),
        ],
    )

    assert [question.question_id for question in totals.questions] == ["1a", "1b", "2"]
    assert totals.awarded == 7
    assert totals.maximum == 7
    assert totals.decided == 2
    assert totals.missing == ("1b",)
    assert totals.complete is False
    assert totals.describe()["complete"] is False


def test_aggregation_refuses_an_award_above_the_maximum() -> None:
    plan = build_plan([_leaf("1a", "1", 2)])

    totals = aggregate(plan, [_row("1a", awarded=3, max_marks=2)])

    assert totals.over_max == ("1a",)
    assert totals.complete is False
    assert totals.awarded == 3


def test_aggregation_reports_duplicate_rows() -> None:
    plan = build_plan([_leaf("1a", "1", 2)])

    totals = aggregate(
        plan,
        [_row("1a", awarded=1, max_marks=2), _row("1a", awarded=2, max_marks=2)],
    )

    assert totals.duplicates == ("1a",)
    assert totals.complete is False


def test_a_complete_paper_counts_marks_awaiting_review() -> None:
    plan = build_plan([_leaf("1a", "1", 2), _leaf("2", "2", 5)])

    totals = aggregate(
        plan,
        [
            _row("1a", awarded=1, max_marks=2, state="NEEDS_REVIEW", review=True),
            _row("2", awarded=5, max_marks=5),
        ],
    )

    assert totals.complete is True
    assert totals.awarded == 6
    assert totals.awaiting_review == 1


# -- configuration ------------------------------------------------------


def test_parallel_mode_is_selectable_with_a_bounded_concurrency() -> None:
    settings = MarkingSettings(marking_mode=MODE_PARALLEL, parallel_max_concurrency=4)

    assert settings.marking_mode == "PARALLEL"
    assert settings.parallel_max_concurrency == 4

    with pytest.raises(ValidationError):
        MarkingSettings(parallel_max_concurrency=0)
    with pytest.raises(ValidationError):
        MarkingSettings(parallel_max_concurrency=9)
    with pytest.raises(ValidationError):
        MarkingSettings(marking_mode="PARALLEL_KEYS")
