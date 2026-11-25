"""Dependency-aware, bounded parallel question correction.

The whole-paper mode asks for every leaf in one request; the per-question mode
asks for one leaf at a time, sequentially.  This module adds the third mode the
engine supports: the *same* per-question request and the *same* strict contract,
but independent questions are corrected concurrently under a bounded worker
pool.

Three rules make the concurrency safe rather than merely faster:

* **The paper is planned first.**  Every scoreable leaf becomes one task, in
  blueprint order.  Two leaves with the same identifier are a blueprint defect
  and are reported, never silently de-duplicated.
* **Dependencies are preserved.**  Sub-questions of one parent are chained in
  paper order: a later part can carry method marks that follow through from an
  earlier part, so it is never dispatched before that part has a stored
  decision.  Separate parent questions are independent and run together.  The
  blueprint expresses no cross-question dependency beyond this structure, and
  the scheduler does not invent one.
* **Aggregation is deterministic.**  Totals are computed from stored rows in
  blueprint order, and a paper with a missing, duplicated or over-maximum
  question is reported as incomplete instead of being totalled as if it were
  whole.

Nothing here calls a provider or touches an ORM object: the caller supplies the
request function (run on a worker thread) and the accept function (which parses,
validates and persists one reply, always on the calling thread).  Keeping every
database write on one thread is what makes the concurrency safe.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

#: The mode name recorded on a job and on every result row it produces.
MODE_PARALLEL = "PARALLEL"

#: What one task did.  ``ACCEPTED`` means a row was stored for the question.
STATUS_ACCEPTED = "ACCEPTED"
STATUS_UNUSABLE = "UNUSABLE"
STATUS_FAILED = "FAILED"
STATUS_BLOCKED = "BLOCKED"

_TERMINAL_OK = frozenset({STATUS_ACCEPTED})


class ParallelPlanError(RuntimeError):
    """The blueprint cannot be distributed: it names one question twice."""


@dataclass(frozen=True, slots=True)
class QuestionTask:
    """One scoreable leaf, its place in the paper and what must precede it."""

    question_id: str
    parent_id: str
    max_marks: int
    answer_type: str | None
    order: int
    depends_on: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "parent_id": self.parent_id,
            "max_marks": self.max_marks,
            "order": self.order,
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True, slots=True)
class ParallelPlan:
    """The complete task set and the deterministic waves it executes in."""

    tasks: tuple[QuestionTask, ...]
    waves: tuple[tuple[QuestionTask, ...], ...]
    duplicates: tuple[str, ...]

    @property
    def question_ids(self) -> tuple[str, ...]:
        return tuple(task.question_id for task in self.tasks)

    def task(self, question_id: str) -> QuestionTask:
        for task in self.tasks:
            if task.question_id == question_id:
                return task
        raise KeyError(question_id)

    def describe(self) -> dict[str, Any]:
        return {
            "mode": MODE_PARALLEL,
            "questions": len(self.tasks),
            "waves": len(self.waves),
            "wave_sizes": [len(wave) for wave in self.waves],
            "dependencies": {
                task.question_id: list(task.depends_on)
                for task in self.tasks
                if task.depends_on
            },
            "duplicates": list(self.duplicates),
        }


def build_plan(leaves: Iterable[tuple[str, int, str | None, str]]) -> ParallelPlan:
    """Plan one paper from its scoreable leaves, in the order they are listed.

    The leaves arrive as ``(question_id, max_marks, answer_type, parent_id)`` —
    exactly the tuple the marking engine already uses.  Leaves sharing a parent
    are chained in that order; a leaf with no siblings depends on nothing.
    """

    ordered: list[tuple[str, int, str | None, str]] = list(leaves)
    counts: dict[str, int] = defaultdict(int)
    for question_id, _max_marks, _answer_type, _parent_id in ordered:
        counts[question_id] += 1
    duplicates = tuple(sorted(qid for qid, count in counts.items() if count > 1))

    previous_by_parent: dict[str, str] = {}
    tasks: list[QuestionTask] = []
    for order, (question_id, max_marks, answer_type, parent_id) in enumerate(ordered):
        previous = previous_by_parent.get(parent_id)
        depends_on: tuple[str, ...] = (previous,) if previous is not None else ()
        # A leaf that shares its own identifier as a parent (the usual case for a
        # question without sub-parts) must not depend on itself.
        if previous is not None and previous == question_id:
            depends_on = ()
        previous_by_parent[parent_id] = question_id
        tasks.append(
            QuestionTask(
                question_id=question_id,
                parent_id=parent_id,
                max_marks=max_marks,
                answer_type=answer_type,
                order=order,
                depends_on=depends_on,
            )
        )

    depth: dict[str, int] = {}
    for task in tasks:
        if not task.depends_on:
            depth[task.question_id] = 0
            continue
        depth[task.question_id] = depth.get(task.depends_on[0], 0) + 1
    buckets: dict[int, list[QuestionTask]] = defaultdict(list)
    for task in tasks:
        buckets[depth[task.question_id]].append(task)
    waves = tuple(tuple(buckets[index]) for index in sorted(buckets))

    return ParallelPlan(tasks=tuple(tasks), waves=waves, duplicates=duplicates)


@dataclass(frozen=True, slots=True)
class RequestFailure:
    """A provider request that produced no reply, with what to report."""

    error_class: str
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    question_id: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.status in _TERMINAL_OK


@dataclass
class ParallelExecution:
    """What one parallel pass over a paper did."""

    outcomes: dict[str, TaskOutcome]
    waves: int
    requested: int
    peak_in_flight: int
    cancelled: bool = False

    def accepted(self) -> list[str]:
        return [
            task_id
            for task_id, outcome in self.outcomes.items()
            if outcome.status == STATUS_ACCEPTED
        ]

    def failures(self) -> list[TaskOutcome]:
        return [
            outcome
            for outcome in self.outcomes.values()
            if outcome.status in {STATUS_FAILED, STATUS_UNUSABLE}
        ]

    def describe(self) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        for outcome in self.outcomes.values():
            counts[outcome.status] += 1
        return {
            "mode": MODE_PARALLEL,
            "waves_executed": self.waves,
            "requests": self.requested,
            "peak_in_flight": self.peak_in_flight,
            "accepted": len(self.accepted()),
            "status_counts": dict(sorted(counts.items())),
            "cancelled": self.cancelled,
            "failures": [
                {"question_id": failure.question_id, **failure.detail}
                for failure in self.failures()
            ][:20],
        }


def execute(
    plan: ParallelPlan,
    *,
    request: Callable[[QuestionTask], Any],
    accept: Callable[[QuestionTask, Any], TaskOutcome],
    max_concurrency: int,
    should_stop: Callable[[], bool] | None = None,
) -> ParallelExecution:
    """Run the plan wave by wave, at most ``max_concurrency`` requests at once.

    ``request`` runs on a worker thread and must not touch the calling thread's
    database session: it performs the provider call (on its own session) and
    returns whatever ``accept`` needs.  ``accept`` always runs on the calling
    thread, in blueprint order, so parsing, validation and persistence stay
    single-threaded and one question cannot corrupt another's rows.

    A request that raises is handed to ``accept`` as a ``RequestFailure``: a
    failed question is recorded as failed and the rest of the paper continues.
    A question whose prerequisite was not accepted is never dispatched; it is
    reported as ``BLOCKED`` so the paper cannot claim a decision it never made.
    """

    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    outcomes: dict[str, TaskOutcome] = {}
    requested = 0
    peak_in_flight = 0
    in_flight = 0
    lock = threading.Lock()

    def counters() -> None:
        nonlocal in_flight, peak_in_flight
        with lock:
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)

    def release() -> None:
        nonlocal in_flight
        with lock:
            in_flight = max(0, in_flight - 1)

    def call(task: QuestionTask) -> Any:
        counters()
        try:
            return request(task)
        except Exception as error:
            # Reported as a failed question, never swallowed: a worker crash must
            # not take the paper with it.
            return RequestFailure(
                error_class=type(error).__name__,
                message=str(error)[:500],
                retryable=bool(getattr(error, "retryable", False)),
            )
        finally:
            release()

    waves_run = 0
    for wave in plan.waves:
        if should_stop is not None and should_stop():
            return ParallelExecution(
                outcomes=outcomes,
                waves=waves_run,
                requested=requested,
                peak_in_flight=peak_in_flight,
                cancelled=True,
            )
        runnable: list[QuestionTask] = []
        for task in wave:
            blocked = [
                dependency
                for dependency in task.depends_on
                if outcomes.get(dependency) is None
                or not outcomes[dependency].accepted
            ]
            if blocked:
                outcomes[task.question_id] = TaskOutcome(
                    question_id=task.question_id,
                    status=STATUS_BLOCKED,
                    detail={
                        "reason": "DEPENDENCY_NOT_ACCEPTED",
                        "depends_on": blocked,
                    },
                )
                continue
            runnable.append(task)
        if not runnable:
            continue

        waves_run += 1
        requested += len(runnable)
        with ThreadPoolExecutor(
            max_workers=min(max_concurrency, len(runnable))
        ) as executor:
            futures = {task.question_id: executor.submit(call, task) for task in runnable}
            replies = {question_id: future.result() for question_id, future in futures.items()}

        if should_stop is not None and should_stop():
            return ParallelExecution(
                outcomes=outcomes,
                waves=waves_run,
                requested=requested,
                peak_in_flight=peak_in_flight,
                cancelled=True,
            )
        # Persist in blueprint order, whatever order the requests finished in.
        for task in runnable:
            reply = replies[task.question_id]
            try:
                outcome = accept(task, reply)
            except Exception as error:
                # A defect while storing one reply is recorded against that
                # question; the other questions keep their decisions.
                outcome = TaskOutcome(
                    question_id=task.question_id,
                    status=STATUS_FAILED,
                    detail={
                        "error_class": type(error).__name__,
                        "message": str(error)[:500],
                    },
                )
            outcomes[task.question_id] = outcome

    return ParallelExecution(
        outcomes=outcomes,
        waves=waves_run,
        requested=requested,
        peak_in_flight=peak_in_flight,
        cancelled=False,
    )


@dataclass(frozen=True, slots=True)
class QuestionTotal:
    question_id: str
    parent_id: str
    max_marks: int
    awarded: int | None
    processing_state: str | None
    review_required: bool

    def describe(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "parent_id": self.parent_id,
            "max_marks": self.max_marks,
            "awarded": self.awarded,
            "processing_state": self.processing_state,
            "review_required": self.review_required,
        }


@dataclass(frozen=True, slots=True)
class PaperTotals:
    """The deterministic aggregation of one paper's stored rows."""

    questions: tuple[QuestionTotal, ...]
    awarded: int
    maximum: int
    decided: int
    awaiting_review: int
    missing: tuple[str, ...]
    duplicates: tuple[str, ...]
    over_max: tuple[str, ...]
    complete: bool

    def describe(self) -> dict[str, Any]:
        return {
            "questions": len(self.questions),
            "decided": self.decided,
            "awaiting_review": self.awaiting_review,
            "awarded": self.awarded,
            "maximum": self.maximum,
            "missing": list(self.missing),
            "duplicates": list(self.duplicates),
            "over_max": list(self.over_max),
            "complete": self.complete,
            "rows": [question.describe() for question in self.questions],
        }


def aggregate(
    plan: ParallelPlan,
    rows: Iterable[Any],
) -> PaperTotals:
    """Total the stored rows in blueprint order, refusing an inconsistent paper.

    A row is read for its identifier, award, maximum and state; nothing is
    repaired.  A question with no row is missing, a question with two rows is
    duplicated, and an award above its maximum is reported — each of them makes
    the paper incomplete.  An authoritative total is never produced from a paper
    that does not add up.
    """

    by_question: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        by_question[str(row.question_id)].append(row)

    questions: list[QuestionTotal] = []
    missing: list[str] = []
    duplicates: list[str] = []
    over_max: list[str] = []
    awarded_total = 0
    maximum_total = 0
    decided = 0
    awaiting_review = 0

    for task in plan.tasks:
        found = by_question.get(task.question_id, [])
        if not found:
            missing.append(task.question_id)
            questions.append(
                QuestionTotal(
                    question_id=task.question_id,
                    parent_id=task.parent_id,
                    max_marks=task.max_marks,
                    awarded=None,
                    processing_state=None,
                    review_required=True,
                )
            )
            continue
        if len(found) > 1:
            duplicates.append(task.question_id)
        row = found[0]
        awarded = getattr(row, "awarded_marks", None)
        max_marks = int(getattr(row, "max_marks", None) or task.max_marks)
        state = getattr(row, "processing_state", None)
        review_required = bool(getattr(row, "review_required", False))
        if awarded is None:
            missing.append(task.question_id)
        else:
            awarded = int(awarded)
            if awarded > max_marks:
                over_max.append(task.question_id)
            awarded_total += awarded
            maximum_total += max_marks
            decided += 1
            if review_required:
                awaiting_review += 1
        questions.append(
            QuestionTotal(
                question_id=task.question_id,
                parent_id=task.parent_id,
                max_marks=max_marks,
                awarded=awarded if awarded is None else int(awarded),
                processing_state=str(state) if state is not None else None,
                review_required=review_required,
            )
        )

    complete = not missing and not duplicates and not over_max and decided == len(plan.tasks)
    return PaperTotals(
        questions=tuple(questions),
        awarded=awarded_total,
        maximum=maximum_total,
        decided=decided,
        awaiting_review=awaiting_review,
        missing=tuple(missing),
        duplicates=tuple(duplicates),
        over_max=tuple(over_max),
        complete=complete,
    )


__all__ = [
    "MODE_PARALLEL",
    "STATUS_ACCEPTED",
    "STATUS_BLOCKED",
    "STATUS_FAILED",
    "STATUS_UNUSABLE",
    "PaperTotals",
    "ParallelExecution",
    "ParallelPlan",
    "ParallelPlanError",
    "QuestionTask",
    "QuestionTotal",
    "RequestFailure",
    "TaskOutcome",
    "aggregate",
    "build_plan",
    "execute",
]
