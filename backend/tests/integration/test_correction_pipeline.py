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

import pytest
from app.core.config import (
    MarkingSettings,
    ModelQuota,
    QuotaSettings,
    StorageSettings,
    get_settings,
)
from app.core.errors import AppError
from app.core.ids import content_hash
from app.correction.aetrix.pipeline import _MarkingRun
from app.correction.engine import AetrixEngine
from app.correction.scheme_criteria import criteria_rules_hash
from app.db.models import (
    CorrectionJob,
    CriterionResult,
    Document,
    DocumentPage,
    EngineRun,
    ExamBlueprintVersion,
    JobApproval,
    MarkingCriterion,
    MarkingEvidence,
    PageQuestionMapping,
    ProviderUsage,
    QuestionResult,
    VerificationResult,
)
from app.db.repositories import ResultRepository
from app.jobs.pipeline import build_pipeline
from app.jobs.runner import JobRunner
from app.jobs.states import JobState
from app.prompts.registry import PromptRegistry
from app.providers.base import LLMResponse, TokenUsage
from app.providers.gemini import GeminiProvider
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
    # ``page`` is part of the reply contract: a quotation with no page cannot be
    # found again, so the engine refuses it.  These fixtures are one-page
    # scripts, so every quotation is on page 1.
    return {
        "code": code,
        "marks": 1,
        "awarded": awarded,
        "reason": "the step is present" if awarded else "the step is missing",
        "evidence": evidence,
        "page": 1,
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


def _settings(tmp_path, *, transcription: bool = False, gate: bool = False, **overrides):
    """Per-question settings for a suite that pins the per-question engine.

    Whole paper is the product default now, but every test here drives one
    question at a time (double check, transcription, cancellation, verification),
    so the mode is stated rather than inherited — the stub provider answers a
    single-question request, not a paper.

    The blind second reading is on in the product and off here unless a test asks
    for it: these stubs answer a marking request, so a test that is not about the
    reading stage must not be made to pay for one or to interpret its absence.
    """

    settings = get_settings().model_copy(
        update={"storage": StorageSettings(root=tmp_path / "documents")}
    )
    # The production default allows five marking requests a minute for a free-tier
    # key.  A suite that runs several jobs in one test would exhaust that budget
    # and then fail on the budget instead of on the behaviour it is about, so the
    # fixture states its own allowance.  The budget rules themselves are proven in
    # ``tests/unit/test_credential_pools.py``; nothing here asserts about them.
    # Every model this deployment can actually call needs a declared allowance:
    # the engine refuses to spend against an unknown one, and the checkers are
    # now reached by these tests too.  The set comes from the configured limits,
    # so adding a model cannot silently leave it unspendable.
    declared = set(settings.quota.model_limits) | {
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-4-hydrogen",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    }
    settings = settings.model_copy(
        update={
            "quota": QuotaSettings(
                model_limits={
                    model: ModelQuota(
                        requests_per_minute=60,
                        tokens_per_minute=2_000_000,
                        requests_per_day=1000,
                        source="operator",
                    )
                    for model in declared
                }
            )
        }
    )
    if overrides:
        settings = settings.model_copy(update=overrides)
    marking = settings.marking.model_copy(
        update={
            "marking_mode": "PER_QUESTION",
            "transcription_enabled": transcription,
            # The evidence gate is the production default and these tests state
            # it rather than inherit it: a suite that turns the blind reading off
            # would otherwise send every award in its fixtures to review, which
            # would replace each test's own subject with that one outcome.  The
            # gate has its own tests below, which ask for it explicitly.
            "require_evidence_for_award": gate,
        }
    )
    return settings.model_copy(update={"marking": marking})


def _reapprove_criteria(db_session, paper) -> None:
    """Record the digest of the marking rules as they now stand.

    A test that rewrites a scheme is a re-approval, not a silent edit: the engine
    marks only against criteria whose approval names the rules reviewed.
    """

    rows = (
        db_session.query(MarkingCriterion)
        .filter(MarkingCriterion.scheme_version_id == paper.scheme_version.id)
        .all()
    )
    paper.scheme_version.criteria_rules_hash = criteria_rules_hash(
        rows, paper.blueprint.structure
    )
    db_session.commit()


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

    #: The second reading is answered by a different model in production, and the
    #: fixture says so unless a test is about the same-model case.
    reader = "aetrix-blind-reader"

    def __init__(
        self,
        transcripts: dict[str, str | None],
        *,
        model: str | None = None,
        same_model: bool = False,
    ) -> None:
        super().__init__()
        self.transcripts = transcripts
        self.model = model
        #: Answer as the marking model would: independent of nothing.
        self.same_model = same_model
        #: Who the marking chain answered as, learned from its own replies.
        self.read_by: str | None = None

    def generate(self, request, api_key):
        blind = "independent transcription" in request.prompt
        if not blind:
            # Who the marking chain answered as: the same-model case needs it.
            self.read_by = request.model
        if blind:
            context = next((part.text for part in request.inputs if part.text), "")
            question_id = context.splitlines()[0].split(":", 1)[1].strip()
            self.calls += 1
            transcript = self.transcripts.get(question_id)
            payload = {
                "question_id": question_id,
                "evidence_status": "WRITTEN" if (transcript or "").strip() else "ABSENT",
                "transcript": transcript,
                "confidence": 0.9,
                "review_reasons": [],
            }
            return LLMResponse(
                text=json.dumps(payload),
                model=(
                    self.read_by or request.model
                    if self.same_model
                    else self.model or self.reader
                ),
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

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
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
        "not_independent": 0,
        "unknown_independence": 0,
        "unavailable": 0,
        "page_unverified": 0,
        "unverified_award": 0,
        "evidence_failures": 0,
        "evidence_unverified": 0,
        "disagreements": ["2"],
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
    concern = next(
        concern
        for concern in rows["2"].scheme_concerns
        if concern["code"] == "TRANSCRIPTION_DIFFERS"
    )
    assert concern["severity"] == "DEFINITE_MISMATCH"

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

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-agrees")
    provider = TranscriptionProvider({"2": ""})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert outcome.detail["transcription"]["absent"] == 1
    assert outcome.detail["transcription"]["differences"] == 0
    # A one-page script has no page to choose, so the page selection is
    # independent of the marking pass and an agreement is not circular.
    assert outcome.detail["transcription"]["page_unverified"] == 0

    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    zero = next(row for row in rows if row.question_id == "2")
    assert zero.processing_state == "CONFIRMED_ZERO"
    assert not any(
        concern["code"] == "TRANSCRIPTION_DIFFERS" for concern in zero.scheme_concerns
    )
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.detail["page_source"] == "SINGLE_PAGE"
    assert verdict.detail["page_confidence"] == "INDEPENDENT"


#: Q6 of production correction 7ed1c143 as the marking pass recorded it: the
#: minus that belongs to the second bracket has been read as a plus inside it.
Q6_MISREAD = "4x^2 + 12x + 9 - 4x^2 - 12x + 9"

#: The same line as it is written on the page: two brackets, subtracted.
Q6_WRITTEN = "(4x^2 + 12x + 9) - (4x^2 - 12x + 9)"


def test_the_q6_misread_minus_cannot_stand_as_a_confident_zero(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The Mission 3 defect, end to end: a sign nobody read must stop a mark.

    The marking pass writes the second bracket's subtraction as if the bracket
    had been added; the blind reading of the same page keeps the brackets and
    the minus.  The zero
    is internally consistent, so no arithmetic check can see the problem — the
    only defence is that two readers disagree about what is on the page.
    """

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="q6-sign-misread")
    answers = dict(ANSWERS)
    answers["2"] = {
        **_answer("2", 0, [_component("B1", False, Q6_MISREAD)], None),
        # The production zero was recorded at full confidence: nothing about how
        # sure the marking pass was may keep the disagreement out of review.
        "confidence": 1.0,
    }
    provider = TranscriptionProvider({"2": Q6_WRITTEN})
    provider.answers = answers

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert outcome.detail["transcription"]["differences"] == 1
    assert outcome.detail["transcription"]["disagreements"] == ["2"]
    # The guard, not only the row: a disagreement fails this run's validation, so
    # no later stage that happens to balance can settle the paper around it, and
    # this run's marks are not presented at all.
    assert outcome.detail.get("guard_reason"), outcome.detail
    assert outcome.detail["guard"] == "BLOCKED", outcome.detail["guard_reason"]

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    zero = rows["2"]
    assert zero.awarded_marks == 0, "a disagreement never rewrites a mark"
    assert zero.processing_state == "NEEDS_REVIEW"
    assert zero.student_answer is None, "the original reading is preserved"
    concern = next(
        concern
        for concern in zero.scheme_concerns
        if concern["code"] == "TRANSCRIPTION_DIFFERS"
    )
    assert concern["severity"] == "DEFINITE_MISMATCH"
    assert Q6_WRITTEN in concern["message"]
    assert Q6_MISREAD in concern["message"]

    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "DIFFERS"
    difference = verdict.detail["differences"][0]
    assert difference["kind"] == "SIGN"
    assert difference["marking"] == Q6_MISREAD
    assert difference["independent"] == Q6_WRITTEN
    # Both wrong signs are reported, not only the first.
    assert len(verdict.detail["differences"]) == 2
    assert {item["kind"] for item in verdict.detail["differences"]} == {"SIGN"}
    # The provenance a reviewer needs: which page was read, how it was chosen,
    # the ranking that selected this question, and the reply as it arrived.
    assert verdict.detail["page_source"] == "EVIDENCE"
    assert verdict.detail["pages"] == [1]
    assert verdict.detail["independence"] == "MODEL"
    assert verdict.detail["ranking"]["rank"] == 1
    assert Q6_WRITTEN in verdict.detail["raw_response"]

    # The marking pass's own words are untouched: only a person may replace them.
    quotes = db_session.scalars(
        select(MarkingEvidence).where(MarkingEvidence.question_result_id == zero.id)
    )
    assert [item.quote for item in quotes] == [Q6_MISREAD]


def test_a_reader_who_is_the_marking_model_is_not_independent(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The same model asked twice is a prompt check, and it must say so."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-same-model")
    provider = TranscriptionProvider({"2": ""}, same_model=True)

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["not_independent"] == 1
    assert outcome.detail["transcription"]["differences"] == 0

    db_session.expire_all()
    zero = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "2"
    )
    assert zero.processing_state == "NEEDS_REVIEW"
    concern = next(
        concern
        for concern in zero.scheme_concerns
        if concern["code"] == "TRANSCRIPTION_NOT_INDEPENDENT"
    )
    assert concern["severity"] == "POSSIBLE_MISMATCH"
    assert zero.awarded_marks == 0


class MalformedReaderProvider(StubProvider):
    """Answers the blind prompt with prose instead of the output contract."""

    def generate(self, request, api_key):
        if "independent transcription" in request.prompt:
            self.calls += 1
            return LLMResponse(
                text="I think the candidate meant to write 18.",
                model="aetrix-blind-reader",
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                finish_reason="STOP",
                provider_request_id=f"stub-malformed-{self.calls}",
                latency_ms=1,
            )
        return super().generate(request, api_key)


def test_a_malformed_reading_cannot_confirm_a_zero(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A reply outside the contract verifies nothing, so the zero is not settled."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-malformed")

    outcome = _run(monkeypatch, session_factory, job.id, settings, MalformedReaderProvider())

    assert outcome.detail["transcription"]["unverifiable"] == 1
    assert outcome.detail["transcription"]["agreements"] == 0

    db_session.expire_all()
    zero = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "2"
    )
    assert zero.awarded_marks == 0
    assert zero.processing_state == "NEEDS_REVIEW"
    assert any(
        concern["code"] == "TRANSCRIPTION_UNVERIFIED"
        for concern in zero.scheme_concerns
    )
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "UNVERIFIABLE"


def test_a_reader_who_finds_nothing_where_the_mark_quotes_work_disagrees(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """An empty reading is a claim about the page, not proof that nothing is there."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-independent-absent")
    answers = dict(ANSWERS)
    answers["2"] = _answer("2", 0, [_component("B1", False, Q6_WRITTEN)], None)
    provider = TranscriptionProvider({"2": None})
    provider.answers = answers

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert outcome.detail["transcription"]["differences"] == 1
    db_session.expire_all()
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "DIFFERS"
    assert verdict.detail["differences"][0]["kind"] == "INDEPENDENT_ABSENT"


def test_economy_never_pays_for_a_blind_reading(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    paper.assignment.review_mode = "ECONOMY"
    db_session.commit()
    job = _job(db_session, paper, identity, key="transcription-economy")
    provider = TranscriptionProvider({"2": "x = 3"})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"] is None
    assert provider.calls == 3


def test_the_operator_switch_still_decides(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The second reading is part of the correction now, and can still be shut off."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="transcription-disabled")
    provider = TranscriptionProvider({"2": "x = 3"})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"] is None
    assert provider.calls == 3, "a disabled stage costs nothing"


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
    # The reply reaches the question's two marks through a code the approved
    # scheme does not define, so the award rests on nothing the scheme printed.
    answers = {
        **ANSWERS,
        "1a": _answer(
            "1a",
            2,
            [_component("M1", True, "2x + 6 = 12"), _component("X9", True, "x = 3")],
            "x = 3",
        ),
    }
    job = _job(db_session, paper, identity, key="scheme-mismatch")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider(answers))

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert any("UNKNOWN_CRITERION" in finding for finding in outcome.detail["scheme_findings"])

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    messages = [concern["message"] for concern in rows["1a"].scheme_concerns]
    assert any("UNKNOWN_CRITERION" in message for message in messages), messages
    assert rows["1a"].awarded_marks == 2, "the award is kept as evidence"
    assert rows["1a"].processing_state == "NEEDS_REVIEW"
    # A question whose reply names only defined mark points is unaffected.
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


@pytest.mark.parametrize("document_status", ["UPLOADED", "REJECTED"])
def test_a_document_that_failed_processing_blocks_marking_before_any_request(
    monkeypatch,
    session_factory,
    db_session,
    paper,
    identity,
    provider_credential,
    tmp_path,
    document_status,
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
            status=document_status,
        )
    )
    db_session.commit()
    job = _job(db_session, paper, identity, key=f"unprocessed-document-{document_status}")
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


#: Fields Mission 5 found in the blind request, plus the rest of the marking
#: context.  Every one carries a value that would be visible if it leaked.
BLIND_FORBIDDEN = {
    "maximum marks": "Maximum marks",
    "scheme references": "Scheme references",
    "special instructions": "Special instructions",
    "mark scheme criteria": "Mark scheme criteria",
    "criterion description": "ZEBRA scheme note",
    "expected answer": "ZEBRA-EXPECTED-ANSWER",
    "marking answer": "ZEBRA-MARKING-ANSWER",
    "marking quote": "ZEBRA-MARKING-QUOTE",
    "awarded marks": "ZEBRA-AWARDED-MARKS",
    "confidence": "ZEBRA-CONFIDENCE",
}


def test_a_blind_reading_receives_neither_scheme_nor_marks(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The reader must not be able to agree with a conclusion it never saw."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    # An approved blueprint is immutable, so the blueprint-level sentinels
    # (``special_instructions``, ``criteria_refs``) are proven at the header
    # level in ``tests/unit/test_transcription_blind_inputs.py``; this test proves
    # the scheme, the marks and the marking pass's own reading do not travel.
    # Replace question 2's criteria so the scheme carries a marker the reader must
    # not see, keeping the question's own five marks so the criteria still cover it.
    db_session.query(MarkingCriterion).filter(
        MarkingCriterion.scheme_version_id == paper.scheme_version.id,
        MarkingCriterion.question_id == "2",
    ).delete(synchronize_session=False)
    db_session.add(
        MarkingCriterion(
            tenant_id=identity.tenant_a.id,
            scheme_version_id=paper.scheme_version.id,
            blueprint_version_id=paper.blueprint.id,
            question_id="2",
            code="B1",
            ordinal=0,
            marks=5,
            description="ZEBRA scheme note that must not reach the reader",
            expected_answer="ZEBRA-EXPECTED-ANSWER",
            dependencies=[],
            alternatives=[],
            source_ref={},
        )
    )
    db_session.commit()
    _reapprove_criteria(db_session, paper)
    job = _job(db_session, paper, identity, key="blind-context")
    # The marking pass records its own reading in the answer and the quotation.
    provider = CapturingProvider(
        {
            **ANSWERS,
            "2": _answer(
                "2", 0, [_component("B1", False, "ZEBRA-MARKING-QUOTE")], "ZEBRA-MARKING-ANSWER"
            ),
        }
    )

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["checked"] == 1
    transcriptions = [
        request for request in provider.requests if "independent transcription" in request.prompt
    ]
    assert len(transcriptions) == 1
    request = transcriptions[0]
    texts = [part.text for part in request.inputs if part.text]
    # Apart from the page label each image carries, the reader gets the question
    # and nothing else: no scheme block, no marks, no second opinion.
    prose = [text for text in texts if not text.startswith("Page ")]
    assert len(prose) == 1, "the reader gets the question, not a second scheme block"
    assert prose[0] == "Question: 2\nAnswer type: working"
    assert all("ZEBRA" not in text for text in texts)
    assert "Mark scheme criteria" not in request.prompt
    assert request.response_schema["properties"].keys() >= {"question_id", "transcript"}
    assert "awarded_marks" not in request.response_schema["properties"]
    # Pages still reach the reader; it reads the script, just not the marking.
    images = [part for part in request.inputs if part.image is not None]
    assert len(images) == 1
    assert len(request.inputs) == 3, "question, the page's label and the page image"

    # The serialised request the provider would send: the real Gemini encoder,
    # not a summary of the parts.
    payload = json.dumps(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.prompt}]
                    + [GeminiProvider._part(part) for part in request.inputs],
                }
            ]
        }
    )
    for name, value in BLIND_FORBIDDEN.items():
        assert value.lower() not in payload.lower(), f"{name} reached the blind reader"
    assert "ZEBRA" not in payload
    assert "Maximum marks" not in payload

    marking = next(
        request
        for request in provider.requests
        if "independent transcription" not in request.prompt
        and any((part.text or "").startswith("Question: 2") for part in request.inputs)
    )
    assert any("Mark scheme criteria" in (part.text or "") for part in marking.inputs)
    assert any("ZEBRA" in (part.text or "") for part in marking.inputs)
    assert any("Maximum marks" in (part.text or "") for part in marking.inputs)


class SilentModelProvider(TranscriptionProvider):
    """A reader whose provider does not say which model answered."""

    def __init__(self, transcripts: dict[str, str | None]) -> None:
        super().__init__(transcripts)
        self.reader = ""


def test_an_unreported_reader_model_is_not_independent(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """An unknown identity cannot be claimed as an independent reading."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-unknown-model")
    provider = SilentModelProvider({"2": ""})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["unknown_independence"] == 1
    assert outcome.detail["transcription"]["not_independent"] == 0

    db_session.expire_all()
    zero = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "2"
    )
    assert zero.processing_state == "NEEDS_REVIEW"
    assert any(
        concern["code"] == "TRANSCRIPTION_INDEPENDENCE_UNKNOWN"
        for concern in zero.scheme_concerns
    )
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.detail["independence"] == "UNKNOWN"


def _extra_page(db_session, paper, identity, settings, *, index: int = 2) -> DocumentPage:
    """A second rendered page, so a paper is no longer a single-page script."""

    storage = LocalStorage(settings.storage.root)
    # Distinct bytes: two identical page checksums are a duplicate-page coverage
    # finding, which would put every row in review before transcription runs.
    stored = storage.put(
        f"submissions/8a6b/answer{index}.png", f"png-bytes-{index}".encode(), "image/png"
    )
    document = db_session.scalar(
        select(Document).where(Document.submission_id == paper.submission.id)
    )
    document.page_count = max(document.page_count, index)
    page = DocumentPage(
        tenant_id=identity.tenant_a.id,
        document_id=document.id,
        page_index=index,
        storage_key=stored.key,
        quality_status="READABLE",
        checksum=stored.sha256,
    )
    db_session.add(page)
    db_session.commit()
    return page


def test_a_question_with_no_usable_page_is_not_sent_the_whole_script(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Mission 5: an unmapped question would have carried all eight pages.

    With nothing attributing the question to a page, the request is refused and
    the zero goes to a person.  No request is spent guessing.
    """

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    _extra_page(db_session, paper, identity, settings)
    job = _job(db_session, paper, identity, key="transcription-no-page")
    provider = CapturingProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["unavailable"] == 1, (
        outcome.detail["transcription"]
    )
    assert outcome.detail["transcription"]["checked"] == 1
    assert outcome.detail["transcription"]["differences"] == 0
    # Three marking requests, no blind reading: an unusable request is not sent.
    assert provider.calls == 3
    assert not [
        request for request in provider.requests if "independent transcription" in request.prompt
    ]

    db_session.expire_all()
    zero = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "2"
    )
    assert zero.awarded_marks == 0
    assert zero.processing_state == "NEEDS_REVIEW"
    concern = next(
        concern
        for concern in zero.scheme_concerns
        if concern["code"] == "TRANSCRIPTION_UNAVAILABLE"
    )
    assert concern["severity"] == "POSSIBLE_MISMATCH"
    assert "NO_PAGE_MAPPING" in concern["message"]

    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "UNVERIFIABLE"
    assert verdict.detail["status"] == "UNAVAILABLE"
    assert verdict.detail["reason"] == "NO_PAGE_MAPPING"
    assert verdict.detail["pages"] == []


def test_an_oversized_blind_request_is_not_sent(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A payload over the image budget is refused, not base64'd and hoped for."""

    page = _page(
        db_session,
        paper,
        identity,
        settings := _settings(
            tmp_path,
            transcription=True,
            marking=MarkingSettings(
                transcription_enabled=True, transcription_max_image_bytes=1_048_576
            ),
        ),
    )
    # A two-megabyte page image, larger than the one-megabyte budget above.
    (settings.storage.root / page.storage_key).write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024)
    )
    job = _job(db_session, paper, identity, key="transcription-oversized")
    provider = CapturingProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["unavailable"] == 1
    assert provider.calls == 3

    db_session.expire_all()
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "UNVERIFIABLE"
    assert verdict.detail["reason"].startswith("IMAGE_PAYLOAD_EXCEEDED:")


def test_a_scheme_contradiction_is_not_second_guessed(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A question a person already decides is not re-marked by another stage."""

    _page(db_session, paper, identity, settings := _settings(
        tmp_path, marking=MarkingSettings(double_check_enabled=True)
    ))
    # This paper's question 1a is marked against a scheme that states an answer.
    db_session.query(MarkingCriterion).filter(
        MarkingCriterion.scheme_version_id == paper.scheme_version.id,
        MarkingCriterion.question_id == "1a",
    ).delete(synchronize_session=False)
    for code, description in (
        ("M1", "M1 for forming the equation"),
        ("A1", "4"),
    ):
        db_session.add(
            MarkingCriterion(
                tenant_id=identity.tenant_a.id,
                scheme_version_id=paper.scheme_version.id,
                blueprint_version_id=paper.blueprint.id,
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
    _reapprove_criteria(db_session, paper)
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

    _page(
        db_session,
        paper,
        identity,
        settings := _settings(
            tmp_path, transcription=True, marking=MarkingSettings(double_check_enabled=False)
        ),
    )
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
    kinds = {
        record.kind
        for record in db_session.scalars(
            select(VerificationResult).where(VerificationResult.job_id == job.id)
        )
    }
    assert "INTEGRITY" in kinds, "disabling second opinions must not skip integrity"
    assert "TRANSCRIPTION" in kinds, "the blind reading still ran"
    assert "DOUBLE_CHECK" not in kinds


def test_a_resumed_run_does_not_pay_for_the_same_blind_reading(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A stored reading is a decision: the next execution must not buy it twice."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
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


class CancellingMarkingProvider(StubProvider):
    """Requests cancellation while the first marking request is in flight."""

    def __init__(self, session_factory) -> None:
        super().__init__()
        self.session_factory = session_factory
        self.cancelled = False

    def generate(self, request, api_key):
        if not self.cancelled:
            self.cancelled = True
            with self.session_factory() as session:
                job = session.scalar(select(CorrectionJob))
                job.cancel_requested = True
                session.commit()
        return super().generate(request, api_key)


def test_a_cancel_during_marking_discards_the_rows_and_stops_spending(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="cancel-marking")
    provider = CancellingMarkingProvider(session_factory)

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.CANCELLED, outcome.detail
    assert outcome.detail["reason"] == "cancelled during marking"
    assert provider.calls == 1, "the loop marked the next question after cancellation"
    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id) == []
    assert db_session.scalars(
        select(VerificationResult).where(VerificationResult.job_id == job.id)
    ).all() == []


class CancellingTranscriptionProvider(TranscriptionProvider):
    """Requests cancellation during the blind transcription request."""

    def __init__(self, session_factory, transcripts) -> None:
        super().__init__(transcripts)
        self.session_factory = session_factory

    def generate(self, request, api_key):
        if "independent transcription" in request.prompt:
            with self.session_factory() as session:
                job = session.scalar(select(CorrectionJob))
                job.cancel_requested = True
                session.commit()
        return super().generate(request, api_key)


def test_a_cancel_during_transcription_discards_rows_and_verdicts(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="cancel-transcription")
    provider = CancellingTranscriptionProvider(session_factory, {"2": "x = 3"})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.CANCELLED, outcome.detail
    assert outcome.detail["reason"] == "cancelled during verification"
    assert provider.calls == 4, "three marks and the one selected transcription"
    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id) == []
    assert db_session.scalars(
        select(VerificationResult).where(VerificationResult.job_id == job.id)
    ).all() == []


def test_a_cancel_arriving_before_the_guard_discards_the_finished_run(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Cancellation is observable after the last stage and before the guard."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="cancel-before-guard")
    original = __import__(
        "app.correction.aetrix.pipeline", fromlist=["validation_failed_for"]
    ).validation_failed_for

    def cancel_then_validate(rows, findings):
        with session_factory() as session:
            pending = session.get(CorrectionJob, job.id)
            pending.cancel_requested = True
            session.commit()
        return original(rows, findings)

    monkeypatch.setattr(
        "app.correction.aetrix.pipeline.validation_failed_for", cancel_then_validate
    )
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.CANCELLED, outcome.detail
    assert outcome.detail["reason"] == "cancelled before the result guard"
    assert provider.calls == 3
    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id) == []
    assert db_session.scalars(
        select(VerificationResult).where(VerificationResult.job_id == job.id)
    ).all() == []


def test_a_retry_replaces_a_stale_mathematical_verdict(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A verdict from a reply that no longer exists must not survive a retry."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="stale-verification")

    def invalid_marking(request, api_key):
        del api_key
        return LLMResponse(
            text="not json at all",
            model=request.model,
            usage=TokenUsage(input_tokens=10, output_tokens=10),
            finish_reason="STOP",
            provider_request_id="stub-invalid",
            latency_ms=1,
        )

    first = _run(
        monkeypatch,
        session_factory,
        job.id,
        settings,
        type("Invalid", (StubProvider,), {"generate": staticmethod(invalid_marking)})(),
    )
    assert first.state is JobState.REVIEW_REQUIRED, first.detail
    db_session.expire_all()
    stale_row = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "1a"
    )
    assert stale_row.processing_state == "NEEDS_REVIEW"
    db_session.add(
        VerificationResult(
            tenant_id=identity.tenant_a.id,
            job_id=job.id,
            question_id="1a",
            kind="MATHEMATICAL",
            status="DIFFERENT",
            detail={"left": "x = 4", "right": "x = 3"},
        )
    )
    db_session.commit()

    second = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert second.state is JobState.FINALIZING, second.detail
    db_session.expire_all()
    kinds = set(
        db_session.scalars(
            select(VerificationResult.kind).where(
                VerificationResult.job_id == job.id,
                VerificationResult.question_id == "1a",
            )
        ).all()
    )
    assert kinds == {"INTEGRITY"}, f"stale verdicts survived the retry: {kinds}"
    row = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "1a"
    )
    assert row.awarded_marks == 2


def test_a_crash_before_verification_persistence_leaves_no_partial_question(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A question is persisted with its verdicts, or not at all."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="crash-before-verification")
    original = _MarkingRun._persist_verifications

    def crash_on_second_question(self, question_id, verification, extra=None):
        if question_id == "1b":
            raise RuntimeError("process died before the verification commit")
        return original(self, question_id, verification, extra)

    monkeypatch.setattr(
        _MarkingRun, "_persist_verifications", crash_on_second_question
    )
    with pytest.raises(RuntimeError, match="before the verification commit"):
        _run(monkeypatch, session_factory, job.id, settings, StubProvider())
    monkeypatch.setattr(_MarkingRun, "_persist_verifications", original)

    db_session.expire_all()
    assert [
        row.question_id
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    ] == ["1a"]
    assert {
        record.question_id
        for record in db_session.scalars(
            select(VerificationResult).where(VerificationResult.job_id == job.id)
        )
    } == {"1a"}

    provider = StubProvider()
    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert provider.calls == 2, "the decided question was marked a second time"
    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.question_id for row in rows} == {"1a", "1b", "2"}
    assert sum(row.awarded_marks for row in rows) == 5


def test_a_crash_after_the_verification_commit_is_resumed_without_duplicates(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A committed question survives; the rest is completed once on resume."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="crash-after-verification")
    original = _MarkingRun._persist_verifications

    def crash_after_second_question(self, question_id, verification, extra=None):
        original(self, question_id, verification, extra)
        self.session.commit()
        if question_id == "1b":
            raise RuntimeError("process died after the verification commit")

    monkeypatch.setattr(
        _MarkingRun, "_persist_verifications", crash_after_second_question
    )
    with pytest.raises(RuntimeError, match="after the verification commit"):
        _run(monkeypatch, session_factory, job.id, settings, StubProvider())
    monkeypatch.setattr(_MarkingRun, "_persist_verifications", original)

    db_session.expire_all()
    persisted = {
        row.question_id
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    assert persisted == {"1a", "1b"}

    provider = StubProvider()
    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert provider.calls == 1, "only the question that never persisted was retried"
    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.question_id for row in rows} == {"1a", "1b", "2"}
    for question_id in ("1a", "1b"):
        count = len(
            db_session.scalars(
                select(VerificationResult).where(
                    VerificationResult.job_id == job.id,
                    VerificationResult.question_id == question_id,
                    VerificationResult.kind == "INTEGRITY",
                )
            ).all()
        )
        assert count == 1, f"the resumed run duplicated the verdict for {question_id}"


def test_a_database_write_failure_leaves_no_half_persisted_question(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A failed flush rolls the whole question back, and a retry can persist it."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="database-failure")
    from sqlalchemy import text as sql_text
    from sqlalchemy.exc import SQLAlchemyError

    original = _MarkingRun._persist_verifications

    def fail_inside_the_transaction(self, question_id, verification, extra=None):
        self.session.execute(sql_text("SELECT 1 / 0"))
        return original(self, question_id, verification, extra)

    monkeypatch.setattr(
        _MarkingRun, "_persist_verifications", fail_inside_the_transaction
    )

    with pytest.raises(SQLAlchemyError):
        _run(monkeypatch, session_factory, job.id, settings, StubProvider())
    monkeypatch.setattr(_MarkingRun, "_persist_verifications", original)

    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id) == [], (
        "a failed transaction left a question behind"
    )

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.FINALIZING, outcome.detail
    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert {row.question_id for row in rows} == {"1a", "1b", "2"}
    assert sum(row.awarded_marks for row in rows) == 5


class OneBadQuestionProvider(StubProvider):
    """Leaves question 1b undecided so the job needs a retry."""

    def generate(self, request, api_key):
        context = next((part.text for part in request.inputs if part.text), "")
        if context.splitlines()[0].split(":", 1)[1].strip() == "1b":
            self.calls += 1
            return LLMResponse(
                text="not json at all",
                model=request.model,
                usage=TokenUsage(input_tokens=10, output_tokens=10),
                finish_reason="STOP",
                provider_request_id=f"stub-invalid-{self.calls}",
                latency_ms=1,
            )
        return super().generate(request, api_key)


def test_a_retry_cannot_switch_the_marking_prompt_version(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A job is one experiment: resuming with another prompt fails closed."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="prompt-switch")
    pinned = _settings(
        tmp_path, marking=MarkingSettings(marking_prompt_version=1)
    )

    first = _run(monkeypatch, session_factory, job.id, pinned, OneBadQuestionProvider())
    assert first.state is JobState.REVIEW_REQUIRED, first.detail

    provider = StubProvider()
    with pytest.raises(AppError, match="refusing to mix prompt versions"):
        _run(monkeypatch, session_factory, job.id, settings, provider)

    assert provider.calls == 0, "no request was spent before the job failed closed"
    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert rows
    assert {row.prompt_version for row in rows} == {"aetrix_v5_5_marking:v1"}
    assert all(row.prompt_version != "aetrix_v5_5_marking:v2" for row in rows)


def test_a_pinned_marking_prompt_is_used_and_its_version_recorded(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The baseline experiment can pin v1 without editing a prompt file."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    job = _job(db_session, paper, identity, key="prompt-pin-v1")

    _run(
        monkeypatch,
        session_factory,
        job.id,
        _settings(tmp_path, marking=MarkingSettings(marking_prompt_version=1)),
        StubProvider(),
    )
    db_session.expire_all()
    pinned = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert pinned
    assert {row.prompt_version for row in pinned} == {"aetrix_v5_5_marking:v1"}

    default_job = _job(db_session, paper, identity, key="prompt-default")
    _run(monkeypatch, session_factory, default_job.id, settings, StubProvider())
    db_session.expire_all()
    current = ResultRepository(db_session).list_for_job(
        identity.tenant_a.id, default_job.id
    )
    assert current
    # The version this deployment selects, whatever it is: a prompt bump is a
    # content change and a pin is an operator decision, neither of which is a
    # reason for this test to fail.  What it proves is that an unpinned job
    # records the version the settings resolve, not a hard-coded one.
    selected = PromptRegistry(settings.provider.prompt_root).load(
        "aetrix_v5_5_marking", settings.marking.marking_prompt_version
    )
    assert {row.prompt_version for row in current} == {
        f"{selected.prompt_id}:v{selected.version}"
    }


# -- imported criteria must be approved and complete before marking starts -----
def _assert_refused(outcome, job_id, identity, db_session, provider) -> None:
    """A gate refusal spends no request and stores no decision."""

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert provider.calls == 0, "a request was paid for before the scheme was usable"
    db_session.expire_all()
    assert ResultRepository(db_session).list_for_job(identity.tenant_a.id, job_id) == []


def test_marking_refuses_to_start_without_imported_criteria(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """An approved scheme with no criteria rows must not be marked against."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    db_session.query(MarkingCriterion).filter(
        MarkingCriterion.scheme_version_id == paper.scheme_version.id
    ).delete(synchronize_session=False)
    db_session.commit()
    job = _job(db_session, paper, identity, key="criteria-missing")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["reason"] == "SCHEME_CRITERIA_MISSING", outcome.detail
    _assert_refused(outcome, job.id, identity, db_session, provider)


def test_marking_refuses_to_start_on_unapproved_criteria(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Imported rows are inert until a person approves them."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    paper.scheme_version.criteria_approved_at = None
    paper.scheme_version.criteria_approved_by = None
    paper.scheme_version.criteria_approval_reason = None
    db_session.commit()
    job = _job(db_session, paper, identity, key="criteria-unapproved")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["reason"] == "SCHEME_CRITERIA_NOT_APPROVED", outcome.detail
    assert any("approved" in problem for problem in outcome.detail["problems"])
    _assert_refused(outcome, job.id, identity, db_session, provider)


def test_marking_refuses_criteria_approved_against_another_blueprint(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Criteria reviewed against a different paper cannot decide this paper's marks."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    # A second, real blueprint version of the same paper: the criteria name it,
    # and this job marks version 1.
    other = ExamBlueprintVersion(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        version=2,
        status="APPROVED",
        structure=paper.blueprint.structure,
        total_marks=paper.blueprint.total_marks,
        content_hash=content_hash(paper.blueprint.structure),
        created_by=identity.user_a.id,
        approved_by=identity.user_a.id,
        approved_at=datetime.now(UTC),
        approval_reason="fixture",
    )
    db_session.add(other)
    db_session.flush()
    paper.scheme_version.criteria_blueprint_version_id = other.id
    db_session.commit()
    job = _job(db_session, paper, identity, key="criteria-other-blueprint")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["reason"] == "SCHEME_CRITERIA_BLUEPRINT_MISMATCH", outcome.detail
    _assert_refused(outcome, job.id, identity, db_session, provider)


def test_marking_refuses_criteria_changed_after_approval(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The approval covers the reviewed rules, not whatever the rows say now."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    criterion = (
        db_session.query(MarkingCriterion)
        .filter(
            MarkingCriterion.scheme_version_id == paper.scheme_version.id,
            MarkingCriterion.question_id == "1a",
            MarkingCriterion.code == "M1",
        )
        .one()
    )
    criterion.description = "M1 for a tolerance nobody reviewed"
    db_session.commit()
    job = _job(db_session, paper, identity, key="criteria-rules-changed")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["reason"] == "SCHEME_CRITERIA_RULES_CHANGED", outcome.detail
    assert any("changed after they were approved" in p for p in outcome.detail["problems"])
    _assert_refused(outcome, job.id, identity, db_session, provider)


def test_marking_refuses_an_approval_that_records_no_rules_digest(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """An approval with no digest cannot prove which rules were reviewed."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    paper.scheme_version.criteria_rules_hash = None
    db_session.commit()
    job = _job(db_session, paper, identity, key="criteria-rules-unverified")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["reason"] == "SCHEME_CRITERIA_RULES_UNVERIFIED", outcome.detail
    _assert_refused(outcome, job.id, identity, db_session, provider)


def test_marking_refuses_criteria_that_do_not_cover_every_question(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A question with no criteria would be marked with nothing to check it against."""

    _page(db_session, paper, identity, settings := _settings(tmp_path))
    db_session.query(MarkingCriterion).filter(
        MarkingCriterion.scheme_version_id == paper.scheme_version.id,
        MarkingCriterion.question_id == "2",
    ).delete(synchronize_session=False)
    db_session.commit()
    job = _job(db_session, paper, identity, key="criteria-incomplete")
    provider = StubProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["reason"] == "SCHEME_CRITERIA_INCOMPLETE", outcome.detail
    assert any("'2'" in problem for problem in outcome.detail["problems"])
    _assert_refused(outcome, job.id, identity, db_session, provider)

# -- Mission 6.2: page provenance and unverifiable awards -------------------


def test_an_agreement_on_the_marking_pass_own_page_is_not_page_verification(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Two readers can agree about a page the first pass chose for itself.

    The citation is the marking pass naming the page it read.  Sending that page
    to a second reader and finding the same characters confirms what is on the
    page; it does not confirm that the page was the right one.  The reading is
    still recorded as an agreement, and the page is reported as circular.
    """

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-circular-page")
    answers = dict(ANSWERS)
    answers["2"] = _answer("2", 0, [_component("B1", False, Q6_WRITTEN)], None)
    provider = TranscriptionProvider({"2": Q6_WRITTEN})
    provider.answers = answers

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    transcription_detail = outcome.detail["transcription"]
    assert transcription_detail["agreements"] == 1
    assert transcription_detail["differences"] == 0
    assert transcription_detail["page_unverified"] == 1
    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail

    db_session.expire_all()
    zero = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "2"
    )
    assert zero.awarded_marks == 0, "an agreement never changes an award"
    assert zero.processing_state == "NEEDS_REVIEW"
    concern = next(
        concern
        for concern in zero.scheme_concerns
        if concern["code"] == "TRANSCRIPTION_PAGE_UNVERIFIED"
    )
    assert concern["severity"] == "POSSIBLE_MISMATCH"
    assert "evidence" in concern["message"]

    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "AGREES"
    assert verdict.detail["page_source"] == "EVIDENCE"
    assert verdict.detail["page_confidence"] == "CIRCULAR"


def test_a_mapped_page_is_independent_and_an_agreement_leaves_the_award_alone(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """The same agreement, on a page an approved mapping chose, needs no person."""

    page = _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    db_session.add(
        PageQuestionMapping(
            tenant_id=identity.tenant_a.id,
            document_id=page.document_id,
            page_id=page.id,
            blueprint_version_id=paper.blueprint.id,
            question_id="1a",
            confidence=1.0,
            method="MANUAL",
        )
    )
    db_session.commit()
    job = _job(db_session, paper, identity, key="transcription-mapped-page")
    answers = dict(ANSWERS)
    # Low confidence is what buys the reading; the award stays a normal one.
    answers["1a"] = {**ANSWERS["1a"], "confidence": 0.7}
    provider = TranscriptionProvider({"2": "", "1a": "2x + 6 = 12\nx = 3"})
    provider.answers = answers

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    transcription_detail = outcome.detail["transcription"]
    assert transcription_detail["agreements"] == 1
    assert transcription_detail["page_unverified"] == 0
    assert transcription_detail["unverified_award"] == 0
    assert outcome.state is JobState.FINALIZING, outcome.detail

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    assert rows["1a"].awarded_marks == 2
    assert not any(
        concern["code"].startswith("TRANSCRIPTION")
        for concern in rows["1a"].scheme_concerns
    )
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "1a",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "AGREES"
    assert verdict.detail["page_source"] == "MAPPING"
    assert verdict.detail["page_confidence"] == "INDEPENDENT"


def test_an_illegible_reading_on_a_non_zero_award_goes_to_a_person(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Mission 6.1: a positive award with an unusable reading was silent."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-unverifiable-award")
    answers = dict(ANSWERS)
    answers["1a"] = {**ANSWERS["1a"], "confidence": 0.7}
    provider = MalformedReaderProvider()
    provider.answers = answers

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    transcription_detail = outcome.detail["transcription"]
    assert transcription_detail["unverifiable"] == 2, transcription_detail
    assert transcription_detail["unverified_award"] == 1
    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    assert rows["1a"].awarded_marks == 2, "an unusable reading never changes an award"
    assert rows["1a"].student_answer == "x = 3", "the original reading is preserved"
    assert rows["1a"].processing_state == "NEEDS_REVIEW"
    concern = next(
        concern
        for concern in rows["1a"].scheme_concerns
        if concern["code"] == "TRANSCRIPTION_UNVERIFIED"
    )
    assert concern["severity"] == "POSSIBLE_MISMATCH"
    assert "2 mark(s)" in concern["message"]


def test_a_difference_on_a_non_zero_award_blocks_presentation(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A disagreement is a disagreement whatever the award is."""

    page = _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    db_session.add(
        PageQuestionMapping(
            tenant_id=identity.tenant_a.id,
            document_id=page.document_id,
            page_id=page.id,
            blueprint_version_id=paper.blueprint.id,
            question_id="1a",
            confidence=1.0,
            method="MANUAL",
        )
    )
    db_session.commit()
    job = _job(db_session, paper, identity, key="transcription-differs-award")
    answers = dict(ANSWERS)
    answers["1a"] = {**ANSWERS["1a"], "confidence": 0.7}
    provider = TranscriptionProvider({"2": "", "1a": "2x + 6 = 12\nx = 4"})
    provider.answers = answers

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["differences"] == 1
    assert outcome.detail["transcription"]["disagreements"] == ["1a"]
    assert outcome.detail.get("guard") == "BLOCKED", outcome.detail.get("guard_reason")

    db_session.expire_all()
    row = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "1a"
    )
    assert row.awarded_marks == 2, "a disagreement never rewrites a mark"
    assert row.student_answer == "x = 3"
    assert row.processing_state == "NEEDS_REVIEW"


def test_a_question_whose_pages_exceed_the_request_budget_is_refused(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Mission 6.1: a page set over the limit was thinned, silently.

    Six pages is what one request may carry; this deployment allows two, and the
    approved mapping gives question 2 three pages.  The set is over budget before
    any image is read, so it is refused rather than cut down to two pages.
    """

    settings = _settings(
        tmp_path,
        transcription=True,
        marking=MarkingSettings(transcription_enabled=True, transcription_max_pages=2),
    )
    first = _page(db_session, paper, identity, settings)
    extra = [
        _extra_page(db_session, paper, identity, settings, index=index)
        for index in range(2, 5)
    ]
    # Every readable page is mapped and every question is mapped, so coverage has
    # nothing to flag: the only reason this run stops is the transcription budget.
    for page in (first, extra[0], extra[1]):
        db_session.add(
            PageQuestionMapping(
                tenant_id=identity.tenant_a.id,
                document_id=first.document_id,
                page_id=page.id,
                blueprint_version_id=paper.blueprint.id,
                question_id="2",
                confidence=1.0,
                method="MANUAL",
            )
        )
    for question_id in ("1a", "1b"):
        db_session.add(
            PageQuestionMapping(
                tenant_id=identity.tenant_a.id,
                document_id=first.document_id,
                page_id=extra[2].id,
                blueprint_version_id=paper.blueprint.id,
                question_id=question_id,
                confidence=1.0,
                method="MANUAL",
            )
        )
    db_session.commit()
    job = _job(db_session, paper, identity, key="transcription-page-budget")
    provider = CapturingProvider()

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    transcription_detail = outcome.detail["transcription"]
    assert transcription_detail["unavailable"] == 1, transcription_detail
    assert transcription_detail["checked"] == 1
    # Three marking requests and no blind reading: a refused page set costs
    # nothing and is never sent in part.
    assert provider.calls == 3
    assert not [
        request
        for request in provider.requests
        if "independent transcription" in request.prompt
    ]

    db_session.expire_all()
    zero = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "2"
    )
    assert zero.awarded_marks == 0
    assert zero.processing_state == "NEEDS_REVIEW"
    concern = next(
        concern
        for concern in zero.scheme_concerns
        if concern["code"] == "TRANSCRIPTION_UNAVAILABLE"
    )
    assert "PAGE_BUDGET_EXCEEDED" in concern["message"]

    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.status == "UNVERIFIABLE"
    assert verdict.detail["reason"].startswith("PAGE_BUDGET_EXCEEDED:")
    assert verdict.detail["pages"] == []


def test_a_model_recorded_by_an_earlier_execution_is_a_marking_model(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Mission 6.1: a resumed job forgot who had marked it.

    The append-only usage ledger still knows: a fallback that answered before the
    resume is a model that read this paper, so a blind reading answered by it is
    a prompt check, not an independent reading.
    """

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-resumed-fallback")
    db_session.add(
        ProviderUsage(
            tenant_id=identity.tenant_a.id,
            job_id=job.id,
            project_id="earlier-execution",
            provider="stub",
            model="earlier-fallback-model",
            purpose="marking",
            success=True,
        )
    )
    db_session.commit()
    provider = TranscriptionProvider({"2": ""}, model="earlier-fallback-model")

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["not_independent"] == 1
    assert outcome.detail["transcription"]["unknown_independence"] == 0

    db_session.expire_all()
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.detail["independence"] == "PROMPT"
    assert "earlier-fallback-model" in verdict.detail["marking_models"]
    zero = next(
        row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.question_id == "2"
    )
    assert zero.processing_state == "NEEDS_REVIEW"
    assert any(
        concern["code"] == "TRANSCRIPTION_NOT_INDEPENDENT"
        for concern in zero.scheme_concerns
    )


def test_a_failed_marking_attempt_is_not_a_marking_model(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Only an attempt that produced a reply counts as having read the script."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, transcription=True))
    job = _job(db_session, paper, identity, key="transcription-failed-attempt")
    db_session.add(
        ProviderUsage(
            tenant_id=identity.tenant_a.id,
            job_id=job.id,
            project_id="earlier-execution",
            provider="stub",
            model="model-that-returned-503",
            purpose="marking",
            success=False,
        )
    )
    db_session.commit()
    provider = TranscriptionProvider({"2": ""}, model="model-that-returned-503")

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    assert outcome.detail["transcription"]["not_independent"] == 0

    db_session.expire_all()
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.question_id == "2",
            VerificationResult.kind == "TRANSCRIPTION",
        )
    )
    assert verdict.detail["independence"] == "MODEL"
    assert "model-that-returned-503" not in verdict.detail["marking_models"]


# -- the evidence gate ------------------------------------------------------
# STUDENT_02 recorded 3/3 for Q37b on an answer that was not written: the award
# was made, the evidence comparison had never been bought for that question, and
# nothing routed it anywhere.  These tests pin the gate that closes that hole.
def test_an_award_no_evidence_check_examined_goes_to_a_person(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Marks with no evidence comparison are kept and routed, never presented."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, gate=True))
    job = _job(db_session, paper, identity, key="evidence-gate-on")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert outcome.detail["evidence_gate"]["enabled"] is True
    assert set(outcome.detail["evidence_gate"]["ungrounded"]) == {"1a", "1b"}
    assert any(
        "no check has compared this question's quoted evidence" in reason
        for reason in outcome.detail["review_reasons"]
    )

    db_session.expire_all()
    rows = {
        row.question_id: row
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    }
    # The answer is evidence, not a verdict the gate re-decides.
    assert (rows["1a"].awarded_marks, rows["1b"].awarded_marks) == (2, 3)
    for question_id in ("1a", "1b"):
        row = rows[question_id]
        assert row.review_required is True
        assert (row.status, row.processing_state) == ("REVIEW_REQUIRED", "NEEDS_REVIEW")
        assert any(
            concern.get("code") == "EVIDENCE_NOT_CHECKED"
            for concern in (row.scheme_concerns or [])
        ), row.scheme_concerns

    # A question that holds no marks is not an unverified award, and remains the
    # confirmed zero its reply stated.
    assert rows["2"].awarded_marks == 0
    assert rows["2"].processing_state == "CONFIRMED_ZERO"
    assert rows["2"].review_required is False


def test_the_gate_is_the_only_reason_the_same_paper_is_a_review_item(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """Switching the gate off restores the old end state, so the gate is the cause."""

    _page(db_session, paper, identity, settings := _settings(tmp_path, gate=False))
    job = _job(db_session, paper, identity, key="evidence-gate-off")

    outcome = _run(monkeypatch, session_factory, job.id, settings, StubProvider())

    assert outcome.state is JobState.FINALIZING, outcome.detail
    assert outcome.detail["evidence_gate"] == {
        "enabled": False,
        "questions": 3,
        "unverified_awards": 0,
        "ungrounded": [],
    }

    db_session.expire_all()
    rows = ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
    assert all(
        not any(
            str(concern.get("code")) == "EVIDENCE_NOT_CHECKED"
            for concern in (row.scheme_concerns or [])
        )
        for row in rows
    )


def test_a_checked_quotation_keeps_its_question_out_of_the_gate(
    monkeypatch, session_factory, db_session, paper, identity, provider_credential, tmp_path
) -> None:
    """A recorded evidence verdict — even one that disagrees — is a check taken."""

    _page(
        db_session,
        paper,
        identity,
        settings := _settings(tmp_path, transcription=True, gate=True),
    )
    job = _job(db_session, paper, identity, key="evidence-gate-checked")
    provider = TranscriptionProvider({"2": ""})

    outcome = _run(monkeypatch, session_factory, job.id, settings, provider)

    from app.db.models import VerificationResult

    db_session.expire_all()
    checked = {
        record.question_id
        for record in db_session.scalars(
            select(VerificationResult).where(
                VerificationResult.job_id == job.id,
                VerificationResult.kind == "EVIDENCE",
            )
        )
    }
    # The stage that buys the blind reading really did record a check, so the
    # gate is reading verdicts rather than assuming there are none.
    assert checked, "the transcription stage recorded no evidence verdict"

    awarded = {
        row.question_id
        for row in ResultRepository(db_session).list_for_job(identity.tenant_a.id, job.id)
        if row.awarded_marks
    }
    gate = outcome.detail["evidence_gate"]
    assert gate["enabled"] is True
    assert not (checked & set(gate["ungrounded"])), "a checked question was named"
    # Every award no check examined is named, and nothing else is.
    assert set(gate["ungrounded"]) == awarded - checked
    assert outcome.state is (
        JobState.FINALIZING if not gate["ungrounded"] else JobState.REVIEW_REQUIRED
    ), outcome.detail
