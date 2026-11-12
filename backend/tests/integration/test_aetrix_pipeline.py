"""The marking pipeline, exercised with a scripted provider and real pages."""

from __future__ import annotations

import json
import uuid

import pytest
from app.core.config import get_settings
from app.core.security import Principal
from app.correction.aetrix.pipeline import AetrixPipeline
from app.correction.processing import STATUS_TO_STATE, ensure_consistent
from app.db.models import (
    CorrectionJob,
    CriterionResult,
    Document,
    DocumentPage,
    QuestionResult,
    VerificationResult,
)
from app.jobs.pipeline import RetryablePipelineError
from app.jobs.service import JobService
from app.jobs.states import JobState
from app.providers.base import ProviderNotConfigured
from app.schemas.api import CorrectionCreate
from app.storage.local import LocalStorage
from sqlalchemy import event, func, select

from tests.support import FakeProvider, make_png

# The fixture blueprint has three scoreable leaves: 1a (2), 1b (3), 2 (5).
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
                    "marks": awarded,
                    "awarded": awarded > 0,
                    "reason": "Matches the scheme." if awarded > 0 else "No response seen.",
                    "evidence": "x = 3" if awarded > 0 else None,
                }
            ],
            "confidence": confidence,
        }
    )


def _full_script() -> dict[str, str]:
    """A valid, full-mark response for every scoreable leaf."""

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


class CancellingProvider(ScriptedProvider):
    def __init__(self, payloads, session_factory, job_id) -> None:
        super().__init__(payloads)
        self.session_factory = session_factory
        self.job_id = job_id

    def generate(self, request, api_key):
        response = super().generate(request, api_key)
        with self.session_factory() as other:
            other.get(CorrectionJob, self.job_id).cancel_requested = True
            other.commit()
        return response


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
            idempotency_key=f"marking-{uuid.uuid4().hex[:12]}",
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


def _all_marks(db_session, job) -> list[QuestionResult]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(QuestionResult)
            .where(QuestionResult.job_id == job.id)
            .order_by(QuestionResult.question_id)
        )
    )


def test_a_full_run_persists_one_mark_per_leaf_question(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ScriptedProvider(_full_script())

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    assert outcome.state is JobState.FINALIZING
    marks = _all_marks(db_session, job)
    assert [row.question_id for row in marks] == ["1a", "1b", "2"]
    assert [row.awarded_marks for row in marks] == [2, 3, 5]
    assert all(row.status == "AWARDED" for row in marks)
    assert all(row.review_required is False for row in marks)
    assert all(row.max_marks == LEAVES[row.question_id] for row in marks)
    assert len(provider.requests) == 3

    assert db_session.scalar(select(func.count()).select_from(CriterionResult)) == 3
    assert db_session.scalar(select(func.count()).select_from(VerificationResult)) == 3


def test_the_maximum_mark_is_never_exceeded_or_clamped(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ScriptedProvider(
        {
            "1a": _payload("1a", awarded=7),
            "1b": _payload("1b", awarded=3),
            "2": _payload("2", awarded=5),
        }
    )

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    marks = {row.question_id: row for row in _all_marks(db_session, job)}
    assert marks["1a"].awarded_marks == 0
    assert marks["1a"].status == "REVIEW_REQUIRED"
    assert marks["1a"].review_required is True
    assert marks["1b"].status == "AWARDED"


def test_low_confidence_requires_review_rather_than_a_zero(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    floor = get_settings().marking.min_confidence
    provider = ScriptedProvider(
        {
            "1a": _payload("1a", awarded=2),
            "1b": _payload("1b", awarded=0, confidence=max(0.0, floor - 0.2)),
            "2": _payload("2", awarded=5),
        }
    )

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    marks = {row.question_id: row for row in _all_marks(db_session, job)}
    assert marks["1b"].awarded_marks == 0
    assert marks["1b"].status == "REVIEW_REQUIRED"
    assert marks["1b"].review_required is True
    assert any("confidence" in concern["message"] for concern in marks["1b"].scheme_concerns)


def test_a_malformed_response_is_a_typed_review_item(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ScriptedProvider(
        {
            "1a": "The student deserves about two marks.",
            "1b": _payload("1b", awarded=3),
            "2": _payload("2", awarded=5),
        }
    )

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    marks = {row.question_id: row for row in _all_marks(db_session, job)}
    assert marks["1a"].status == "REVIEW_REQUIRED"
    assert marks["1a"].awarded_marks == 0
    assert marks["1a"].confidence is None
    assert marks["1a"].scheme_concerns[0]["code"] == "MODEL_RESPONSE_INVALID"
    assert marks["1b"].status == "AWARDED"


def test_a_repeat_run_reuses_committed_marks_without_calling_the_model_again(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ScriptedProvider(_full_script())
    pipeline = AetrixPipeline(provider=provider, storage=storage)

    first = pipeline.run(job, db_session, get_settings())
    calls_after_first = len(provider.requests)
    second = pipeline.run(job, db_session, get_settings())

    assert first.state is JobState.FINALIZING
    assert second.state is JobState.FINALIZING
    assert len(provider.requests) == calls_after_first == 3
    assert len(_all_marks(db_session, job)) == 3
    assert db_session.scalar(select(func.count()).select_from(CriterionResult)) == 3


def test_a_cancelled_job_leaves_no_partial_results(
    paper, identity, db_session, session_factory, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = CancellingProvider(_full_script(), session_factory, job.id)

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    assert outcome.state is JobState.CANCELLED
    assert _all_marks(db_session, job) == []
    assert db_session.scalar(select(func.count()).select_from(CriterionResult)) == 0
    assert len(provider.requests) == 1


def test_a_cancel_requested_before_marking_does_no_work(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    job.cancel_requested = True
    db_session.commit()
    provider = ScriptedProvider(_full_script())

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    assert outcome.state is JobState.CANCELLED
    assert provider.requests == []
    assert _all_marks(db_session, job) == []


def test_an_unreadable_submission_is_reviewed_not_zeroed(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    for page in db_session.scalars(
        select(DocumentPage).where(DocumentPage.document_id.is_not(None))
    ):
        page.quality_status = "UNREADABLE"
    db_session.commit()
    provider = ScriptedProvider(_full_script())

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    assert outcome.detail["reason"] == "NO_RENDERABLE_PAGES"
    assert provider.requests == []
    assert _all_marks(db_session, job) == []


# -- behaviours carried over from the removed legacy suite --------------------


class BrokenProvider(FakeProvider):
    """Fails every call, so the execution ends without a usable result."""

    def __init__(self) -> None:
        super().__init__(error=ProviderNotConfigured("the provider is not configured"))


def test_a_provider_failure_never_becomes_a_zero(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """An outage is a finding about us, not about the student.

    The provider error is raised as retryable so the runner parks the job, and no
    question result — least of all a zero — is written for the paper.
    """

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = BrokenProvider()

    with pytest.raises(RetryablePipelineError):
        AetrixPipeline(provider=provider, storage=storage).run(
            job, db_session, get_settings()
        )

    assert provider.requests, "the failure must have come from the model call"
    db_session.expire_all()
    assert _all_marks(db_session, job) == []
    assert db_session.scalar(
        select(QuestionResult.id).where(
            QuestionResult.job_id == job.id, QuestionResult.status == "ZERO"
        )
    ) is None


def test_a_failed_run_never_persists_a_confirmed_zero(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = BrokenProvider()

    with pytest.raises(RetryablePipelineError):
        AetrixPipeline(provider=provider, storage=storage).run(
            job, db_session, get_settings()
        )

    db_session.expire_all()
    assert db_session.scalar(
        select(QuestionResult.id).where(
            QuestionResult.job_id == job.id,
            QuestionResult.processing_state == "CONFIRMED_ZERO",
        )
    ) is None
    assert db_session.scalar(
        select(QuestionResult.id).where(
            QuestionResult.job_id == job.id, QuestionResult.status == "ZERO"
        )
    ) is None


def test_every_persisted_state_agrees_with_its_status(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ScriptedProvider({**_full_script(), "2": _payload("2", awarded=0)})

    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, get_settings()
    )

    rows = {row.question_id: row for row in _all_marks(db_session, job)}
    assert {(row.status, row.processing_state) for row in rows.values()} == {
        ("AWARDED", "MARKED"),
        ("ZERO", "CONFIRMED_ZERO"),
    }
    for row in rows.values():
        assert row.processing_state is not None, row.question_id
        ensure_consistent(row.status, row.processing_state)


def test_the_state_is_written_in_the_same_insert_as_the_status(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """One INSERT carries both columns; there is no later reconciliation step."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ScriptedProvider(_full_script())

    captured: list[dict] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, context, executemany
        if "INSERT INTO question_results" in statement:
            rows = parameters if isinstance(parameters, list) else [parameters]
            captured.extend(rows)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        AetrixPipeline(provider=provider, storage=storage).run(
            job, db_session, get_settings()
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert len(captured) == 3
    for params in captured:
        assert params["status"] in STATUS_TO_STATE
        assert params["processing_state"] == STATUS_TO_STATE[params["status"]]
        assert params["engine_version"] == "5.5.0"
