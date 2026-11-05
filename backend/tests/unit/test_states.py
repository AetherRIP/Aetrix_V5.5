from __future__ import annotations

import itertools

import pytest
from app.jobs.states import (
    ACTIVE_STATES,
    RUNNABLE_STATES,
    TERMINAL_STATES,
    IllegalTransition,
    JobState,
    can_transition,
    ensure_transition,
    is_terminal,
    progress_for,
)


def test_happy_path_reaches_completion() -> None:
    path = [
        JobState.CREATED,
        JobState.VALIDATING,
        JobState.PROCESSING_DOCUMENTS,
        JobState.BUILDING_BLUEPRINT,
        JobState.CORRECTING,
        JobState.VERIFYING,
        JobState.COHORT_PENDING,
        JobState.REVIEW_REQUIRED,
        JobState.FINALIZING,
        JobState.COMPLETED,
    ]
    for current, target in itertools.pairwise(path):
        ensure_transition(current, target)


def test_created_cannot_jump_to_completed() -> None:
    assert not can_transition(JobState.CREATED, JobState.COMPLETED)
    with pytest.raises(IllegalTransition):
        ensure_transition(JobState.CREATED, JobState.COMPLETED)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in TERMINAL_STATES:
        for target in JobState:
            assert not can_transition(state, target)


def test_retry_suspended_is_not_automatically_runnable() -> None:
    assert JobState.RETRY_SUSPENDED not in RUNNABLE_STATES
    assert JobState.RETRY_SUSPENDED in ACTIVE_STATES
    ensure_transition(JobState.RETRY_SUSPENDED, JobState.VALIDATING)


def test_cancellation_is_terminal() -> None:
    assert is_terminal(JobState.CANCELLED)
    assert can_transition(JobState.CORRECTING, JobState.CANCELLED)
    assert not can_transition(JobState.COMPLETED, JobState.CANCELLED)


def test_progress_is_monotonic_on_the_main_path() -> None:
    path = [
        JobState.CREATED,
        JobState.VALIDATING,
        JobState.PROCESSING_DOCUMENTS,
        JobState.BUILDING_BLUEPRINT,
        JobState.CORRECTING,
        JobState.VERIFYING,
        JobState.COHORT_PENDING,
        JobState.FINALIZING,
        JobState.COMPLETED,
    ]
    values = [progress_for(state) for state in path]
    assert values == sorted(values)
    assert progress_for(JobState.COMPLETED) == 1.0
