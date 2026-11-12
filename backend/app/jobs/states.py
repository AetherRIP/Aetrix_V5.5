"""Correction-job lifecycle.

The state names are part of the API contract.  Transitions are checked in one
place, and an illegal transition raises rather than being written: a job that
jumps from ``CREATED`` to ``COMPLETED`` would make the audit trail a fiction.

``RETRY_SUSPENDED`` is a deliberate parking state, not a failure.  A provider
outage or an unavailable pipeline parks the job with a reason; it is resumed by
an explicit retry, never by a silent loop.
"""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    PROCESSING_DOCUMENTS = "PROCESSING_DOCUMENTS"
    BUILDING_BLUEPRINT = "BUILDING_BLUEPRINT"
    CORRECTING = "CORRECTING"
    VERIFYING = "VERIFYING"
    COHORT_PENDING = "COHORT_PENDING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRY_SUSPENDED = "RETRY_SUSPENDED"


#: ``FAILED`` is deliberately not terminal: an operator may retry it with a fresh
#: attempt budget.  Completed and cancelled jobs admit no further transition.
TERMINAL_STATES: frozenset[JobState] = frozenset({JobState.COMPLETED, JobState.CANCELLED})

#: States a worker may claim.  ``RETRY_SUSPENDED`` is intentionally absent:
#: resuming a parked job is an explicit operator action.
RUNNABLE_STATES: frozenset[JobState] = frozenset(
    {
        JobState.CREATED,
        JobState.VALIDATING,
        JobState.PROCESSING_DOCUMENTS,
        JobState.BUILDING_BLUEPRINT,
        JobState.CORRECTING,
        JobState.VERIFYING,
        JobState.COHORT_PENDING,
        JobState.FINALIZING,
    }
)

ACTIVE_STATES: frozenset[JobState] = frozenset(
    set(RUNNABLE_STATES) | {JobState.REVIEW_REQUIRED, JobState.RETRY_SUSPENDED}
)

_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.CREATED: frozenset({JobState.VALIDATING, JobState.CANCELLED, JobState.FAILED}),
    # The worker validates and marks inside one pipeline call, so a paper with
    # nothing to review reaches FINALIZING straight from VALIDATING.  Without
    # this edge a clean run threw on completion and no job could ever finish.
    JobState.VALIDATING: frozenset(
        {
            JobState.PROCESSING_DOCUMENTS,
            JobState.REVIEW_REQUIRED,
            JobState.FINALIZING,
            JobState.RETRY_SUSPENDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.PROCESSING_DOCUMENTS: frozenset(
        {
            JobState.BUILDING_BLUEPRINT,
            JobState.REVIEW_REQUIRED,
            JobState.RETRY_SUSPENDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.BUILDING_BLUEPRINT: frozenset(
        {
            JobState.CORRECTING,
            JobState.REVIEW_REQUIRED,
            JobState.RETRY_SUSPENDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.CORRECTING: frozenset(
        {
            JobState.VERIFYING,
            JobState.REVIEW_REQUIRED,
            JobState.RETRY_SUSPENDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.VERIFYING: frozenset(
        {
            JobState.COHORT_PENDING,
            JobState.REVIEW_REQUIRED,
            JobState.FINALIZING,
            JobState.RETRY_SUSPENDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.COHORT_PENDING: frozenset(
        {
            JobState.REVIEW_REQUIRED,
            JobState.FINALIZING,
            JobState.RETRY_SUSPENDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.REVIEW_REQUIRED: frozenset({JobState.FINALIZING, JobState.FAILED, JobState.CANCELLED}),
    JobState.FINALIZING: frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset(),
    JobState.FAILED: frozenset({JobState.VALIDATING}),
    JobState.CANCELLED: frozenset(),
    JobState.RETRY_SUSPENDED: frozenset({JobState.VALIDATING, JobState.CANCELLED, JobState.FAILED}),
}

_PROGRESS: dict[JobState, float] = {
    JobState.CREATED: 0.0,
    JobState.VALIDATING: 0.05,
    JobState.PROCESSING_DOCUMENTS: 0.2,
    JobState.BUILDING_BLUEPRINT: 0.35,
    JobState.CORRECTING: 0.55,
    JobState.VERIFYING: 0.8,
    JobState.COHORT_PENDING: 0.9,
    JobState.REVIEW_REQUIRED: 0.95,
    JobState.FINALIZING: 0.98,
    JobState.COMPLETED: 1.0,
    JobState.FAILED: 1.0,
    JobState.CANCELLED: 1.0,
    JobState.RETRY_SUSPENDED: 0.95,
}


class IllegalTransition(RuntimeError):
    def __init__(self, current: JobState, target: JobState) -> None:
        super().__init__(f"illegal job transition {current} -> {target}")
        self.current = current
        self.target = target


def can_transition(current: JobState, target: JobState) -> bool:
    return target in _TRANSITIONS[current]


def ensure_transition(current: JobState, target: JobState) -> None:
    if not can_transition(current, target):
        raise IllegalTransition(current, target)


def progress_for(state: JobState) -> float:
    return _PROGRESS[state]


def is_terminal(state: JobState) -> bool:
    return state in TERMINAL_STATES


def is_runnable(state: JobState) -> bool:
    return state in RUNNABLE_STATES
