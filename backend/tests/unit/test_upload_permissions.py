"""Uploading is narrower than managing an exam.

A reviewer may feed a script or a scheme into the engine so marking continues
while Google Classroom is unavailable. Everything else about an exam — creating
it, assigning work, approving a scheme — stays with a teacher or administrator.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal, ensure_exam_manager, ensure_uploader

TENANT_ID = uuid.UUID("06815117-44cd-484d-a61d-17c231c64aa2")


def _principal(role: str) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        subject=f"subject-{role.lower()}",
        role=role,
    )


@pytest.mark.parametrize("role", ["OWNER", "ADMIN", "TEACHER", "PLATFORM_OWNER", "REVIEWER"])
def test_teachers_admins_and_reviewers_may_upload(role: str) -> None:
    ensure_uploader(_principal(role))


@pytest.mark.parametrize("role", ["VIEWER", "UNASSIGNED"])
def test_a_read_only_account_may_not_upload(role: str) -> None:
    with pytest.raises(AppError) as raised:
        ensure_uploader(_principal(role))

    assert raised.value.code == ErrorCode.FORBIDDEN
    assert raised.value.message == "This action requires a teacher, admin or reviewer role."


def test_a_reviewer_may_not_manage_exams() -> None:
    reviewer = _principal("REVIEWER")

    assert reviewer.can_upload_documents is True
    assert reviewer.can_manage_exams is False
    with pytest.raises(AppError) as raised:
        ensure_exam_manager(reviewer)

    assert raised.value.code == ErrorCode.FORBIDDEN
    assert raised.value.message == "This action requires a teacher or admin role."


def test_a_viewer_holds_neither_permission() -> None:
    viewer = _principal("VIEWER")

    assert viewer.can_upload_documents is False
    assert viewer.can_manage_exams is False
