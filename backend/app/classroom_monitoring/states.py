"""The two state machines of automatic submission monitoring.

A submission's *pipeline* state and its *correction* state are separate on
purpose.  ``READY`` with a correction in ``FAILED`` means usable work whose
marking hit a provider problem; merging the two would let an outage look like
unreadable work, and would let a resubmission overwrite the evidence of what an
earlier version did.

Every transition is checked here.  An illegal move raises rather than being
written, because a persisted impossible sequence makes the audit trail a
fiction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ..core.errors import AppError, ErrorCode


class SubmissionState(StrEnum):
    DETECTED = "DETECTED"
    DOWNLOADING = "DOWNLOADING"
    INSPECTING = "INSPECTING"
    READY = "READY"
    IGNORED = "IGNORED"
    NEEDS_TEACHER = "NEEDS_TEACHER"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


class CorrectionState(StrEnum):
    NOT_QUEUED = "NOT_QUEUED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


#: ``READY`` may still become ``NEEDS_TEACHER`` when the mark scheme is withdrawn
#: between inspection and queueing; the work itself did not change.
_TRANSITIONS: dict[SubmissionState, frozenset[SubmissionState]] = {
    SubmissionState.DETECTED: frozenset(
        {
            SubmissionState.DOWNLOADING,
            SubmissionState.IGNORED,
            SubmissionState.FAILED,
            SubmissionState.SUPERSEDED,
        }
    ),
    SubmissionState.DOWNLOADING: frozenset(
        {
            SubmissionState.INSPECTING,
            SubmissionState.IGNORED,
            SubmissionState.NEEDS_TEACHER,
            SubmissionState.FAILED,
            SubmissionState.SUPERSEDED,
        }
    ),
    SubmissionState.INSPECTING: frozenset(
        {
            SubmissionState.READY,
            SubmissionState.IGNORED,
            SubmissionState.NEEDS_TEACHER,
            SubmissionState.FAILED,
            SubmissionState.SUPERSEDED,
        }
    ),
    SubmissionState.READY: frozenset(
        {
            SubmissionState.NEEDS_TEACHER,
            SubmissionState.IGNORED,
            SubmissionState.SUPERSEDED,
        }
    ),
    SubmissionState.NEEDS_TEACHER: frozenset(
        {
            SubmissionState.READY,
            SubmissionState.IGNORED,
            SubmissionState.SUPERSEDED,
        }
    ),
    SubmissionState.IGNORED: frozenset({SubmissionState.SUPERSEDED}),
    SubmissionState.FAILED: frozenset(
        {
            SubmissionState.DOWNLOADING,
            SubmissionState.NEEDS_TEACHER,
            SubmissionState.IGNORED,
            SubmissionState.SUPERSEDED,
        }
    ),
    # Superseded is final: a resubmission creates a new version row instead.
    SubmissionState.SUPERSEDED: frozenset(),
}

_CORRECTION_TRANSITIONS: dict[CorrectionState, frozenset[CorrectionState]] = {
    CorrectionState.NOT_QUEUED: frozenset({CorrectionState.QUEUED, CorrectionState.FAILED}),
    CorrectionState.QUEUED: frozenset(
        {
            CorrectionState.PROCESSING,
            CorrectionState.REVIEW_REQUIRED,
            CorrectionState.COMPLETED,
            CorrectionState.FAILED,
        }
    ),
    CorrectionState.PROCESSING: frozenset(
        {
            CorrectionState.REVIEW_REQUIRED,
            CorrectionState.COMPLETED,
            CorrectionState.FAILED,
        }
    ),
    CorrectionState.REVIEW_REQUIRED: frozenset({CorrectionState.COMPLETED, CorrectionState.FAILED}),
    CorrectionState.COMPLETED: frozenset(),
    CorrectionState.FAILED: frozenset({CorrectionState.QUEUED}),
}


def can_transition(current: str, target: str) -> bool:
    try:
        state = SubmissionState(current)
        return SubmissionState(target) in _TRANSITIONS[state]
    except ValueError:
        return False


def transition(version: Any, target: SubmissionState) -> bool:
    """Move a version row to ``target``, refusing an illegal sequence.

    Returns ``True`` when the row changed.  Re-applying the current state is a
    no-op so a resumed run is safe.
    """

    current = version.state
    if current == target.value:
        return False
    if not can_transition(current, target.value):
        raise AppError(
            ErrorCode.CLASSROOM_SUBMISSION_STATE_INVALID,
            f"A submission cannot move from {current} to {target.value}.",
            details={"from": current, "to": target.value},
        )
    version.state = target.value
    return True


#: A cancelled marking job is not a failure of the work, so it maps to the
#: state that lets a teacher retry deliberately.
_JOB_STATE_TO_CORRECTION: dict[str, CorrectionState] = {
    "CREATED": CorrectionState.QUEUED,
    "VALIDATING": CorrectionState.PROCESSING,
    "PROCESSING_DOCUMENTS": CorrectionState.PROCESSING,
    "BUILDING_BLUEPRINT": CorrectionState.PROCESSING,
    "CORRECTING": CorrectionState.PROCESSING,
    "VERIFYING": CorrectionState.PROCESSING,
    "COHORT_PENDING": CorrectionState.PROCESSING,
    "FINALIZING": CorrectionState.PROCESSING,
    "REVIEW_REQUIRED": CorrectionState.REVIEW_REQUIRED,
    "COMPLETED": CorrectionState.COMPLETED,
    "FAILED": CorrectionState.FAILED,
    "RETRY_SUSPENDED": CorrectionState.FAILED,
    "CANCELLED": CorrectionState.FAILED,
}


def correction_state_for(job_state: str | None) -> CorrectionState:
    return _JOB_STATE_TO_CORRECTION.get(job_state or "", CorrectionState.FAILED)


def set_correction_state(version: Any, target: CorrectionState) -> bool:
    """Move the correction state, allowing the observability-only changes.

    The correction state is a projection of the existing job, so a job that
    moves more than once between two polls (queued -> processing -> completed)
    must not make the projection raise.  Only a move *out of* a terminal state
    is refused.
    """

    current = version.correction_state
    if current == target.value:
        return False
    try:
        state = CorrectionState(current)
    except ValueError:
        state = CorrectionState.NOT_QUEUED
    if state is CorrectionState.COMPLETED:
        return False
    if state is CorrectionState.FAILED and target is CorrectionState.PROCESSING:
        return False
    # A skip forward is still a truthful projection of the job, so it is
    # recorded rather than refused: the job, not this projection, is the
    # authority.  Only the two moves above would make the projection lie.
    version.correction_state = target.value
    return True
