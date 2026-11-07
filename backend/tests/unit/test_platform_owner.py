"""Platform ownership as an engine role.

These checks are pure: they exercise the role vocabulary and the fleet gate
without a database, which is the part of the owner work that can be verified on
a machine with no PostgreSQL.
"""

from __future__ import annotations

import uuid

import pytest
from app.api.v1.admin_providers import FLEET_ADMIN_ROLES, require_fleet_admin
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal


def _principal(role: str) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        subject="owner-subject",
        role=role,
    )


def test_fleet_administration_admits_the_platform_owner() -> None:
    assert frozenset({"ADMIN", "PLATFORM_OWNER"}) == FLEET_ADMIN_ROLES


def test_a_platform_owner_passes_the_fleet_gate() -> None:
    principal = require_fleet_admin(_principal("PLATFORM_OWNER"))
    assert principal.role == "PLATFORM_OWNER"


def test_a_workspace_owner_does_not_administer_the_platform_fleet() -> None:
    with pytest.raises(AppError) as error:
        require_fleet_admin(_principal("OWNER"))
    assert error.value.code is ErrorCode.FORBIDDEN


def test_platform_ownership_keeps_the_workspace_capabilities() -> None:
    principal = _principal("PLATFORM_OWNER")
    assert principal.is_reviewer is True
    assert principal.can_manage_exams is True


def test_the_other_roles_are_unchanged() -> None:
    assert _principal("REVIEWER").can_manage_exams is False
    assert _principal("VIEWER").is_reviewer is False
    assert _principal("TEACHER").can_manage_exams is True
