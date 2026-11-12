"""Write ``processing_state`` in the same flush as ``status``.

The legacy pipeline commits one question result at a time and this module must
not edit it.  A session-level ``before_flush`` hook therefore fills the
explicit-state columns at the moment the row is flushed: the INSERT that carries
``status`` also carries ``processing_state`` (and ``engine_version``), so there
is no window in which a committed row has a status and no state.

The state comes from the single mapping in ``app.correction.processing`` that
the migration backfill also generates its SQL from.  A status the mapping cannot
express consistently makes the hook raise, aborting that flush: persisting a
NULL state, or a state that contradicts ``status``, is not an available outcome.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from ...db.models import QuestionResult
from ..processing import ProcessingState, ensure_consistent, state_for_status

_HOOK_ATTRIBUTE = "_aetrix_processing_state_hook"


def apply_processing_state(
    row: QuestionResult, *, engine_version: str
) -> ProcessingState:
    """Set both columns on one row, or refuse the contradictory case."""

    state = state_for_status(row.status, review_required=bool(row.review_required))
    ensure_consistent(row.status, state)
    row.processing_state = str(state)
    if not row.engine_version:
        row.engine_version = engine_version
    return state


def install_processing_state_hook(session: Session, *, engine_version: str) -> None:
    """Install the flush hook once per session, before anything is marked."""

    if getattr(session, _HOOK_ATTRIBUTE, False):
        return

    def _before_flush(
        flushed_session: Session,
        flush_context: Any,
        instances: Sequence[object] | None,
    ) -> None:
        del flush_context, instances
        for obj in (*flushed_session.new, *flushed_session.dirty):
            if isinstance(obj, QuestionResult):
                apply_processing_state(obj, engine_version=engine_version)

    event.listen(session, "before_flush", _before_flush)
    setattr(session, _HOOK_ATTRIBUTE, True)
