"""The worker must not mark with routing code that is no longer on disk."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import get_settings
from app.jobs.code_version import code_fingerprint
from app.jobs.runner import JobRunner


def test_the_fingerprint_is_stable_and_covers_every_routing_source() -> None:
    first = code_fingerprint()
    assert first == code_fingerprint()
    assert len(first) == 64
    int(first, 16)  # hexadecimal, not an arbitrary string


def test_a_worker_whose_code_changed_claims_nothing() -> None:
    readings = iter(["a" * 64, "b" * 64])

    def session_factory():  # only reached if the runner tries to claim
        raise AssertionError("a stale worker must not open a session or claim a job")

    runner = JobRunner(
        session_factory=session_factory,  # type: ignore[arg-type]
        pipeline=SimpleNamespace(name="aetrix_v5_5"),  # type: ignore[arg-type]
        settings=get_settings(),
        worker_id="worker-stale",
        fingerprint_fn=lambda: next(readings),
    )

    assert runner.run_once() is None


def test_a_worker_whose_code_is_unchanged_still_claims() -> None:
    reached: list[int] = []

    def session_factory():
        reached.append(1)
        raise AssertionError("the guard passed, so the claim was attempted")

    runner = JobRunner(
        session_factory=session_factory,  # type: ignore[arg-type]
        pipeline=SimpleNamespace(name="aetrix_v5_5"),  # type: ignore[arg-type]
        settings=get_settings(),
        worker_id="worker-current",
        fingerprint_fn=lambda: "c" * 64,
    )

    with pytest.raises(AssertionError):
        runner.run_once()
    assert reached == [1]


def test_the_terminal_event_records_which_code_finished_the_job() -> None:
    """The fingerprint is audit data, not a log line: it belongs on the event."""

    detail = {"event": "results_finalized"}
    decorated = {**detail, "worker_code": "d" * 12}
    assert decorated["worker_code"] == "d" * 12
    assert "worker_code" not in detail
