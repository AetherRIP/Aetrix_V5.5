"""What a question result is allowed to claim.

The existing ``status`` column is the API and UI contract and stays as it is.
``processing_state`` is the engine's own claim about a question, and it is
narrower on purpose: a question is either marked, a confirmed zero, untouched,
or waiting for a person.

The distinction that matters is ``UNMARKED`` versus ``CONFIRMED_ZERO``.  A
provider error, an unusable response or an exhausted retry budget leaves the
question unmarked; it must never be recorded as a zero, because a zero is a
finding about the student and an unmarked question is a finding about us.

There is one mapping.  The migration backfill, the legacy adapter and the
consistency check all read ``STATUS_TO_STATE``; nothing restates the pairs.
"""

from __future__ import annotations

from enum import StrEnum

#: The existing ``status`` value for each processing state.
_STATUS_FOR_STATE: dict[str, str] = {
    "MARKED": "AWARDED",
    "CONFIRMED_ZERO": "ZERO",
    "UNMARKED": "UNMARKED",
    "NEEDS_REVIEW": "REVIEW_REQUIRED",
}

#: The single status -> state mapping.
#: ``EXCLUDED`` questions are not scoreable, so they are recorded as unmarked
#: while keeping their own status.  A ``ZERO`` becomes ``CONFIRMED_ZERO`` only
#: when it does not still need a person; the migration carries that condition
#: explicitly because it reads rows that predate the states.
STATUS_TO_STATE: dict[str, str] = {
    "AWARDED": "MARKED",
    "ZERO": "CONFIRMED_ZERO",
    "UNMARKED": "UNMARKED",
    "REVIEW_REQUIRED": "NEEDS_REVIEW",
    "EXCLUDED": "UNMARKED",
}

#: Kept as the historical alias used by older imports.
_STATE_FOR_STATUS = STATUS_TO_STATE


class ProcessingState(StrEnum):
    MARKED = "MARKED"
    CONFIRMED_ZERO = "CONFIRMED_ZERO"
    UNMARKED = "UNMARKED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


def status_for(state: ProcessingState | str) -> str:
    return _STATUS_FOR_STATE[str(state)]


def state_for_status(status: str, *, review_required: bool = False) -> ProcessingState:
    """Best available reading of a stored row.

    A ``ZERO`` that still needs review is not a confirmed zero: the mapping says
    so, and the backfill uses the same rule.
    """

    state = STATUS_TO_STATE.get(status)
    if state is None:
        return ProcessingState.NEEDS_REVIEW
    if state == "CONFIRMED_ZERO" and review_required:
        return ProcessingState.NEEDS_REVIEW
    return ProcessingState(state)


def effective_state(
    status: str, state: str | None, *, review_required: bool = False
) -> str:
    """The explicit state, or the one a historical row's status implies.

    ``processing_state`` is nullable for rows written before the column existed,
    so every reader resolves it the same way instead of guessing.
    """

    if state:
        return state
    return state_for_status(status, review_required=review_required).value


def backfill_state_case_sql() -> str:
    """The status -> state backfill as SQL, generated from ``STATUS_TO_STATE``.

    Migration ``0023_engine_provenance`` uses this so the historical mapping and
    the live adapter cannot drift: there is one table of pairs, and both read it.
    """

    branches: list[str] = []
    for status, state in STATUS_TO_STATE.items():
        if status == "REVIEW_REQUIRED":
            # Handled by the ELSE branch, exactly like any future status.
            continue
        condition = (
            "status = 'ZERO' AND review_required = false"
            if status == "ZERO"
            else f"status = '{status}'"
        )
        branches.append(f"WHEN {condition} THEN '{state}'")
    return "CASE " + " ".join(branches) + " ELSE 'NEEDS_REVIEW' END"


def state_for_mark(
    *,
    awarded: int,
    review_required: bool,
    integrity_failed: bool,
    confidence: float | None,
    min_confidence: float,
) -> ProcessingState:
    """Classify a parsed mark.

    A zero only becomes ``CONFIRMED_ZERO`` when the model's response was usable,
    the integrity checks passed, and the confidence clears the review floor.
    Everything else that carries a mark is either ``MARKED`` or needs a person.
    """

    if review_required or integrity_failed:
        return ProcessingState.NEEDS_REVIEW
    if awarded > 0:
        return ProcessingState.MARKED
    if confidence is None or confidence < min_confidence:
        return ProcessingState.NEEDS_REVIEW
    return ProcessingState.CONFIRMED_ZERO


def ensure_consistent(status: str, state: ProcessingState | str | None) -> None:
    """Refuse a row whose two claims disagree.

    ``processing_state`` is nullable for historical rows written before the
    column existed, so ``None`` passes; a value that contradicts ``status``
    does not.
    """

    if state is None:
        return
    expected = status_for(state)
    if expected != status and not (str(state) == "UNMARKED" and status == "EXCLUDED"):
        raise ValueError(
            f"processing_state {state!s} contradicts status {status!r}; "
            f"{state!s} implies {expected!r}"
        )


def is_scoreable(state: ProcessingState | str | None) -> bool:
    """True only for a state that carries a decision about the question."""

    return str(state) in {"MARKED", "CONFIRMED_ZERO"}
