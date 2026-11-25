"""Whole-paper marking against a real PostgreSQL database.

These tests prove what the unit tests cannot: that migration ``0029`` reproduces
the archive and provenance schema, that a whole-paper reply is stored once and
every row it produced reaches it, that a partial or partly invalid reply falls
back question by question, that a failed transaction leaves nothing behind, and
that a second execution neither re-asks nor duplicates.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import Principal
from app.correction.aetrix.pipeline import AetrixPipeline, _MarkingRun
from app.db.models import (
    CorrectionJob,
    Document,
    DocumentPage,
    ProviderResponse,
    QuestionResult,
)
from app.jobs.pipeline import RetryablePipelineError
from app.jobs.service import JobService
from app.jobs.states import JobState
from app.schemas.api import CorrectionCreate
from app.storage.local import LocalStorage
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from tests.support import FakeProvider, make_png

pytestmark = pytest.mark.integration

# The fixture blueprint has three scoreable leaves: 1a (2), 1b (3), 2 (5).
LEAVES = {"1a": 2, "1b": 3, "2": 5}


def _settings(mode: str, *, gate: bool = False) -> Settings:
    base = get_settings()
    marking = base.marking.model_copy(
        update={
            "marking_mode": mode,
            # The evidence gate is stated rather than inherited: this suite buys
            # no blind reading, so an inherited gate would send every award to
            # review and replace the subject of each test with that outcome.  The
            # gate's own tests live in the sibling pipeline suite.
            "require_evidence_for_award": gate,
        }
    )
    return base.model_copy(update={"marking": marking})


#: The fixture scheme's printed mark points per scoreable leaf.  A reply names the
#: codes it was given: claiming the whole leaf on one code would tell the verifier
#: that a mark point is worth more than the scheme printed for it.
PRINTED = {
    "1a": (("M1", 1), ("A1", 1)),
    "1b": (("M1", 1), ("M2", 1), ("A1", 1)),
    "2": (("M1", 2), ("A1", 3)),
}


def _item(question_id: str, *, awarded: int | None = None, evidence: str | None = "x = 3") -> dict:
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
                # Partial credit is recorded as what was earned, never as a larger
                # printed mark point with a zero-value sibling.
                "marks": printed if credit in (0, printed) else credit,
                "awarded": credit > 0,
                "reason": "Matches the scheme." if credit else "Not earned.",
                "evidence": evidence if credit else None,
                # The reply contract asks for the page each quotation is on.
                "page": 1,
            }
        )
    return {
        "question_id": question_id,
        "student_answer": "x = 3",
        "awarded_marks": sum(
            component["marks"] for component in components if component["awarded"]
        ),
        "components": components,
        "confidence": 0.95,
    }


def _paper_body(*question_ids: str, **overrides: dict) -> str:
    items = []
    for question_id in question_ids:
        item = _item(question_id)
        item.update(overrides.get(question_id, {}))
        items.append(item)
    return json.dumps({"questions": items})


def _is_paper_request(request) -> bool:
    return any(
        (part.text or "").startswith("This request carries one complete student paper")
        for part in request.inputs
    )


def _question_of(request) -> str:
    for part in request.inputs:
        text_value = part.text or ""
        if text_value.startswith("Question: "):
            return text_value.splitlines()[0].split(": ", 1)[1].strip()
    return ""


class ModeAwareProvider(FakeProvider):
    """Answers a paper request with the paper body and a single one otherwise."""

    def __init__(self, paper_body: str, per_question: dict[str, str] | None = None) -> None:
        super().__init__()
        self.paper_body = paper_body
        self.per_question = per_question or {
            question_id: json.dumps(_item(question_id)) for question_id in LEAVES
        }
        self.paper_requests = 0

    def generate(self, request, api_key):
        if _is_paper_request(request):
            self.paper_requests += 1
            self.text = self.paper_body
        else:
            self.text = self.per_question.get(_question_of(request), "{}")
        return super().generate(request, api_key)


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
            idempotency_key=f"whole-paper-{uuid.uuid4().hex[:12]}",
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


def _rows(db_session, job) -> dict[str, QuestionResult]:
    db_session.expire_all()
    return {
        row.question_id: row
        for row in db_session.scalars(
            select(QuestionResult).where(QuestionResult.job_id == job.id)
        )
    }


def _archives(db_session, job) -> list[ProviderResponse]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(ProviderResponse)
            .where(ProviderResponse.job_id == job.id)
            .order_by(ProviderResponse.created_at)
        )
    )


# -- schema -------------------------------------------------------------


def test_the_migration_reproduces_the_archive_and_provenance_schema(engine) -> None:
    with engine.connect() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'provider_responses'"
                )
            )
        }
        assert {
            "id",
            "tenant_id",
            "job_id",
            "provider_usage_id",
            "prompt_version_id",
            "response_source",
            "sequence",
            "content_sha256",
            "content_length",
            "body",
            "body_truncated",
            "finish_reason",
            "model",
            "created_at",
        } <= columns
        result_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'question_results'"
                )
            )
        }
        assert {"response_source", "response_sequence", "provider_usage_id"} <= result_columns
        job_columns = {
            row[0]
            for row in connection.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'correction_jobs'"
                )
            )
        }
        assert "marking_mode" in job_columns
        constraints = {
            row[0]
            for row in connection.execute(
                text(
                    "select conname from pg_constraint "
                    "where conrelid = 'provider_responses'::regclass"
                )
            )
        }
        assert {
            "pk_provider_responses",
            "uq_provider_responses_usage",
            "ck_provider_responses_response_source",
        } <= constraints
        # One archive per audited call, never one per distinct body: a retried
        # call that receives the same reply keeps its own copy so the archive
        # cannot claim a call received a body it did not.
        assert "uq_provider_responses_job_content" not in constraints
        assert connection.execute(
            text("select relrowsecurity from pg_class where relname = 'provider_responses'")
        ).scalar()


# -- whole paper --------------------------------------------------------


def test_one_paper_request_stores_every_mark_and_links_it_to_the_archive(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    body = _paper_body("1a", "1b", "2")
    provider = ModeAwareProvider(body)

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("WHOLE_PAPER")
    )

    assert outcome.state is JobState.FINALIZING
    assert provider.paper_requests == 1
    assert len(provider.requests) == 1

    rows = _rows(db_session, job)
    assert sorted(rows) == ["1a", "1b", "2"]
    assert [rows[qid].awarded_marks for qid in ("1a", "1b", "2")] == [2, 3, 5]
    assert {row.response_source for row in rows.values()} == {"WHOLE_PAPER"}
    assert [rows[qid].response_sequence for qid in ("1a", "1b", "2")] == [0, 1, 2]
    usage_ids = {row.provider_usage_id for row in rows.values()}
    assert len(usage_ids) == 1 and None not in usage_ids

    archives = _archives(db_session, job)
    assert len(archives) == 1
    archive = archives[0]
    assert archive.body == json.loads(body)
    assert archive.content_sha256 == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert archive.content_length == len(body)
    assert archive.body_truncated is False
    assert archive.response_source == "WHOLE_PAPER"
    assert archive.finish_reason == "STOP"

    # The link in both directions: each row names the audited call, and that call
    # addresses the archived document.
    assert usage_ids == {archive.provider_usage_id}
    assert {
        row.raw_response["paper_sha256"] for row in rows.values()
    } == {archive.content_sha256}
    assert job.marking_mode == "WHOLE_PAPER"


def test_a_partial_paper_marks_only_the_missing_questions_individually(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a"))

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("WHOLE_PAPER")
    )

    assert outcome.state is JobState.FINALIZING
    assert provider.paper_requests == 1
    # One paper request plus one per unanswered question; the paper is not repeated.
    assert len(provider.requests) == 3

    rows = _rows(db_session, job)
    assert sorted(rows) == ["1a", "1b", "2"]
    assert [rows[qid].awarded_marks for qid in ("1a", "1b", "2")] == [2, 3, 5]
    assert rows["1a"].response_source == "WHOLE_PAPER"
    assert rows["1b"].response_source == "PER_QUESTION"
    assert rows["2"].response_source == "PER_QUESTION"
    assert rows["1b"].response_sequence is None
    assert len({rows[qid].provider_usage_id for qid in ("1b", "2")}) == 2
    assert len(_archives(db_session, job)) == 1


def test_an_invalid_item_falls_back_without_repeating_the_paper(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    # 1b awards a mark with no quoted evidence: a contract failure for 1b only.
    body = json.dumps(
        {
            "questions": [
                _item("1a"),
                _item("1b", evidence=None),
                _item("2"),
            ]
        }
    )
    provider = ModeAwareProvider(body)

    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("WHOLE_PAPER")
    )

    assert provider.paper_requests == 1
    assert len(provider.requests) == 2
    rows = _rows(db_session, job)
    assert sorted(rows) == ["1a", "1b", "2"]
    assert rows["1b"].response_source == "PER_QUESTION"
    assert rows["1b"].awarded_marks == 3


def test_a_second_execution_asks_nothing_and_duplicates_nothing(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a", "1b", "2"))
    settings = _settings("WHOLE_PAPER")

    AetrixPipeline(provider=provider, storage=storage).run(job, db_session, settings)
    first = {qid: row.id for qid, row in _rows(db_session, job).items()}
    requests_after_first = len(provider.requests)

    AetrixPipeline(provider=provider, storage=storage).run(job, db_session, settings)

    assert len(provider.requests) == requests_after_first
    rows = _rows(db_session, job)
    assert {qid: row.id for qid, row in rows.items()} == first
    assert db_session.scalar(
        select(func.count()).select_from(QuestionResult).where(QuestionResult.job_id == job.id)
    ) == 3
    assert len(_archives(db_session, job)) == 1


# -- per question -------------------------------------------------------


def test_per_question_mode_records_its_own_provenance(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a", "1b", "2"))

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PER_QUESTION")
    )

    assert outcome.state is JobState.FINALIZING
    assert provider.paper_requests == 0
    assert len(provider.requests) == 3
    rows = _rows(db_session, job)
    assert {row.response_source for row in rows.values()} == {"PER_QUESTION"}
    assert all(row.response_sequence is None for row in rows.values())
    assert len({row.provider_usage_id for row in rows.values()}) == 3
    # A per-question reply lives in its own row; no paper archive is created.
    assert _archives(db_session, job) == []
    assert job.marking_mode == "PER_QUESTION"


# -- atomicity ----------------------------------------------------------


def test_a_failed_persistence_keeps_the_paid_reply_for_the_retry(
    paper, identity, db_session, provider_credential, tmp_path, monkeypatch
) -> None:
    """The reply is committed before the rows, so a row failure cannot lose it."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a", "1b", "2"))
    settings = _settings("WHOLE_PAPER")

    def _fail(*args, **kwargs):
        raise OperationalError("insert", {}, Exception("storage unavailable"))

    monkeypatch.setattr(_MarkingRun, "_persist_mark", _fail)

    with pytest.raises(RetryablePipelineError, match="could not be stored"):
        AetrixPipeline(provider=provider, storage=storage).run(
            job, db_session, settings
        )

    db_session.rollback()
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(QuestionResult)
            .where(QuestionResult.job_id == job.id)
        )
        == 0
    )
    assert len(_archives(db_session, job)) == 1
    requests = len(provider.requests)

    # The retry rebuilds the rows from the archive instead of paying again.
    monkeypatch.undo()
    AetrixPipeline(provider=provider, storage=storage).run(job, db_session, settings)

    assert len(provider.requests) == requests
    assert sorted(_rows(db_session, job)) == ["1a", "1b", "2"]
    assert len(_archives(db_session, job)) == 1


def test_a_paid_paper_whose_reply_was_lost_is_never_requested_again(
    paper, identity, db_session, provider_credential, tmp_path, monkeypatch
) -> None:
    """Paying twice is worse than marking the rest per question."""

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a", "1b", "2"))
    settings = _settings("WHOLE_PAPER")

    def _fail(*args, **kwargs):
        raise OperationalError("insert", {}, Exception("archive unavailable"))

    monkeypatch.setattr(_MarkingRun, "_archive_response", _fail)

    with pytest.raises(RetryablePipelineError, match="could not be archived"):
        AetrixPipeline(provider=provider, storage=storage).run(
            job, db_session, settings
        )

    db_session.rollback()
    assert _archives(db_session, job) == []
    assert len(provider.requests) == 1
    assert provider.paper_requests == 1

    # The usage ledger remembers the paid attempt, so the paper is not re-sent;
    # every question is marked on its own instead.
    monkeypatch.undo()
    AetrixPipeline(provider=provider, storage=storage).run(job, db_session, settings)

    assert provider.paper_requests == 1
    assert len(provider.requests) == 1 + 3
    assert sorted(_rows(db_session, job)) == ["1a", "1b", "2"]


# -- mode pinning -------------------------------------------------------


def test_a_resumed_paper_keeps_the_mode_it_started_in(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a", "1b", "2"))

    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("WHOLE_PAPER")
    )
    # A retryable row for one question makes the job look unfinished.
    row = _rows(db_session, job)["1b"]
    row.processing_state = "NEEDS_REVIEW"
    row.normalisation_anomaly = "MODEL_RESPONSE_INVALID"
    db_session.commit()
    requests_before = len(provider.requests)

    # The deployment now says per question; this paper must not switch.
    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("PER_QUESTION")
    )

    db_session.expire_all()
    assert job.marking_mode == "WHOLE_PAPER"
    # The resumed paper reuses its archived reply instead of buying the paper a
    # second time, and the retried row still carries whole-paper provenance.
    assert provider.paper_requests == 1
    assert len(provider.requests) == requests_before
    rows = _rows(db_session, job)
    assert rows["1b"].response_source == "WHOLE_PAPER"
    assert len(_archives(db_session, job)) == 1


def test_a_job_whose_rows_disagree_with_its_mode_fails_closed(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a", "1b", "2"))

    AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("WHOLE_PAPER")
    )
    # Simulate a job whose recorded mode was corrupted: the rows say whole paper.
    db_session.expire_all()
    db_session.get(CorrectionJob, job.id).marking_mode = "PER_QUESTION"
    db_session.commit()
    row = _rows(db_session, job)["1b"]
    row.processing_state = "NEEDS_REVIEW"
    row.normalisation_anomaly = "MODEL_RESPONSE_INVALID"
    db_session.commit()
    requests_before = len(provider.requests)

    with pytest.raises(AppError, match="different marking mode"):
        AetrixPipeline(provider=provider, storage=storage).run(
            job, db_session, _settings("PER_QUESTION")
        )

    assert len(provider.requests) == requests_before


def test_an_unchecked_whole_paper_award_is_routed_to_a_person(
    paper, identity, db_session, provider_credential, tmp_path
) -> None:
    """STUDENT_02's shape: one paper reply, marks recorded, nothing examined.

    The paper request produced every award in one reply and no evidence check was
    bought for any of them, which is how 3/3 stood for an answer that was not on
    the page.  The paper must not present itself as a finished correction, and no
    award may be changed to achieve that.
    """

    storage = LocalStorage(tmp_path / "store")
    job = _setup(paper, identity, db_session, storage)
    provider = ModeAwareProvider(_paper_body("1a", "1b", "2"))

    outcome = AetrixPipeline(provider=provider, storage=storage).run(
        job, db_session, _settings("WHOLE_PAPER", gate=True)
    )

    assert outcome.state is JobState.REVIEW_REQUIRED, outcome.detail
    assert provider.paper_requests == 1
    assert outcome.detail["evidence_gate"]["enabled"] is True
    assert set(outcome.detail["evidence_gate"]["ungrounded"]) == {"1a", "1b", "2"}

    rows = _rows(db_session, job)
    assert [rows[qid].awarded_marks for qid in ("1a", "1b", "2")] == [2, 3, 5]
    assert {row.processing_state for row in rows.values()} == {"NEEDS_REVIEW"}
    assert all(
        any(
            concern.get("code") == "EVIDENCE_NOT_CHECKED"
            for concern in (row.scheme_concerns or [])
        )
        for row in rows.values()
    )
