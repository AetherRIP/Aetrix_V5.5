"""Review, approval and grade publication for Classroom submissions.

Publishing a grade changes what a student sees in Google Classroom, so this
module is deliberately narrow:

* only an approved final result is eligible;
* approval is refused while any question is uncertain or unmarked;
* the actor who approved and the actor who authorised the write are both
  recorded, with a stated reason;
* a write is idempotent, and an attempt whose outcome Google did not confirm is
  reconciled against Google before anything is written again;
* a grade Google already holds that this integration did not write is never
  overwritten without an explicit instruction.

``draftGrade`` and ``assignedGrade`` stay distinct: a draft is a provisional mark
a teacher can see, an assigned grade is the returned result.  Publishing the
final result writes ``assignedGrade``; writing a draft never releases it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal
from ..db.models import (
    ClassroomCourseworkLink,
    ClassroomGradePublication,
    ClassroomSubmissionLink,
    CorrectionJob,
    QuestionResult,
)
from ..schemas.classroom_integration import (
    ApprovalRequest,
    GradePublicationRead,
    GradePublishRequest,
    PublicationStatusRead,
    ReviewRead,
)
from .classroom_access import ensure_grade_approver, require_course_access
from .classroom_google import (
    ClassroomUpstreamError,
    UpstreamKind,
    get_submission,
    patch_submission_grade,
    return_submission,
)
from .classroom_oauth import ClassroomOAuthService

#: A question in one of these states is not a decided mark.
UNCERTAIN_STATUSES = frozenset({"REVIEW_REQUIRED", "UNMARKED"})


def _money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _safe_message(value: str) -> str:
    return " ".join(value.split())[:500]


class ClassroomGradeService:
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
    def _link(self, tenant_id: uuid.UUID, link_id: uuid.UUID) -> ClassroomSubmissionLink:
        link = self.session.scalar(
            select(ClassroomSubmissionLink).where(
                ClassroomSubmissionLink.id == link_id,
                ClassroomSubmissionLink.tenant_id == tenant_id,
            )
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission link not found.")
        return link

    def _coursework(
        self, tenant_id: uuid.UUID, link: ClassroomSubmissionLink
    ) -> ClassroomCourseworkLink:
        row = self.session.scalar(
            select(ClassroomCourseworkLink).where(
                ClassroomCourseworkLink.id == link.coursework_link_id,
                ClassroomCourseworkLink.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Coursework link not found.")
        return row

    def _job(
        self, tenant_id: uuid.UUID, link: ClassroomSubmissionLink
    ) -> CorrectionJob | None:
        if link.correction_job_id is None:
            return None
        return self.session.scalar(
            select(CorrectionJob).where(
                CorrectionJob.id == link.correction_job_id,
                CorrectionJob.tenant_id == tenant_id,
            )
        )

    def _result_rows(
        self, tenant_id: uuid.UUID, job_id: uuid.UUID
    ) -> list[QuestionResult]:
        return list(
            self.session.scalars(
                select(QuestionResult)
                .where(
                    QuestionResult.tenant_id == tenant_id,
                    QuestionResult.job_id == job_id,
                )
                .order_by(QuestionResult.question_id.asc())
            )
        )

    def _evaluate(
        self, tenant_id: uuid.UUID, link: ClassroomSubmissionLink
    ) -> tuple[CorrectionJob | None, Decimal, Decimal, list[dict[str, Any]], str]:
        job = self._job(tenant_id, link)
        if job is None:
            return (
                None,
                Decimal("0.00"),
                Decimal("0.00"),
                [],
                "This submission has no correction job yet.",
            )
        rows = self._result_rows(tenant_id, job.id)
        decided = [row for row in rows if row.status != "EXCLUDED"]
        total = sum((row.awarded_marks for row in decided), 0)
        maximum = sum((row.max_marks for row in decided), 0)
        uncertain = [
            {
                "question_id": row.question_id,
                "status": row.status,
                "review_required": row.review_required,
                "awarded_marks": row.awarded_marks,
                "max_marks": row.max_marks,
            }
            for row in decided
            if row.status in UNCERTAIN_STATUSES or row.review_required
        ]
        if job.state != "COMPLETED":
            return (
                job,
                _money(total),
                _money(maximum),
                uncertain,
                f"The correction job is {job.state}; only a completed run can be "
                "approved.",
            )
        if not rows:
            return (
                job,
                _money(total),
                _money(maximum),
                uncertain,
                "The correction job produced no question results.",
            )
        if uncertain:
            return (
                job,
                _money(total),
                _money(maximum),
                uncertain,
                f"{len(uncertain)} question(s) still need a human decision.",
            )
        return (
            job,
            _money(total),
            _money(maximum),
            uncertain,
            "Every decision is final and the run is complete.",
        )

    def review(self, principal: Principal, link_id: uuid.UUID) -> ReviewRead:
        link = self._link(principal.tenant_id, link_id)
        require_course_access(self.session, principal, course_id=link.course_id)
        job, total, maximum, uncertain, reason = self._evaluate(
            principal.tenant_id, link
        )
        return ReviewRead(
            submission_link_id=link.id,
            job_id=job.id if job is not None else None,
            job_state=job.state if job is not None else None,
            total=total,
            maximum=maximum,
            uncertain=uncertain,
            approvable=bool(job is not None and not uncertain and reason.startswith("Every")),
            reason=reason,
        )

    # -- approval ---------------------------------------------------------
    def approve(
        self, principal: Principal, link_id: uuid.UUID, payload: ApprovalRequest
    ) -> ReviewRead:
        ensure_grade_approver(principal)
        link = self.session.scalar(
            select(ClassroomSubmissionLink)
            .where(
                ClassroomSubmissionLink.id == link_id,
                ClassroomSubmissionLink.tenant_id == principal.tenant_id,
            )
            .with_for_update()
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission link not found.")
        require_course_access(self.session, principal, course_id=link.course_id)
        job, total, maximum, uncertain, reason = self._evaluate(
            principal.tenant_id, link
        )
        if job is None or uncertain or not reason.startswith("Every"):
            raise AppError(
                ErrorCode.CLASSROOM_GRADE_NOT_APPROVED,
                f"This result cannot be approved yet. {reason}",
                details={"uncertain": uncertain},
            )

        previous = (
            {
                "total": str(link.approved_total),
                "max": str(link.approved_max),
                "approved_at": link.approved_at.isoformat()
                if link.approved_at
                else None,
                "job_id": str(link.correction_job_id)
                if link.correction_job_id
                else None,
            }
            if link.approved_at is not None
            else None
        )
        link.approved_total = total
        link.approved_max = maximum
        link.approved_by_subject = principal.subject
        link.approved_by_role = principal.role
        link.approved_at = utcnow()
        if link.state in {"INGESTED", "CORRECTING"}:
            link.state = "CORRECTED"
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.result.approved",
            entity_type="classroom_submission_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "job_id": str(job.id),
                "total": str(total),
                "max": str(maximum),
                "note": payload.note,
                "previous": previous,
            },
        )
        self.session.commit()
        return self.review(principal, link_id)

    # -- publication ------------------------------------------------------
    def _history(
        self, tenant_id: uuid.UUID, link_id: uuid.UUID
    ) -> list[ClassroomGradePublication]:
        return list(
            self.session.scalars(
                select(ClassroomGradePublication)
                .where(
                    ClassroomGradePublication.tenant_id == tenant_id,
                    ClassroomGradePublication.submission_link_id == link_id,
                )
                .order_by(ClassroomGradePublication.created_at.desc())
            )
        )

    def status(
        self, principal: Principal, link_id: uuid.UUID
    ) -> PublicationStatusRead:
        link = self._link(principal.tenant_id, link_id)
        require_course_access(self.session, principal, course_id=link.course_id)
        history = self._history(principal.tenant_id, link.id)
        return PublicationStatusRead(
            submission_link_id=link.id,
            approved_total=link.approved_total,
            published=any(row.state == "SUCCEEDED" for row in history),
            state=history[0].state if history else None,
            attempts=len(history),
            history=[GradePublicationRead.model_validate(row) for row in history],
        )

    def _record(
        self,
        link: ClassroomSubmissionLink,
        coursework: ClassroomCourseworkLink,
        principal: Principal,
        *,
        state: str,
        grade: Decimal,
        grade_field: str,
        external_before: float | None,
        detail: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        reason: str | None = None,
    ) -> ClassroomGradePublication:
        row = ClassroomGradePublication(
            tenant_id=principal.tenant_id,
            submission_link_id=link.id,
            coursework_link_id=coursework.id,
            state=state,
            draft_grade=grade if grade_field == "draftGrade" else None,
            assigned_grade=grade if grade_field == "assignedGrade" else None,
            approved_by_subject=link.approved_by_subject or "",
            approved_by_role=link.approved_by_role or principal.role,
            authorized_by_subject=principal.subject,
            reason=reason,
            external_grade_before=(
                _money(external_before) if external_before is not None else None
            ),
            response_detail=detail or {},
            error_code=error_code,
            error_message=error_message,
            attempted_at=utcnow(),
            resolved_at=utcnow() if state in {"SUCCEEDED", "FAILED"} else None,
        )
        self.session.add(row)
        return row

    def publish(
        self, principal: Principal, link_id: uuid.UUID, payload: GradePublishRequest
    ) -> GradePublicationRead:
        ensure_grade_approver(principal)
        link = self.session.scalar(
            select(ClassroomSubmissionLink)
            .where(
                ClassroomSubmissionLink.id == link_id,
                ClassroomSubmissionLink.tenant_id == principal.tenant_id,
            )
            .with_for_update()
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission link not found.")
        require_course_access(self.session, principal, course_id=link.course_id)
        coursework = self._coursework(principal.tenant_id, link)
        if coursework.state != "PUBLISHED" or not coursework.coursework_id:
            raise AppError(
                ErrorCode.CLASSROOM_ASSIGNMENT_NOT_PUBLISHED,
                "The Classroom coursework must be published before a grade can "
                "be written to it.",
            )
        require_course_access(self.session, principal, course_id=coursework.course_id)
        if link.approved_total is None or link.approved_at is None:
            raise AppError(
                ErrorCode.CLASSROOM_GRADE_NOT_APPROVED,
                "Only an approved final result can be published. Approve the "
                "result first.",
            )

        grade = _money(link.approved_total)
        if coursework.max_points is not None and grade > coursework.max_points:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The approved total exceeds the coursework's maximum points, so "
                "Google would reject it.",
                details={
                    "approved_total": str(grade),
                    "max_points": str(coursework.max_points),
                },
            )

        history = self._history(principal.tenant_id, link.id)
        for row in history:
            if (
                row.state == "SUCCEEDED"
                and payload.grade_field == "assignedGrade"
                and row.assigned_grade == grade
            ):
                # Already published at exactly this value: no second write.
                return GradePublicationRead.model_validate(row)

        access_token = self.oauth.access_token()
        try:
            current = get_submission(
                self.settings.classroom,
                access_token,
                coursework.course_id,
                coursework.coursework_id,
                link.google_submission_id,
                transport=self.oauth.transport,  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            if error.kind in {
                UpstreamKind.RECONNECT_REQUIRED,
                UpstreamKind.SCOPE_MISSING,
            }:
                self.oauth._raise_upstream(error)
            raise AppError(
                ErrorCode.CLASSROOM_UPSTREAM_ERROR,
                "The submission's current Google grade could not be read, so "
                "nothing was written.",
            ) from error

        # Reconcile an earlier uncertain attempt before writing anything.
        for row in history:
            if row.state != "UNKNOWN":
                continue
            if (
                row.assigned_grade is not None
                and current.assigned_grade is not None
                and _money(current.assigned_grade) == row.assigned_grade
            ):
                row.state = "SUCCEEDED"
                row.resolved_at = utcnow()
                row.response_detail = {
                    **row.response_detail,
                    "reconciled": (
                        "Google already holds the grade this attempt wrote."
                    ),
                }
                self.session.commit()
                if row.assigned_grade == grade:
                    return GradePublicationRead.model_validate(row)
            break

        ours = {
            row.assigned_grade
            for row in history
            if row.state == "SUCCEEDED" and row.assigned_grade is not None
        }
        if (
            payload.grade_field == "assignedGrade"
            and current.assigned_grade is not None
            and _money(current.assigned_grade) != grade
            and _money(current.assigned_grade) not in ours
            and not payload.allow_overwrite_external
        ):
            conflict = self._record(
                link,
                coursework,
                principal,
                state="CONFLICT",
                grade=grade,
                grade_field=payload.grade_field,
                external_before=current.assigned_grade,
                detail={
                    "coursework_id": coursework.coursework_id,
                    "google_submission_id": link.google_submission_id,
                },
                error_code=str(ErrorCode.CLASSROOM_PUBLISH_CONFLICT),
                error_message=(
                    "Google already holds an assigned grade this integration did "
                    "not write."
                ),
                reason=payload.reason,
            )
            self.session.commit()
            raise AppError(
                ErrorCode.CLASSROOM_PUBLISH_CONFLICT,
                "Google Classroom already holds a grade of "
                f"{current.assigned_grade} for this student. Re-publish with "
                "overwrite permission if Aetrix's approved result must replace it.",
                details={
                    "publication_id": str(conflict.id),
                    "external_grade": current.assigned_grade,
                    "approved_total": str(grade),
                },
            )

        value = float(grade)
        try:
            updated = patch_submission_grade(
                self.settings.classroom,
                access_token,
                coursework.course_id,
                coursework.coursework_id or "",
                link.google_submission_id,
                assigned_grade=value if payload.grade_field == "assignedGrade" else None,
                draft_grade=value if payload.grade_field == "draftGrade" else None,
                transport=self.oauth.transport,  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            state = (
                "UNKNOWN"
                if error.kind
                in {UpstreamKind.TRANSIENT, UpstreamKind.RECONNECT_REQUIRED}
                else "FAILED"
            )
            row = self._record(
                link,
                coursework,
                principal,
                state=state,
                grade=grade,
                grade_field=payload.grade_field,
                external_before=current.assigned_grade,
                detail={
                    "coursework_id": coursework.coursework_id,
                    "google_submission_id": link.google_submission_id,
                    "status_code": error.status_code,
                },
                error_code=f"CLASSROOM_GRADE_{state}",
                error_message=_safe_message(error.message),
                reason=payload.reason,
            )
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="classroom.grade.publish_failed",
                entity_type="classroom_grade_publication",
                entity_id=row.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "state": state,
                    "coursework_id": coursework.coursework_id,
                    "google_submission_id": link.google_submission_id,
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
                "Google Classroom did not confirm the grade write. Retrying "
                "reconciles against Google before anything is written again.",
                details={"publication_id": str(row.id), "state": state},
            ) from error

        returned = False
        return_error: str | None = None
        if payload.return_to_student:
            try:
                return_submission(
                    self.settings.classroom,
                    access_token,
                    coursework.course_id,
                    coursework.coursework_id or "",
                    link.google_submission_id,
                    transport=self.oauth.transport,  # type: ignore[arg-type]
                )
                returned = True
            except ClassroomUpstreamError as error:
                # The grade was written; failing the whole publication would be
                # wrong.  The return is reported separately.
                return_error = _safe_message(error.message)

        row = self._record(
            link,
            coursework,
            principal,
            state="SUCCEEDED",
            grade=grade,
            grade_field=payload.grade_field,
            external_before=current.assigned_grade,
            detail={
                "course_id": coursework.course_id,
                "coursework_id": coursework.coursework_id,
                "google_submission_id": link.google_submission_id,
                "grade_field": payload.grade_field,
                "grade": value,
                "google_state": updated.state,
                "returned_to_student": returned,
                "return_error": return_error,
            },
            reason=payload.reason,
        )
        if link.state != "CORRECTED":
            link.state = "CORRECTED"
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.grade.published",
            entity_type="classroom_grade_publication",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "coursework_id": coursework.coursework_id,
                "google_submission_id": link.google_submission_id,
                "grade_field": payload.grade_field,
                "grade": value,
                "approved_by": link.approved_by_subject,
                "returned_to_student": returned,
            },
        )
        self.session.commit()
        self.session.refresh(row)
        return GradePublicationRead.model_validate(row)
