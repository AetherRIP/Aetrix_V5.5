"""The rewritten pipeline and the engine seam, executed against real PostgreSQL.

These tests mark a paper end to end through ``build_pipeline`` — the same
call the worker makes — with a stub provider standing in for Gemini.  Everything
else is real: the credential lease, the usage ledger, the prompt registry, the
storage adapter, the per-question writes, the guard's locking reads and the job
transitions.  A stub provider is the only way to prove the pipeline's behaviour
without spending the owner's credits on a model whose answers must be fixed for
the assertions to mean anything.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, datetime

from app.core.config import MarkingSettings, StorageSettings, get_settings
from app.correction.engine import AetrixEngine
from app.db.models import (
    CorrectionJob,
    CriterionResult,
    Document,
    DocumentPage,
    EngineRun,
    JobApproval,
    MarkingEvidence,
    QuestionResult,
    VerificationResult,
)
from app.db.repositories import ResultRepository
from app.jobs.pipeline import build_pipeline
from app.jobs.runner import JobRunner
from app.jobs.states import JobState
from app.providers.base import LLMResponse, TokenUsage
from app.storage import LocalStorage
from sqlalchemy import select, text


def _answer(question_id: str, awarded: int, components: list[dict], answer: str | None) -> dict:
    return {
        "question_id": question_id,
        "student_answer": answer,
        "awarded_marks": awarded,
        "components": components,
        "confidence": 0.95,
    }


def _component(code: str, awarded: bool, evidence: str | None) -> dict:
    return {
        "code": code,
        "marks": 1,
        "awarded": awarded,
        "reason": "the step is present" if awarded else "the step is missing",
        "evidence": evidence,
    }


#: Three leaves, five of ten marks, one deliberate zero with high confidence.
ANSWERS = {
    "1a": _answer(
        "1a",
        2,
        [_component("M1", True, "2x + 6 = 12"), _component("A1", True, "x = 3")],
        "x = 3",
    ),
    "1b": _answer(
        "1b",
        3,
        [
            _component("M1", True, "y = 2x + 1"),
            _component("M2", True, "2x + 1 = 7"),
            _component("A1", True, "x = 3, y = 7"),
        ],
        "x = 3, y = 7",
    ),
    "2": _answer("2", 0, [], None),
}

#: A second run that agrees with nothing: one mark instead of five.
LOWER_ANSWERS = {
    "1a": _answer("1a", 1, [_component("M1", True, "x = 3")], "3"),
    "1b": _answer("1b", 1, [_component("M1", True, "y = 2x + 1")], "y = 2x + 1"),
    "2": _answer("2", 0, [], None),
}


class StubProvider:
    """A provider that answers with fixed JSON and counts its calls."""

    name = "stub"

    def __init__(self, answers: dict[str, dict] | None = None) -> None:
        self.answers = answers or ANSWERS
        self.calls = 0

    def generate(self, request, api_key):
        del api_key
        self.calls += 1
        context = next(
            (part.text for part in request.inputs if part.text), ""
        )
        question_id = context.splitlines()[0].split(":", 1)[1].strip()
        return LLMResponse(
            text=json.dumps(self.answers[question_id]),
            model=request.model,
            usage=TokenUsage(input_tokens=100, output_tokens=100),
            finish_reason="STOP",
            provider_request_id=f"stub-{self.calls}",
            latency_ms=1,
        )


def _settings(tmp_path, **overrides):
    settings = get_settings().model_copy(
        update={"storage": StorageSettings(root=tmp_path / "documents")}
    )
    return settings.model_copy(update=overrides) if overrides else settings


def _job(db_session, paper, identity, *, key: str, state: str = "CREATED") -> CorrectionJob:
    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        idempotency_key=key,
        request_hash="e" * 64,
        state=state,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _page(db_session, paper, identity, settings) -> DocumentPage:
    storage = LocalStorage(settings.storage.root)
    stored = storage.put("submissions/8a6b/answer.png", b"png-bytes", "image/png")
    document = Document(
        tenant_id=identity.tenant_a.id,
        submission_id=paper.submission.id,
        exam_id=paper.exam.id,
        kind="STUDENT",
        storage_key="submissions/8a6b/answer.pdf",
        original_filename="answer.png",
        sha256="f" * 64,
        mime_type="image/png",
        size_bytes=len(b"png-bytes"),
        page_count=1,
        status="PROCESSED",
    )
    db_session.add(document)
    db_session.flush()
    page = DocumentPage(
        tenant_id=identity.tenant_a.id,
        document_id=document.id,
        page_index=1,
        storage_key=stored.key,
        quality_status="READABLE",
        checksum=stored.sha256,
    )
    db_session.add(page)
    db_session.commit()
    return page


def _run(monkeypatch, session_factory, job_id, settings, provider):
    """Run the in-tree V5 implementation through its adapter."""

    monkeypatch.setattr(
        "app.correction.aetrix.pipeline.build_provider", lambda _settings: provider
    )
    engine = AetrixEngine()
    with session_factory() as session:
        job = session.get(CorrectionJob, job_id)
        outcome = engine.run(job, session, settings)
    return outcome


def test_a_full_run_through_the_seam_persists_every_question(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="live-1")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert provider.calls == 3

    db_session.expire_all()
    stored = db_session.get(CorrectionJob, job.id)
    assert stored.engine_name == "aetrix_v5_5"
    assert stored.engine_version == "5.5.0"
    assert stored.result_source == "AI_PRIMARY"
    assert stored.primary_model
    assert stored.submission_hash and stored.scheme_hash

    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.question_id for row in rows} == {"1a", "1b", "2"}
    assert sum(row.awarded_marks for row in rows) == 5

    first = next(row for row in rows if row.question_id == "1a")
    assert (first.status, first.processing_state) == ("AWARDED", "MARKED")
    assert first.raw_awarded_marks == 2
    assert first.normalised_awarded_marks == 2
    assert first.normalisation_anomaly is None
    assert first.raw_response == ANSWERS["1a"]
    assert first.raw_response_truncated is False
    assert first.engine_version == "5.5.0"
    assert first.prompt_version and first.prompt_version.startswith("aetrix_v5_5_marking:")

    zero = next(row for row in rows if row.question_id == "2")
    assert (zero.status, zero.processing_state) == ("ZERO", "CONFIRMED_ZERO")
    assert zero.review_required is False

    components = db_session.scalars(
        select(CriterionResult).where(
            CriterionResult.question_result_id.in_([row.id for row in rows])
        )
    ).all()
    assert len(components) == 5
    evidence = db_session.scalars(
        select(MarkingEvidence).where(
            MarkingEvidence.question_result_id.in_([row.id for row in rows])
        )
    ).all()
    assert len(evidence) == 5
    assert all(item.quote for item in evidence)

    stages = {
        run.stage: run
        for run in db_session.scalars(
            select(EngineRun).where(EngineRun.job_id == job.id)
        )
    }
    assert stages["MARKING"].outcome == "OK"
    assert stages["MARKING"].detail["questions"] == 3
    assert stages["GUARD"].detail["action"] == "INSERT"
    assert stages["MARKING"].engine_name == "aetrix_v5_5"


def test_running_the_job_again_does_not_re_mark_anything(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="idempotent")
    provider = StubProvider()

    _run(monkeypatch, session_factory, job.id, settings, provider)
    first_ids = set(
        db_session.scalars(
            select(QuestionResult.id).where(QuestionResult.job_id == job.id)
        )
    )
    first_awarded = sum(
        db_session.scalars(
            select(QuestionResult.awarded_marks).where(QuestionResult.job_id == job.id)
        )
    )

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.FINALIZING
    assert provider.calls == 3, "a decided question must never be sent to the model again"
    second_ids = set(
        db_session.scalars(
            select(QuestionResult.id).where(QuestionResult.job_id == job.id)
        )
    )
    assert second_ids == first_ids
    assert (
        sum(
            db_session.scalars(
                select(QuestionResult.awarded_marks).where(QuestionResult.job_id == job.id)
            )
        )
        == first_awarded
    )


def _approve(db_session, job, *, earned: int, total: int) -> None:
    db_session.add(
        JobApproval(
            tenant_id=job.tenant_id,
            job_id=job.id,
            approved_at=datetime.now(UTC),
            approved_marks=earned,
            total_marks=total,
            record_version=job.record_version,
        )
    )
    db_session.commit()


def _snapshot(db_session, job_id):
    return [
        (
            row.id,
            row.question_id,
            row.awarded_marks,
            row.status,
            row.processing_state,
            row.updated_at,
        )
        for row in db_session.scalars(
            select(QuestionResult)
            .where(QuestionResult.job_id == job_id)
            .order_by(QuestionResult.question_id)
        )
    ]


def test_an_approved_result_is_not_replaced_and_its_rows_do_not_change(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    approved = _job(db_session, paper, identity, key="approved-run")
    _run(monkeypatch, session_factory, approved.id, settings, StubProvider())
    db_session.expire_all()
    _approve(db_session, db_session.get(CorrectionJob, approved.id), earned=5, total=10)
    before = _snapshot(db_session, approved.id)

    second = _job(db_session, paper, identity, key="second-run")
    outcome = _run(
        monkeypatch, session_factory, second.id, settings, StubProvider(LOWER_ANSWERS)
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    assert outcome.detail["guard"] == "BLOCKED"

    db_session.expire_all()
    assert _snapshot(db_session, approved.id) == before
    refused = db_session.get(CorrectionJob, second.id)
    assert refused.result_source == "AUTOMATED_REFUSED"

    refused_event = db_session.scalar(
        text(
            "select count(*) from audit_events "
            "where action = 'result.overwrite_refused' and entity_id = :id"
        ),
        {"id": str(second.id)},
    )
    assert refused_event == 1

    # The refused run's own marks are still recorded for the reviewer; they are
    # simply not presented as the submission's result.
    second_rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, second.id)
    assert sum(row.awarded_marks for row in second_rows) == 2


def test_a_suspicious_drop_keeps_the_stored_result(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    first = _job(db_session, paper, identity, key="drop-first")
    _run(monkeypatch, session_factory, first.id, settings, StubProvider())

    second = _job(db_session, paper, identity, key="drop-second")
    outcome = _run(
        monkeypatch, session_factory, second.id, settings, StubProvider(LOWER_ANSWERS)
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    assert outcome.detail["guard"] == "KEEP_EXISTING"
    db_session.expire_all()
    assert sum(
        row.awarded_marks
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, first.id)
    ) == 5


def test_two_workers_cannot_both_decide_against_a_stale_prior(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    prior = _job(db_session, paper, identity, key="lock-prior")
    _run(monkeypatch, session_factory, prior.id, settings, StubProvider())
    current = _job(db_session, paper, identity, key="lock-current")
    before = _snapshot(db_session, prior.id)

    holding = threading.Event()
    release = threading.Event()
    result: dict[str, float] = {}

    def holder() -> None:
        with session_factory() as session:
            ResultRepository(session).prior_job_totals(
                identity.tenant_a.id,
                paper.submission.id,
                exclude_job_id=current.id,
            )
            holding.set()
            release.wait(15)
            session.commit()

    def reader() -> None:
        with session_factory() as session:
            started = time.monotonic()
            ResultRepository(session).prior_job_totals(
                identity.tenant_a.id,
                paper.submission.id,
                exclude_job_id=current.id,
            )
            result["elapsed"] = time.monotonic() - started
            session.commit()

    holder_thread = threading.Thread(target=holder, name="guard-holder")
    holder_thread.start()
    assert holding.wait(15), "the holding session never acquired the lock"

    reader_thread = threading.Thread(target=reader, name="guard-reader")
    reader_thread.start()
    time.sleep(0.7)
    assert "elapsed" not in result, "the second guard read was not blocked by the row lock"

    release.set()
    holder_thread.join(20)
    reader_thread.join(20)

    assert result.get("elapsed", 0.0) >= 0.6, (
        "the second read returned without waiting for the lock"
    )
    db_session.expire_all()
    assert _snapshot(db_session, prior.id) == before


class DoubleCheckProvider(StubProvider):
    """A second examiner that always awards one mark fewer."""

    def generate(self, request, api_key):
        if "independent double check" in request.prompt:
            context = next((part.text for part in request.inputs if part.text), "")
            question_id = context.splitlines()[0].split(":", 1)[1].strip()
            self.calls += 1
            payload = dict(self.answers[question_id])
            payload["awarded_marks"] = max(0, payload["awarded_marks"] - 1)
            payload["components"] = []
            return LLMResponse(
                text=json.dumps(payload),
                model=request.model,
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                finish_reason="STOP",
                provider_request_id=f"stub-double-{self.calls}",
                latency_ms=1,
            )
        return super().generate(request, api_key)


#: One low-confidence award, so the double check has a question to re-mark.
LOW_CONFIDENCE = {**ANSWERS, "1a": {**ANSWERS["1a"], "confidence": 0.7}}


def test_the_double_check_records_agreement_without_changing_a_mark(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="double-agrees")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider(LOW_CONFIDENCE))

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert outcome.detail["double_check"] == {
        "enabled": True,
        "checked": 1,
        "disagreements": 0,
        "unverifiable": 0,
    }
    db_session.expire_all()
    stored = db_session.get(CorrectionJob, job.id)
    assert stored.double_check_status == "COMPLETED"
    assert stored.disagreement_status == "NONE"
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.kind == "DOUBLE_CHECK",
        )
    )
    assert verdict.status == "AGREES"
    assert verdict.detail["first_awarded"] == verdict.detail["second_awarded"] == 2


def test_a_double_check_disagreement_goes_to_a_person_and_keeps_the_first_award(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="double-disagrees")

    outcome = _run(
        monkeypatch, session_factory, job.id, settings, DoubleCheckProvider(LOW_CONFIDENCE)
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    assert outcome.detail["double_check"]["disagreements"] == 1

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    assert rows["1a"].awarded_marks == 2, "the second opinion must never replace the first award"
    assert (rows["1a"].status, rows["1a"].processing_state) == (
        "REVIEW_REQUIRED",
        "NEEDS_REVIEW",
    )
    assert any(
        concern["code"] == "DOUBLE_CHECK_DISAGREEMENT"
        for concern in rows["1a"].scheme_concerns
    )
    assert rows["1b"].awarded_marks == 3

    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.kind == "DOUBLE_CHECK",
        )
    )
    assert verdict.status == "DISAGREES"
    assert verdict.detail["first_awarded"] == 2
    assert verdict.detail["second_awarded"] == 1

    stored = db_session.get(CorrectionJob, job.id)
    assert stored.disagreement_status == "DISAGREEMENTS"
    stage = db_session.scalar(
        select(EngineRun).where(
            EngineRun.job_id == job.id, EngineRun.stage == "DOUBLE_CHECK"
        )
    )
    assert stage.outcome == "REVIEW_REQUIRED"
    assert stage.detail["threshold"] == MarkingSettings().double_check_min_confidence


def test_the_double_check_is_recorded_as_skipped_when_disabled(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="double-off")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.FINALIZING
    assert outcome.detail["double_check"]["enabled"] is False
    db_session.expire_all()
    stored = db_session.get(CorrectionJob, job.id)
    assert stored.double_check_status == "DISABLED"
    stage = db_session.scalar(
        select(EngineRun).where(
            EngineRun.job_id == job.id, EngineRun.stage == "DOUBLE_CHECK"
        )
    )
    assert stage.outcome == "SKIPPED"


def test_the_worker_entry_point_completes_a_job_through_v5(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The exact object the worker process builds must mark a claimable job."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="worker-e2e", state="CREATED")
    provider = StubProvider()
    monkeypatch.setattr(
        "app.correction.aetrix.pipeline.build_provider", lambda _settings: provider
    )

    pipeline = AetrixEngine()
    assert pipeline.name == "aetrix_v5_5"
    runner = JobRunner(
        session_factory=session_factory,
        pipeline=pipeline,
        settings=settings,
        worker_id="worker-e2e",
    )

    assert runner.run_once() == str(job.id)

    db_session.expire_all()
    stored = db_session.get(CorrectionJob, job.id)
    assert stored.state == JobState.COMPLETED.value
    assert stored.error_code is None
    assert stored.engine_name == "aetrix_v5_5"
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert len(rows) == 3
    assert sum(row.awarded_marks for row in rows) == 5
    assert provider.calls == 3


def test_a_job_created_through_the_api_is_marked_by_the_configured_v5_5_engine(
    client,
    auth_headers,
    monkeypatch,
    session_factory,
    db_session,
    paper,
    identity,
    provider_credential,
    tmp_path,
) -> None:
    """Configuration, not a test stub, must choose the engine for an API job."""

    settings = _settings(tmp_path)
    _page(db_session, paper, identity, settings)
    provider = StubProvider()
    monkeypatch.setattr(
        "app.correction.aetrix.pipeline.build_provider", lambda _settings: provider
    )

    # Whatever the worker builds from settings must be the V5.5 engine, with no
    # fallback to the legacy pipeline.
    pipeline = build_pipeline(settings)
    assert isinstance(pipeline, AetrixEngine)
    assert pipeline.name == "aetrix_v5_5"

    created = client.post(
        "/api/v1/corrections",
        headers=auth_headers(identity.user_a),
        json={
            "assignment_id": str(paper.assignment.id),
            "submission_id": str(paper.submission.id),
            "idempotency_key": "api-selects-v5-5",
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    runner = JobRunner(
        session_factory=session_factory,
        pipeline=pipeline,
        settings=settings,
        worker_id="api-engine-worker",
    )
    assert runner.run_once() == job_id

    db_session.expire_all()
    stored = db_session.get(CorrectionJob, uuid.UUID(job_id))
    assert stored.state == JobState.COMPLETED.value
    assert (stored.engine_name, stored.engine_version) == ("aetrix_v5_5", "5.5.0")

    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, stored.id)
    assert {row.question_id for row in rows} == {"1a", "1b", "2"}
    assert sum(row.awarded_marks for row in rows) == 5
    assert {row.processing_state for row in rows} == {"MARKED", "CONFIRMED_ZERO"}
    assert provider.calls == 3

    # Per-stage provenance belongs to the V5 path; the legacy engine never
    # wrote an engine_runs row.
    stages = set(
        db_session.scalars(select(EngineRun.stage).where(EngineRun.job_id == stored.id))
    )
    assert {"MARKING", "INTEGRITY", "DOUBLE_CHECK", "GUARD"} <= stages


def test_the_worker_always_builds_the_one_engine() -> None:
    pipeline = build_pipeline(get_settings())

    assert isinstance(pipeline, AetrixEngine)
    assert (pipeline.name, pipeline.version) == ("aetrix_v5_5", "5.5.0")
