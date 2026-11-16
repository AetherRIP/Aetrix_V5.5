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
    MarkingCriterion,
    MarkingEvidence,
    PageQuestionMapping,
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

#: A reply whose components add up to less than the award it states.
MISCOUNTED = {
    **ANSWERS,
    "1a": _answer("1a", 2, [_component("M1", True, "2x + 6 = 12")], "x = 3"),
}


def test_the_double_check_records_agreement_without_changing_a_mark(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="double-agrees")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider(LOW_CONFIDENCE))

    assert outcome.state is JobState.FINALIZING, outcome.detail
    # Two questions earn a second opinion: 1a is low confidence, and 1b takes
    # full marks on a three-mark question, which is worth confirming.
    assert outcome.detail["double_check"] == {
        "enabled": True,
        "checked": 2,
        "already_checked": 0,
        "disagreements": 0,
        "unverifiable": 0,
    }
    db_session.expire_all()
    stored = db_session.get(CorrectionJob, job.id)
    assert stored.double_check_status == "COMPLETED"
    assert stored.disagreement_status == "NONE"
    verdicts = {
        verdict.question_id: verdict
        for verdict in db_session.scalars(
            select(VerificationResult).where(
                VerificationResult.job_id == job.id,
                VerificationResult.kind == "DOUBLE_CHECK",
            )
        )
    }
    assert {question_id: row.status for question_id, row in verdicts.items()} == {
        "1a": "AGREES",
        "1b": "AGREES",
    }
    assert verdicts["1a"].detail["first_awarded"] == verdicts["1a"].detail["second_awarded"] == 2
    assert verdicts["1b"].detail["first_awarded"] == verdicts["1b"].detail["second_awarded"] == 3
    assert any(
        reason.startswith("FULL_MARKS_VALUABLE")
        for reason in verdicts["1b"].detail["selection"]
    ), "a generous award was checked without a recorded reason"


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
    # Both re-marked questions disagree: the second examiner is one mark lower
    # on each, and neither second opinion replaces the first award.
    assert outcome.detail["double_check"]["disagreements"] == 2

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    for question_id, first_award in (("1a", 2), ("1b", 3)):
        row = rows[question_id]
        assert row.awarded_marks == first_award, (
            "the second opinion must never replace the first award"
        )
        assert (row.status, row.processing_state) == ("REVIEW_REQUIRED", "NEEDS_REVIEW")
        assert any(
            concern["code"] == "DOUBLE_CHECK_DISAGREEMENT"
            for concern in row.scheme_concerns
        )
    # A question nobody doubted keeps its decision.
    assert rows["2"].processing_state == "CONFIRMED_ZERO"

    verdicts = {
        verdict.question_id: verdict
        for verdict in db_session.scalars(
            select(VerificationResult).where(
                VerificationResult.job_id == job.id,
                VerificationResult.kind == "DOUBLE_CHECK",
            )
        )
    }
    assert set(verdicts) == {"1a", "1b"}
    assert all(verdict.status == "DISAGREES" for verdict in verdicts.values())
    assert verdicts["1a"].detail["first_awarded"] == 2
    assert verdicts["1a"].detail["second_awarded"] == 1

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


class OverMaxSecondOpinion(StubProvider):
    """A second examiner that returns a value no question can be worth."""

    def generate(self, request, api_key):
        if "independent double check" in request.prompt:
            context = next((part.text for part in request.inputs if part.text), "")
            question_id = context.splitlines()[0].split(":", 1)[1].strip()
            self.calls += 1
            payload = dict(self.answers[question_id])
            payload["awarded_marks"] = 99
            payload["components"] = []
            return LLMResponse(
                text=json.dumps(payload),
                model=request.model,
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                finish_reason="STOP",
                provider_request_id=f"stub-over-max-{self.calls}",
                latency_ms=1,
            )
        return super().generate(request, api_key)


def test_a_second_award_above_the_maximum_is_unverifiable_not_a_disagreement(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """An impossible second award is an unusable opinion, not a mark to adjudicate."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="double-over-max")

    outcome = _run(
        monkeypatch, session_factory, job.id, settings, OverMaxSecondOpinion(LOW_CONFIDENCE)
    )

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert outcome.detail["double_check"]["unverifiable"] == 2
    assert outcome.detail["double_check"]["disagreements"] == 0

    db_session.expire_all()
    verdicts = {
        verdict.question_id: verdict
        for verdict in db_session.scalars(
            select(VerificationResult).where(
                VerificationResult.job_id == job.id,
                VerificationResult.kind == "DOUBLE_CHECK",
            )
        )
    }
    assert set(verdicts) == {"1a", "1b"}
    for question_id, max_marks in (("1a", 2), ("1b", 3)):
        verdict = verdicts[question_id]
        assert verdict.status == "UNVERIFIABLE"
        assert verdict.detail["second_awarded"] == 99
        assert verdict.detail["max_marks"] == max_marks

    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    for question_id, first_award in (("1a", 2), ("1b", 3)):
        row = rows[question_id]
        assert row.awarded_marks == first_award
        assert row.processing_state == "MARKED"
        assert not any(
            concern["code"] == "DOUBLE_CHECK_DISAGREEMENT"
            for concern in row.scheme_concerns
        )


def test_the_double_check_is_not_asked_twice_for_the_same_question(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A resumed execution must not spend a second request on a taken verdict."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="double-idempotent")
    provider = StubProvider(LOW_CONFIDENCE)

    first = _run(monkeypatch, session_factory, job.id, settings, provider)
    assert first.detail["double_check"]["checked"] == 2
    calls_after_first_run = provider.calls
    assert calls_after_first_run == 5  # three markings and two second opinions

    second = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert provider.calls == calls_after_first_run, (
        "the second execution called the provider again for a question it had "
        "already double-checked"
    )
    assert second.detail["double_check"]["checked"] == 0
    assert second.detail["double_check"]["already_checked"] == 2

    db_session.expire_all()
    stored = db_session.get(CorrectionJob, job.id)
    assert stored.double_check_status == "COMPLETED"
    assert stored.disagreement_status == "NONE"
    verdicts = {
        verdict.question_id: verdict.status
        for verdict in db_session.scalars(
            select(VerificationResult).where(
                VerificationResult.job_id == job.id,
                VerificationResult.kind == "DOUBLE_CHECK",
            )
        )
    }
    assert verdicts == {"1a": "AGREES", "1b": "AGREES"}


def _more_pages(db_session, page, count: int) -> list:
    """Add pages to the fixture document, as a scanned multi-page script."""

    extra = []
    for index in range(2, count + 1):
        row = DocumentPage(
            tenant_id=page.tenant_id,
            document_id=page.document_id,
            page_index=index,
            storage_key=page.storage_key,
            quality_status="READABLE",
            # Each rendered page has its own checksum; a repeated one is the
            # duplicate-image signal the coverage audit reports.
            checksum=(f"{page.checksum[:55]}-{index:08d}" if page.checksum else None),
        )
        db_session.add(row)
        extra.append(row)
    document = db_session.get(Document, page.document_id)
    if document is not None:
        document.page_count = max(int(document.page_count or 0), count)
    db_session.commit()
    return extra


def test_an_unmapped_question_beyond_the_page_limit_requires_review(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A truncated script must not produce an unreviewed award.

    The pipeline sends at most six page images per question.  A seven-page script
    with no page mapping would otherwise be marked from pages 1-6, so an answer
    on page 7 could be recorded as absent.  The award is kept as evidence and a
    person decides it.
    """

    first = _page(db_session, paper, identity, settings := _settings(tmp_path))
    _more_pages(db_session, first, 7)
    job = _job(db_session, paper, identity, key="page-limit")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert any("PAGE_LIMIT_TRUNCATED" in reason for reason in outcome.detail["review_reasons"])

    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.processing_state for row in rows} == {"NEEDS_REVIEW"}
    assert all(
        any("PAGE_LIMIT_TRUNCATED" in concern["message"] for concern in row.scheme_concerns)
        for row in rows
    )
    assert sum(row.awarded_marks for row in rows) == 5, "the award is kept as evidence"


class CancellingRecoveryProvider(StubProvider):
    """Fails the first marking, then requests cancellation during recovery.

    Call 1 is the marking request for question 1a and returns unusable text, so
    one question needs recovery.  Calls 2 and 3 mark 1b and 2.  Call 4 is the
    recovery request for 1a; it answers with a usable mark and, while answering,
    records a cancellation request in another session, exactly as a teacher
    pressing cancel would.
    """

    def __init__(self, session_factory, cancel_on_call: int = 4) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.cancel_on_call = cancel_on_call
        self.call_index = 0

    def generate(self, request, api_key):
        self.call_index += 1
        if self.call_index == 1:
            self.calls += 1
            return LLMResponse(
                text="not json at all",
                model=request.model,
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                finish_reason="STOP",
                provider_request_id=f"stub-invalid-{self.calls}",
                latency_ms=1,
            )
        if self.call_index == self.cancel_on_call:
            with self.session_factory() as session:
                job = session.scalar(select(CorrectionJob))
                job.cancel_requested = True
                session.commit()
        return super().generate(request, api_key)


def test_a_cancel_during_recovery_discards_the_recovered_rows(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A cancelled job must not keep the marks recovery produced."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="cancel-recovery")

    outcome = _run(
        monkeypatch,
        session_factory,
        job.id,
        settings,
        CancellingRecoveryProvider(session_factory),
    )

    db_session.expire_all()
    assert outcome.state is JobState.CANCELLED, outcome.detail
    assert db_session.get(CorrectionJob, job.id).cancel_requested is True
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert rows == [], "a cancelled job kept the rows recovery had written"


class TranscriptionProvider(StubProvider):
    """Answers the blind transcription prompt with a recorded second reading."""

    def __init__(self, transcripts: dict[str, str | None]) -> None:
        super().__init__()
        self.transcripts = transcripts

    def generate(self, request, api_key):
        if "independent transcription" in request.prompt:
            context = next((part.text for part in request.inputs if part.text), "")
            question_id = context.splitlines()[0].split(":", 1)[1].strip()
            self.calls += 1
            payload = {
                "question_id": question_id,
                "transcript": self.transcripts.get(question_id),
                "confidence": 0.9,
                "review_reasons": [],
            }
            return LLMResponse(
                text=json.dumps(payload),
                model=request.model,
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                finish_reason="STOP",
                provider_request_id=f"stub-transcribe-{self.calls}",
                latency_ms=1,
            )
        return super().generate(request, api_key)


def test_a_blind_reading_that_finds_writing_reviews_the_blank_zero(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A zero taken beside a blank answer is the shape of an unread answer."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(transcription_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="transcription-differs")
    provider = TranscriptionProvider({"2": "x = 3, y = 7"})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert outcome.detail["transcription"] == {
        "enabled": True,
        "checked": 1,
        "agreements": 0,
        "differences": 1,
        "absent": 0,
        "unverifiable": 0,
    }
    assert provider.calls == 4, "three markings and one blind reading"

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    assert rows["2"].awarded_marks == 0, "the award is not changed by a transcription"
    assert rows["2"].processing_state == "NEEDS_REVIEW"
    assert rows["2"].student_answer is None, "the original evidence is preserved"
    assert any(
        concern["code"] == "TRANSCRIPTION_DIFFERS"
        for concern in rows["2"].scheme_concerns
    )

    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "DIFFERS"
    assert verdict.detail["transcript"] == "x = 3, y = 7"
    assert verdict.detail["original_answer"] is None

    db_session.expire_all()
    run = db_session.scalar(
        select(EngineRun).where(
            EngineRun.job_id == job.id, EngineRun.stage == "TRANSCRIPTION"
        )
    )
    assert run.detail["differences"] == 1
    assert run.detail["selection"]["2"][0].startswith("BLANK_ZERO")


def test_a_blind_reading_that_agrees_leaves_the_mark_alone(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Two readers who see the same blank produce no concern."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(transcription_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="transcription-agrees")
    provider = TranscriptionProvider({"2": ""})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert outcome.detail["transcription"]["absent"] == 1
    assert outcome.detail["transcription"]["differences"] == 0

    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    zero = next(row for row in rows if row.question_id == "2")
    assert zero.processing_state == "CONFIRMED_ZERO"
    assert not any(
        concern["code"] == "TRANSCRIPTION_DIFFERS" for concern in zero.scheme_concerns
    )


def test_economy_never_pays_for_a_blind_reading(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(transcription_enabled=True)
    ))
    paper.assignment.review_mode = "ECONOMY"
    db_session.commit()
    job = _job(db_session, paper, identity, key="transcription-economy")
    provider = TranscriptionProvider({"2": "x = 3"})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"] is None
    assert provider.calls == 3


def test_transcription_is_off_unless_the_operator_enables_it(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="transcription-disabled")
    provider = TranscriptionProvider({"2": "x = 3"})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"] is None
    assert provider.calls == 3


def test_review_modes_trade_requests_for_certainty(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The assignment's review mode is a visible, counted choice.

    ECONOMY buys no second opinion.  BALANCED re-marks the one award worth
    doubting (full marks on a three-mark question).  ACCURACY also samples one
    confident answer, which is the only way a confidently wrong mark is found.
    """

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))

    expected = {"ECONOMY": (3, 0), "BALANCED": (4, 1), "ACCURACY": (5, 2)}
    for mode, (provider_calls, checks) in expected.items():
        paper.assignment.review_mode = mode
        db_session.commit()
        job = _job(db_session, paper, identity, key=f"mode-{mode}")
        provider = StubProvider()

        outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

        assert outcome.state is JobState.FINALIZING, (mode, outcome.detail)
        assert provider.calls == provider_calls, mode
        assert outcome.detail["review_mode"] == mode
        assert outcome.detail["double_check"]["checked"] == checks, mode

        db_session.expire_all()
        run = db_session.scalar(
            select(EngineRun).where(
                EngineRun.job_id == job.id, EngineRun.stage == "DOUBLE_CHECK"
            )
        )
        assert run.detail["mode"] == mode
        if checks == 0:
            assert "ECONOMY" in run.detail["reason"]
            assert "selection" not in run.detail
        else:
            assert any(
                reason.startswith("FULL_MARKS_VALUABLE")
                for reason in run.detail["selection"]["1b"]
            )


def test_economy_still_runs_every_integrity_check(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Economy buys fewer opinions, never fewer checks."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    paper.assignment.review_mode = "ECONOMY"
    db_session.commit()
    job = _job(db_session, paper, identity, key="economy-integrity")
    provider = StubProvider(MISCOUNTED)

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert provider.calls == 3, "no second opinion is bought, but every mark is checked"

    db_session.expire_all()
    run = db_session.scalar(
        select(EngineRun).where(EngineRun.job_id == job.id, EngineRun.stage == "MARKING")
    )
    assert any(
        "COMPONENT_TOTAL_MISMATCH" in finding
        for finding in run.detail["integrity_findings"]
    ), run.detail["integrity_findings"]

    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    assert rows["1a"].awarded_marks == 2
    assert rows["1a"].processing_state == "NEEDS_REVIEW"


def test_an_award_the_approved_scheme_does_not_support_requires_review(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The scheme is evidence independent of the reply that produced the mark."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    db_session.add(
        MarkingCriterion(
            tenant_id=identity.tenant_a.id,
            scheme_version_id=paper.scheme_version.id,
            question_id="1a",
            code="M1",
            ordinal=0,
            marks=1,
            description="M1 for forming the equation",
            dependencies=[],
            alternatives=[],
            source_ref={},
        )
    )
    db_session.commit()
    job = _job(db_session, paper, identity, key="scheme-mismatch")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert any("UNKNOWN_CRITERION" in finding for finding in outcome.detail["scheme_findings"])

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    messages = [concern["message"] for concern in rows["1a"].scheme_concerns]
    assert any("UNKNOWN_CRITERION" in message for message in messages), messages
    assert any("OVER_SCHEME_CAPACITY" in message for message in messages), messages
    assert rows["1a"].awarded_marks == 2, "the award is kept as evidence"
    assert rows["1a"].processing_state == "NEEDS_REVIEW"
    # No scheme detail for 1b is silence, not a finding.
    assert rows["1b"].processing_state == "MARKED"


def test_a_page_missing_from_storage_blocks_marking_before_any_request(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A page the document declares but storage lacks may hold the answer."""

    page = _page(db_session, paper, identity, settings := _settings(tmp_path))
    document = db_session.get(Document, page.document_id)
    document.page_count = 3
    db_session.commit()
    job = _job(db_session, paper, identity, key="missing-page")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.REVIEW_REQUIRED
    assert outcome.detail["reason"] == "PAGE_COVERAGE_INCOMPLETE"
    assert outcome.detail["page_coverage"] == [{"code": "MISSING_PAGE", "blocking": True}]
    assert provider.calls == 0, "marking an incomplete script buys requests it cannot use"

    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id) == []
    run = db_session.scalar(
        select(EngineRun).where(EngineRun.job_id == job.id, EngineRun.stage == "MARKING")
    )
    assert run.detail["blocked"] == "MISSING_PAGE"
    assert run.outcome == "REVIEW_REQUIRED"


def test_a_partially_mapped_script_is_marked_and_the_gap_is_reviewed(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """When a question has no mapping, an unmapped page can hide its continuation."""

    first = _page(db_session, paper, identity, settings := _settings(tmp_path))
    _more_pages(db_session, first, 2)
    db_session.add(
        PageQuestionMapping(
            tenant_id=identity.tenant_a.id,
            document_id=first.document_id,
            page_id=first.id,
            blueprint_version_id=paper.blueprint.id,
            question_id="1a",
            confidence=1.0,
            method="TEXT_MATCH",
            source_ref={},
        )
    )
    db_session.commit()
    job = _job(db_session, paper, identity, key="partial-mapping")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert provider.calls == 3, "the award is still taken and kept as evidence"
    assert outcome.detail["page_coverage"] == [{"code": "UNMAPPED_PAGE", "blocking": False}]

    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.processing_state for row in rows} == {"NEEDS_REVIEW"}
    assert sum(row.awarded_marks for row in rows) == 5
    assert all(
        any("PAGE_COVERAGE" in concern["message"] for concern in row.scheme_concerns)
        for row in rows
    )


def test_a_page_mapping_removes_the_truncation_review(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """When the mapping fits inside one request, the run is not flagged."""

    first = _page(db_session, paper, identity, settings := _settings(tmp_path))
    pages = [first, *_more_pages(db_session, first, 7)]
    for page in pages[:6]:
        for question_id in ("1a", "1b", "2"):
            db_session.add(
                PageQuestionMapping(
                    tenant_id=identity.tenant_a.id,
                    document_id=page.document_id,
                    page_id=page.id,
                    blueprint_version_id=paper.blueprint.id,
                    question_id=question_id,
                    confidence=1.0,
                    method="TEXT_MATCH",
                    source_ref={},
                )
            )
    db_session.commit()
    job = _job(db_session, paper, identity, key="page-mapped")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.FINALIZING, outcome.detail
    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.processing_state for row in rows} == {"MARKED", "CONFIRMED_ZERO"}


def test_a_document_that_failed_processing_blocks_marking_before_any_request(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A document nobody could read is not the same as a blank answer."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    db_session.add(
        Document(
            tenant_id=identity.tenant_a.id,
            submission_id=paper.submission.id,
            exam_id=paper.exam.id,
            kind="STUDENT",
            storage_key="submissions/8a6b/continuation.pdf",
            original_filename="continuation.pdf",
            sha256="b" * 64,
            mime_type="application/pdf",
            size_bytes=len(b"pdf"),
            page_count=2,
            status="REJECTED",
        )
    )
    db_session.commit()
    job = _job(db_session, paper, identity, key="unprocessed-document")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.REVIEW_REQUIRED
    assert outcome.detail["reason"] == "PAGE_COVERAGE_INCOMPLETE"
    assert {"code": "UNPROCESSED_DOCUMENT", "blocking": True} in outcome.detail[
        "page_coverage"
    ]
    assert provider.calls == 0, "a document nobody read cannot be marked around"

    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id) == []


def test_an_unreadable_page_prevents_a_confident_zero(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """One unreadable page makes every award on that script provisional."""

    first = _page(db_session, paper, identity, settings := _settings(tmp_path))
    second = _more_pages(db_session, first, 2)[0]
    second.quality_status = "UNREADABLE"
    db_session.commit()
    job = _job(db_session, paper, identity, key="unreadable-page")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert any(
        "unreadable" in reason for reason in outcome.detail["review_reasons"]
    ), outcome.detail["review_reasons"]

    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.processing_state for row in rows} == {"NEEDS_REVIEW"}
    zero = next(row for row in rows if row.question_id == "2")
    assert (zero.status, zero.awarded_marks) == ("REVIEW_REQUIRED", 0)


def test_a_duplicated_page_image_is_marked_and_reviewed(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A repeated page makes the reading order ambiguous; the award is kept."""

    first = _page(db_session, paper, identity, settings := _settings(tmp_path))
    second = _more_pages(db_session, first, 2)[0]
    second.checksum = first.checksum
    db_session.commit()
    job = _job(db_session, paper, identity, key="duplicate-page")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert {"code": "DUPLICATE_PAGE", "blocking": False} in outcome.detail[
        "page_coverage"
    ]

    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.processing_state for row in rows} == {"NEEDS_REVIEW"}
    assert sum(row.awarded_marks for row in rows) == 5, "the award is kept as evidence"


class CapturingProvider(StubProvider):
    """Keeps every request so its inputs can be audited."""

    def __init__(self, answers: dict[str, dict] | None = None) -> None:
        super().__init__(answers)
        self.requests = []

    def generate(self, request, api_key):
        self.requests.append(request)
        return super().generate(request, api_key)


def test_a_blind_reading_receives_neither_scheme_nor_marks(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The reader must not be able to agree with a conclusion it never saw."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(transcription_enabled=True)
    ))
    db_session.add(
        MarkingCriterion(
            tenant_id=identity.tenant_a.id,
            scheme_version_id=paper.scheme_version.id,
            question_id="2",
            code="M1",
            ordinal=0,
            marks=1,
            description="ZEBRA scheme note that must not reach the reader",
            dependencies=[],
            alternatives=[],
            source_ref={},
        )
    )
    db_session.commit()
    job = _job(db_session, paper, identity, key="blind-context")
    provider = CapturingProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["checked"] == 1
    transcriptions = [
        request for request in provider.requests if "independent transcription" in request.prompt
    ]
    assert len(transcriptions) == 1
    request = transcriptions[0]
    texts = [part.text for part in request.inputs if part.text]
    assert len(texts) == 1, "the reader gets the question, not a second scheme block"
    assert "Mark scheme" not in texts[0]
    assert all("ZEBRA" not in text for text in texts)
    assert "Mark scheme criteria" not in request.prompt
    assert request.response_schema["properties"].keys() >= {"question_id", "transcript"}
    assert "awarded_marks" not in request.response_schema["properties"]
    # Pages still reach the reader; it reads the script, just not the marking.
    assert len(request.inputs) == 2

    marking = next(
        request
        for request in provider.requests
        if "independent transcription" not in request.prompt
        and any((part.text or "").startswith("Question: 2") for part in request.inputs)
    )
    assert any("Mark scheme criteria" in (part.text or "") for part in marking.inputs)
    assert any("ZEBRA" in (part.text or "") for part in marking.inputs)


def test_a_scheme_contradiction_is_not_second_guessed(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A question a person already decides is not re-marked by another stage."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    for code, description in (
        ("M1", "M1 for forming the equation"),
        ("A1", "4"),
    ):
        db_session.add(
            MarkingCriterion(
                tenant_id=identity.tenant_a.id,
                scheme_version_id=paper.scheme_version.id,
                question_id="1a",
                code=code,
                ordinal=0 if code == "M1" else 1,
                marks=1,
                description=description,
                dependencies=[],
                alternatives=[],
                source_ref={},
            )
        )
    db_session.commit()
    job = _job(db_session, paper, identity, key="scheme-not-second-guessed")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    # The contradiction stops the question from being re-marked, so the second
    # opinion cannot replace the evidence a person is about to read.  Only 1b,
    # whose full marks are worth confirming, is re-marked.
    assert outcome.detail["double_check"]["checked"] == 1

    db_session.expire_all()
    row = db_session.scalar(
        select(QuestionResult).where(
            QuestionResult.job_id == job.id, QuestionResult.question_id == "1a"
        )
    )
    assert row.awarded_marks == 2, "no later stage changed the award"
    assert row.student_answer == "x = 3", "the quoted evidence is preserved"
    assert any(
        "SCHEME_ANSWER_DIFFERENT" in (concern.get("message") or "")
        for concern in row.scheme_concerns
    ), row.scheme_concerns
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "1a",
            VerificationResult.kind == "DOUBLE_CHECK",
        )
    )
    assert verdict is None, "a reviewed question was sent for a second opinion"


def test_accuracy_keeps_integrity_and_transcription_when_double_check_is_off(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The operator's switch disables second opinions, never the reading stage."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path,
        marking=MarkingSettings(transcription_enabled=True, double_check_enabled=False),
    ))
    paper.assignment.review_mode = "ACCURACY"
    db_session.commit()
    job = _job(db_session, paper, identity, key="accuracy-double-off")
    provider = TranscriptionProvider({"2": ""})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert outcome.detail["double_check"]["enabled"] is False
    assert outcome.detail["transcription"]["absent"] == 1
    assert provider.calls == 4, "three markings and one blind reading"

    db_session.expire_all()
    stage = db_session.scalar(
        select(EngineRun).where(
            EngineRun.job_id == job.id, EngineRun.stage == "DOUBLE_CHECK"
        )
    )
    assert stage.outcome == "SKIPPED"
    assert db_session.get(CorrectionJob, job.id).double_check_status == "DISABLED"


def test_a_resumed_run_does_not_pay_for_the_same_blind_reading(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A stored reading is a decision: the next execution must not buy it twice."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(transcription_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="transcription-resume")
    first = TranscriptionProvider({"2": ""})

    _run(monkeypatch, session_factory, job.id, settings, first)
    assert first.calls == 4

    second = TranscriptionProvider({"2": "x = 3"})
    outcome = _run(monkeypatch, session_factory, job.id, settings, second)

    assert second.calls == 0, "the resumed run re-asked the reader"
    assert outcome.detail["transcription"]["checked"] == 0
    assert outcome.detail["double_check"]["checked"] == 0


class CancellingDoubleCheckProvider(StubProvider):
    """Requests cancellation while the second opinion is being taken."""

    def __init__(self, session_factory, cancel_on_call: int = 4) -> None:
        super().__init__(LOW_CONFIDENCE)
        self.session_factory = session_factory
        self.cancel_on_call = cancel_on_call
        self.call_index = 0

    def generate(self, request, api_key):
        self.call_index += 1
        if self.call_index == self.cancel_on_call:
            with self.session_factory() as session:
                job = session.scalar(select(CorrectionJob))
                job.cancel_requested = True
                session.commit()
        return super().generate(request, api_key)


def test_a_cancel_during_the_double_check_keeps_no_verdicts(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A cancelled job may not leave a verdict that a resumed run would trust."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    job = _job(db_session, paper, identity, key="cancel-double-check")
    provider = CancellingDoubleCheckProvider(session_factory)

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.CANCELLED, outcome.detail
    assert provider.calls == 4, "the run stopped spending once cancellation was seen"
    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id) == []
    assert (
        db_session.scalars(
            select(VerificationResult).where(VerificationResult.job_id == job.id)
        ).all()
        == []
    ), "a discarded row left its verification records behind"
