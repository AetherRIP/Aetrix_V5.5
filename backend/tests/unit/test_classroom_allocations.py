"""Pure tests for Classroom allocation contracts and capability reporting."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.config import ClassroomSettings
from app.schemas.classroom_allocations import (
    AllocationReassign,
    ClassroomClassCreate,
)
from app.services.classroom_allocations import ClassroomAllocationService
from pydantic import SecretStr, ValidationError


def test_a_course_must_be_explicitly_attested() -> None:
    with pytest.raises(ValidationError):
        ClassroomClassCreate.model_validate(
            {"course_id": "600100", "name": "10A Maths", "attested": False}
        )


def test_a_course_id_cannot_contain_url_or_whitespace_characters() -> None:
    for course_id in ("https://classroom.google.com/c/1", "600 100", ""):
        with pytest.raises(ValidationError):
            ClassroomClassCreate.model_validate(
                {"course_id": course_id, "name": "10A Maths", "attested": True}
            )


def test_a_valid_course_is_trimmed() -> None:
    payload = ClassroomClassCreate.model_validate(
        {
            "course_id": " 600100 ",
            "name": "  10A Maths ",
            "section": "  ",
            "attested": True,
        }
    )
    assert payload.course_id == "600100"
    assert payload.name == "10A Maths"
    assert payload.section is None


def test_reassignment_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        AllocationReassign(workspace_id=uuid4(), reason="  ")
    with pytest.raises(ValidationError):
        AllocationReassign(workspace_id=uuid4(), reason="x")


def test_capability_reports_discovery_only_when_it_is_configured() -> None:
    # Unconfigured: the routes exist, but the screen must say they cannot run.
    capability = ClassroomAllocationService(None).capability()  # type: ignore[arg-type]
    assert capability.allocation_available is True
    assert capability.discovery_configured is False
    assert capability.verification == "UNVERIFIED"
    assert "No Google Classroom OAuth client" in capability.reason
    assert "CLASSROOM_NOT_CONFIGURED" in capability.reason
    discovery = next(
        operation
        for operation in capability.operations
        if operation.name == "discover classes from Google Classroom"
    )
    assert discovery.supported is True
    assert "classroom.courses.readonly" in discovery.note

    configured_settings = SimpleNamespace(
        classroom=ClassroomSettings(
            client_id="client-id.apps.googleusercontent.com",
            client_secret=SecretStr("client-secret"),
            redirect_uri="http://127.0.0.1:3000/auth/classroom",
        )
    )
    configured = ClassroomAllocationService(
        None, configured_settings  # type: ignore[arg-type]
    ).capability()
    assert configured.discovery_configured is True
    assert "No Google Classroom OAuth client" not in configured.reason
    assert "course sync" in configured.reason
    assert "VERIFIED" in configured.reason
