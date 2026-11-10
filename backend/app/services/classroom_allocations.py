"""Google Classroom course inventory and workspace allocation.

The lifecycle is deliberately append-only.  Releasing an allocation keeps its
row; reassigning releases the old row and creates a new one pointing back at it.
The database has a partial unique index for ACTIVE allocations, so two operators
allocating the same course cannot both succeed.  Every successful mutation writes
a platform audit event in the same transaction.

A course enters the inventory by operator registration or by a workspace's
successful Google Classroom course sync.  Only the sync path writes
``VERIFIED``; an operator-recorded row stays ``UNVERIFIED`` until Google
actually lists it.  Course discovery does not import rosters or grades.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.logging import request_id_var
from ..core.security import Principal, platform_authority
from ..db.models import (
    ClassroomAllocation,
    ClassroomClass,
    PlatformAuditEvent,
    Tenant,
    User,
)
from ..schemas.classroom_allocations import (
    AllocationCreate,
    AllocationOperationRead,
    AllocationPage,
    AllocationRead,
    AllocationReassign,
    AllocationRelease,
    ClassroomCapabilityRead,
    ClassroomClassCreate,
    ClassroomClassRead,
    WorkspaceAllocationRead,
    WorkspaceTargetRead,
)
from .platform_accounts import ensure_platform_admin

DISCOVERY_REASON_CONFIGURED = (
    "A Google Classroom OAuth client is configured. A workspace owner or "
    "administrator can authorise the classroom.courses.readonly scope and run "
    "a course sync; listed courses are stored VERIFIED with source "
    "google_classroom. Operator-recorded classes stay UNVERIFIED until a sync "
    "lists them. Rosters and grades are not read or written."
)

DISCOVERY_REASON_UNCONFIGURED = (
    "No Google Classroom OAuth client is configured in this engine. The "
    "authorisation and sync routes exist, but they report "
    "CLASSROOM_NOT_CONFIGURED until AETRIX_CLASSROOM__CLIENT_ID, "
    "AETRIX_CLASSROOM__CLIENT_SECRET and AETRIX_CLASSROOM__REDIRECT_URI are set."
)


def _audit(
    session: Session,
    actor: Principal,
    action: str,
    course_id: str,
    detail: dict[str, object],
) -> None:
    session.add(
        PlatformAuditEvent(
            actor_user_id=actor.user_id,
            actor_subject=actor.subject,
            actor_platform_role=platform_authority(actor) or actor.role,
            action=action,
            target_subject=course_id,
            target_email=None,
            detail=detail,
            request_id=request_id_var.get(),
            created_at=utcnow(),
        )
    )


def _class_read(row: ClassroomClass) -> ClassroomClassRead:
    return ClassroomClassRead(
        id=row.id,
        course_id=row.course_id,
        name=row.name,
        section=row.section,
        course_state=row.course_state,
        verification=row.verification,
        source=row.source,
        owner_email=row.owner_email,
        synced_at=row.synced_at,
        created_at=row.created_at,
    )


def _allocation_read(
    row: ClassroomAllocation, classroom: ClassroomClass
) -> AllocationRead:
    return AllocationRead(
        id=row.id,
        classroom_class_id=row.classroom_class_id,
        course_id=row.course_id,
        class_name=row.class_name,
        class_section=classroom.section,
        verification=classroom.verification,
        workspace_id=row.workspace_id,
        workspace_name=row.workspace_name,
        status=row.status,
        origin=row.origin,
        allocated_by_subject=row.allocated_by_subject,
        allocated_by_label=row.allocated_by_label,
        allocated_at=row.allocated_at,
        released_by_subject=row.released_by_subject,
        released_by_label=row.released_by_label,
        released_at=row.released_at,
        release_reason=row.release_reason,
        reason=row.reason,
        previous_allocation_id=row.previous_allocation_id,
    )


class ClassroomAllocationService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    # -- reads -----------------------------------------------------------
    def capability(self) -> ClassroomCapabilityRead:
        configured = bool(
            self.settings is not None and self.settings.classroom.configured()
        )
        return ClassroomCapabilityRead(
            allocation_available=True,
            discovery_configured=configured,
            verification="UNVERIFIED",
            reason=(
                DISCOVERY_REASON_CONFIGURED
                if configured
                else DISCOVERY_REASON_UNCONFIGURED
            ),
            operations=[
                AllocationOperationRead(
                    name="allocate a recorded class",
                    supported=True,
                    note="Platform owner or administrator; one ACTIVE allocation per class.",
                ),
                AllocationOperationRead(
                    name="release an allocation",
                    supported=True,
                    note="Keeps the released row as history; the class becomes available.",
                ),
                AllocationOperationRead(
                    name="reassign an allocation",
                    supported=True,
                    note="Releases the current row and allocates a new one in one transaction.",
                ),
                AllocationOperationRead(
                    name="discover classes from Google Classroom",
                    supported=True,
                    note=(
                        "A workspace owner or administrator authorises the "
                        "classroom.courses.readonly scope and runs a course "
                        "sync; listed courses are stored VERIFIED with source "
                        "google_classroom. Rosters and grades are not read."
                    ),
                ),
            ],
        )

    def list_workspaces(self, actor: Principal) -> list[WorkspaceTargetRead]:
        ensure_platform_admin(actor)
        tenants = list(
            self.session.scalars(
                select(Tenant)
                .where(Tenant.is_active.is_(True), Tenant.is_demo.is_(False))
                .order_by(Tenant.name.asc(), Tenant.id.asc())
            )
        )
        if not tenants:
            return []
        counts = {
            workspace_id: int(count)
            for workspace_id, count in self.session.execute(
                select(ClassroomAllocation.workspace_id, func.count())
                .where(
                    ClassroomAllocation.workspace_id.in_([row.id for row in tenants]),
                    ClassroomAllocation.status == "ACTIVE",
                )
                .group_by(ClassroomAllocation.workspace_id)
            ).all()
        }
        users = list(
            self.session.scalars(
                select(User)
                .where(User.tenant_id.in_([row.id for row in tenants]))
                .order_by(User.created_at.asc(), User.id.asc())
            )
        )
        owners: dict[uuid.UUID, User] = {}
        for user in users:
            current = owners.get(user.tenant_id)
            if current is None or (user.role == "OWNER" and current.role != "OWNER"):
                owners[user.tenant_id] = user
        rows: list[WorkspaceTargetRead] = []
        for tenant in tenants:
            owner = owners.get(tenant.id)
            rows.append(
                WorkspaceTargetRead(
                    id=tenant.id,
                    name=tenant.name,
                    slug=tenant.slug,
                    owner_label=(
                        owner.display_name or owner.email or owner.subject
                        if owner is not None
                        else None
                    ),
                    owner_email=owner.email if owner is not None else None,
                    active_allocations=counts.get(tenant.id, 0),
                )
            )
        return rows

    def list_available_classes(
        self, actor: Principal, *, q: str | None = None
    ) -> list[ClassroomClassRead]:
        ensure_platform_admin(actor)
        allocated = select(ClassroomAllocation.classroom_class_id).where(
            ClassroomAllocation.status == "ACTIVE"
        )
        statement = select(ClassroomClass).where(
            ClassroomClass.course_state == "ACTIVE",
            ClassroomClass.id.not_in(allocated),
        )
        if q:
            needle = f"%{q.strip()}%"
            statement = statement.where(
                ClassroomClass.name.ilike(needle)
                | ClassroomClass.course_id.ilike(needle)
            )
        rows = self.session.scalars(
            statement.order_by(ClassroomClass.name.asc(), ClassroomClass.id.asc())
        )
        return [_class_read(row) for row in rows]

    def list_allocations(
        self,
        actor: Principal,
        *,
        status: str = "ALL",
        workspace_id: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AllocationPage:
        ensure_platform_admin(actor)
        statement = select(ClassroomAllocation, ClassroomClass).join(
            ClassroomClass, ClassroomAllocation.classroom_class_id == ClassroomClass.id
        )
        count_statement = select(func.count()).select_from(ClassroomAllocation).join(
            ClassroomClass, ClassroomAllocation.classroom_class_id == ClassroomClass.id
        )
        conditions = []
        if status in {"ACTIVE", "RELEASED"}:
            conditions.append(ClassroomAllocation.status == status)
        if workspace_id is not None:
            conditions.append(ClassroomAllocation.workspace_id == workspace_id)
        if q:
            needle = f"%{q.strip()}%"
            conditions.append(
                ClassroomAllocation.class_name.ilike(needle)
                | ClassroomAllocation.course_id.ilike(needle)
                | ClassroomAllocation.workspace_name.ilike(needle)
            )
        for condition in conditions:
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)
        total = int(self.session.scalar(count_statement) or 0)
        rows = self.session.execute(
            statement.order_by(
                ClassroomAllocation.allocated_at.desc(),
                ClassroomAllocation.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return AllocationPage(
            items=[_allocation_read(allocation, classroom) for allocation, classroom in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    # -- helpers ---------------------------------------------------------
    def _class(self, class_id: uuid.UUID) -> ClassroomClass:
        row = self.session.get(ClassroomClass, class_id)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "That Classroom class does not exist.")
        return row

    def _workspace(self, workspace_id: uuid.UUID) -> Tenant:
        row = self.session.get(Tenant, workspace_id)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "That workspace does not exist.")
        if not row.is_active or row.is_demo:
            raise AppError(
                ErrorCode.CONFLICT,
                "A class can only be allocated to an active, non-demo workspace.",
            )
        return row

    def _active_for_class(self, class_id: uuid.UUID) -> ClassroomAllocation | None:
        return self.session.scalar(
            select(ClassroomAllocation).where(
                ClassroomAllocation.classroom_class_id == class_id,
                ClassroomAllocation.status == "ACTIVE",
            )
        )

    # -- mutations -------------------------------------------------------
    def register_class(
        self, actor: Principal, payload: ClassroomClassCreate
    ) -> ClassroomClassRead:
        ensure_platform_admin(actor)
        existing = self.session.scalar(
            select(ClassroomClass).where(
                ClassroomClass.course_id == payload.course_id
            )
        )
        if existing is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "That Google Classroom course is already recorded.",
            )
        row = ClassroomClass(
            course_id=payload.course_id,
            name=payload.name,
            section=payload.section,
            owner_email=payload.owner_email,
            course_state="ACTIVE",
            verification="UNVERIFIED",
            source="operator_recorded",
            synced_at=None,
            created_by_subject=actor.subject,
        )
        self.session.add(row)
        _audit(
            self.session,
            actor,
            "classroom.class_recorded",
            payload.course_id,
            {
                "course_id": payload.course_id,
                "name": payload.name,
                "verification": "UNVERIFIED",
                "result": "SUCCEEDED",
            },
        )
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise AppError(
                ErrorCode.CONFLICT,
                "That Google Classroom course is already recorded.",
            ) from error
        self.session.refresh(row)
        return _class_read(row)

    def allocate(
        self, actor: Principal, payload: AllocationCreate
    ) -> AllocationRead:
        ensure_platform_admin(actor)
        classroom = self._class(payload.classroom_class_id)
        if classroom.course_state != "ACTIVE":
            raise AppError(
                ErrorCode.CONFLICT,
                "Only an active Classroom course can be allocated.",
            )
        workspace = self._workspace(payload.workspace_id)
        if self._active_for_class(classroom.id) is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "That class already has an active allocation. Release it before "
                "allocating it again.",
            )
        row = ClassroomAllocation(
            classroom_class_id=classroom.id,
            workspace_id=workspace.id,
            course_id=classroom.course_id,
            class_name=classroom.name,
            workspace_name=workspace.name,
            status="ACTIVE",
            origin="ALLOCATE",
            allocated_by_subject=actor.subject,
            allocated_by_label=actor.subject,
            allocated_at=utcnow(),
            reason=payload.reason,
        )
        self.session.add(row)
        _audit(
            self.session,
            actor,
            "classroom.allocation_created",
            classroom.course_id,
            {
                "allocation_id": str(row.id),
                "workspace_id": str(workspace.id),
                "workspace_name": workspace.name,
                "result": "SUCCEEDED",
            },
        )
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise AppError(
                ErrorCode.CONFLICT,
                "That class was allocated by another request. Refresh and try again.",
            ) from error
        self.session.refresh(row)
        return _allocation_read(row, classroom)

    def release(
        self, actor: Principal, allocation_id: uuid.UUID, payload: AllocationRelease
    ) -> AllocationRead:
        ensure_platform_admin(actor)
        row = self.session.scalar(
            select(ClassroomAllocation)
            .where(
                ClassroomAllocation.id == allocation_id,
                ClassroomAllocation.status == "ACTIVE",
            )
            .with_for_update()
        )
        if row is None:
            raise AppError(
                ErrorCode.CONFLICT,
                "That allocation is not active; it cannot be released.",
            )
        classroom = self._class(row.classroom_class_id)
        row.status = "RELEASED"
        row.released_by_subject = actor.subject
        row.released_by_label = actor.subject
        row.released_at = utcnow()
        row.release_reason = payload.reason
        _audit(
            self.session,
            actor,
            "classroom.allocation_released",
            row.course_id,
            {
                "allocation_id": str(row.id),
                "workspace_id": str(row.workspace_id),
                "reason": payload.reason,
                "result": "SUCCEEDED",
            },
        )
        self.session.commit()
        self.session.refresh(row)
        return _allocation_read(row, classroom)

    def reassign(
        self,
        actor: Principal,
        allocation_id: uuid.UUID,
        payload: AllocationReassign,
    ) -> AllocationRead:
        ensure_platform_admin(actor)
        old = self.session.scalar(
            select(ClassroomAllocation)
            .where(
                ClassroomAllocation.id == allocation_id,
                ClassroomAllocation.status == "ACTIVE",
            )
            .with_for_update()
        )
        if old is None:
            raise AppError(
                ErrorCode.CONFLICT,
                "Reassignment needs an active allocation to release first.",
            )
        if old.workspace_id == payload.workspace_id:
            raise AppError(
                ErrorCode.CONFLICT,
                "That class is already allocated to this workspace.",
            )
        classroom = self._class(old.classroom_class_id)
        new_workspace = self._workspace(payload.workspace_id)

        old.status = "RELEASED"
        old.released_by_subject = actor.subject
        old.released_by_label = actor.subject
        old.released_at = utcnow()
        old.release_reason = f"Reassigned: {payload.reason}"
        new_row = ClassroomAllocation(
            classroom_class_id=classroom.id,
            workspace_id=new_workspace.id,
            course_id=classroom.course_id,
            class_name=classroom.name,
            workspace_name=new_workspace.name,
            status="ACTIVE",
            origin="REASSIGN",
            allocated_by_subject=actor.subject,
            allocated_by_label=actor.subject,
            allocated_at=utcnow(),
            reason=payload.reason,
            previous_allocation_id=old.id,
        )
        self.session.add(new_row)
        _audit(
            self.session,
            actor,
            "classroom.allocation_reassigned",
            classroom.course_id,
            {
                "previous_allocation_id": str(old.id),
                "new_allocation_id": str(new_row.id),
                "previous_workspace_id": str(old.workspace_id),
                "new_workspace_id": str(new_workspace.id),
                "reason": payload.reason,
                "result": "SUCCEEDED",
            },
        )
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise AppError(
                ErrorCode.CONFLICT,
                "That class changed while it was being reassigned. Refresh and try again.",
            ) from error
        self.session.refresh(new_row)
        return _allocation_read(new_row, classroom)

    # -- teacher view ----------------------------------------------------
    def workspace_allocations(
        self, actor: Principal, workspace_id: uuid.UUID
    ) -> list[WorkspaceAllocationRead]:
        if workspace_id != actor.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        rows = self.session.execute(
            select(ClassroomAllocation, ClassroomClass)
            .join(
                ClassroomClass,
                ClassroomAllocation.classroom_class_id == ClassroomClass.id,
            )
            .where(
                ClassroomAllocation.workspace_id == workspace_id,
                ClassroomAllocation.status == "ACTIVE",
            )
            .order_by(ClassroomAllocation.allocated_at.desc())
        ).all()
        return [
            WorkspaceAllocationRead(
                id=allocation.id,
                course_id=allocation.course_id,
                class_name=allocation.class_name,
                class_section=classroom.section,
                verification=classroom.verification,
                allocated_at=allocation.allocated_at,
                allocated_by_label=allocation.allocated_by_label,
            )
            for allocation, classroom in rows
        ]
