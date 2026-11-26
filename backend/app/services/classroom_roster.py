"""Google Classroom roster synchronisation and student identity mapping.

The Google user id is the only basis for identity.  A display name never matches
a student: two people called "Alex Smith" stay two people, and a rename changes
a name rather than a person.

Matching rules, in order, are recorded on the row so the decision is auditable:

``EXTERNAL_ID``
    An existing Aetrix student already uses the Google id as ``student_ref``.
``CREATED``
    Aetrix created a student for this Google identity, using the Google id as
    the reference.  That reference cannot collide with a human-entered
    admission number in practice, and a teacher can reassign it explicitly.
``MANUAL``
    A teacher resolved the identity through ``link``, after the auto-created
    student was shown to hold no work.

Manually maintained names are never overwritten: a synchronisation fills a blank
display name and nothing else.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal
from ..db.models import (
    ClassroomAllocation,
    ClassroomClass,
    ClassroomCourseworkLink,
    ClassroomRosterEntry,
    ClassroomSyncRun,
    Student,
    Submission,
)
from ..db.repositories import StudentRepository
from ..schemas.classroom_integration import (
    RosterEntryRead,
    RosterLinkRequest,
    RosterSyncRead,
    TeacherCourseRead,
)
from .classroom_access import (
    allowed_course_ids,
    ensure_teaching,
    require_course_access,
)
from .classroom_google import ClassroomUpstreamError, list_students
from .classroom_oauth import ClassroomOAuthService


def _safe_message(value: str) -> str:
    return " ".join(value.split())[:500]


class ClassroomRosterService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        oauth: ClassroomOAuthService | None = None,
        transport: object | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.oauth = oauth or ClassroomOAuthService(
            session, settings, transport=transport
        )
        self.students = StudentRepository(session)
        self.audit = AuditService(session)

    # -- reads -----------------------------------------------------------
    def courses(self, principal: Principal) -> list[TeacherCourseRead]:
        allowed = allowed_course_ids(self.session, principal)
        statement = (
            select(ClassroomAllocation, ClassroomClass)
            .join(
                ClassroomClass,
                ClassroomAllocation.classroom_class_id == ClassroomClass.id,
            )
            .where(
                ClassroomAllocation.workspace_id == principal.tenant_id,
                ClassroomAllocation.status == "ACTIVE",
            )
        )
        if allowed is not None:
            statement = statement.where(ClassroomAllocation.course_id.in_(allowed))
        rows = self.session.execute(
            statement.order_by(ClassroomAllocation.class_name.asc())
        ).all()
        if not rows:
            return []
        course_ids = [allocation.course_id for allocation, _ in rows]
        roster_counts = {
            course_id: int(count)
            for course_id, count in self.session.execute(
                select(
                    ClassroomRosterEntry.course_id, func.count()
                )
                .where(
                    ClassroomRosterEntry.tenant_id == principal.tenant_id,
                    ClassroomRosterEntry.course_id.in_(course_ids),
                    ClassroomRosterEntry.status == "ACTIVE",
                )
                .group_by(ClassroomRosterEntry.course_id)
            ).all()
        }
        coursework_counts = {
            course_id: int(count)
            for course_id, count in self.session.execute(
                select(ClassroomCourseworkLink.course_id, func.count())
                .where(
                    ClassroomCourseworkLink.tenant_id == principal.tenant_id,
                    ClassroomCourseworkLink.course_id.in_(course_ids),
                )
                .group_by(ClassroomCourseworkLink.course_id)
            ).all()
        }
        return [
            TeacherCourseRead(
                allocation_id=allocation.id,
                classroom_class_id=classroom.id,
                course_id=allocation.course_id,
                name=allocation.class_name,
                section=classroom.section,
                course_state=classroom.course_state,
                students=roster_counts.get(allocation.course_id, 0),
                coursework=coursework_counts.get(allocation.course_id, 0),
            )
            for allocation, classroom in rows
        ]

    def _rows(self, tenant_id: uuid.UUID, course_id: str) -> list[tuple[Any, ...]]:
        return list(
            self.session.execute(
                select(ClassroomRosterEntry, Student)
                .join(Student, ClassroomRosterEntry.student_id == Student.id)
                .where(
                    ClassroomRosterEntry.tenant_id == tenant_id,
                    ClassroomRosterEntry.course_id == course_id,
                )
                .order_by(
                    Student.student_ref.asc(), ClassroomRosterEntry.id.asc()
                )
            ).all()
        )

    @staticmethod
    def _read(entry: ClassroomRosterEntry, student: Student) -> RosterEntryRead:
        return RosterEntryRead(
            google_user_id=entry.google_user_id,
            student_id=student.id,
            student_ref=student.student_ref,
            display_name=student.display_name,
            google_name=entry.full_name,
            email=entry.email,
            status=entry.status,
            match_source=entry.match_source,
            last_seen_at=entry.last_seen_at,
        )

    def roster(self, principal: Principal, course_id: str) -> list[RosterEntryRead]:
        require_course_access(self.session, principal, course_id=course_id)
        return [
            self._read(entry, student)
            for entry, student in self._rows(principal.tenant_id, course_id)
        ]

    # -- synchronisation --------------------------------------------------
    def _entry_for(
        self, tenant_id: uuid.UUID, course_id: str, google_user_id: str
    ) -> ClassroomRosterEntry | None:
        return self.session.scalar(
            select(ClassroomRosterEntry).where(
                ClassroomRosterEntry.tenant_id == tenant_id,
                ClassroomRosterEntry.course_id == course_id,
                ClassroomRosterEntry.google_user_id == google_user_id,
            )
        )

    def _record_run(
        self,
        principal: Principal,
        *,
        course_id: str,
        status: str,
        counts: dict[str, int],
        problems: list[str],
    ) -> None:
        now = utcnow()
        self.session.add(
            ClassroomSyncRun(
                tenant_id=principal.tenant_id,
                kind="ROSTER",
                status=status,
                course_id=course_id,
                actor_subject=principal.subject,
                counts=counts,
                error_code=None if status == "SUCCEEDED" else "PARTIAL_ROSTER",
                error_message="; ".join(problems)[:500] or None,
                started_at=now,
                finished_at=now,
            )
        )

    def sync(self, principal: Principal, course_id: str) -> RosterSyncRead:
        ensure_teaching(principal)
        _allocation, classroom = require_course_access(
            self.session, principal, course_id=course_id
        )
        if classroom.course_state != "ACTIVE":
            raise AppError(
                ErrorCode.CONFLICT,
                "An archived or deleted Classroom course cannot be rostered.",
            )

        access_token = self.oauth.access_token()
        try:
            listing = list_students(
                self.settings.classroom,
                access_token,
                course_id,
                max_students=self.settings.classroom.max_roster_students,
                transport=self.oauth.transport,  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            self._record_run(
                principal,
                course_id=course_id,
                status="FAILED",
                counts={"discovered": 0},
                problems=[error.message],
            )
            self.session.commit()
            self.oauth._raise_upstream(error)

        now = utcnow()
        counts = {
            "discovered": 0,
            "created": 0,
            "matched": 0,
            "updated": 0,
            "removed": 0,
            "problems": 0,
        }
        problems: list[str] = []
        seen: set[str] = set()

        for person in listing.people:
            seen.add(person.user_id)
            counts["discovered"] += 1
            savepoint = self.session.begin_nested()
            try:
                entry = self._entry_for(
                    principal.tenant_id, course_id, person.user_id
                )
                if entry is not None:
                    entry.full_name = person.full_name or entry.full_name
                    entry.email = person.email or entry.email
                    entry.last_seen_at = now
                    entry.status = "ACTIVE"
                    student = self.students.get(
                        principal.tenant_id, entry.student_id
                    )
                    if student is not None and not student.display_name:
                        student.display_name = person.full_name
                    counts["updated"] += 1
                else:
                    student = self.students.get_by_ref(
                        principal.tenant_id, person.user_id
                    )
                    if student is not None:
                        match_source = "EXTERNAL_ID"
                        counts["matched"] += 1
                    else:
                        student = self.students.create(
                            tenant_id=principal.tenant_id,
                            student_ref=person.user_id,
                            display_name=person.full_name,
                            class_id=None,
                        )
                        match_source = "CREATED"
                        counts["created"] += 1
                    self.session.add(
                        ClassroomRosterEntry(
                            tenant_id=principal.tenant_id,
                            course_id=course_id,
                            google_user_id=person.user_id,
                            student_id=student.id,
                            full_name=person.full_name,
                            email=person.email,
                            status="ACTIVE",
                            match_source=match_source,
                            last_seen_at=now,
                        )
                    )
                self.session.flush()
                savepoint.commit()
            except SQLAlchemyError as error:
                savepoint.rollback()
                counts["problems"] += 1
                problems.append(
                    f"Google user {person.user_id} could not be recorded: "
                    f"{type(error).__name__}."
                )

        # A student who left the course is marked, not deleted: their marks and
        # submission history stay where they are.
        for entry, _student in self._rows(principal.tenant_id, course_id):
            if entry.google_user_id in seen or entry.status == "REMOVED":
                continue
            entry.status = "REMOVED"
            counts["removed"] += 1

        status = "PARTIAL" if (listing.truncated or problems) else "SUCCEEDED"
        self._record_run(
            principal,
            course_id=course_id,
            status=status,
            counts=counts,
            problems=problems,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.roster.synchronized",
            entity_type="classroom_course",
            entity_id=course_id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={**counts, "truncated": listing.truncated},
        )
        self.session.commit()

        return RosterSyncRead(
            status=status,
            course_id=course_id,
            counts=counts,
            truncated=listing.truncated,
            entries=[
                self._read(entry, student)
                for entry, student in self._rows(principal.tenant_id, course_id)
            ],
            problems=problems,
        )

    # -- explicit identity resolution -------------------------------------
    def link(
        self,
        principal: Principal,
        course_id: str,
        payload: RosterLinkRequest,
    ) -> RosterEntryRead:
        ensure_teaching(principal)
        require_course_access(self.session, principal, course_id=course_id)
        entry = self._entry_for(
            principal.tenant_id, course_id, payload.google_user_id
        )
        if entry is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "That Google account is not on this course's synchronized roster.",
            )
        target = self.students.get(principal.tenant_id, payload.student_id)
        if target is None:
            raise AppError(ErrorCode.NOT_FOUND, "Student not found.")
        if entry.student_id == target.id:
            student = self.students.get(principal.tenant_id, target.id)
            assert student is not None
            return self._read(entry, student)

        clash = self.session.scalar(
            select(ClassroomRosterEntry).where(
                ClassroomRosterEntry.tenant_id == principal.tenant_id,
                ClassroomRosterEntry.course_id == course_id,
                ClassroomRosterEntry.student_id == target.id,
            )
        )
        if clash is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "That Aetrix student is already linked to another Google account "
                "on this course.",
            )

        previous = self.students.get(principal.tenant_id, entry.student_id)
        previous_ref = previous.student_ref if previous is not None else None
        if previous_ref is not None:
            held = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(Submission)
                    .where(
                        Submission.tenant_id == principal.tenant_id,
                        Submission.student_ref == previous_ref,
                    )
                )
                or 0
            )
            if held:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "The student Aetrix created for this Google account already "
                    f"holds {held} submission(s). Linking a different identity "
                    "would detach that work from its owner, so it was refused.",
                    details={"submissions": held, "student_ref": previous_ref},
                )

        previous_id = entry.student_id
        entry.student_id = target.id
        entry.match_source = "MANUAL"
        entry.last_seen_at = utcnow()
        if not target.display_name:
            target.display_name = entry.full_name

        # Only an auto-created placeholder is removable, and only once nothing
        # else points at it.  A manually maintained student is never deleted.
        if previous is not None:
            other_entries = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(ClassroomRosterEntry)
                    .where(
                        ClassroomRosterEntry.tenant_id == principal.tenant_id,
                        ClassroomRosterEntry.student_id == previous.id,
                    )
                )
                or 0
            )
            if other_entries == 0:
                self.students.delete(previous)

        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.roster.linked",
            entity_type="classroom_roster_entry",
            entity_id=entry.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "course_id": course_id,
                "google_user_id": payload.google_user_id,
                "previous_student_id": str(previous_id),
                "student_id": str(target.id),
                "reason": payload.reason,
            },
        )
        self.session.commit()
        self.session.refresh(entry)
        student = self.students.get(principal.tenant_id, target.id)
        assert student is not None
        return self._read(entry, student)
