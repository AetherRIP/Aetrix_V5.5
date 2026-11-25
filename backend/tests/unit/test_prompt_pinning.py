"""A job may not resume across prompt generations.

Marking rows carry their prompt version, but double-check and transcription
verdicts do not.  The usage ledger does, so the guard compares every prompt the
job has called with the version this execution would load.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.core.errors import AppError
from app.correction.aetrix.pipeline import _MarkingRun


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows) -> None:
        self._rows = rows

    def execute(self, statement):
        del statement
        return _Result(self._rows)


class _Registry:
    def __init__(self, version: int) -> None:
        self.version = version

    def load(self, prompt_id: str, version: int | None = None):
        del version
        return SimpleNamespace(prompt_id=prompt_id, version=self.version)


def _run(rows, *, current_version: int) -> _MarkingRun:
    run = object.__new__(_MarkingRun)
    run.session = _Session(rows)
    run.job = SimpleNamespace(id=uuid.uuid4())
    run.marking_prompt_version = None
    run.calls = SimpleNamespace(registry=_Registry(current_version))
    return run


def test_a_job_that_used_another_double_check_prompt_fails_closed() -> None:
    run = _run([("aetrix_v5_5_double_check", 1)], current_version=2)

    with pytest.raises(AppError, match="prompt generations"):
        run.assert_prompt_versions_stable([])


def test_a_job_that_used_the_current_prompt_generation_may_resume() -> None:
    run = _run([("aetrix_v5_5_double_check", 2)], current_version=2)

    run.assert_prompt_versions_stable([])
