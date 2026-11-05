from __future__ import annotations

import pytest
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal
from app.schemas.api import ExamCreate
from app.schemas.blueprint import BlueprintPut, BlueprintStructure
from app.services.exams import BlueprintService, ExamService


def principal_for(user) -> Principal:
    return Principal(
        user_id=user.id, tenant_id=user.tenant_id, subject=user.subject, role=user.role
    )


def structure(marks: int = 4) -> BlueprintStructure:
    return BlueprintStructure.model_validate(
        {"questions": [{"question_id": "1", "max_marks": marks}], "total_marks": marks}
    )


def test_draft_then_approval_is_the_only_path(identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    exam = ExamService(db_session).create(actor, ExamCreate(title="Paper"))
    service = BlueprintService(db_session)

    draft = service.put(actor, exam.id, BlueprintPut(structure=structure(4)))
    assert draft.status == "DRAFT"
    assert draft.version == 1

    with pytest.raises(AppError) as error:
        service.put(
            actor,
            exam.id,
            BlueprintPut(structure=structure(5), approve=True, reason="different content"),
        )
    assert error.value.code is ErrorCode.CONFLICT

    approved = service.put(
        actor,
        exam.id,
        BlueprintPut(structure=structure(4), approve=True, reason="checked"),
    )
    assert approved.status == "APPROVED"
    assert approved.approval_reason == "checked"


def test_approving_a_new_version_supersedes_the_old_one(identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    exam = ExamService(db_session).create(actor, ExamCreate(title="Versioned paper"))
    service = BlueprintService(db_session)

    first = service.put(actor, exam.id, BlueprintPut(structure=structure(4)))
    first = service.put(
        actor, exam.id, BlueprintPut(structure=structure(4), approve=True, reason="v1")
    )
    assert first.status == "APPROVED"

    second = service.put(actor, exam.id, BlueprintPut(structure=structure(6)))
    assert second.version == 2
    assert second.status == "DRAFT"

    # The approved version remains the latest approved contract while a new
    # draft exists.
    latest = service.get_latest(identity.tenant_a.id, exam.id)
    assert latest.id == first.id
    assert latest.status == "APPROVED"

    second = service.put(
        actor, exam.id, BlueprintPut(structure=structure(6), approve=True, reason="v2")
    )
    assert second.status == "APPROVED"
    db_session.refresh(first)
    assert first.status == "SUPERSEDED"
    assert service.get_latest(identity.tenant_a.id, exam.id).id == second.id


def test_blueprint_is_tenant_scoped(identity, db_session) -> None:
    actor = principal_for(identity.user_a)
    exam = ExamService(db_session).create(actor, ExamCreate(title="Private paper"))
    BlueprintService(db_session).put(actor, exam.id, BlueprintPut(structure=structure(4)))

    with pytest.raises(AppError) as error:
        BlueprintService(db_session).get_latest(identity.tenant_b.id, exam.id)
    assert error.value.code is ErrorCode.NOT_FOUND


def test_approval_requires_a_reason_at_the_schema_level() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BlueprintPut.model_validate(
            {"structure": structure(3).model_dump(mode="json"), "approve": True}
        )
