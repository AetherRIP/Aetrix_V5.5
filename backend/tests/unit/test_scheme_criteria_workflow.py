"""The teacher workflow that turns an uploaded scheme into approved criteria.

The engine refuses to mark without criteria rows that a person approved against
one blueprint version.  Before this workflow existed, a scheme could be uploaded
and approved and still leave every assignment unmarkable, and the review screen
called two endpoints the API did not have.  These tests pin each step that
closes that gap.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1 import documents
from app.core.errors import AppError, ErrorCode
from app.correction.scheme_criteria import (
    REASON_CRITERIA_BLUEPRINT_MISMATCH,
    REASON_CRITERIA_NOT_APPROVED,
    REASON_CRITERIA_RULES_CHANGED,
    criteria_rules_hash,
    rows_as_document,
    validate,
)
from app.prompts.registry import PromptRegistry
from app.services.scheme_criteria import (
    criteria_response_schema,
    readiness_for,
    readiness_of_assignment,
    reconcile_max_points,
)

PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "prompts"

TENANT = uuid.UUID("06815117-44cd-484d-a61d-17c231c64aa2")
BLUEPRINT_ID = uuid.UUID("f3aaeba3-5484-4226-b99c-ce9c79f8fe44")
OTHER_BLUEPRINT_ID = uuid.UUID("173ed303-51b9-41d5-99f7-e0448b235594")
SCHEME_VERSION_ID = uuid.UUID("355f5480-623e-46f8-8fd0-34c7b204523b")
APPROVED_AT = datetime(2026, 11, 12, 16, 58, 2, tzinfo=UTC)

STRUCTURE = {
    "paper_code": "SMALL",
    "questions": [
        {
            "question_id": "1",
            "max_marks": 2,
            "excluded": False,
            "subquestions": [],
        },
        {
            "question_id": "2",
            "max_marks": 3,
            "excluded": False,
            "subquestions": [
                {"question_id": "2a", "max_marks": 1, "excluded": False},
                {"question_id": "2b", "max_marks": 2, "excluded": False},
            ],
        },
    ],
    "total_marks": 5,
}


def _row(question_id: str, code: str, marks: int, ordinal: int) -> SimpleNamespace:
    return SimpleNamespace(
        question_id=question_id,
        code=code,
        marks=marks,
        ordinal=ordinal,
        description=f"{code} point for {question_id}",
        required_evidence=None,
        dependencies=[],
        alternatives=[],
        award_conditions=None,
        withhold_conditions=None,
        source_ref={"pdf_page": 3},
        source_page=3,
        source_quote=f"{code} printed",
        expected_answer=None,
    )


def _rows() -> list[SimpleNamespace]:
    return [
        _row("1", "M1", 1, 0),
        _row("1", "A1", 1, 1),
        _row("2a", "B1", 1, 0),
        _row("2b", "M1", 1, 0),
        _row("2b", "A1", 1, 1),
    ]


def _blueprint(structure: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=BLUEPRINT_ID,
        tenant_id=TENANT,
        structure=structure or STRUCTURE,
        total_marks=5,
        status="APPROVED",
        content_hash="0" * 64,
        version=1,
    )


def _version(
    *,
    approved_at: datetime | None = APPROVED_AT,
    approved_against: uuid.UUID | None = BLUEPRINT_ID,
    rules_hash: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=SCHEME_VERSION_ID,
        tenant_id=TENANT,
        criteria_blueprint_version_id=approved_against,
        criteria_approved_at=approved_at,
        criteria_rules_hash=rules_hash,
    )


# -- the endpoints the review screen calls ------------------------------------
def test_the_review_screen_endpoints_exist() -> None:
    """The assignment page calls these; before the workflow they were 404s."""

    routes = {
        (route.path, method)
        for route in documents.router.routes
        for method in getattr(route, "methods", ())
    }

    assert ("/schemes/{version_id}/criteria", "GET") in routes
    assert ("/schemes/{version_id}/criteria/extractions", "POST") in routes
    assert ("/schemes/{version_id}/criteria/approval", "POST") in routes


# -- the prompt that does the transcription -----------------------------------
def test_the_transcription_prompt_is_registered_and_matches_its_hash() -> None:
    registry = PromptRegistry(PROMPTS)

    asset = registry.load("scheme_criteria_extraction")

    assert asset.version == 1
    assert asset.model_role == "primary"
    assert "mark points" in asset.content
    # The registry refuses an asset whose bytes differ from the manifest, so a
    # prompt edit without a version bump fails here rather than in production.
    assert len(asset.content_hash) == 64


def test_the_response_schema_names_every_field_a_row_needs() -> None:
    schema = criteria_response_schema()
    question = schema["properties"]["questions"]["items"]
    criterion = question["properties"]["criteria"]["items"]

    assert schema["required"] == ["questions", "total_marks"]
    assert question["required"] == ["question_id", "criteria"]
    assert {"code", "marks", "description"} <= set(criterion["required"])
    assert {"ordinal", "dependencies", "alternatives", "source_page"} <= set(
        criterion["properties"]
    )


# -- review: the stored rows are the document that gets checked ---------------
def test_stored_rows_can_be_re_validated_as_the_document_they_came_from() -> None:
    report = validate(rows_as_document(_rows()), STRUCTURE)

    assert report.complete, report.problems
    assert report.total_expected == 5
    assert report.total_criteria == 5


def test_a_changed_mark_point_fails_the_re_check_not_only_the_transcription() -> None:
    rows = _rows()
    rows[0].marks = 2  # Q1 would then carry 3 of its 2 marks

    report = validate(rows_as_document(rows), STRUCTURE)

    assert not report.complete
    assert any("'1'" in problem for problem in report.problems)


def test_a_row_for_a_question_the_paper_does_not_have_is_refused() -> None:
    rows = [*_rows(), _row("9", "B1", 1, 0)]

    report = validate(rows_as_document(rows), STRUCTURE)

    assert not report.complete
    assert any("'9'" in problem for problem in report.problems)


# -- the engine's own gate, asked through the workflow ------------------------
def test_approved_rows_against_the_right_blueprint_are_ready() -> None:
    rows = _rows()

    verdict = readiness_for(
        rows,
        _blueprint(),
        _version(rules_hash=criteria_rules_hash(rows, STRUCTURE)),
    )

    assert verdict.ready, verdict.problems
    assert verdict.reason is None


def test_criteria_that_were_never_approved_are_not_ready() -> None:
    verdict = readiness_for(_rows(), _blueprint(), _version(approved_at=None))

    assert not verdict.ready
    assert verdict.reason == REASON_CRITERIA_NOT_APPROVED


def test_criteria_approved_against_another_paper_are_not_ready() -> None:
    rows = _rows()

    verdict = readiness_for(
        rows,
        _blueprint(),
        _version(
            approved_against=OTHER_BLUEPRINT_ID,
            rules_hash=criteria_rules_hash(rows, STRUCTURE),
        ),
    )

    assert not verdict.ready
    assert verdict.reason == REASON_CRITERIA_BLUEPRINT_MISMATCH


def test_rules_changed_after_approval_are_not_ready() -> None:
    rows = _rows()
    approved_digest = criteria_rules_hash(rows, STRUCTURE)
    # The marks still cover the paper; only the approved rule text changed, which
    # is the case a timestamp alone could never detect.
    rows[4].description = "A1 for a differently worded mark point"

    verdict = readiness_for(rows, _blueprint(), _version(rules_hash=approved_digest))

    assert not verdict.ready
    assert verdict.reason == REASON_CRITERIA_RULES_CHANGED


def test_an_approval_without_a_digest_cannot_be_assumed_to_match() -> None:
    verdict = readiness_for(_rows(), _blueprint(), _version(rules_hash=None))

    assert not verdict.ready
    assert "digest" in " ".join(verdict.problems)


# -- an assignment asks the same question before it can exist -----------------
class _Session:
    def __init__(self, objects: dict[tuple[type, uuid.UUID], object]) -> None:
        self.objects = objects

    def get(self, model: type, ident: uuid.UUID):
        return self.objects.get((model, ident))


def test_an_assignment_without_criteria_is_reported_not_ready(monkeypatch) -> None:
    from app.db.models import ExamBlueprintVersion, MarkSchemeVersion
    from app.db.repositories import MarkSchemeRepository

    monkeypatch.setattr(
        MarkSchemeRepository, "list_criteria", lambda self, tenant, version: []
    )
    session = _Session(
        {
            (ExamBlueprintVersion, BLUEPRINT_ID): _blueprint(),
            (MarkSchemeVersion, SCHEME_VERSION_ID): _version(),
        }
    )

    verdict = readiness_of_assignment(
        session,
        tenant_id=TENANT,
        blueprint_version_id=BLUEPRINT_ID,
        scheme_version_id=SCHEME_VERSION_ID,
    )

    assert not verdict.ready
    assert verdict.questions == 3


def test_an_assignment_whose_scheme_is_missing_is_reported_not_ready() -> None:
    verdict = readiness_of_assignment(
        _Session({}),
        tenant_id=TENANT,
        blueprint_version_id=BLUEPRINT_ID,
        scheme_version_id=None,
    )

    assert not verdict.ready
    assert "no blueprint or mark scheme" in " ".join(verdict.problems)


# -- Classroom points must be the paper's own --------------------------------
def test_maximum_points_default_to_the_approved_total() -> None:
    assert reconcile_max_points(91, None) == 91


def test_maximum_points_matching_the_paper_are_accepted() -> None:
    assert reconcile_max_points(91, 91) == 91


def test_maximum_points_that_are_not_the_paper_total_are_refused() -> None:
    with pytest.raises(AppError) as raised:
        reconcile_max_points(91, 6)

    assert raised.value.code is ErrorCode.CONFLICT
    assert "91" in raised.value.message


def test_fractional_maximum_points_are_refused() -> None:
    with pytest.raises(AppError) as raised:
        reconcile_max_points(91, "91.5")

    assert raised.value.code is ErrorCode.CONFLICT
