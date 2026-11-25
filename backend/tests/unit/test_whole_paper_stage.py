"""The whole-paper stage: one request, atomic rows, provenance, fallback.

These exercise the stage without a database or a provider.  What they pin is the
contract the pipeline relies on: rows are written in one transaction, every row
names the paper it came from, and every question the paper did not decide is
reported so the per-question engine marks exactly those.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from app.core.errors import AppError
from app.correction.aetrix.pipeline import _MarkingRun, _paper_targets
from app.correction.aetrix.whole_paper import MAX_WHOLE_PAPER_LEAVES
from sqlalchemy.exc import OperationalError


class _Rows(list):
    def all(self) -> list:
        return list(self)


class _Session:
    """Counts the transaction boundaries the stage makes.

    ``archives`` is what the recovery query sees: an empty list means this job has
    no archived reply.  ``paid`` is the count of successful whole-paper calls in
    the usage ledger.  A test that wants the recovery or the no-repeat guard looks
    at these two, so the stage's queries must go through them.

    ``fail_commit`` fails the first commit (the archive); ``fail_after`` allows
    that many commits and fails the next one (the rows).  They are separate
    because the stage archives the paid reply in its own transaction before it
    writes any question.
    """

    def __init__(
        self,
        *,
        fail_commit: bool = False,
        fail_after: int | None = None,
        archives: list | None = None,
        paid: int = 0,
    ) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = fail_commit
        self.fail_after = fail_after
        self.archives = list(archives or [])
        self.paid = paid

    def scalars(self, statement) -> _Rows:
        return _Rows(self.archives)

    def scalar(self, statement):
        return self.paid

    def commit(self) -> None:
        self.commits += 1
        if self.fail_commit or (
            self.fail_after is not None and self.commits > self.fail_after
        ):
            raise OperationalError("commit", {}, Exception("database went away"))

    def rollback(self) -> None:
        self.rollbacks += 1

    def add(self, row) -> None:
        raise AssertionError("the stage must use the archive helper")

    def flush(self) -> None:
        raise AssertionError("the stage must use the archive helper")


def _leaves(ids: list[str]) -> list[tuple[str, int, str | None, str]]:
    return [(question_id, 2, "MATHEMATICAL", question_id) for question_id in ids]


def _item(question_id: str) -> dict:
    return {
        "question_id": question_id,
        "student_answer": "x = 3",
        "awarded_marks": 1,
        "components": [
            {
                "code": "M1",
                "marks": 1,
                "awarded": True,
                "reason": "Substituted.",
                "evidence": "x = 3",
            }
        ],
        "confidence": 0.91,
    }


def _body(*question_ids: str) -> str:
    return json.dumps({"questions": [_item(question_id) for question_id in question_ids]})


def _call(text: str, *, finish: str = "STOP") -> SimpleNamespace:
    return SimpleNamespace(
        response=SimpleNamespace(
            text=text,
            finish_reason=finish,
            usage=SimpleNamespace(output_tokens=1234),
            provider_request_id="req-paper-1",
        ),
        usage_id=uuid.uuid4(),
        prompt=SimpleNamespace(version=1),
    )


def _run(
    question_ids: list[str],
    *,
    pages: int = 3,
    page_cap: int = 12,
    call: SimpleNamespace | None = None,
    fail_commit: bool = False,
    fail_after: int | None = None,
    archives: list | None = None,
    paid: int = 0,
    persist_error: bool = False,
) -> tuple[_MarkingRun, _Session, list[dict]]:
    leaves = _leaves(question_ids)
    run = object.__new__(_MarkingRun)
    run.job = SimpleNamespace(id=uuid.uuid4())
    run.session = _Session(
        fail_commit=fail_commit, fail_after=fail_after, archives=archives, paid=paid
    )
    run.settings = SimpleNamespace(
        marking=SimpleNamespace(
            whole_paper_max_pages=page_cap,
            whole_paper_max_output_tokens=32768,
        )
    )
    run.readable = [SimpleNamespace(id=index) for index in range(pages)]
    run.criteria_by_question = {}
    run.leaf_by_question = {leaf[0]: leaf for leaf in leaves}
    run.marking_prompt_version = None
    run.prompt_version = None
    run.prompt_versions = []
    run._page_inputs = lambda pages, cap=None: ()  # type: ignore[method-assign]
    run._blueprint_question = lambda parent, question_id: None  # type: ignore[method-assign]
    run.withheld_pages = lambda question_id, cap=None: 0  # type: ignore[method-assign]
    run.call_model = lambda *args, **kwargs: call  # type: ignore[method-assign]

    written: list[dict] = []

    def _persist(
        mark,
        *,
        captured,
        max_marks,
        existing,
        withheld_pages,
        usage_id=None,
        source=None,
        sequence=None,
        commit=True,
    ):
        assert commit is False, "a paper row must not commit on its own"
        written.append(
            {
                "question_id": mark.question_id,
                "captured": captured,
                "existing": existing,
                "max_marks": max_marks,
                "usage_id": usage_id,
                "source": source,
                "sequence": sequence,
            }
        )
        return SimpleNamespace(id=uuid.uuid4())

    run._persist_mark = _persist  # type: ignore[method-assign]
    run._archive_response = lambda **kwargs: SimpleNamespace(  # type: ignore[method-assign]
        id=uuid.uuid4(), captured=kwargs, content_sha256=kwargs["digest"] or "digest"
    )
    return run, run.session, written


def test_one_request_persists_every_row_in_a_single_transaction() -> None:
    run, session, written = _run(["1a", "1b", "1c"], call=_call(_body("1a", "1b", "1c")))

    outcome = run.mark_paper(_leaves(["1a", "1b", "1c"]), existing={})

    assert sorted(outcome.rows) == ["1a", "1b", "1c"]
    assert [entry["question_id"] for entry in written] == ["1a", "1b", "1c"]
    assert [entry["source"] for entry in written] == ["WHOLE_PAPER"] * 3
    assert [entry["sequence"] for entry in written] == [0, 1, 2]
    assert len({entry["usage_id"] for entry in written}) == 1
    # Two boundaries: the paid reply is archived and committed on its own, then
    # the question rows are written in one transaction.
    assert session.commits == 2
    assert session.rollbacks == 0
    assert outcome.detail["status"] == "PARSED"
    assert outcome.detail["persisted"] == 3


def test_each_row_carries_provenance_naming_the_paper_it_came_from() -> None:
    body = _body("1a", "1b")
    run, _session, written = _run(["1a", "1b"], call=_call(body))

    outcome = run.mark_paper(_leaves(["1a", "1b"]), existing={})

    slice_a, slice_b = (entry["captured"].value for entry in written)
    assert slice_a["format"] == "WHOLE_PAPER_SLICE"
    assert slice_a["paper_sha256"] == outcome.detail["paper_sha256"]
    assert slice_a["provider_usage_id"] == outcome.detail["provider_usage_id"]
    assert [slice_a["sequence"], slice_b["sequence"]] == [0, 1]
    assert slice_a["question_id"] == "1a"
    assert slice_a["item"]["awarded_marks"] == 1
    # The complete reply is archived once, by digest, not once per row and not
    # copied into the run record.
    assert "archived_response" not in outcome.detail
    assert outcome.detail["paper_sha256"]
    assert outcome.detail["provider_response_id"]


def test_a_script_with_more_pages_than_one_request_may_carry_is_not_sent() -> None:
    run, session, written = _run(["1a"], pages=13, page_cap=12, call=_call(_body("1a")))

    outcome = run.mark_paper(_leaves(["1a"]), existing={})

    assert outcome.detail["status"] == "SKIPPED"
    assert outcome.detail["reason"] == "PAGES_EXCEED_REQUEST_CAP"
    assert outcome.rows == {}
    assert written == []
    assert session.commits == 0


def test_a_paper_with_too_many_questions_is_marked_per_question_instead() -> None:
    ids = [f"q{index}" for index in range(MAX_WHOLE_PAPER_LEAVES + 1)]
    run, _session, _written = _run(ids, call=_call(_body(ids[0])))

    outcome = run.mark_paper(_leaves(ids), existing={})

    assert outcome.detail["status"] == "SKIPPED"
    assert outcome.detail["reason"] == "TOO_MANY_QUESTIONS"
    assert outcome.rows == {}


def test_a_truncated_reply_keeps_finished_questions_and_reports_the_rest() -> None:
    body = _body("1a", "1b", "1c")
    cut = body[: body.index('"1c"')]
    run, _session, written = _run(["1a", "1b", "1c"], call=_call(cut, finish="MAX_TOKENS"))

    outcome = run.mark_paper(_leaves(["1a", "1b", "1c"]), existing={})

    assert outcome.detail["truncated"] is True
    assert sorted(outcome.rows) == ["1a", "1b"]
    assert outcome.detail["missing"] == 1
    assert [entry["question_id"] for entry in written] == ["1a", "1b"]


def test_an_unreadable_reply_persists_nothing_and_names_the_reason() -> None:
    run, session, written = _run(["1a"], call=_call("I cannot mark this paper."))

    outcome = run.mark_paper(_leaves(["1a"]), existing={})

    assert outcome.detail["status"] == "UNREADABLE"
    assert outcome.rows == {}
    assert written == []
    # No question is stored, but the paid reply is archived as evidence.
    assert session.commits == 1
    assert outcome.detail["paper_sha256"]
    assert outcome.detail["provider_response_id"]
    assert "archived_response" not in outcome.detail


def test_a_failed_row_commit_leaves_no_question_behind() -> None:
    run, session, _written = _run(
        ["1a", "1b"], call=_call(_body("1a", "1b")), fail_after=1
    )

    outcome = run.mark_paper(_leaves(["1a", "1b"]), existing={})

    assert outcome.detail["status"] == "PERSIST_FAILED"
    assert outcome.rows == {}
    assert session.commits == 2
    assert session.rollbacks == 1


def test_reply_that_cannot_be_archived_is_not_reported_as_marked() -> None:
    """The archive is the only record of a paid reply, so its failure is fatal here."""

    run, session, written = _run(
        ["1a", "1b"], call=_call(_body("1a", "1b")), fail_commit=True
    )

    outcome = run.mark_paper(_leaves(["1a", "1b"]), existing={})

    assert outcome.detail["status"] == "ARCHIVE_FAILED"
    assert outcome.rows == {}
    assert written == []
    assert session.rollbacks == 1


def test_a_retryable_row_is_updated_rather_than_duplicated() -> None:
    existing_row = SimpleNamespace(id=uuid.uuid4())
    run, _session, written = _run(["1a"], call=_call(_body("1a")))

    run.mark_paper(_leaves(["1a"]), existing={"1a": existing_row})

    assert written[0]["existing"] is existing_row


class _Results:
    def __init__(self, rows: dict[str, object | None]) -> None:
        self._rows = rows
        self.asked: list[str] = []

    def get_question(self, job_id, question_id):
        del job_id
        self.asked.append(question_id)
        return self._rows.get(question_id)


def test_a_decided_question_is_never_sent_again_in_the_paper() -> None:
    decided = SimpleNamespace(
        processing_state="MARKED", normalisation_anomaly=None
    )
    retryable = SimpleNamespace(
        processing_state="NEEDS_REVIEW", normalisation_anomaly="MODEL_RESPONSE_INVALID"
    )
    results = _Results({"1a": decided, "1b": retryable, "1c": None})

    targets = _paper_targets(_leaves(["1a", "1b", "1c"]), results, uuid.uuid4())

    assert [leaf[0] for leaf in targets] == ["1b", "1c"]


def test_a_fully_decided_job_sends_no_paper_request() -> None:
    decided = SimpleNamespace(processing_state="MARKED", normalisation_anomaly=None)
    results = _Results({"1a": decided, "1b": decided})

    assert _paper_targets(_leaves(["1a", "1b"]), results, uuid.uuid4()) == []


def _mode_run(mode: str) -> _MarkingRun:
    run = object.__new__(_MarkingRun)
    run.marking_mode = mode
    return run


def test_a_job_cannot_switch_marking_mode_after_it_has_marks() -> None:
    run = _mode_run("PER_QUESTION")

    with pytest.raises(AppError, match="different marking mode"):
        run.assert_marking_mode_stable([SimpleNamespace(response_source="WHOLE_PAPER")])


def test_a_whole_paper_job_may_contain_its_own_fallback_rows() -> None:
    run = _mode_run("WHOLE_PAPER")

    run.assert_marking_mode_stable(
        [
            SimpleNamespace(response_source="WHOLE_PAPER"),
            SimpleNamespace(response_source="PER_QUESTION"),
        ]
    )


def test_rows_without_recorded_provenance_do_not_block_a_resume() -> None:
    """Legacy rows predate the column; they must not lock a job out of marking."""

    run = _mode_run("WHOLE_PAPER")

    run.assert_marking_mode_stable([SimpleNamespace(response_source=None)])


def test_the_paper_reply_names_its_prompt_through_the_call() -> None:
    """The stage asks for the paper asset and the paper's output budget."""

    run, _session, _written = _run(["1a"], call=_call(_body("1a")))
    seen: dict = {}

    def _call_model(leaf, **kwargs):
        seen.update(kwargs)
        return _call(_body("1a"))

    run.call_model = _call_model  # type: ignore[method-assign]

    run.mark_paper(_leaves(["1a"]), existing={})

    assert seen["prompt_id"] == "aetrix_v5_5_marking_whole_paper"
    assert seen["purpose"] == "marking"
    assert seen["max_output_tokens"] == 32768
    assert seen["response_schema"]["required"] == ["questions"]


# -- recovery -----------------------------------------------------------


def _archive_row(body: str, *, finish: str = "STOP") -> SimpleNamespace:
    """An archived reply as the recovery query returns it (body decoded once)."""

    return SimpleNamespace(
        id=uuid.uuid4(),
        body=json.loads(body),
        content_sha256="0" * 64,
        finish_reason=finish,
        provider_usage_id=uuid.uuid4(),
    )


def test_an_archived_reply_is_reused_without_a_new_request() -> None:
    body = _body("1a", "1b")
    run, session, written = _run(
        ["1a", "1b"], call=None, archives=[_archive_row(body)]
    )

    outcome = run.mark_paper(_leaves(["1a", "1b"]), existing={})

    assert outcome.detail["status"] == "PARSED"
    assert outcome.detail["recovered_from_archive"] is True
    assert sorted(outcome.rows) == ["1a", "1b"]
    assert [entry["question_id"] for entry in written] == ["1a", "1b"]
    assert {entry["captured"].value["format"] for entry in written} == {
        "WHOLE_PAPER_SLICE"
    }
    assert session.commits == 1


def test_a_paid_paper_without_an_archive_is_not_requested_again() -> None:
    run, session, written = _run(["1a", "1b"], call=None, paid=1)

    outcome = run.mark_paper(_leaves(["1a", "1b"]), existing={})

    assert outcome.detail["status"] == "SKIPPED"
    assert outcome.detail["reason"] == "PAID_ATTEMPT_UNRECOVERABLE"
    assert outcome.rows == {}
    assert written == []
    assert session.commits == 0


def test_an_archive_clipped_for_storage_is_not_mistaken_for_the_reply() -> None:
    clipped = SimpleNamespace(
        id=uuid.uuid4(),
        body={"format": "TEXT_TRUNCATED", "text": '{"items": ['},
        content_sha256="0" * 64,
        finish_reason="STOP",
        provider_usage_id=uuid.uuid4(),
    )
    run, _session, written = _run(["1a"], call=None, archives=[clipped], paid=1)

    outcome = run.mark_paper(_leaves(["1a"]), existing={})

    assert outcome.detail["reason"] == "PAID_ATTEMPT_UNRECOVERABLE"
    assert written == []


def test_an_archived_reply_that_no_longer_parses_falls_back_to_the_guard() -> None:
    unreadable = SimpleNamespace(
        id=uuid.uuid4(),
        body="I cannot mark this paper.",
        content_sha256="0" * 64,
        finish_reason="STOP",
        provider_usage_id=uuid.uuid4(),
    )
    run, _session, written = _run(["1a"], call=None, archives=[unreadable], paid=1)

    outcome = run.mark_paper(_leaves(["1a"]), existing={})

    assert outcome.detail["status"] == "SKIPPED"
    assert outcome.detail["reason"] == "PAID_ATTEMPT_UNRECOVERABLE"
    assert written == []


def test_a_duplicated_question_object_is_written_once() -> None:
    """The reply may repeat a question; the second copy is dropped, not persisted."""

    item = json.loads(_body("1a"))["questions"][0]
    body = json.dumps({"questions": [item, item]})
    run, _session, written = _run(["1a"], call=_call(body))

    outcome = run.mark_paper(_leaves(["1a"]), existing={})

    assert [entry["question_id"] for entry in written] == ["1a"]
    assert outcome.detail["persisted"] == 1
    assert sorted(outcome.rows) == ["1a"]
