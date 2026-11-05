from __future__ import annotations

import pytest
from app.core.security import Principal
from app.schemas.blueprint import BlueprintPut, BlueprintStructure
from app.schemas.documents import BlueprintOverrideCreate, BlueprintOverrideOperation
from app.services.blueprint_overrides import BlueprintOverrideService
from app.services.exams import BlueprintService
from sqlalchemy.exc import DBAPIError


def _actor(identity) -> Principal:
    return Principal(
        user_id=identity.user_a.id,
        tenant_id=identity.tenant_a.id,
        subject=identity.user_a.subject,
        role=identity.user_a.role,
    )


def test_override_creates_a_new_draft_and_leaves_the_approved_base_untouched(
    paper, identity, db_session
) -> None:
    service = BlueprintOverrideService(db_session)
    result = service.create(
        _actor(identity),
        paper.exam.id,
        BlueprintOverrideCreate(
            base_version_id=paper.blueprint.id,
            rationale="The mark scheme changed after publication.",
            operations=[
                BlueprintOverrideOperation(op="set_question_marks", question_id="2", max_marks=7)
            ],
        ),
    )
    assert result.base.id == paper.blueprint.id
    assert result.base.status == "APPROVED"
    assert result.base.structure == paper.blueprint.structure
    assert result.result.status == "DRAFT"
    assert result.result.version == 2
    assert result.result.total_marks == 12
    assert result.override.result_version_id == result.result.id
    assert result.override.rationale

    approved = BlueprintService(db_session).put(
        _actor(identity),
        paper.exam.id,
        BlueprintPut(
            structure=BlueprintStructure.model_validate(result.result.structure),
            approve=True,
            reason="approved override",
        ),
    )
    assert approved.id == result.result.id
    assert approved.status == "APPROVED"
    db_session.refresh(paper.blueprint)
    assert paper.blueprint.status == "SUPERSEDED"


def test_approved_blueprint_cannot_be_mutated_in_the_database(paper, db_session) -> None:
    original = dict(paper.blueprint.structure)
    paper.blueprint.structure = {"questions": [], "total_marks": 999}
    with pytest.raises(DBAPIError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    db_session.refresh(paper.blueprint)
    assert paper.blueprint.structure == original
    assert paper.blueprint.status == "APPROVED"


def test_approved_blueprint_cannot_return_to_draft(paper, db_session) -> None:
    paper.blueprint.status = "DRAFT"
    with pytest.raises(DBAPIError, match="cannot return to"):
        db_session.commit()
    db_session.rollback()
    db_session.refresh(paper.blueprint)
    assert paper.blueprint.status == "APPROVED"


def test_override_cannot_exclude_without_a_reason(paper, identity, db_session) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BlueprintOverrideCreate(
            base_version_id=paper.blueprint.id,
            rationale="bad",
            operations=[BlueprintOverrideOperation(op="exclude_question", question_id="2")],
        )
