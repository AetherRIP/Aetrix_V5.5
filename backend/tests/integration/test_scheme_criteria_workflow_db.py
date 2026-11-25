"""The criteria workflow against PostgreSQL.

The decisions are unit-tested; these tests prove what only a real database
shows: a scheme version with no approved criteria cannot become an assignment,
approving reviewed criteria records the digest the marking gate recomputes, a
properly configured assignment can produce a correction job, and a Classroom
coursework's points cannot disagree with the approved paper.

They need a disposable loopback PostgreSQL (``AETRIX_TEST_DATABASE_URL``); no
Google or model call is made here.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import utcnow
from app.core.security import Principal
from app.correction.scheme_criteria import (
    REASON_CRITERIA_NOT_APPROVED,
    REASON_CRITERIA_RULES_CHANGED,
    criteria_rules_hash,
)
from app.db.models import (
    Assignment,
    ClassroomAllocation,
    ClassroomClass,
    ClassroomCourseworkLink,
    ExamBlueprintVersion,
    MarkingCriterion,
    MarkScheme,
    MarkSchemeVersion,
    Submission,
)
from app.jobs.service import JobService
from app.prompts.registry import PromptRegistry
from app.providers.base import LLMResponse
from app.schemas.api import AssignmentCreate, CorrectionCreate
from app.schemas.classroom_integration import CourseworkCreate
from app.services.classroom_assignments import ClassroomCourseworkService
from app.services.exams import AssignmentService
from app.services.provider_calls import ProviderCallResult
from app.services.scheme_criteria import (
    SchemeCriteriaService,
    readiness_of_assignment,
)
from app.storage import build_storage
from sqlalchemy import select

pytestmark = pytest.mark.integration

COURSE_ID = "600100"
PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "prompts"


def _principal(identity) -> Principal:
    return Principal(
        user_id=identity.user_a.id,
        tenant_id=identity.tenant_a.id,
        subject=identity.user_a.subject,
        role="OWNER",
    )


def _approval_only_service(db_session) -> SchemeCriteriaService:
    """The service as the approval screen uses it.

    ``approve`` reads rows, re-validates them and writes the review trail; it
    never calls a provider, so the transcription collaborators are placeholders.
    """

    settings = get_settings()
    return SchemeCriteriaService(
        db_session,
        settings,
        build_storage(settings),
        registry=cast(Any, PromptRegistry(PROMPTS)),
        provider_calls=cast(Any, None),
    )


def _scheme_version_without_approval(db_session, identity, paper) -> MarkSchemeVersion:
    """An approved-document scheme version with rows but no criteria review."""

    scheme = MarkScheme(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        title="Unreviewed scheme",
    )
    db_session.add(scheme)
    db_session.flush()
    version = MarkSchemeVersion(
        tenant_id=identity.tenant_a.id,
        mark_scheme_id=scheme.id,
        version=1,
        status="APPROVED",
        source="FIXTURE",
        content_hash="c" * 64,
        approved_at=utcnow(),
    )
    db_session.add(version)
    db_session.flush()

    source_rows = list(
        db_session.scalars(
            select(MarkingCriterion).where(
                MarkingCriterion.scheme_version_id == paper.scheme_version.id
            )
        )
    )
    db_session.add_all(
        [
            MarkingCriterion(
                tenant_id=identity.tenant_a.id,
                scheme_version_id=version.id,
                blueprint_version_id=paper.blueprint.id,
                question_id=row.question_id,
                code=row.code,
                ordinal=row.ordinal,
                marks=row.marks,
                description=row.description,
                dependencies=list(row.dependencies),
                alternatives=list(row.alternatives),
                source_ref=dict(row.source_ref),
                source_page=row.source_page,
                source_quote=row.source_quote,
            )
            for row in source_rows
        ]
    )
    db_session.commit()
    return version


def _allocated_course(db_session, identity) -> ClassroomClass:
    classroom = ClassroomClass(
        course_id=COURSE_ID,
        name="Year 10 Algebra",
        section="A",
        course_state="ACTIVE",
        verification="VERIFIED",
        source="google_classroom",
        owner_email="central@example.org",
        teacher_name="Central Account",
        synced_at=utcnow(),
        created_by_subject="operator",
    )
    db_session.add(classroom)
    db_session.flush()
    db_session.add(
        ClassroomAllocation(
            classroom_class_id=classroom.id,
            workspace_id=identity.tenant_a.id,
            course_id=COURSE_ID,
            class_name="Year 10 Algebra",
            workspace_name="Alpha",
            status="ACTIVE",
            origin="ALLOCATE",
            allocated_by_subject="operator",
            allocated_at=utcnow(),
        )
    )
    db_session.commit()
    return classroom


# -- the assignment gate ------------------------------------------------------
def test_an_assignment_is_refused_until_its_criteria_are_approved(
    db_session, identity, paper
) -> None:
    version = _scheme_version_without_approval(db_session, identity, paper)

    with pytest.raises(AppError) as raised:
        AssignmentService(db_session).create(
            _principal(identity),
            AssignmentCreate(
                exam_id=paper.exam.id,
                blueprint_version_id=paper.blueprint.id,
                scheme_version_id=version.id,
                name="Never markable",
            ),
        )

    assert raised.value.code is ErrorCode.ASSIGNMENT_NOT_READY
    assert raised.value.details["reason"] == REASON_CRITERIA_NOT_APPROVED


def test_a_scheme_from_another_paper_cannot_configure_an_assignment(
    db_session, identity, paper
) -> None:
    from app.db.models import Exam

    other_exam = Exam(tenant_id=identity.tenant_a.id, title="Another paper")
    db_session.add(other_exam)
    db_session.flush()
    other_scheme = MarkScheme(
        tenant_id=identity.tenant_a.id, exam_id=other_exam.id, title="Other scheme"
    )
    db_session.add(other_scheme)
    db_session.flush()
    other_version = MarkSchemeVersion(
        tenant_id=identity.tenant_a.id,
        mark_scheme_id=other_scheme.id,
        version=1,
        status="APPROVED",
        source="FIXTURE",
        content_hash="d" * 64,
        approved_at=utcnow(),
    )
    db_session.add(other_version)
    db_session.commit()

    with pytest.raises(AppError) as raised:
        AssignmentService(db_session).create(
            _principal(identity),
            AssignmentCreate(
                exam_id=paper.exam.id,
                blueprint_version_id=paper.blueprint.id,
                scheme_version_id=other_version.id,
                name="Mismatched pair",
            ),
        )

    assert raised.value.code is ErrorCode.NOT_FOUND


# -- review and approval ------------------------------------------------------
def test_approving_reviewed_criteria_records_the_rules_it_covered(
    db_session, identity, paper
) -> None:
    version = _scheme_version_without_approval(db_session, identity, paper)

    approved = _approval_only_service(db_session).approve(
        _principal(identity),
        version.id,
        blueprint_version_id=paper.blueprint.id,
        reason="Reviewed every printed mark point against the approved paper.",
    )

    rows = list(
        db_session.scalars(
            select(MarkingCriterion).where(
                MarkingCriterion.scheme_version_id == version.id
            )
        )
    )
    assert approved.criteria_approved_at is not None
    assert approved.criteria_approved_by == identity.user_a.id
    assert approved.criteria_blueprint_version_id == paper.blueprint.id
    assert approved.criteria_blueprint_hash == paper.blueprint.content_hash
    assert approved.criteria_rules_hash == criteria_rules_hash(
        rows, paper.blueprint.structure
    )


def test_criteria_that_do_not_cover_the_named_blueprint_are_refused(
    db_session, identity, paper
) -> None:
    version = _scheme_version_without_approval(db_session, identity, paper)
    other_blueprint = ExamBlueprintVersion(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        version=2,
        status="APPROVED",
        structure={"questions": [], "total_marks": 0},
        total_marks=0,
        content_hash="e" * 64,
        approved_at=utcnow(),
        approval_reason="fixture",
    )
    db_session.add(other_blueprint)
    db_session.commit()

    with pytest.raises(AppError) as raised:
        _approval_only_service(db_session).approve(
            _principal(identity),
            version.id,
            blueprint_version_id=other_blueprint.id,
            reason="Approved against the wrong paper on purpose.",
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert raised.value.details["problems"]


def test_approval_requires_a_reason(db_session, identity, paper) -> None:
    version = _scheme_version_without_approval(db_session, identity, paper)

    with pytest.raises(AppError) as raised:
        _approval_only_service(db_session).approve(
            _principal(identity),
            version.id,
            blueprint_version_id=paper.blueprint.id,
            reason="   ",
        )

    assert raised.value.code is ErrorCode.VALIDATION_ERROR


# -- a properly configured assignment produces a job --------------------------
def test_approved_criteria_let_the_assignment_and_a_correction_job_exist(
    db_session, identity, paper
) -> None:
    version = _scheme_version_without_approval(db_session, identity, paper)
    _approval_only_service(db_session).approve(
        _principal(identity),
        version.id,
        blueprint_version_id=paper.blueprint.id,
        reason="Reviewed and approved against the approved paper.",
    )

    assignment = AssignmentService(db_session).create(
        _principal(identity),
        AssignmentCreate(
            exam_id=paper.exam.id,
            blueprint_version_id=paper.blueprint.id,
            scheme_version_id=version.id,
            name="Workflow assignment",
        ),
    )
    submission = Submission(
        tenant_id=identity.tenant_a.id,
        assignment_id=assignment.id,
        student_ref="student-workflow",
        status="PROCESSED",
        content_hash="f" * 64,
    )
    db_session.add(submission)
    db_session.commit()

    creation = JobService(db_session, get_settings()).create(
        _principal(identity),
        CorrectionCreate(
            assignment_id=assignment.id,
            submission_id=submission.id,
            idempotency_key=f"workflow:{uuid.uuid4()}",
        ),
    )

    assert creation.created is True
    assert creation.job.state == "CREATED"
    assert creation.job.blueprint_version_id == paper.blueprint.id
    assert creation.job.scheme_version_id == version.id


# -- Classroom publication ----------------------------------------------------
def test_coursework_points_must_equal_the_approved_paper_total(
    db_session, identity, paper
) -> None:
    classroom = _allocated_course(db_session, identity)
    service = ClassroomCourseworkService(db_session, get_settings())

    with pytest.raises(AppError) as raised:
        service.create(
            _principal(identity),
            CourseworkCreate(
                assignment_id=paper.assignment.id,
                classroom_class_id=classroom.id,
                title="Smoke coursework",
                max_points=Decimal(6),
            ),
        )

    assert raised.value.code is ErrorCode.CONFLICT
    assert raised.value.details["blueprint_total"] == paper.blueprint.total_marks


def test_coursework_defaults_to_the_approved_paper_total(
    db_session, identity, paper
) -> None:
    classroom = _allocated_course(db_session, identity)

    link = ClassroomCourseworkService(db_session, get_settings()).create(
        _principal(identity),
        CourseworkCreate(
            assignment_id=paper.assignment.id,
            classroom_class_id=classroom.id,
            title="Configured coursework",
        ),
    )

    assert link.max_points == paper.blueprint.total_marks


def test_a_coursework_is_refused_before_its_criteria_are_approved(
    db_session, identity, paper
) -> None:
    version = _scheme_version_without_approval(db_session, identity, paper)
    assignment = Assignment(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=version.id,
        name="Unmarkable assignment",
        completion_threshold=0.8,
        review_mode="BALANCED",
    )
    db_session.add(assignment)
    db_session.commit()
    classroom = _allocated_course(db_session, identity)

    with pytest.raises(AppError) as raised:
        ClassroomCourseworkService(db_session, get_settings()).create(
            _principal(identity),
            CourseworkCreate(
                assignment_id=assignment.id,
                classroom_class_id=classroom.id,
                title="Should not publish",
            ),
        )

    assert raised.value.code is ErrorCode.ASSIGNMENT_NOT_READY
    assert raised.value.details["reason"] == REASON_CRITERIA_NOT_APPROVED


def test_a_stored_coursework_is_refused_at_publication_when_its_criteria_lapse(
    db_session, identity, paper
) -> None:
    """The publish step asks the gate again, not just the draft step.

    A coursework drafted while the criteria were approved must not reach Google
    after that approval lapses.  The refusal happens before any token is
    fetched, so nothing is published and the link stays a draft.
    """

    classroom = _allocated_course(db_session, identity)
    service = ClassroomCourseworkService(db_session, get_settings())
    created = service.create(
        _principal(identity),
        CourseworkCreate(
            assignment_id=paper.assignment.id,
            classroom_class_id=classroom.id,
            title="Lapsed coursework",
        ),
    )
    version = db_session.get(MarkSchemeVersion, paper.scheme_version.id)
    assert version is not None
    version.criteria_approved_at = None
    db_session.commit()

    with pytest.raises(AppError) as raised:
        service.publish(_principal(identity), created.id)

    assert raised.value.code is ErrorCode.ASSIGNMENT_NOT_READY
    assert raised.value.details["reason"] == REASON_CRITERIA_NOT_APPROVED
    stored = db_session.get(ClassroomCourseworkLink, created.id)
    assert stored is not None
    assert stored.state == "DRAFT"
    assert stored.coursework_id is None


def test_a_stored_coursework_whose_points_drifted_is_refused_at_publication(
    db_session, identity, paper
) -> None:
    classroom = _allocated_course(db_session, identity)
    service = ClassroomCourseworkService(db_session, get_settings())
    created = service.create(
        _principal(identity),
        CourseworkCreate(
            assignment_id=paper.assignment.id,
            classroom_class_id=classroom.id,
            title="Drifted coursework",
        ),
    )
    stored = db_session.get(ClassroomCourseworkLink, created.id)
    assert stored is not None
    stored.max_points = Decimal(6)
    db_session.commit()

    with pytest.raises(AppError) as raised:
        service._require_matching_points(stored, paper.blueprint.total_marks)

    assert raised.value.code is ErrorCode.CONFLICT


# -- extraction: only a transcription that covers the paper is stored ---------
def _criteria_payload(*, description_tag: str = "") -> dict[str, Any]:
    """A complete transcription of the fixture paper's seven mark points."""

    def point(question_id: str, code: str, ordinal: int, marks: int) -> dict[str, Any]:
        return {
            "code": code,
            "marks": marks,
            "ordinal": ordinal,
            "description": f"{description_tag}{code} for {question_id}",
            "expected_answer": f"printed answer for {question_id} {code}",
        }

    return {
        "questions": [
            {
                "question_id": "1a",
                "criteria": [point("1a", "M1", 0, 1), point("1a", "A1", 1, 1)],
            },
            {
                "question_id": "1b",
                "criteria": [
                    point("1b", "M1", 0, 1),
                    point("1b", "M2", 1, 1),
                    point("1b", "A1", 2, 1),
                ],
            },
            {
                "question_id": "2",
                "criteria": [point("2", "M1", 0, 2), point("2", "A1", 1, 3)],
            },
        ],
        "total_marks": 10,
    }


class _FakeProviderCalls:
    """The service's provider seam, answered from a fixture instead of a model."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []
        self.asset = PromptRegistry(PROMPTS).load("scheme_criteria_extraction")

    def call(self, **kwargs: Any) -> ProviderCallResult:
        self.calls.append(kwargs)
        return ProviderCallResult(
            response=LLMResponse(
                text=json.dumps(self.payload),
                model="fixture-model",
                latency_ms=1,
            ),
            usage_id=uuid.uuid4(),
            prompt=self.asset,
            prompt_version_id=uuid.uuid4(),
            cost_usd=Decimal("0"),
            provider_name="fixture",
        )


class _StubDocuments:
    """A processed scheme document with no page images to render."""

    def get(self, tenant_id, document_id):
        return SimpleNamespace(
            id=document_id, tenant_id=tenant_id, kind="MARK_SCHEME", status="PROCESSED"
        )

    def page_images(self, tenant_id, document_id):
        return []


def _extraction_service(db_session, payload: dict[str, Any]):
    settings = get_settings()
    provider = _FakeProviderCalls(payload)
    service = SchemeCriteriaService(
        db_session,
        settings,
        build_storage(settings),
        registry=PromptRegistry(PROMPTS),
        provider_calls=cast(Any, provider),
    )
    service.documents = cast(Any, _StubDocuments())
    return service, provider


def _unreviewed_scheme_with_document(db_session, identity, paper) -> MarkSchemeVersion:
    scheme = MarkScheme(
        tenant_id=identity.tenant_a.id,
        exam_id=paper.exam.id,
        title="Scanned scheme",
        document_id=uuid.uuid4(),
    )
    db_session.add(scheme)
    db_session.flush()
    version = MarkSchemeVersion(
        tenant_id=identity.tenant_a.id,
        mark_scheme_id=scheme.id,
        version=1,
        status="APPROVED",
        source="UPLOAD",
        content_hash="1" * 64,
        approved_at=utcnow(),
    )
    db_session.add(version)
    db_session.commit()
    return version


def _stored_rows(db_session, version: MarkSchemeVersion) -> list[MarkingCriterion]:
    return list(
        db_session.scalars(
            select(MarkingCriterion).where(
                MarkingCriterion.scheme_version_id == version.id
            )
        )
    )


def test_extraction_stores_the_rows_that_cover_the_paper(
    db_session, identity, paper
) -> None:
    version = _unreviewed_scheme_with_document(db_session, identity, paper)
    service, provider = _extraction_service(db_session, _criteria_payload())

    result = service.extract(
        _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
    )

    assert len(provider.calls) == 1
    # The registered prompt is what was asked for, not an inline string.
    assert provider.calls[0]["prompt_id"] == "scheme_criteria_extraction"
    assert provider.calls[0]["purpose"] == "SCHEME_CRITERIA_EXTRACTION"
    stored = _stored_rows(db_session, version)
    assert len(stored) == 7
    by_question: dict[str, int] = {}
    for row in stored:
        by_question[row.question_id] = by_question.get(row.question_id, 0) + row.marks
    assert by_question == {"1a": 2, "1b": 3, "2": 5}
    # The scheme's printed answer survives transcription; it is part of the
    # rules the digest and the marking comparison use.
    answers = {(row.question_id, row.code): row.expected_answer for row in stored}
    assert answers[("1a", "M1")] == "printed answer for 1a M1"
    assert all(answers.values())
    assert result.coverage.complete
    # Transcription is not approval: the review trail stays empty.
    assert version.criteria_approved_at is None
    assert version.criteria_rules_hash is None


def test_an_incomplete_extraction_stores_nothing(db_session, identity, paper) -> None:
    version = _unreviewed_scheme_with_document(db_session, identity, paper)
    payload = _criteria_payload()
    payload["questions"] = payload["questions"][:-1]  # question 2 is missing
    service, provider = _extraction_service(db_session, payload)

    with pytest.raises(AppError) as raised:
        service.extract(
            _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
        )

    assert raised.value.code is ErrorCode.EXTRACTION_INVALID
    assert raised.value.details["problems"]
    assert provider.calls  # the transcription was attempted
    assert _stored_rows(db_session, version) == []


def test_a_refused_re_extraction_leaves_the_approved_rows_untouched(
    db_session, identity, paper
) -> None:
    version = _unreviewed_scheme_with_document(db_session, identity, paper)
    service, _ = _extraction_service(db_session, _criteria_payload())
    service.extract(
        _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
    )
    _approval_only_service(db_session).approve(
        _principal(identity),
        version.id,
        blueprint_version_id=paper.blueprint.id,
        reason="Reviewed the printed mark points.",
    )
    before = sorted(row.id for row in _stored_rows(db_session, version))

    payload = _criteria_payload(description_tag="second pass ")
    payload["questions"] = payload["questions"][:-1]
    bad_service, _ = _extraction_service(db_session, payload)
    with pytest.raises(AppError) as raised:
        bad_service.extract(
            _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
        )

    assert raised.value.code is ErrorCode.EXTRACTION_INVALID
    db_session.refresh(version)
    assert sorted(row.id for row in _stored_rows(db_session, version)) == before
    assert version.criteria_approved_at is not None
    assert readiness_of_assignment(
        db_session,
        tenant_id=identity.tenant_a.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=version.id,
    ).ready


def test_re_extraction_replaces_the_rows_and_clears_the_approval(
    db_session, identity, paper
) -> None:
    version = _unreviewed_scheme_with_document(db_session, identity, paper)
    service, _ = _extraction_service(db_session, _criteria_payload())
    service.extract(
        _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
    )
    _approval_only_service(db_session).approve(
        _principal(identity),
        version.id,
        blueprint_version_id=paper.blueprint.id,
        reason="Reviewed the printed mark points.",
    )
    before = sorted(row.id for row in _stored_rows(db_session, version))

    second, _ = _extraction_service(
        db_session, _criteria_payload(description_tag="re-transcribed ")
    )
    second.extract(
        _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
    )

    rows = _stored_rows(db_session, version)
    assert len(rows) == 7
    # Replaced, not appended: the old identities are gone.
    assert not (set(before) & {row.id for row in rows})
    assert all(row.description.startswith("re-transcribed ") for row in rows)
    db_session.refresh(version)
    assert version.criteria_approved_at is None
    assert version.criteria_approved_by is None
    assert version.criteria_approval_reason is None
    assert version.criteria_blueprint_version_id is None
    assert version.criteria_rules_hash is None
    verdict = readiness_of_assignment(
        db_session,
        tenant_id=identity.tenant_a.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=version.id,
    )
    assert not verdict.ready
    assert verdict.reason == REASON_CRITERIA_NOT_APPROVED


# -- a changed rule invalidates the approval ----------------------------------
def test_a_criterion_changed_after_approval_blocks_the_assignment(
    db_session, identity, paper
) -> None:
    version = _unreviewed_scheme_with_document(db_session, identity, paper)
    service, _ = _extraction_service(db_session, _criteria_payload())
    service.extract(
        _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
    )
    _approval_only_service(db_session).approve(
        _principal(identity),
        version.id,
        blueprint_version_id=paper.blueprint.id,
        reason="Reviewed the printed mark points.",
    )
    row = _stored_rows(db_session, version)[0]
    row.description = "edited after the review"
    db_session.commit()

    verdict = readiness_of_assignment(
        db_session,
        tenant_id=identity.tenant_a.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=version.id,
    )
    assert not verdict.ready
    assert verdict.reason == REASON_CRITERIA_RULES_CHANGED

    with pytest.raises(AppError) as raised:
        AssignmentService(db_session).create(
            _principal(identity),
            AssignmentCreate(
                exam_id=paper.exam.id,
                blueprint_version_id=paper.blueprint.id,
                scheme_version_id=version.id,
                name="Edited criteria",
            ),
        )

    assert raised.value.code is ErrorCode.ASSIGNMENT_NOT_READY
    assert raised.value.details["reason"] == REASON_CRITERIA_RULES_CHANGED


# -- tenant boundaries --------------------------------------------------------
def _other_principal(identity) -> Principal:
    return Principal(
        user_id=identity.user_b.id,
        tenant_id=identity.tenant_b.id,
        subject=identity.user_b.subject,
        role="OWNER",
    )


def test_another_tenant_cannot_read_or_approve_the_criteria(
    db_session, identity, paper
) -> None:
    version = _unreviewed_scheme_with_document(db_session, identity, paper)
    service, _ = _extraction_service(db_session, _criteria_payload())
    service.extract(
        _principal(identity), version.id, blueprint_version_id=paper.blueprint.id
    )

    # The rows are tenant-scoped, so the other workspace reads no criteria at
    # all rather than reading this workspace's.
    assert service.criteria(identity.tenant_b.id, version.id) == []
    with pytest.raises(AppError) as get_refused:
        service.get_version(identity.tenant_b.id, version.id)
    with pytest.raises(AppError) as approve_refused:
        _approval_only_service(db_session).approve(
            _other_principal(identity),
            version.id,
            blueprint_version_id=paper.blueprint.id,
            reason="Approved from the wrong workspace.",
        )

    for raised in (get_refused, approve_refused):
        assert raised.value.code is ErrorCode.NOT_FOUND
    db_session.refresh(version)
    assert version.criteria_approved_at is None
    assert len(_stored_rows(db_session, version)) == 7
    assert service.criteria(identity.tenant_a.id, version.id)


def test_another_tenant_cannot_extract_against_a_foreign_blueprint(
    db_session, identity, paper
) -> None:
    version = _unreviewed_scheme_with_document(db_session, identity, paper)
    service, provider = _extraction_service(db_session, _criteria_payload())

    with pytest.raises(AppError) as raised:
        service.extract(
            _other_principal(identity),
            version.id,
            blueprint_version_id=paper.blueprint.id,
        )

    assert raised.value.code is ErrorCode.NOT_FOUND
    # Refused before any provider request and before any row was written.
    assert provider.calls == []
    assert _stored_rows(db_session, version) == []


def test_another_tenant_cannot_build_an_assignment_or_coursework(
    db_session, identity, paper
) -> None:
    classroom = _allocated_course(db_session, identity)

    with pytest.raises(AppError) as assignment_refused:
        AssignmentService(db_session).create(
            _other_principal(identity),
            AssignmentCreate(
                exam_id=paper.exam.id,
                blueprint_version_id=paper.blueprint.id,
                scheme_version_id=paper.scheme_version.id,
                name="Foreign assignment",
            ),
        )
    with pytest.raises(AppError) as coursework_refused:
        ClassroomCourseworkService(db_session, get_settings()).create(
            _other_principal(identity),
            CourseworkCreate(
                assignment_id=paper.assignment.id,
                classroom_class_id=classroom.id,
                title="Foreign coursework",
            ),
        )

    assert assignment_refused.value.code is ErrorCode.NOT_FOUND
    assert coursework_refused.value.code is ErrorCode.NOT_FOUND
