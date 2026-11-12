"""Targeted recovery for questions the marker did not resolve.

Recovery re-marks only the questions that came back unusable, in bounded
chunks, under a budget that is recorded on the job so a restart never spends it
twice.  Successful work is never re-run and an existing valid row is never
overwritten.

Two gaps are refused on purpose rather than retried:

* a gap covering essentially the whole paper is a failed run or a broken
  blueprint, not a marker omission;
* a gap beyond the chunk budget stays unresolved for a person.

Nothing here decides a mark.  It decides whether another attempt is allowed and
what to tell the teacher about the questions that are still open.
"""

from __future__ import annotations

from dataclasses import dataclass

#: One retry request re-marks at most this many questions, so recovery cost is
#: proportional to the gap rather than to the paper.
MAX_QUESTIONS_PER_CHUNK = 6

#: How many retry requests one job may spend.  8 x 6 covers a 48-question gap,
#: larger than any genuine marker omission seen on a real paper.
DEFAULT_MAX_CHUNKS = 8

#: Rounds persisted on the job; a restart continues rather than starting over.
DEFAULT_MAX_ROUNDS = 2

#: A gap this large is the paper, not a gap.
WHOLE_PAPER_GAP_SHARE = 0.9


@dataclass(frozen=True, slots=True)
class RecoveryChunk:
    index: int
    questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    chunks: tuple[RecoveryChunk, ...]
    deferred: tuple[str, ...]
    blocked_reason: str | None = None

    @property
    def questions(self) -> tuple[str, ...]:
        return tuple(question for chunk in self.chunks for question in chunk.questions)


def plan_recovery(
    *,
    missing: list[str] | tuple[str, ...],
    chunk_size: int = MAX_QUESTIONS_PER_CHUNK,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    already_attempted: int = 0,
    scheme_questions: int | None = None,
) -> RecoveryPlan:
    """Turn a gap into bounded retry requests, or explain why none may run."""

    ordered = [str(question) for question in missing if str(question).strip()]
    if not ordered:
        return RecoveryPlan(chunks=(), deferred=())

    if scheme_questions and scheme_questions > 0:
        threshold = max(2, int(scheme_questions * WHOLE_PAPER_GAP_SHARE))
        if len(ordered) >= threshold:
            return RecoveryPlan(
                chunks=(),
                deferred=tuple(ordered),
                blocked_reason=(
                    f"{len(ordered)} of the paper's {scheme_questions} questions came "
                    "back without a usable result. That is essentially the whole paper, "
                    "which points at a failed run or an incomplete blueprint rather "
                    "than a marker omission. A targeted retry cannot fix it."
                ),
            )

    remaining = max(0, int(max_chunks) - max(0, int(already_attempted)))
    if remaining <= 0:
        return RecoveryPlan(
            chunks=(),
            deferred=tuple(ordered),
            blocked_reason=(
                f"The targeted retry already used its budget of {max_chunks} "
                "request(s); the remaining questions stay unmarked pending a person."
            ),
        )

    size = max(1, int(chunk_size))
    pieces = [ordered[index : index + size] for index in range(0, len(ordered), size)]
    chunks = tuple(
        RecoveryChunk(index=index, questions=tuple(piece))
        for index, piece in enumerate(pieces[:remaining])
    )
    deferred = tuple(question for piece in pieces[remaining:] for question in piece)
    return RecoveryPlan(chunks=chunks, deferred=deferred)


def need_recovery(
    *,
    missing: list[str] | tuple[str, ...],
    already_attempted: int,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> tuple[bool, str | None]:
    """Whether another automatic round may run, and why not when it may not."""

    if not missing:
        return False, None
    if already_attempted >= max(1, int(max_rounds)):
        return False, (
            f"A targeted retry already ran {already_attempted} round(s) and these "
            "questions are still unresolved, so automatic retries stop here."
        )
    return True, None


def unresolved_reason(
    *,
    chunks_run: int = 0,
    questions_covered: int = 0,
    recovered: int = 0,
    blocked_reason: str | None = None,
    error: str | None = None,
) -> str:
    """The explicit reason a question still has no mark.

    A teacher must never be shown a bare zero for a question the engine could
    not read; this sentence is what the review item says instead.
    """

    reason = (
        "The marker returned no usable result for this question, although the "
        "mark scheme requires it. It is unmarked, not a confirmed zero."
    )
    if chunks_run:
        reason += (
            f" A targeted retry re-marked {chunks_run} chunk(s) covering "
            f"{questions_covered} question(s) and recovered {recovered} of them."
        )
    if blocked_reason:
        reason += f" No further retry ran: {blocked_reason}"
    if error:
        reason += f" Last retry error: {error[:200]}"
    return reason
