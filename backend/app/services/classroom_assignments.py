"""Aetrix assignments and their Google Classroom coursework.

An Aetrix assignment owns the marking configuration; the Classroom coursework is
its external representation.  Publication is explicit, idempotent and
reconciled: a retry after a lost response looks for the coursework it may already
have created instead of creating a second one.

Only fields Google actually supports are synchronised (title, description, due
date/time and points).  Materials are not uploaded: Google coursework materials
need Drive files, and this integration does not create them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal
from ..db.models import (
    Assignment,
    ClassroomCourseworkLink,
    ClassroomSubmissionLink,
    ExamBlueprintVersion,
)
from ..schemas.classroom_integration import (
    CourseworkCreate,
    CourseworkRead,
    CourseworkUpdate,
)
from .classroom_access import (
    allowed_course_ids,
    ensure_teaching,
    require_course_access,
)
from .classroom_google import (
    ClassroomUpstreamError,
    UpstreamKind,
    create_coursework,
    get_course,
    list_coursework,
    patch_coursework,
)
from .classroom_oauth import ClassroomOAuthService
from .scheme_criteria import readiness_of_assignment, reconcile_max_points


def _safe_message(value: str) -> str:
    return " ".join(value.split())[:500]


def _due_parts(
    due_at: datetime, time_zone: str | None
) -> tuple[dict[str, int], dict[str, int]]:
    """Google wants a civil date and time in the course's own time zone."""

    zone = UTC
    if time_zone:
        try:
            zone = ZoneInfo(time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = UTC
    moment = due_at if due_at.tzinfo is not None else due_at.replace(tzinfo=UTC)
    local = moment.astimezone(zone)
    return (
        {"year": local.year, "month": local.month, "day": local.day},
        {"hours": local.hour, "minutes": local.minute},
    )


class ClassroomCourseworkService:
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
        self.audit = AuditService(session)

    # -- reads -----------------------------------------------------------
    def _submission_counts(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, int]:
        return {
            link_id: int(count)
            for link_id, count in self.session.execute(
                select(ClassroomSubmissionLink.coursework_link_id, func.count())
                .where(ClassroomSubmissionLink.tenant_id == tenant_id)
                .group_by(ClassroomSubmissionLink.coursework_link_id)
            ).all()
        }

    @staticmethod
    def _read(
        link: ClassroomCourseworkLink,
        assignment: Assignment,
        submissions: int,
    ) -> CourseworkRead:
        return CourseworkRead(
            id=link.id,
            assignment_id=link.assignment_id,
            assignment_name=assignment.name,
            classroom_class_id=link.classroom_class_id,
            course_id=link.course_id,
            coursework_id=link.coursework_id,
            state=link.state,
            title=link.title,
            description=link.description,
            due_at=link.due_at,
            max_points=link.max_points,
            publish_attempts=link.publish_attempts,
            published_at=link.published_at,
            published_by_subject=link.published_by_subject,
            last_error_code=link.last_error_code,
            last_error_message=link.last_error_message,
            submissions=submissions,
            created_at=link.created_at,
        )

    def list(self, principal: Principal) -> list[CourseworkRead]:
        allowed = allowed_course_ids(self.session, principal)
        statement = (
            select(ClassroomCourseworkLink, Assignment)
            .join(Assignment, ClassroomCourseworkLink.assignment_id == Assignment.id)
            .where(ClassroomCourseworkLink.tenant_id == principal.tenant_id)
        )
        if allowed is not None:
            statement = statement.where(ClassroomCourseworkLink.course_id.in_(allowed))
        rows = self.session.execute(
            statement.order_by(ClassroomCourseworkLink.created_at.desc())
        ).all()
        counts = self._submission_counts(principal.tenant_id)
        return [
            self._read(link, assignment, counts.get(link.id, 0))
            for link, assignment in rows
        ]

    def _get(
        self, tenant_id: uuid.UUID, link_id: uuid.UUID
    ) -> tuple[ClassroomCourseworkLink, Assignment]:
        row = self.session.execute(
            select(ClassroomCourseworkLink, Assignment)
            .join(Assignment, ClassroomCourseworkLink.assignment_id == Assignment.id)
            .where(
                ClassroomCourseworkLink.id == link_id,
                ClassroomCourseworkLink.tenant_id == tenant_id,
            )
        ).first()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Coursework link not found.")
        link, assignment = row
        return link, assignment

    def read(self, principal: Principal, link_id: uuid.UUID) -> CourseworkRead:
        link, assignment = self._get(principal.tenant_id, link_id)
        require_course_access(self.session, principal, course_id=link.course_id)
        counts = self._submission_counts(principal.tenant_id)
        return self._read(link, assignment, counts.get(link.id, 0))

    # -- creation --------------------------------------------------------
    def create(
        self, principal: Principal, payload: CourseworkCreate
    ) -> CourseworkRead:
        ensure_teaching(principal)
        _allocation, classroom = require_course_access(
            self.session,
            principal,
            classroom_class_id=payload.classroom_class_id,
        )
        if classroom.course_state != "ACTIVE":
            raise AppError(
                ErrorCode.CONFLICT,
                "Only an active Classroom course accepts new coursework.",
            )
        assignment = self.session.scalar(
            select(Assignment).where(
                Assignment.id == payload.assignment_id,
                Assignment.tenant_id == principal.tenant_id,
            )
        )
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")

        existing = self.session.scalar(
            select(ClassroomCourseworkLink).where(
                ClassroomCourseworkLink.tenant_id == principal.tenant_id,
                ClassroomCourseworkLink.assignment_id == assignment.id,
            )
        )
        if existing is not None:
            counts = self._submission_counts(principal.tenant_id)
            return self._read(existing, assignment, counts.get(existing.id, 0))

        # A coursework is published with one number of points.  Publishing a
        # paper whose criteria are not approved, or whose points differ from the
        # approved blueprint, would put work into a classroom that cannot be
        # marked and whose denominator is not the paper's own.
        blueprint = self._require_publishable(assignment)
        max_points = reconcile_max_points(blueprint.total_marks, payload.max_points)

        link = ClassroomCourseworkLink(
            tenant_id=principal.tenant_id,
            assignment_id=assignment.id,
            classroom_class_id=classroom.id,
            course_id=classroom.course_id,
            state="DRAFT",
            title=(payload.title or assignment.name)[:300],
            description=payload.description,
            due_at=payload.due_at,
            max_points=max_points,
            publish_attempts=0,
        )
        self.session.add(link)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.coursework.drafted",
            entity_type="classroom_coursework_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "assignment_id": str(assignment.id),
                "course_id": classroom.course_id,
                "title": link.title,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise AppError(
                ErrorCode.CONFLICT,
                "This assignment already has a Classroom coursework link.",
            ) from error
        self.session.refresh(link)
        return self._read(link, assignment, 0)

    # -- publication -----------------------------------------------------
    def _approved_blueprint(self, assignment: Assignment) -> ExamBlueprintVersion:
        """The assignment's approved paper, or the reason there is none."""

        blueprint = (
            self.session.get(ExamBlueprintVersion, assignment.blueprint_version_id)
            if assignment.blueprint_version_id is not None
            else None
        )
        if blueprint is None or blueprint.tenant_id != assignment.tenant_id:
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "This assignment has no blueprint, so there is no paper to publish.",
            )
        if blueprint.status != "APPROVED":
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "The assignment's blueprint is not approved, so it cannot be "
                "published to Classroom.",
                details={"blueprint_status": blueprint.status},
            )
        return blueprint

    def _require_publishable(self, assignment: Assignment) -> ExamBlueprintVersion:
        """The assignment's approved paper, with criteria ready to mark with.

        This is the same question the engine asks before marking, asked before a
        coursework is created: an assignment whose scheme criteria were never
        reviewed would publish work nobody can mark.
        """

        blueprint = self._approved_blueprint(assignment)
        readiness = readiness_of_assignment(
            self.session,
            tenant_id=assignment.tenant_id,
            blueprint_version_id=assignment.blueprint_version_id,
            scheme_version_id=assignment.scheme_version_id,
        )
        if not readiness.ready:
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "The assignment's mark-scheme criteria are not approved for "
                "this paper, so it cannot be published to Classroom. Transcribe "
                "and approve the criteria first.",
                details={
                    "reason": readiness.reason,
                    "problems": list(readiness.problems)[:10],
                },
            )
        return blueprint

    def _require_matching_points(
        self, link: ClassroomCourseworkLink, blueprint_total: int
    ) -> None:
        """A stored coursework's points must be the paper's, before it is used."""

        if link.max_points is None:
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                f"This coursework has no maximum points. Set them to the "
                f"approved paper total ({blueprint_total}) before publishing.",
                details={"blueprint_total": int(blueprint_total)},
            )
        if link.max_points != blueprint_total:
            raise AppError(
                ErrorCode.CONFLICT,
                f"This coursework is worth {link.max_points} points but the "
                f"approved paper is worth {blueprint_total}. Correct the "
                f"coursework's maximum points before publishing.",
                details={
                    "blueprint_total": int(blueprint_total),
                    "coursework_max_points": str(link.max_points),
                },
            )

    def _reconcile(
        self,
        link: ClassroomCourseworkLink,
        access_token: str,
        time_zone: str | None,
    ) -> bool:
        """Adopt a coursework a previous attempt created but did not record.

        Only an unambiguous single match is adopted.  Two similar titles must be
        resolved by a person, because guessing would attach marks to the wrong
        coursework.
        """

        existing = list_coursework(
            self.settings.classroom,
            access_token,
            link.course_id,
            transport=self.oauth.transport,  # type: ignore[arg-type]
        )
        claimed = set(
            self.session.scalars(
                select(ClassroomCourseworkLink.coursework_id).where(
                    ClassroomCourseworkLink.tenant_id == link.tenant_id,
                    ClassroomCourseworkLink.coursework_id.is_not(None),
                )
            )
        )
        matches = [
            item
            for item in existing
            if item.title.strip().casefold() == link.title.strip().casefold()
            and item.coursework_id not in claimed
        ]
        if len(matches) > 1:
            raise AppError(
                ErrorCode.CONFLICT,
                "More than one Classroom coursework matches this title, so the "
                "uncertain outcome cannot be resolved automatically. Check "
                "Classroom and remove the duplicate before publishing again.",
                details={"matches": [item.coursework_id for item in matches]},
            )
        if not matches:
            return False
        link.coursework_id = matches[0].coursework_id
        link.state = "PUBLISHED"
        link.published_at = utcnow()
        link.published_by_subject = link.published_by_subject
        link.last_error_code = None
        link.last_error_message = None
        return True

    def publish(self, principal: Principal, link_id: uuid.UUID) -> CourseworkRead:
        ensure_teaching(principal)
        link = self.session.scalar(
            select(ClassroomCourseworkLink)
            .where(
                ClassroomCourseworkLink.id == link_id,
                ClassroomCourseworkLink.tenant_id == principal.tenant_id,
            )
            .with_for_update()
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Coursework link not found.")
        assignment = self.session.scalar(
            select(Assignment).where(
                Assignment.id == link.assignment_id,
                Assignment.tenant_id == principal.tenant_id,
            )
        )
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        if link.state == "PUBLISHED":
            # Idempotent: never create a second Classroom assignment.
            counts = self._submission_counts(principal.tenant_id)
            return self._read(link, assignment, counts.get(link.id, 0))
        blueprint = self._require_publishable(assignment)
        self._require_matching_points(link, blueprint.total_marks)
        if link.state == "PUBLISHING":
            raise AppError(
                ErrorCode.CONFLICT,
                "This assignment is already being published. Wait for the "
                "current attempt to finish before retrying.",
            )
        _allocation, classroom = require_course_access(
            self.session, principal, course_id=link.course_id
        )
        if classroom.course_state != "ACTIVE":
            raise AppError(
                ErrorCode.CONFLICT,
                "The Classroom course is no longer active, so coursework cannot "
                "be published to it.",
            )

        link.state = "PUBLISHING"
        link.publish_attempts += 1
        self.session.flush()
        self.session.commit()

        try:
            access_token = self.oauth.access_token()
        except AppError as error:
            link = self._reload(principal.tenant_id, link_id)
            link.state = "FAILED"
            link.last_error_code = str(error.code)
            link.last_error_message = _safe_message(error.message)
            self.session.commit()
            raise

        time_zone: str | None = None
        try:
            discovered = get_course(
                self.settings.classroom,
                access_token,
                link.course_id,
                transport=self.oauth.transport,  # type: ignore[arg-type]
            )
            time_zone = discovered.time_zone
        except ClassroomUpstreamError:
            # A time-zone read failure must not block publication; the due date
            # falls back to UTC and is reported as such in the coursework.
            time_zone = None

        try:
            if link.publish_attempts > 1 and self._reconcile(
                link, access_token, time_zone
            ):
                link.published_by_subject = principal.subject
                self.audit.record(
                    tenant_id=principal.tenant_id,
                    action="classroom.coursework.reconciled",
                    entity_type="classroom_coursework_link",
                    entity_id=link.id,
                    actor_type="USER",
                    actor_id=principal.user_id,
                    detail={
                        "coursework_id": link.coursework_id,
                        "course_id": link.course_id,
                    },
                )
                self.session.commit()
                self.session.refresh(link)
                counts = self._submission_counts(principal.tenant_id)
                return self._read(link, assignment, counts.get(link.id, 0))

            due_date = due_time = None
            if link.due_at is not None:
                due_date, due_time = _due_parts(link.due_at, time_zone)
            record = create_coursework(
                self.settings.classroom,
                access_token,
                link.course_id,
                title=link.title,
                description=link.description,
                due_date=due_date,
                due_time=due_time,
                max_points=float(link.max_points)
                if link.max_points is not None
                else None,
                state="PUBLISHED",
                transport=self.oauth.transport,  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            link = self._reload(principal.tenant_id, link_id)
            if error.kind in {
                UpstreamKind.TRANSIENT,
                UpstreamKind.RECONNECT_REQUIRED,
            }:
                # Google may still have created it.  The next attempt reconciles
                # before creating, so this can never become a duplicate.
                link.state = "FAILED"
                link.last_error_code = "CLASSROOM_PUBLISH_UNCONFIRMED"
                link.last_error_message = _safe_message(
                    "Google did not confirm the coursework. The next attempt "
                    "checks Classroom for it before creating another."
                )
            else:
                link.state = "FAILED"
                link.last_error_code = "CLASSROOM_PUBLISH_REFUSED"
                link.last_error_message = _safe_message(error.message)
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="classroom.coursework.publish_failed",
                entity_type="classroom_coursework_link",
                entity_id=link.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "course_id": link.course_id,
                    "error_code": link.last_error_code,
                    "status_code": error.status_code,
                },
            )
            self.session.commit()
            if error.kind in {
                UpstreamKind.RECONNECT_REQUIRED,
                UpstreamKind.SCOPE_MISSING,
            }:
                self.oauth._raise_upstream(error)
            raise AppError(
                ErrorCode.CLASSROOM_UPSTREAM_ERROR,
                link.last_error_message
                or "Google Classroom refused the coursework.",
            ) from error
        except AppError:
            link = self._reload(principal.tenant_id, link_id)
            link.state = "FAILED"
            link.last_error_code = "CLASSROOM_PUBLISH_CONFLICT"
            link.last_error_message = _safe_message(
                "The publication outcome could not be resolved."
            )
            self.session.commit()
            raise

        link.coursework_id = record.coursework_id
        link.state = "PUBLISHED"
        link.published_at = utcnow()
        link.published_by_subject = principal.subject
        link.last_error_code = None
        link.last_error_message = None
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.coursework.published",
            entity_type="classroom_coursework_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "course_id": link.course_id,
                "coursework_id": record.coursework_id,
                "attempt": link.publish_attempts,
                "due_time_zone": time_zone or "UTC",
            },
        )
        self.session.commit()
        self.session.refresh(link)
        counts = self._submission_counts(principal.tenant_id)
        return self._read(link, assignment, counts.get(link.id, 0))

    def _reload(
        self, tenant_id: uuid.UUID, link_id: uuid.UUID
    ) -> ClassroomCourseworkLink:
        self.session.rollback()
        link = self.session.scalar(
            select(ClassroomCourseworkLink)
            .where(
                ClassroomCourseworkLink.id == link_id,
                ClassroomCourseworkLink.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Coursework link not found.")
        return link

    # -- editing ---------------------------------------------------------
    def update(
        self, principal: Principal, link_id: uuid.UUID, payload: CourseworkUpdate
    ) -> CourseworkRead:
        ensure_teaching(principal)
        link, assignment = self._get(principal.tenant_id, link_id)
        require_course_access(self.session, principal, course_id=link.course_id)
        fields = (
            payload.title,
            payload.description,
            payload.due_at,
            payload.max_points,
        )
        if all(field is None for field in fields):
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "No supported field was supplied."
            )

        # Points are the denominator every published grade is scored against, so
        # an edit may set them to the approved paper's total and to nothing else.
        if payload.max_points is not None:
            blueprint = self._approved_blueprint(assignment)
            payload = payload.model_copy(
                update={
                    "max_points": reconcile_max_points(
                        blueprint.total_marks, payload.max_points
                    )
                }
            )

        if link.state == "PUBLISHED" and link.coursework_id:
            access_token = self.oauth.access_token()
            time_zone: str | None = None
            try:
                time_zone = get_course(
                    self.settings.classroom,
                    access_token,
                    link.course_id,
                    transport=self.oauth.transport,  # type: ignore[arg-type]
                ).time_zone
            except ClassroomUpstreamError:
                time_zone = None
            due_date = due_time = None
            if payload.due_at is not None:
                due_date, due_time = _due_parts(payload.due_at, time_zone)
            try:
                patch_coursework(
                    self.settings.classroom,
                    access_token,
                    link.course_id,
                    link.coursework_id,
                    title=payload.title,
                    description=payload.description,
                    due_date=due_date,
                    due_time=due_time,
                    max_points=float(payload.max_points)
                    if payload.max_points is not None
                    else None,
                    transport=self.oauth.transport,  # type: ignore[arg-type]
                )
            except ClassroomUpstreamError as error:
                self.audit.record(
                    tenant_id=principal.tenant_id,
                    action="classroom.coursework.update_failed",
                    entity_type="classroom_coursework_link",
                    entity_id=link.id,
                    actor_type="USER",
                    actor_id=principal.user_id,
                    detail={
                        "course_id": link.course_id,
                        "coursework_id": link.coursework_id,
                    },
                )
                self.session.commit()
                if error.kind in {
                    UpstreamKind.RECONNECT_REQUIRED,
                    UpstreamKind.SCOPE_MISSING,
                }:
                    self.oauth._raise_upstream(error)
                raise AppError(
                    ErrorCode.CLASSROOM_UPSTREAM_ERROR,
                    "Google Classroom refused the coursework update; the "
                    "published copy is unchanged.",
                ) from error

        if payload.title is not None:
            link.title = payload.title
        if payload.description is not None:
            link.description = payload.description
        if payload.due_at is not None:
            link.due_at = payload.due_at
        if payload.max_points is not None:
            link.max_points = payload.max_points
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.coursework.updated",
            entity_type="classroom_coursework_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "coursework_id": link.coursework_id,
                "published": link.state == "PUBLISHED",
            },
        )
        self.session.commit()
        self.session.refresh(link)
        counts = self._submission_counts(principal.tenant_id)
        return self._read(link, assignment, counts.get(link.id, 0))
