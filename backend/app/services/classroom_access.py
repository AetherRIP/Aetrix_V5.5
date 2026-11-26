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
from ..db.models import (
    ClassroomAllocation,
    ClassroomClass,
    ClassroomClassAssignment,
    PlatformAuditEvent,
)

#: Roles that may create, publish, synchronise and re-mark inside their workspace.
TEACHING_ROLES = frozenset({"OWNER", "ADMIN", "TEACHER", "PLATFORM_OWNER"})
#: Roles that manage every class and the assignments to those classes.
CLASS_ADMIN_ROLES = frozenset({"OWNER", "ADMIN", "PLATFORM_OWNER"})
#: Roles that must be explicitly assigned to a class to see it.
ASSIGNABLE_ROLES = frozenset({"TEACHER", "REVIEWER"})
#: Reviewing an assigned result is a REVIEWER act.  Final approval and grade
#: publication are teaching acts and deliberately do not share this set.
REVIEW_ROLES = frozenset({"OWNER", "ADMIN", "TEACHER", "REVIEWER", "PLATFORM_OWNER"})


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
        "Reviewing a result needs a reviewer, teacher or administrator role.",
    )


def ensure_grade_approver(principal: Principal) -> None:
    """Final approval and publication are teacher/admin acts, not reviewer acts."""

    if principal.role in TEACHING_ROLES or principal.is_platform_admin:
        return
    raise AppError(
        ErrorCode.FORBIDDEN,
        "Approving a result or publishing a grade requires a teacher, "
        "administrator or owner role.",
    )


def is_class_manager(principal: Principal) -> bool:
    return principal.is_platform_admin or principal.role in CLASS_ADMIN_ROLES


def allowed_course_ids(
    session: Session, principal: Principal
) -> set[str] | None:
    """The courses this principal may read, or ``None`` for a manager.

    A manager keeps workspace-wide read and administration.  A TEACHER or
    REVIEWER receives only the courses explicitly assigned to their user row.
    A VIEWER has no class assignment and therefore receives an empty set; the
    class list and every direct read stay closed to it.
    """

    if is_class_manager(principal):
        return None
    if principal.role not in ASSIGNABLE_ROLES:
        return set()
    return set(
        session.scalars(
            select(ClassroomAllocation.course_id)
            .join(
                ClassroomClassAssignment,
                ClassroomClassAssignment.allocation_id == ClassroomAllocation.id,
            )
            .where(
                ClassroomAllocation.workspace_id == principal.tenant_id,
                ClassroomAllocation.status == "ACTIVE",
                ClassroomClassAssignment.workspace_id == principal.tenant_id,
                ClassroomClassAssignment.user_id == principal.user_id,
            )
        )
    )


def require_course_access(
    session: Session,
    principal: Principal,
    *,
    course_id: str | None = None,
    classroom_class_id: uuid.UUID | None = None,
) -> tuple[ClassroomAllocation, ClassroomClass]:
    """An allocation this principal may access, or a 404-equivalent refusal.

    The lookup is deliberately the same as an absent course: a user cannot
    learn that an unassigned course exists in the same workspace.
    """

    allocation, classroom = require_allocation(
        session,
        principal.tenant_id,
        course_id=course_id,
        classroom_class_id=classroom_class_id,
    )
    if is_class_manager(principal):
        return allocation, classroom
    if principal.role not in ASSIGNABLE_ROLES:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "That Classroom course is not assigned to you.",
        )
    assigned = session.scalar(
        select(ClassroomClassAssignment.id).where(
            ClassroomClassAssignment.allocation_id == allocation.id,
            ClassroomClassAssignment.workspace_id == principal.tenant_id,
            ClassroomClassAssignment.user_id == principal.user_id,
        )
    )
    if assigned is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "That Classroom course is not assigned to you.",
        )
    return allocation, classroom


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
