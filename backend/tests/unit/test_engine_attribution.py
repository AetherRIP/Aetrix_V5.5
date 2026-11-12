"""The rule that stops a job changing engine underneath itself."""

from __future__ import annotations

from app.correction.engine.protocol import engine_attribution_conflict


def test_an_unattributed_job_is_not_a_conflict() -> None:
    # A brand-new job has not been claimed by any engine yet.
    assert engine_attribution_conflict(None, "aetrix_v5_5") is False


def test_the_same_engine_is_not_a_conflict() -> None:
    assert engine_attribution_conflict("aetrix_v5_5", "aetrix_v5_5") is False


def test_another_engine_is_a_conflict() -> None:
    assert engine_attribution_conflict("aetrix_legacy", "aetrix_v5_5") is True
