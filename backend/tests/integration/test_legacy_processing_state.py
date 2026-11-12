"""The default engine must write both ``status`` and ``processing_state``.

``aetrix_legacy`` is the shipped engine, so the explicit-state requirement is
only real if its own executions satisfy it.  Each test here runs the configured
default engine — the object ``build_engine`` returns — against a real database
and a scripted provider, then asserts the persisted pair and that the two claims
agree according to the shared mapping.

A failed execution must never leave a ``CONFIRMED_ZERO``: an unresolved question
is a finding about the marking service, not a finding about the student.
"""

from __future__ import annotations

import json
import uuid

import pytest
from app.core.config import StorageSettings, get_settings
from app.core.errors import AppError
from app.core.security import Principal
from app.correction.engine.legacy import LegacyEngine
from app.correction.processing import STATUS_TO_STATE, ensure_consistent
from app.correction.registry import build_engine
from app.db.models import CorrectionJob, Document, DocumentPage, QuestionResult
from app.jobs.service import JobService
from app.schemas.api import CorrectionCreate
from app.storage.local import LocalStorage
from sqlalchemy import event, select

from tests.support import FakeProvider, make_png

#: The fixture blueprint has three scoreable leaves: 1a (2), 1b (3), 2 (5).
LEAVES = {"1a": 2, "1b": 3, "2": 5}


def _payload(question_id: str, *, awarded: int, confidence: float = 0.95) -> str:
    return json.dumps(
        {
            "question_id": question_id,
            "student_answer": "x = 3",
            "awarded_marks": awarded,
            "components": [
                {
                    "code": "A1",
                    "description": "Correct final answer",
                    "marks": max(awarded, 1),
                    "awarded": awarded > 0,
                    "reason": "Matches the scheme." if awarded > 0 else "No credit.",
                    "evidence": "x = 3" if awarded > 0 else None,
                }
            ],
            "confidence": confidence,
        }
    )


def _full_script() -> dict[str, str]:
    return {qid: _payload(qid, awarded=marks) for qid, marks in LEAVES.items()}


def _question_of(request) -> str:
    for part in request.inputs:
        text = part.text or ""
        if text.startswith("Question: "):
            return text.splitlines()[0].split(": ", 1)[1].strip()
    return ""


class ScriptedProvider(FakeProvider):
    """Returns a payload chosen by the question the pipeline is marking."""

    def __init__(self, payloads: dict[str, str]) -> None:
        super().__init__()
        self.payloads = payloads

    def generate(self, request, api_key):
        self.text = self.payloads.get(_question_of(request), "{}")
        return super().generate(request, api_key)


class BrokenProvider(FakeProvider):
    """Fails every call, so the execution ends without a usable result."""

    def __init__(self) -> None:
        super().__init__(error=RuntimeError("provider unavailable"))


def _settings(tmp_path):
    return get_settings().model_copy(
        update={"storage": StorageSettings(root=tmp_path / "store")}
    )


def _setup(paper, identity, db_session, storage):
    job = JobService(db_session, get_settings()).create(
        Principal(
            user_id=identity.user_a.id,
            tenant_id=identity.tenant_a.id,
            subject=identity.user_a.subject,
            role=identity.user_a.role,
        ),
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=f"state-{uuid.uuid4().hex[:12]}",
        ),
    ).job
    job.state = "CORRECTING"
    db_session.commit()

    stored = storage.put(f"{identity.tenant_a.id}/page-1.png", make_png(), "image/png")
    document = Document(
        tenant_id=identity.tenant_a.id,
        submission_id=paper.submission.id,
        kind="STUDENT",
        storage_key=stored.key,
        original_filename="answers.png",
        sha256=stored.sha256,
        mime_type="image/png",
        size_bytes=stored.size_bytes,
        page_count=1,
        status="PROCESSED",
        ordering_status="ORDERED",
        mapping_status="UNMAPPED",
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            tenant_id=identity.tenant_a.id,
            document_id=document.id,
            page_index=1,
            storage_key=stored.key,
            width=1000,
            height=1400,
            quality_status="READABLE",
            checksum=stored.sha256,
        )
    )
    db_session.commit()
    return job


def _marks(db_session, job) -> dict[str, QuestionResult]:
    db_session.expire_all()
    rows = db_session.scalars(
        select(QuestionResult).where(QuestionResult.job_id == job.id)
    ).all()
    return {row.question_id: row for row in rows}


def _assert_every_state_agrees(rows: dict[str, QuestionResult]) -> None:
    for row in rows.values():
        assert row.processing_state is not None, row.question_id
        ensure_consistent(row.status, row.processing_state)


def test_an_awarded_question_is_persisted_as_marked(
    monkeypatch, paper, identity, db_session, provider_credential, tmp_path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalStorage(settings.storage.root)
    job = _setup(paper, identity, db_session, storage)
    monkeypatch.setattr(
        "app.marking.pipeline.build_provider", lambda _settings: ScriptedProvider(_full_script())
    )

    outcome = build_engine(settings).run(job, db_session, settings)

    assert outcome.state.value == "FINALIZING"
    rows = _marks(db_session, job)
    assert {qid: (row.status, row.processing_state) for qid, row in rows.items()} == {
        "1a": ("AWARDED", "MARKED"),
        "1b": ("AWARDED", "MARKED"),
        "2": ("AWARDED", "MARKED"),
    }
    _assert_every_state_agrees(rows)

    stored = db_session.get(CorrectionJob, job.id)
    assert (stored.engine_name, stored.engine_version) == ("aetrix_legacy", "1.0.0")
    assert all(row.engine_version == "1.0.0" for row in rows.values())
    assert isinstance(build_engine(settings), LegacyEngine)


def test_a_confident_zero_is_persisted_as_confirmed_zero(
    monkeypatch, paper, identity, db_session, provider_credential, tmp_path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalStorage(settings.storage.root)
    job = _setup(paper, identity, db_session, storage)
    script = {**_full_script(), "2": _payload("2", awarded=0)}
    monkeypatch.setattr(
        "app.marking.pipeline.build_provider", lambda _settings: ScriptedProvider(script)
    )

    build_engine(settings).run(job, db_session, settings)

    rows = _marks(db_session, job)
    assert (rows["2"].status, rows["2"].processing_state) == ("ZERO", "CONFIRMED_ZERO")
    _assert_every_state_agrees(rows)


def test_a_malformed_response_is_persisted_as_needs_review(
    monkeypatch, paper, identity, db_session, provider_credential, tmp_path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalStorage(settings.storage.root)
    job = _setup(paper, identity, db_session, storage)
    script = {**_full_script(), "1a": "The student deserves about two marks."}
    monkeypatch.setattr(
        "app.marking.pipeline.build_provider", lambda _settings: ScriptedProvider(script)
    )

    build_engine(settings).run(job, db_session, settings)

    rows = _marks(db_session, job)
    assert (rows["1a"].status, rows["1a"].processing_state) == (
        "REVIEW_REQUIRED",
        "NEEDS_REVIEW",
    )
    _assert_every_state_agrees(rows)


def test_a_failed_execution_never_persists_a_confirmed_zero(
    monkeypatch, paper, identity, db_session, provider_credential, tmp_path
) -> None:
    settings = _settings(tmp_path)
    storage = LocalStorage(settings.storage.root)
    job = _setup(paper, identity, db_session, storage)
    provider = BrokenProvider()
    monkeypatch.setattr(
        "app.marking.pipeline.build_provider", lambda _settings: provider
    )

    with pytest.raises((RuntimeError, AppError)):
        build_engine(settings).run(job, db_session, settings)

    assert provider.requests, "the failure must have come from the model call"
    db_session.expire_all()
    confirmed = db_session.scalar(
        select(QuestionResult.id).where(
            QuestionResult.job_id == job.id,
            QuestionResult.processing_state == "CONFIRMED_ZERO",
        )
    )
    assert confirmed is None
    assert db_session.scalar(
        select(QuestionResult.id).where(
            QuestionResult.job_id == job.id, QuestionResult.status == "ZERO"
        )
    ) is None


def test_the_state_is_written_in_the_same_insert_as_the_status(
    monkeypatch, paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """One INSERT carries both columns; there is no later reconciliation step."""

    settings = _settings(tmp_path)
    storage = LocalStorage(settings.storage.root)
    job = _setup(paper, identity, db_session, storage)
    monkeypatch.setattr(
        "app.marking.pipeline.build_provider", lambda _settings: ScriptedProvider(_full_script())
    )

    captured: list[dict] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, context, executemany
        if "INSERT INTO question_results" in statement:
            rows = parameters if isinstance(parameters, list) else [parameters]
            captured.extend(rows)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        build_engine(settings).run(job, db_session, settings)
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert len(captured) == 3
    for params in captured:
        assert params["status"] in STATUS_TO_STATE
        assert params["processing_state"] == STATUS_TO_STATE[params["status"]]
        assert params["engine_version"] == "1.0.0"


def test_a_failed_insert_persists_no_status_without_state(
    monkeypatch, paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """Abort the flush that would write the result: no half-state row survives."""

    settings = _settings(tmp_path)
    storage = LocalStorage(settings.storage.root)
    job = _setup(paper, identity, db_session, storage)
    monkeypatch.setattr(
        "app.marking.pipeline.build_provider", lambda _settings: ScriptedProvider(_full_script())
    )

    def explode(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, parameters, context, executemany
        if "INSERT INTO question_results" in statement:
            raise RuntimeError("forced failure while writing the result")

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", explode)
    try:
        with pytest.raises((RuntimeError, AppError)):
            build_engine(settings).run(job, db_session, settings)
    finally:
        event.remove(bind, "before_cursor_execute", explode)

    db_session.rollback()
    db_session.expire_all()
    rows = db_session.scalars(
        select(QuestionResult).where(QuestionResult.job_id == job.id)
    ).all()
    assert rows == []
    assert db_session.scalar(
        select(QuestionResult.id).where(
            QuestionResult.job_id == job.id,
            QuestionResult.status.is_not(None),
            QuestionResult.processing_state.is_(None),
        )
    ) is None
