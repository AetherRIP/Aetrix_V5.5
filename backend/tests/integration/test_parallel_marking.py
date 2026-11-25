"""Parallel correction through the real engine and a real PostgreSQL database.

These tests prove what the unit tests cannot: that the mode is selected through
the job itself, that the pipeline's own parallel path stores every question with
its provenance, that independent questions are genuinely in flight together,
that a refused question does not lose the rest of the paper, that a resumed paper
keeps its mode and buys nothing twice, and that the verification stages the whole
engine already runs are the same ones a parallel run records.
"""

from __future__ import annotations

import json
import threading
import time
import uuid

import pytest
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import Principal
from app.correction.aetrix.pipeline import AetrixPipeline
from app.db.models import (
    Document,
    DocumentPage,
    EngineRun,
    PageQuestionMapping,
    ProviderUsage,
    QuestionResult,
    VerificationResult,
)
from app.jobs.service import JobService
from app.jobs.states import JobState
from app.schemas.api import CorrectionCreate
from app.services.results import ResultsService
from app.storage.local import LocalStorage
from sqlalchemy import func, select, text

from tests.support import FakeProvider, make_png

pytestmark = pytest.mark.integration

# The fixture blueprint has three scoreable leaves: 1a (2), 1b (3), 2 (5).
LEAVES = {"1a": 2, "1b": 3, "2": 5}

#: The fixture scheme's printed mark points per scoreable leaf.
PRINTED = {
    "1a": (("M1", 1), ("A1", 1)),
    "1b": (("M1", 1), ("M2", 1), ("A1", 1)),
    "2": (("M1", 2), ("A1", 3)),
}


def _settings(
    mode: str = "PARALLEL",
    *,
    concurrency: int = 3,
    transcription: bool = False,
    double_check: bool = False,
) -> Settings:
    base = get_settings()
    marking = base.marking.model_copy(
        update={
            "marking_mode": mode,
            "parallel_max_concurrency": concurrency,
            "transcription_enabled": transcription,
            "transcription_max_questions": 1,
            "double_check_enabled": double_check,
            # The evidence gate is stated rather than inherited: this suite buys
            # no blind reading, so an inherited gate would send every award to
            # review and replace the subject of each test with that outcome.  The
            # gate's own tests live in the sibling pipeline suite.
            "require_evidence_for_award": False,
        }
    )
    return base.model_copy(update={"marking": marking})


def _item(question_id: str, *, awarded: int | None = None) -> dict:
    marks = LEAVES[question_id] if awarded is None else awarded
    components = []
    remaining = marks
    for code, printed in PRINTED[question_id]:
        credit = max(0, min(printed, remaining))
        remaining -= credit
        components.append(
            {
                "code": code,
                "description": f"{code} for the printed step",
                "marks": printed if credit in (0, printed) else credit,
                "awarded": credit > 0,
                "reason": "Matches the scheme." if credit else "Not earned.",
                "evidence": "x = 3" if credit else None,
                "page": 1,
            }
        )
    item = {
        "question_id": question_id,
        "student_answer": "x = 3",
        "awarded_marks": sum(
            component["marks"] for component in components if component["awarded"]
        ),
        "components": components,
        "confidence": 0.95,
    }
    if question_id == "2":
        # A trivially equivalent pair, so the SymPy stage has a comparison to
        # record: this proves the mathematical verification runs in parallel mode.
        item["answer_check"] = {
            "student_expression": "2 + 3",
            "expected_expression": "5",
        }
    return item


def _question_of(request) -> str:
    for part in request.inputs:
        value = part.text or ""
        if value.startswith("Question: "):
            return value.splitlines()[0].split(": ", 1)[1].strip()
    return ""


def _is_transcription(request) -> bool:
    schema = request.response_schema or {}
    return "evidence_status" in (schema.get("properties") or {})


def _zero_item(question_id: str) -> dict:
    """A blank answer: no award, no quoted evidence, a usable reply."""

    components = [
        {
            "code": code,
            "description": f"{code} for the printed step",
            "marks": printed,
            "awarded": False,
            "reason": "No working is written.",
            "evidence": None,
        }
        for code, printed in PRINTED[question_id]
    ]
    return {
        "question_id": question_id,
        "student_answer": None,
        "awarded_marks": 0,
        "components": components,
        "confidence": 0.9,
    }


class ParallelProvider(FakeProvider):
    """Answers one question per request, tracking real overlap and failures."""

    def __init__(
        self,
        *,
        bodies: dict[str, str] | None = None,
        gate: threading.Barrier | None = None,
        gate_questions: frozenset[str] = frozenset(),
        fail: frozenset[str] = frozenset(),
        slow: str | None = None,
        transcript: str = "x = 4",
        invalid_once: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__()
        self.bodies = bodies or {qid: json.dumps(_item(qid)) for qid in LEAVES}
        self.transcript = transcript
        self.gate = gate
        self.gate_questions = gate_questions
        self.fail = fail
        self.slow = slow
        self.invalid_once = invalid_once
        self.asked: list[str] = []
        #: Every request, in dispatch order, for input-shape assertions.
        self.requests: list = []
        self.attempts: dict[str, int] = {}
        self.in_flight = 0
        self.peak_in_flight = 0
        self._lock = threading.Lock()

    def generate(self, request, api_key):
        question_id = _question_of(request)
        transcription = _is_transcription(request)
        with self._lock:
            self.asked.append(question_id)
            self.requests.append(request)
            # Only marking attempts count: an unusable reply is recovered by a
            # second marking request, not by the independent reader.
            attempt = self.attempts.get(question_id, 0) + 1
            if not transcription:
                self.attempts[question_id] = attempt
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if self.fail and question_id in self.fail:
                raise RuntimeError("provider client defect for this question")
            if self.gate is not None and question_id in self.gate_questions:
                # Only true concurrency lets both parties reach this line.
                self.gate.wait()
            if self.slow == question_id:
                time.sleep(0.15)
            if transcription:
                self.text = json.dumps(
                    {
                        "question_id": question_id,
                        "evidence_status": "WRITTEN",
                        "transcript": self.transcript,
                        "confidence": 0.9,
                    }
                )
            elif question_id in self.invalid_once and attempt == 1:
                # A reply the engine cannot use: the request was paid for and
                # stored, and the question stays unresolved for recovery.
                self.text = "{}"
            else:
                self.text = self.bodies.get(question_id, "{}")
            return super().generate(request, api_key)
        finally:
            with self._lock:
                self.in_flight -= 1


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
            idempotency_key=f"parallel-{uuid.uuid4().hex[:12]}",
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
    page = DocumentPage(
        tenant_id=identity.tenant_a.id,
        document_id=document.id,
        page_index=1,
        storage_key=stored.key,
        width=1000,
        height=1400,
        quality_status="READABLE",
        checksum=stored.sha256,
    )
    db_session.add(page)
    db_session.flush()
    # An approved mapping for every leaf: the transcription stage resolves its
    # page from the mapping, and coverage sees a fully mapped script.
    for question_id in LEAVES:
        db_session.add(
            PageQuestionMapping(
                tenant_id=identity.tenant_a.id,
                document_id=document.id,
                page_id=page.id,
                blueprint_version_id=paper.blueprint.id,
                question_id=question_id,
                confidence=1.0,
                method="MANUAL",
            )
        )
    db_session.commit()
    return job


def _rows(db_session, job) -> dict[str, QuestionResult]:
    db_session.expire_all()
    return {
        row.question_id: row
        for row in db_session.scalars(
            select(QuestionResult).where(QuestionResult.job_id == job.id)
        )
    }


def _verification_kinds(db_session, job) -> set[str]:
    return {
        row[0]
        for row in db_session.execute(
            select(VerificationResult.kind).where(VerificationResult.job_id == job.id)
        )
    }


# -- the mode runs through the engine ----------------------------------


def test_parallel_mode_marks_every_question_through_the_main_engine(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider()

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL")
    )

    assert outcome.state is JobState.FINALIZING
    assert sorted(provider.asked) == ["1a", "1b", "2"]
    rows = _rows(db_session, job)
    assert sorted(rows) == ["1a", "1b", "2"]
    assert [rows[qid].awarded_marks for qid in ("1a", "1b", "2")] == [2, 3, 5]
    # Provenance: every row names the parallel request shape and its own call.
    sources = {qid: rows[qid].response_source for qid in rows}
    assert set(sources.values()) == {"PARALLEL"}, sources
    assert len({row.provider_usage_id for row in rows.values()}) == 3
    assert all(row.provider_usage_id is not None for row in rows.values())
    assert all(
        str(row.prompt_version).startswith("aetrix_v5_5_marking:v")
        for row in rows.values()
    )

    db_session.expire_all()
    assert job.marking_mode == "PARALLEL"
    detail = outcome.detail
    assert detail["marking_mode"] == "PARALLEL"
    assert detail["parallel"]["waves_executed"] == 2
    assert detail["parallel"]["requests"] == 3
    assert detail["parallel_aggregation"]["complete"] is True
    assert detail["parallel_aggregation"]["awarded"] == 10

    # The shared verification architecture ran: integrity and the SymPy
    # comparison are recorded for the same rows the whole engine produces.
    assert {"INTEGRITY", "MATHEMATICAL"} <= _verification_kinds(db_session, job)

    # Timing and usage are tracked per request, not only in aggregate: the
    # provider latency and the lease queue wait are both on the usage ledger.
    usages = list(
        db_session.scalars(
            select(ProviderUsage).where(
                ProviderUsage.job_id == job.id,
                ProviderUsage.purpose == "marking",
            )
        )
    )
    assert len(usages) == 3
    assert all(usage.latency_ms is not None for usage in usages)
    assert all(usage.queue_wait_ms is not None for usage in usages)
    assert detail["parallel"]["provider_latency_ms_total"] >= 0
    assert detail["parallel"]["queue_wait_ms_total"] >= 0
    assert all(row.processing_state in {"MARKED", "CONFIRMED_ZERO"} for row in rows.values())


def test_parallel_questions_are_really_in_flight_together(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    gate = threading.Barrier(2, timeout=10.0)
    provider = ParallelProvider(
        gate=gate, gate_questions=frozenset({"1a", "2"})
    )

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL", concurrency=2)
    )

    assert outcome.state is JobState.FINALIZING
    assert provider.peak_in_flight >= 2
    assert outcome.detail["parallel"]["peak_in_flight"] >= 2


def test_one_refused_question_does_not_lose_the_others(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider(fail=frozenset({"1a"}))

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL")
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    assert outcome.detail["reason"] == "MISSING_SCOREABLE_LEAF"
    # 1b follows 1a in the same parent question and is not dispatched without
    # its prerequisite's decision; 2 is independent and keeps its award.
    assert sorted(provider.asked) == ["1a", "2"]
    rows = _rows(db_session, job)
    assert sorted(rows) == ["2"]
    assert rows["2"].awarded_marks == 5
    failures = outcome.detail["parallel"]["failures"]
    assert [failure["question_id"] for failure in failures] == ["1a"]
    assert outcome.detail["parallel"]["status_counts"]["BLOCKED"] == 1


def test_a_resumed_paper_keeps_its_mode_and_buys_nothing_again(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider()

    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL")
    )
    first = {qid: row.id for qid, row in _rows(db_session, job).items()}
    requests_after_first = len(provider.asked)

    # The deployment now says whole paper.  The job's own mode is authoritative,
    # so the resumed paper stays parallel and asks nothing.
    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("WHOLE_PAPER")
    )

    db_session.expire_all()
    assert job.marking_mode == "PARALLEL"
    assert len(provider.asked) == requests_after_first
    rows = _rows(db_session, job)
    assert {qid: row.id for qid, row in rows.items()} == first
    assert {row.response_source for row in rows.values()} == {"PARALLEL"}
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(QuestionResult)
            .where(QuestionResult.job_id == job.id)
        )
        == 3
    )


def test_the_mode_can_be_chosen_on_the_job_request_and_is_recorded(
    paper, identity, db_session
) -> None:
    principal = Principal(
        user_id=identity.user_a.id,
        tenant_id=identity.tenant_a.id,
        subject=identity.user_a.subject,
        role=identity.user_a.role,
    )
    key = f"mode-choice-{uuid.uuid4().hex[:12]}"

    created = JobService(db_session, get_settings()).create(
        principal,
        CorrectionCreate(
            assignment_id=paper.assignment.id,
            submission_id=paper.submission.id,
            idempotency_key=key,
            marking_mode="PARALLEL",
        ),
    )

    assert created.job.marking_mode == "PARALLEL"
    # The same key demanding another mode is a different request, not a silent
    # return of a job that will run in the mode it already recorded.
    with pytest.raises(AppError, match="already used for a different request"):
        JobService(db_session, get_settings()).create(
            principal,
            CorrectionCreate(
                assignment_id=paper.assignment.id,
                submission_id=paper.submission.id,
                idempotency_key=key,
                marking_mode="WHOLE_PAPER",
            ),
        )


def test_the_independent_double_check_runs_after_parallel_marking(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """A second, independent pass is bought after the concurrent awards exist.

    The parallel path changes only *when* the questions are sent.  The review
    stage still runs afterwards on the persisted rows, records its own verdicts,
    and must not move a single award.
    """

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)

    outcome = AetrixPipeline(provider=ParallelProvider(), storage=storage).run(
        job, db_session, _settings("PARALLEL", double_check=True)
    )

    assert outcome.state in {JobState.FINALIZING, JobState.REVIEW_REQUIRED}
    assert outcome.detail["double_check"]["enabled"] is True
    assert outcome.detail["double_check"]["checked"] >= 1
    assert "DOUBLE_CHECK" in _verification_kinds(db_session, job)
    assert {qid: row.awarded_marks for qid, row in _rows(db_session, job).items()} == {
        "1a": 2,
        "1b": 3,
        "2": 5,
    }


def test_a_transcription_disagreement_in_parallel_mode_is_reviewed(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """The blind reading is shared with the sequential modes, not bypassed.

    1a is a blank answer with no award, so the transcription selector targets it.
    The independent reader reports writing the marking pass did not record, which
    must be a review item — and the award itself must stay untouched.
    """

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider(
        bodies={
            "1a": json.dumps(_zero_item("1a")),
            "1b": json.dumps(_item("1b")),
            "2": json.dumps(_item("2")),
        },
        transcript="x = 3",
    )

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL", transcription=True)
    )

    assert outcome.state is JobState.REVIEW_REQUIRED
    db_session.expire_all()
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.kind == "TRANSCRIPTION",
            VerificationResult.question_id == "1a",
        )
    )
    assert verdict is not None
    assert verdict.status == "DIFFERS"
    assert verdict.detail["transcript"] == "x = 3"

    row = _rows(db_session, job)["1a"]
    assert row.awarded_marks == 0
    assert row.review_required is True
    assert any(
        str(concern.get("code", "")).startswith("TRANSCRIPTION")
        for concern in (row.scheme_concerns or [])
    )


def test_the_database_accepts_the_parallel_mode(engine) -> None:
    with engine.connect() as connection:
        definitions = {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    "select conname, pg_get_constraintdef(oid) from pg_constraint "
                    "where conname in "
                    "('ck_correction_jobs_marking_mode', "
                    "'ck_question_results_response_source')"
                )
            )
        }
    assert "'PARALLEL'" in definitions["ck_correction_jobs_marking_mode"]
    assert "'PARALLEL'" in definitions["ck_question_results_response_source"]


def test_per_question_mode_is_unchanged_by_the_new_mode(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """Per-question remains selectable and records its own provenance."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider()

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PER_QUESTION")
    )

    assert outcome.state is JobState.FINALIZING
    rows = _rows(db_session, job)
    assert {row.response_source for row in rows.values()} == {"PER_QUESTION"}
    assert outcome.detail["marking_mode"] == "PER_QUESTION"
    assert outcome.detail["parallel"] is None


# -- repaired defects: context, provenance, evidence, coverage ----------

def _quoted_zero_item(question_id: str) -> dict:
    """A blank answer whose reply still claims to quote text from the page."""

    components = [
        {
            "code": code,
            "description": f"{code} for the printed step",
            "marks": printed,
            "awarded": False,
            "reason": "No award is supported.",
            "evidence": "x = 3",
            "page": 1,
        }
        for code, printed in PRINTED[question_id]
    ]
    return {
        "question_id": question_id,
        "student_answer": None,
        "awarded_marks": 0,
        "components": components,
        "confidence": 0.9,
    }




def _request_text(request) -> str:
    return "\n".join(part.text or "" for part in request.inputs)


def _marking_requests(provider: ParallelProvider, question_id: str) -> list:
    return [
        request
        for request in provider.requests
        if _question_of(request) == question_id and not _is_transcription(request)
    ]


def _principal(identity) -> Principal:
    return Principal(
        user_id=identity.user_a.id,
        tenant_id=identity.tenant_a.id,
        subject=identity.user_a.subject,
        role=identity.user_a.role,
    )


def test_a_dependent_part_is_told_the_earlier_parts_working(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """1b is dispatched after 1a and carries 1a's stored answer, not its award."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider()

    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL")
    )

    dependent = _request_text(_marking_requests(provider, "1b")[0])
    assert "Earlier parts of this question are already marked" in dependent
    assert "Part 1a: 2 of 2" in dependent
    assert "Student answer: x = 3" in dependent

    # The first part and an independent question carry no such block.
    assert "Earlier parts of this question" not in _request_text(
        _marking_requests(provider, "1a")[0]
    )
    assert "Earlier parts of this question" not in _request_text(
        _marking_requests(provider, "2")[0]
    )


def test_a_recovered_question_keeps_its_mode_and_records_the_mechanism(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """One unusable reply is recovered sequentially inside a parallel paper."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider(invalid_once=frozenset({"1b"}))

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL")
    )

    rows = _rows(db_session, job)
    assert rows["1b"].awarded_marks == 3
    # The row is a parallel decision, not a fallback into another mode.
    assert rows["1b"].response_source == "PARALLEL"
    assert provider.attempts["1b"] == 2

    recovery = db_session.scalar(
        select(EngineRun).where(
            EngineRun.job_id == job.id,
            EngineRun.stage == "RECOVERY",
        )
    )
    assert recovery is not None
    assert recovery.detail["mode"] == "PARALLEL"
    assert recovery.detail["execution"] == "SEQUENTIAL"
    assert recovery.detail["request_source"] == "PARALLEL"
    assert recovery.detail["recovered"] == 1

    # Resuming the completed paper stays stable and buys nothing again.
    db_session.expire_all()
    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL")
    )
    assert provider.attempts["1b"] == 2
    assert sorted(_rows(db_session, job)) == ["1a", "1b", "2"]
    assert outcome.detail["marking_mode"] == "PARALLEL"


def test_an_invented_quotation_fails_evidence_verification(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """The blind reading says the quoted text is not in the script."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider(
        bodies={
            "1a": json.dumps(_quoted_zero_item("1a")),
            "1b": json.dumps(_item("1b")),
            "2": json.dumps(_item("2")),
        },
        transcript="y = 9",
    )

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL", transcription=True)
    )

    db_session.expire_all()
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.kind == "EVIDENCE",
            VerificationResult.question_id == "1a",
        )
    )
    assert verdict is not None
    assert verdict.status == "FAIL"
    assert verdict.detail["quote_count"] >= 1, "the quoted evidence is preserved"
    assert verdict.detail["pages"], "the pages it was checked against are preserved"

    row = _rows(db_session, job)["1a"]
    assert row.awarded_marks == 0, "the award is evidence, not changed by the check"
    assert row.review_required is True
    assert any(
        concern.get("code") == "EVIDENCE_NOT_FOUND"
        for concern in (row.scheme_concerns or [])
    )
    # Completion is not verification: the stored state says failed.
    assert outcome.state is JobState.REVIEW_REQUIRED
    assert job.verification_status == "VERIFICATION_FAILED"


def test_a_genuine_quotation_is_verified_and_exposed_by_the_api(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """A quotation found in the blind reading passes, without claiming more."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider(
        bodies={
            "1a": json.dumps(_quoted_zero_item("1a")),
            "1b": json.dumps(_item("1b")),
            "2": json.dumps(_item("2")),
        },
        transcript="x = 3",
    )

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PARALLEL", transcription=True)
    )

    db_session.expire_all()
    verdict = db_session.scalar(
        select(VerificationResult).where(
            VerificationResult.job_id == job.id,
            VerificationResult.kind == "EVIDENCE",
            VerificationResult.question_id == "1a",
        )
    )
    assert verdict is not None
    assert verdict.status == "PASS"

    row = _rows(db_session, job)["1a"]
    assert not any(
        str(concern.get("code", "")).startswith("EVIDENCE")
        for concern in (row.scheme_concerns or [])
    )
    # The paper is not fully verified: 1b and 2 award marks whose citations were
    # never selected for a reading, and that is reported as missing, not passed.
    assert outcome.detail["verification"]["status"] == "PARTIALLY_VERIFIED"
    assert job.verification_status == "PARTIALLY_VERIFIED"

    read = ResultsService(db_session).job_results(_principal(identity), job.id)
    assert read.verification_status == "PARTIALLY_VERIFIED"
    evidence_rows = [
        item for item in read.verifications if item.kind == "EVIDENCE"
    ]
    assert len(evidence_rows) == 1
    assert evidence_rows[0].status == "PASS"
    by_question = {question.question_id: question for question in read.questions}
    assert by_question["1a"].verification is not None
    # A question with no award does not require evidence verification.
    assert "EVIDENCE" not in by_question["1b"].verification["verified"]


def test_coverage_findings_are_reconciled_when_a_resumed_paper_changes(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """A gap found later flags existing rows; a closed gap clears only itself."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ParallelProvider()
    pipeline = AetrixPipeline(provider=provider, storage=storage)

    pipeline.run(job, db_session, _settings("PARALLEL"))
    first = _rows(db_session, job)
    assert all(not row.review_required for row in first.values())

    # A second scanned page arrives that no mapping covers.
    document = db_session.scalar(
        select(Document).where(Document.submission_id == paper.submission.id)
    )
    extra = DocumentPage(
        tenant_id=identity.tenant_a.id,
        document_id=document.id,
        page_index=2,
        storage_key=document.storage_key,
        width=1000,
        height=1400,
        quality_status="READABLE",
        checksum="extra-page",
    )
    db_session.add(extra)
    db_session.commit()

    pipeline.run(job, db_session, _settings("PARALLEL"))
    flagged = _rows(db_session, job)
    assert all(row.review_required for row in flagged.values())
    assert all(
        any(concern.get("code") == "PAGE_COVERAGE" for concern in row.scheme_concerns or [])
        for row in flagged.values()
    )
    db_session.expire_all()
    assert job.verification_status == "REVIEW_REQUIRED"

    # The page is withdrawn: the concern closes and the review flag goes with it.
    db_session.delete(extra)
    db_session.commit()
    pipeline.run(job, db_session, _settings("PARALLEL"))

    cleared = _rows(db_session, job)
    assert all(not row.review_required for row in cleared.values())
    assert all(
        not any(concern.get("code") == "PAGE_COVERAGE" for concern in row.scheme_concerns or [])
        for row in cleared.values()
    )
