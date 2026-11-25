"""Criterion provenance and evidence attribution, stored in real PostgreSQL.

The unit suite proves the resolver's decisions.  This suite proves what the
production persistence path actually writes: the approved ``criterion_id`` on the
component and on the quotation, the page of the original student document, and
the refusal of an award whose mark point cannot be identified.

Nothing here calls a provider.  The reply is constructed and handed to the same
``_persist_mark`` the whole-paper stage uses.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.correction import provenance
from app.correction.aetrix.pipeline import _MarkingRun
from app.correction.aetrix.schema import QuestionMark, _disambiguate_component_codes
from app.correction.evidence import CapturedResponse
from app.db.models import (
    CorrectionJob,
    CriterionResult,
    Document,
    DocumentPage,
    MarkingCriterion,
    MarkingEvidence,
    QuestionResult,
)
from app.jobs.states import JobState
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

#: A reply that names both printed mark points of question ``1a``.
AWAITING = {
    "question_id": "1a",
    "student_answer": "x = 4",
    "awarded_marks": 2,
    "confidence": 0.95,
    "components": [
        {
            "code": "M1",
            "reference": "M1#1",
            "marks": 1,
            "awarded": True,
            "evidence": "3x + 1 = 13",
            "page": 2,
        },
        {
            "code": "A1",
            "reference": "A1#2",
            "marks": 1,
            "awarded": True,
            "evidence": "x = 4",
            "page": 2,
        },
    ],
}


def _mark(**overrides) -> QuestionMark:
    import copy

    item = copy.deepcopy(AWAITING)
    item.update(overrides)
    mark = QuestionMark.model_validate(item)
    _disambiguate_component_codes(mark.components)
    return mark


@pytest.fixture
def script(db_session, identity, paper):
    """One processed student document with three readable pages."""

    document = Document(
        tenant_id=identity.tenant_a.id,
        submission_id=paper.submission.id,
        kind="STUDENT",
        storage_key="tenants/a/documents/scan/original.pdf",
        original_filename="script.pdf",
        sha256="d" * 64,
        mime_type="application/pdf",
        size_bytes=1024,
        page_count=3,
        status="PROCESSED",
    )
    db_session.add(document)
    db_session.flush()
    pages = [
        DocumentPage(
            tenant_id=identity.tenant_a.id,
            document_id=document.id,
            page_index=index,
            storage_key=f"tenants/a/documents/scan/pages/{index:03d}.png",
            quality_status="READABLE",
            checksum=f"{index:064d}",
        )
        for index in (1, 2, 3)
    ]
    db_session.add_all(pages)
    db_session.flush()
    job = CorrectionJob(
        tenant_id=identity.tenant_a.id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state=JobState.CORRECTING.value,
        idempotency_key=f"provenance-{uuid.uuid4()}",
        request_hash="e" * 64,
        engine_name="aetrix_v5_5",
        engine_version="5.5.0",
    )
    db_session.add(job)
    db_session.commit()
    return SimpleNamespace(document=document, pages=pages, job=job)


def _run(db_session, script, paper) -> _MarkingRun:
    """The marking run the whole-paper stage builds, without the provider."""

    criteria = db_session.scalars(
        select(MarkingCriterion).where(
            MarkingCriterion.scheme_version_id == paper.scheme_version.id
        )
    ).all()
    by_question: dict[str, list[MarkingCriterion]] = {}
    for criterion in criteria:
        by_question.setdefault(criterion.question_id, []).append(criterion)
    working = object.__new__(_MarkingRun)
    working.session = db_session
    working.job = script.job
    working.settings = SimpleNamespace(marking=SimpleNamespace(min_confidence=0.6))
    working.structure = SimpleNamespace(questions=[])
    working.criteria_by_question = by_question
    working.readable = script.pages
    working.quality = [page.quality_status for page in script.pages]
    working.engine_version = "5.5.0"
    working.policy = SimpleNamespace(mode="BALANCED")
    working.marking_mode = "WHOLE_PAPER"
    working.page_cap = 12
    working.prompt_version = "aetrix_v5_5_marking_whole_paper:v2"
    working.prompt_versions = [working.prompt_version]
    working.integrity_findings = []
    working.scheme_findings = []
    working.coverage_messages = []
    working.leaf_by_question = {}
    working.page_index = provenance.PageIndex.build(
        script.pages, [script.document]
    )
    return working


def _persist(db_session, working, mark, *, max_marks: int = 2) -> QuestionResult:
    return working._persist_mark(
        mark,
        captured=CapturedResponse(value=mark.model_dump(mode="json"), truncated=False),
        max_marks=max_marks,
        existing=None,
        usage_id=None,
        source="WHOLE_PAPER",
        sequence=0,
    )


def _criteria_rows(db_session, row: QuestionResult) -> list[CriterionResult]:
    return list(
        db_session.scalars(
            select(CriterionResult)
            .where(CriterionResult.question_result_id == row.id)
            .order_by(CriterionResult.code)
        )
    )


def _scheme_criteria(db_session, paper, question_id: str) -> list[MarkingCriterion]:
    return list(
        db_session.scalars(
            select(MarkingCriterion)
            .where(
                MarkingCriterion.scheme_version_id == paper.scheme_version.id,
                MarkingCriterion.question_id == question_id,
            )
            .order_by(MarkingCriterion.ordinal)
        )
    )


def test_a_named_mark_point_is_stored_with_its_approved_criterion(
    db_session, script, paper
) -> None:
    working = _run(db_session, script, paper)

    row = _persist(db_session, working, _mark())

    scheme = _scheme_criteria(db_session, paper, "1a")
    rows = _criteria_rows(db_session, row)

    assert [criterion.code for criterion in rows] == ["A1", "M1"]
    assert {criterion.criterion_id for criterion in rows} == {item.id for item in scheme}
    assert row.review_required is False
    assert row.status == "AWARDED"


def test_the_quotation_is_attached_to_the_page_it_is_written_on(
    db_session, script, paper
) -> None:
    working = _run(db_session, script, paper)

    row = _persist(db_session, working, _mark())
    evidence = list(
        db_session.scalars(
            select(MarkingEvidence).where(MarkingEvidence.question_result_id == row.id)
        )
    )

    page_two = next(page for page in script.pages if page.page_index == 2)
    assert len(evidence) == 2
    assert {item.page_id for item in evidence} == {page_two.id}
    assert {item.criterion_id for item in evidence} == {
        criterion.criterion_id for criterion in _criteria_rows(db_session, row)
    }
    # No bounding box was produced, so none is stored: an empty box here would
    # claim the extraction located the writing.
    assert all(item.bbox is None for item in evidence)
    # And absent means SQL NULL.  Stored as the JSON literal ``null`` the column
    # is NOT NULL to every query while holding no coordinates, which is how 87
    # production rows came to look located when they were not.
    for query, expected in (
        ("bbox is null", len(evidence)),
        ("bbox::text = 'null'", 0),
        ("bbox is not null", 0),
    ):
        stored = db_session.execute(
            text(
                "select count(*) from marking_evidence "
                f"where question_result_id = :row and {query}"
            ),
            {"row": row.id},
        ).scalar_one()
        assert stored == expected, query


def test_a_read_box_is_kept_whole_and_an_impossible_one_is_dropped(
    db_session, script, paper
) -> None:
    """A box is kept as read or refused; it is never repaired into a guess."""

    import copy

    working = _run(db_session, script, paper)
    item = copy.deepcopy(AWAITING)
    item["components"][0]["bbox"] = [0.1, 0.25, 0.6, 0.4]
    # Lower corner above the upper one: the reply located nothing.
    item["components"][1]["bbox"] = [0.7, 0.25, 0.2, 0.4]
    mark = QuestionMark.model_validate(item)
    _disambiguate_component_codes(mark.components)

    row = _persist(db_session, working, mark)
    boxes = {
        item.quote: item.bbox
        for item in db_session.scalars(
            select(MarkingEvidence).where(MarkingEvidence.question_result_id == row.id)
        )
    }

    assert boxes["3x + 1 = 13"] == [0.1, 0.25, 0.6, 0.4]
    assert boxes["x = 4"] is None, "an impossible box was stored instead of dropped"

    stored = db_session.execute(
        text(
            "select bbox::text from marking_evidence "
            "where question_result_id = :row and bbox is not null"
        ),
        {"row": row.id},
    ).scalar_one()
    assert stored == "[0.1, 0.25, 0.6, 0.4]", "the kept box round-trips as numbers"

    # The refusal is visible where a reviewer looks, not silent.
    rejected = [
        note
        for criterion in _criteria_rows(db_session, row)
        for note in criterion.evidence
        if "bbox_rejected" in note
    ]
    assert len(rejected) == 1
    assert "no area" in rejected[0]["bbox_rejected"]


def test_a_quotation_with_no_page_is_stored_unlocated_and_refused(
    db_session, script, paper
) -> None:
    working = _run(db_session, script, paper)
    item = _mark().model_dump(mode="json")
    for component in item["components"]:
        component["page"] = None
    mark = QuestionMark.model_validate(item)

    row = _persist(db_session, working, mark)
    evidence = list(
        db_session.scalars(
            select(MarkingEvidence).where(MarkingEvidence.question_result_id == row.id)
        )
    )

    assert all(item.page_id is None for item in evidence)
    assert row.review_required is True
    assert row.status == "REVIEW_REQUIRED"
    assert row.processing_state == "NEEDS_REVIEW"
    assert "EVIDENCE_UNLOCATED" in str(row.scheme_concerns)


def test_a_page_the_script_does_not_have_is_refused_not_stored(
    db_session, script, paper
) -> None:
    working = _run(db_session, script, paper)
    item = _mark().model_dump(mode="json")
    for component in item["components"]:
        component["page"] = 9
    mark = QuestionMark.model_validate(item)

    row = _persist(db_session, working, mark)
    evidence = list(
        db_session.scalars(
            select(MarkingEvidence).where(MarkingEvidence.question_result_id == row.id)
        )
    )

    assert row.review_required is True
    assert "EVIDENCE_PAGE_INVALID" in str(row.scheme_concerns)
    assert all(item.page_id is None for item in evidence)
    # The page the reply claimed is kept with the component, so a person can see
    # what it said rather than being shown nothing.
    stored = next(item for item in _criteria_rows(db_session, row) if item.code == "M1")
    assert stored.evidence[0]["page"] == 9


def test_a_repeated_code_beyond_the_scheme_is_refused_without_a_second_link(
    db_session, script, paper
) -> None:
    """Question 1a prints one ``M1``; a second award of it cannot be linked."""

    working = _run(db_session, script, paper)
    item = _mark().model_dump(mode="json")
    item["components"] = [
        {"code": "M1", "marks": 1, "awarded": True, "evidence": "3x + 1", "page": 2},
        {"code": "M1", "marks": 1, "awarded": True, "evidence": "= 13", "page": 2},
    ]
    item["awarded_marks"] = 2
    mark = QuestionMark.model_validate(item)
    _disambiguate_component_codes(mark.components)

    row = _persist(db_session, working, mark)
    rows = _criteria_rows(db_session, row)

    # The first award links to the one printed point; the second cannot, and is
    # refused rather than attached to the same point again.
    assert [item.code for item in rows] == ["M1", "M1-2"]
    assert rows[0].criterion_id is not None
    assert rows[1].criterion_id is None
    assert row.review_required is True
    assert "EXCESS_CRITERION_AWARD" in str(row.scheme_concerns)


def test_one_mark_point_is_never_paid_twice(
    db_session, script, paper
) -> None:
    """Two awards of one mark point keep the first link and refuse the second."""

    working = _run(db_session, script, paper)
    item = {
        "question_id": "1a",
        "awarded_marks": 2,
        "confidence": 0.95,
        "components": [
            {
                "code": "M1",
                "reference": "M1#1",
                "marks": 1,
                "awarded": True,
                "evidence": "3x + 1 = 13",
                "page": 2,
            },
            {
                "code": "M1",
                "reference": "M1#1",
                "marks": 1,
                "awarded": True,
                "evidence": "3x = 12",
                "page": 2,
            },
        ],
    }
    mark = QuestionMark.model_validate(item)

    row = _persist(db_session, working, mark)
    rows = _criteria_rows(db_session, row)

    assert [item.criterion_id for item in rows].count(None) == 1
    assert "DUPLICATE_CRITERION_AWARD" in str(row.scheme_concerns)
    assert row.review_required is True


def test_the_database_refuses_a_second_row_for_one_mark_point(
    db_session, script, paper
) -> None:
    """The migration's partial unique index is the backstop, not the only check."""

    working = _run(db_session, script, paper)
    row = _persist(db_session, working, _mark())
    criterion_id = next(
        item.criterion_id for item in _criteria_rows(db_session, row) if item.code == "M1"
    )
    db_session.add(
        CriterionResult(
            tenant_id=row.tenant_id,
            question_result_id=row.id,
            criterion_id=criterion_id,
            code="M1",
            awarded=True,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_historical_row_without_a_criterion_survives_new_marking(
    db_session, script, paper
) -> None:
    """Rows written before the identity existed keep their NULL and their mark.

    The index is partial, so any number of unlinked rows are allowed; nothing
    backfills a criterion id, because nobody can know which one a historical
    reply meant.
    """

    historical = QuestionResult(
        tenant_id=paper.submission.tenant_id,
        job_id=script.job.id,
        question_id="1b",
        max_marks=3,
        awarded_marks=1,
        status="AWARDED",
        processing_state="MARKED",
        normalisation_anomaly=None,
    )
    db_session.add(historical)
    db_session.flush()
    db_session.add_all(
        [
            CriterionResult(
                tenant_id=historical.tenant_id,
                question_result_id=historical.id,
                criterion_id=None,
                code="M1",
                awarded=True,
                evidence=[{"quote": "x + y = 9"}],
            ),
            CriterionResult(
                tenant_id=historical.tenant_id,
                question_result_id=historical.id,
                criterion_id=None,
                code="A1",
                awarded=False,
                evidence=[],
            ),
        ]
    )
    db_session.flush()

    working = _run(db_session, script, paper)
    fresh = _persist(db_session, working, _mark())

    stored = db_session.get(QuestionResult, historical.id)
    assert stored is not None
    assert stored.awarded_marks == 1
    assert [item.code for item in _criteria_rows(db_session, stored)] == ["A1", "M1"]
    assert all(item.criterion_id is None for item in _criteria_rows(db_session, stored))
    assert {item.criterion_id for item in _criteria_rows(db_session, fresh)} != {None}


def test_the_persisted_payload_does_not_carry_parser_internal_state(
    db_session, script, paper
) -> None:
    """``bbox_invalid`` is a validation note, not part of the marked reply."""

    item = _mark().model_dump(mode="json")

    assert "bbox_invalid" not in item["components"][0]
