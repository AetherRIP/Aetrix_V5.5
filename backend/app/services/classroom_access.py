"""Shared authorisation helpers for the Classroom integration.

Tenant isolation is a query condition, never a client-supplied identifier.  A
course that is not allocated to the caller's workspace is reported as missing,
so a teacher cannot learn that another workspace owns it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.logging import request_id_var
from ..core.security import Principal, platform_authority
from ..db.models import ClassroomAllocation, ClassroomClass, PlatformAuditEvent

#: Roles that may create, publish and synchronise inside their workspace.
TEACHING_ROLES = frozenset({"OWNER", "ADMIN", "TEACHER", "PLATFORM_OWNER"})
#: Roles that may approve a final result or authorise a grade publication.
REVIEW_ROLES = frozenset({"OWNER", "ADMIN", "REVIEWER", "PLATFORM_OWNER"})


def ensure_teaching(principal: Principal) -> None:
    if principal.role in TEACHING_ROLES or principal.is_platform_admin:
        return
    raise AppError(
        ErrorCode.FORBIDDEN,
        "This Classroom action needs a teaching role in the workspace.",
    )


def ensure_reviewer(principal: Principal) -> None:
    if principal.role in REVIEW_ROLES or principal.is_platform_admin:
        return
    raise AppError(
        ErrorCode.FORBIDDEN,
        "Approving a result or publishing a grade needs a reviewer or "
        "administrator role.",
    )


def platform_audit(
    session: Session,
    actor: Principal,
    action: str,
    detail: dict[str, Any],
    *,
    target: str,
) -> None:
    """Append a platform-level event for an administrative Classroom action."""

    session.add(
        PlatformAuditEvent(
            actor_user_id=actor.user_id,
            actor_subject=actor.subject,
            actor_platform_role=platform_authority(actor) or actor.role,
            action=action,
            target_subject=target,
            target_email=None,
            detail=detail,
            request_id=request_id_var.get(),
            created_at=utcnow(),
        )
    )


def require_allocation(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    course_id: str | None = None,
    classroom_class_id: uuid.UUID | None = None,
) -> tuple[ClassroomAllocation, ClassroomClass]:
    """The ACTIVE allocation of a course to this workspace, or a 404."""

    if course_id is None and classroom_class_id is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "A course must be named."
        )
    statement = (
        select(ClassroomAllocation, ClassroomClass)
        .join(
            ClassroomClass,
            ClassroomAllocation.classroom_class_id == ClassroomClass.id,
        )
        .where(
            ClassroomAllocation.workspace_id == tenant_id,
            ClassroomAllocation.status == "ACTIVE",
        )
    )
    if course_id is not None:
        statement = statement.where(ClassroomAllocation.course_id == course_id)
    if classroom_class_id is not None:
        statement = statement.where(
            ClassroomAllocation.classroom_class_id == classroom_class_id
        )
    row = session.execute(statement).first()
    if row is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "That Classroom course is not allocated to this workspace.",
        )
    allocation, classroom = row
    return allocation, classroom
