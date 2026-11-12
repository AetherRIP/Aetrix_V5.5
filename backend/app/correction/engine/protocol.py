"""The boundary between the worker and the correction engine.

The engine is handed a claimed job, its own session and the resolved settings,
and returns the ``PipelineOutcome`` the job runner already understands.  Nothing
else changes for the runner: it still owns the lease, the heartbeat and the
terminal transition.

The type is deliberately narrow.  The engine may not transition a job, approve a
result, or reach for a tenant it was not given; the only way it affects the
platform is the persisted question results it writes for the claimed job.

Since this build contains one engine, the only rule left here is attribution: a
job recorded as created or marked by a different engine is never re-marked by
this one.  Historical rows still name ``aetrix_legacy`` and ``mathchecker_v5``;
those names are read as stored and are never rewritten.
"""

from __future__ import annotations


def engine_attribution_conflict(recorded: str | None, name: str) -> bool:
    """True when a job was created or marked by an engine other than this one.

    Re-marking a paper under a different engine is a deliberate act, never a
    side effect of which worker happened to claim the job.  A historical engine
    name is still a different engine.
    """

    return bool(recorded) and recorded != name
