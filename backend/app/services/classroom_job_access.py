"""Keep correction and submission reads inside the caller's class assignments.

A job belongs to the course of its assignment: the assignment's own
``course_id`` (written when it was created) or, for assignments created before
class scoping, its Classroom coursework link.  A TEACHER or REVIEWER without an
assignment to the course must not read the job, its result or its submission
pages.

An assignment with no course at all is a legacy or manual record.  A TEACHER and
the read-only VIEWER keep the existing manual-upload visibility for it.  A
REVIEWER does not: the production playtest found an assistant reading every
unlinked workspace job, and workspace membership is not class access.  Managers
(OWNER, ADMIN, PLATFORM_OWNER) keep workspace-wide reads.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..db.models import (
    Assignment,
    ClassroomCourseworkLink,
    CorrectionJob,
    Submission,
)
from .classroom_access import allowed_course_ids, is_class_manager


def _courses_for_assignments(
    session: Session, tenant_id: uuid.UUID, assignment_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    ids = list({assignment_id for assignment_id in assignment_ids})
    if not ids:
        return {}
    return {
        assignment_id: course_id
        for assignment_id, course_id in session.execute(
            select(
                ClassroomCourseworkLink.assignment_id,
                ClassroomCourseworkLink.course_id,
            ).where(
                ClassroomCourseworkLink.tenant_id == tenant_id,
                ClassroomCourseworkLink.assignment_id.in_(ids),
            )
        ).all()
    }


def _visible_course_id(
    session: Session, principal: Principal, assignment_id: uuid.UUID
) -> str | None:
    course_id = session.scalar(
        select(Assignment.course_id).where(
            Assignment.id == assignment_id,
            Assignment.tenant_id == principal.tenant_id,
        )
    )
    if course_id:
        return course_id
    return session.scalar(
        select(ClassroomCourseworkLink.course_id).where(
            ClassroomCourseworkLink.tenant_id == principal.tenant_id,
            ClassroomCourseworkLink.assignment_id == assignment_id,
        )
    )


def _legacy_visible(principal: Principal) -> bool:
    """Who may read an assignment that has no class at all.

    A teacher and the read-only viewer keep the manual-upload workflow that
    predates class scoping.  An assistant does not, because nothing in the
    request proved the work belongs to one of their classes.
    """

    return principal.role in {"TEACHER", "VIEWER"}


def visible_jobs(
    session: Session, principal: Principal, jobs: Iterable[CorrectionJob]
) -> list[CorrectionJob]:
    """Drop jobs whose linked Classroom course is not assigned to the caller."""

    rows = list(jobs)
    if is_class_manager(principal):
        return rows
    allowed = allowed_course_ids(session, principal) or set()
    courses = _courses_for_assignments(
        session, principal.tenant_id, (job.assignment_id for job in rows)
    )
    legacy = _legacy_visible(principal)
    return [
        job
        for job in rows
        if (
            courses.get(job.assignment_id) in allowed
            if courses.get(job.assignment_id) is not None
            else legacy
        )
    ]


def require_job_access(
    session: Session, principal: Principal, job: CorrectionJob
) -> None:
    if is_class_manager(principal):
        return
    course_id = _visible_course_id(session, principal, job.assignment_id)
    if course_id is None:
        if _legacy_visible(principal):
            return
        raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")
    if course_id not in (allowed_course_ids(session, principal) or set()):
        raise AppError(ErrorCode.NOT_FOUND, "Correction job not found.")


def require_submission_access(
    session: Session, principal: Principal, submission: Submission
) -> None:
    if is_class_manager(principal):
        return
    course_id = _visible_course_id(session, principal, submission.assignment_id)
    if course_id is None:
        if _legacy_visible(principal):
            return
        raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
    if course_id not in (allowed_course_ids(session, principal) or set()):
        raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")


def require_assignment_access(
    session: Session, principal: Principal, assignment_id: uuid.UUID
) -> None:
    if is_class_manager(principal):
        return
    course_id = _visible_course_id(session, principal, assignment_id)
    if course_id is None:
        if _legacy_visible(principal):
            return
        raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
    if course_id not in (allowed_course_ids(session, principal) or set()):
        raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")