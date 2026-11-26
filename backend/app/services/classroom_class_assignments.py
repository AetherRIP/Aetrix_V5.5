"""Explicit class assignments for Classroom teachers and reviewers.

This is deliberately separate from workspace membership and from the platform
allocation of a Google course.  A manager assigns one workspace TEACHER or
REVIEWER to one ACTIVE allocation; removing the row is immediate and audited.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal
from ..db.models import (
    ClassroomAllocation,
    ClassroomClass,
    ClassroomClassAssignment,
    User,
)
from ..schemas.classroom_class_assignments import (
    ClassroomClassAssignmentCreate,
    ClassroomClassAssignmentRead,
)
from .classroom_access import is_class_manager, require_course_access

ASSIGNABLE_ROLES = frozenset({"TEACHER", "REVIEWER"})


class ClassroomClassAssignmentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditService(session)

    def _manager(self, principal: Principal) -> None:
        if not is_class_manager(principal):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only a workspace owner or administrator may manage class "
                "assignments.",
            )

    @staticmethod
    def _label(user: User) -> str | None:
        return user.display_name or user.email or user.subject

    def _read(
        self, row: ClassroomClassAssignment, user: User, assigned_by: User | None
    ) -> ClassroomClassAssignmentRead:
        allocation, classroom = self.session.execute(
            select(ClassroomAllocation, ClassroomClass)
            .join(
                ClassroomClass,
                ClassroomAllocation.classroom_class_id == ClassroomClass.id,
            )
            .where(ClassroomAllocation.id == row.allocation_id)
        ).one()
        return ClassroomClassAssignmentRead(
            id=row.id,
            allocation_id=allocation.id,
            classroom_class_id=classroom.id,
            course_id=allocation.course_id,
            class_name=allocation.class_name,
            user_id=user.id,
            user_label=self._label(user),
            user_email=user.email,
            user_role=user.role,
            assigned_by_label=self._label(assigned_by) if assigned_by else None,
            assigned_at=row.assigned_at,
        )

    def list_for_course(
        self, principal: Principal, workspace_id: uuid.UUID, course_id: str
    ) -> list[ClassroomClassAssignmentRead]:
        self._manager(principal)
        if workspace_id != principal.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        allocation, _classroom = require_course_access(
            self.session, principal, course_id=course_id
        )
        rows = self.session.execute(
            select(ClassroomClassAssignment, User)
            .join(User, ClassroomClassAssignment.user_id == User.id)
            .where(
                ClassroomClassAssignment.workspace_id == principal.tenant_id,
                ClassroomClassAssignment.allocation_id == allocation.id,
                User.tenant_id == principal.tenant_id,
            )
            .order_by(User.display_name.asc(), User.email.asc(), User.id.asc())
        ).all()
        return [
            self._read(
                row,
                user,
                self.session.get(User, row.assigned_by_user_id)
                if row.assigned_by_user_id
                else None,
            )
            for row, user in rows
        ]

    def create(
        self,
        principal: Principal,
        workspace_id: uuid.UUID,
        course_id: str,
        payload: ClassroomClassAssignmentCreate,
    ) -> ClassroomClassAssignmentRead:
        self._manager(principal)
        if workspace_id != principal.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        allocation, _classroom = require_course_access(
            self.session, principal, course_id=course_id
        )
        if payload.user_id == principal.user_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "You cannot assign a class to yourself.",
            )
        target = self.session.get(User, payload.user_id)
        if target is None or target.tenant_id != principal.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace member not found.")
        if target.role not in ASSIGNABLE_ROLES:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "A class can only be assigned to a teacher or reviewer.",
            )
        existing = self.session.scalar(
            select(ClassroomClassAssignment).where(
                ClassroomClassAssignment.allocation_id == allocation.id,
                ClassroomClassAssignment.user_id == target.id,
            )
        )
        if existing is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "That teacher or reviewer is already assigned to this class.",
            )
        row = ClassroomClassAssignment(
            allocation_id=allocation.id,
            workspace_id=principal.tenant_id,
            user_id=target.id,
            assigned_by_user_id=principal.user_id,
            assigned_at=utcnow(),
        )
        self.session.add(row)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.class_assignment.created",
            entity_type="classroom_class_assignment",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "course_id": allocation.course_id,
                "allocation_id": str(allocation.id),
                "user_id": str(target.id),
                "user_role": target.role,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise AppError(
                ErrorCode.CONFLICT,
                "That teacher or reviewer is already assigned to this class.",
            ) from error
        self.session.refresh(row)
        return self._read(row, target, self.session.get(User, principal.user_id))

    def remove(
        self,
        principal: Principal,
        workspace_id: uuid.UUID,
        course_id: str,
        assignment_id: uuid.UUID,
    ) -> None:
        self._manager(principal)
        if workspace_id != principal.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        allocation, _classroom = require_course_access(
            self.session, principal, course_id=course_id
        )
        row = self.session.scalar(
            select(ClassroomClassAssignment).where(
                ClassroomClassAssignment.id == assignment_id,
                ClassroomClassAssignment.workspace_id == principal.tenant_id,
                ClassroomClassAssignment.allocation_id == allocation.id,
            )
        )
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Class assignment not found.")
        target = self.session.get(User, row.user_id)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.class_assignment.removed",
            entity_type="classroom_class_assignment",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "course_id": allocation.course_id,
                "allocation_id": str(allocation.id),
                "user_id": str(row.user_id),
                "user_role": target.role if target else None,
            },
        )
        self.session.delete(row)
        self.session.commit()