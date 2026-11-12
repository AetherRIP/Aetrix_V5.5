"""Tenant-scoped aggregation for the workspace screens.

Every count and figure here is computed from stored rows.  Where there is not
enough data to state a figure honestly the field is null and the row's ``state``
says ``INSUFFICIENT_DATA``; no mean is defaulted to zero.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..correction.guard import RESULT_SOURCE_REFUSED
from ..correction.processing import effective_state, is_scoreable
from ..db.models import (
    Assignment,
    AuditEvent,
    CorrectionJob,
    JobApproval,
    QuestionResult,
    Submission,
)
from ..db.repositories import (
    InvitationRepository,
    ResultRepository,
    SubmissionRepository,
)
from ..jobs.states import ACTIVE_STATES, JobState
from ..schemas.workspace import (
    AuditEventRead,
    DashboardRead,
    GradebookAssignment,
    GradebookCell,
    GradebookRead,
    GradebookStudent,
    InboxItemRead,
    MarkingHistoryPage,
    MarkingHistoryRow,
    NotificationRead,
    ReportRow,
)

_FAILED_STATES = {JobState.FAILED.value, JobState.RETRY_SUSPENDED.value}

#: A job is "provisional" only when it produced marks a person has not approved
#: yet.  A failed, cancelled or unstarted job produced nothing to approve, so
#: counting it as provisional would overstate the work awaiting sign-off.
_MARKED_STATES = {JobState.COMPLETED.value, JobState.REVIEW_REQUIRED.value}


class WorkspaceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.submissions = SubmissionRepository(session)
        self.results = ResultRepository(session)

    def _check(self, principal: Principal, workspace_id: uuid.UUID) -> None:
        if workspace_id != principal.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")

    def _count(self, model: object, *conditions: object) -> int:
        value = self.session.scalar(
            select(func.count()).select_from(model).where(*conditions)  # type: ignore[arg-type]
        )
        return int(value or 0)

    # -- dashboard -------------------------------------------------------
    def dashboard(
        self, principal: Principal, workspace_id: uuid.UUID
    ) -> DashboardRead:
        self._check(principal, workspace_id)
        tenant = principal.tenant_id
        active = [state.value for state in ACTIVE_STATES]
        jobs = list(
            self.session.scalars(
                select(CorrectionJob)
                .where(CorrectionJob.tenant_id == tenant)
                .order_by(CorrectionJob.updated_at.desc())
                .limit(8)
            )
        )
        students = {
            submission.id: submission.student_ref
            for submission in self.session.scalars(
                select(Submission).where(
                    Submission.tenant_id == tenant,
                    Submission.id.in_([job.submission_id for job in jobs]),
                )
            )
        }
        return DashboardRead(
            assignments=self._count(Assignment, Assignment.tenant_id == tenant),
            submissions=self._count(Submission, Submission.tenant_id == tenant),
            jobs_active=self._count(
                CorrectionJob,
                CorrectionJob.tenant_id == tenant,
                CorrectionJob.state.in_(active),
            ),
            awaiting_review=self._count(
                CorrectionJob,
                CorrectionJob.tenant_id == tenant,
                CorrectionJob.state == JobState.REVIEW_REQUIRED.value,
            ),
            # A parked job is waiting for an operator, not broken; the lifecycle
            # documents RETRY_SUSPENDED as "not a failure", so it is excluded.
            failed_jobs=self._count(
                CorrectionJob,
                CorrectionJob.tenant_id == tenant,
                CorrectionJob.state == JobState.FAILED.value,
            ),
            approved_results=self._count(
                JobApproval, JobApproval.tenant_id == tenant
            ),
            recent_jobs=[
                {
                    "id": str(job.id),
                    "submission_id": str(job.submission_id),
                    "student_ref": students.get(job.submission_id),
                    "state": job.state,
                    "progress": job.progress,
                    "error_code": job.error_code,
                    "updated_at": job.updated_at.isoformat(),
                }
                for job in jobs
            ],
        )

    # -- inbox -----------------------------------------------------------
    def inbox(self, principal: Principal, workspace_id: uuid.UUID) -> list[InboxItemRead]:
        self._check(principal, workspace_id)
        jobs = list(
            self.session.scalars(
                select(CorrectionJob)
                .where(
                    CorrectionJob.tenant_id == principal.tenant_id,
                    CorrectionJob.state.in_(
                        [JobState.REVIEW_REQUIRED.value, *_FAILED_STATES]
                    ),
                )
                .order_by(CorrectionJob.updated_at.desc())
                .limit(50)
            )
        )
        if not jobs:
            return []
        submissions = {
            row.id: row
            for row in self.session.scalars(
                select(Submission).where(
                    Submission.tenant_id == principal.tenant_id,
                    Submission.id.in_([job.submission_id for job in jobs]),
                )
            )
        }
        counts: dict[uuid.UUID, int] = {}
        for job_id, count in self.session.execute(
            select(QuestionResult.job_id, func.count())
            .where(
                QuestionResult.tenant_id == principal.tenant_id,
                QuestionResult.job_id.in_([job.id for job in jobs]),
                QuestionResult.review_required.is_(True),
            )
            .group_by(QuestionResult.job_id)
        ):
            counts[job_id] = int(count)

        items: list[InboxItemRead] = []
        for job in jobs:
            submission = submissions.get(job.submission_id)
            student = submission.student_ref if submission else "an unknown student"
            if job.state == JobState.REVIEW_REQUIRED.value:
                pending = counts.get(job.id, 0)
                items.append(
                    InboxItemRead(
                        id=str(job.id),
                        kind="REVIEW_REQUIRED",
                        title=f"{student} needs review",
                        detail=(
                            f"{pending} question(s) could not be marked with confidence."
                            if pending
                            else "The engine stopped this job for a human decision."
                        ),
                        created_at=job.updated_at,
                        job_id=job.id,
                        submission_id=job.submission_id,
                    )
                )
            else:
                items.append(
                    InboxItemRead(
                        id=str(job.id),
                        kind="JOB_FAILED",
                        title=f"{student} could not be marked",
                        detail=job.error_message or job.error_code or "The job did not finish.",
                        created_at=job.updated_at,
                        job_id=job.id,
                        submission_id=job.submission_id,
                    )
                )
        return items

    # -- reports ---------------------------------------------------------
    def reports(self, principal: Principal, workspace_id: uuid.UUID) -> list[ReportRow]:
        self._check(principal, workspace_id)
        tenant = principal.tenant_id
        assignments = list(
            self.session.scalars(
                select(Assignment)
                .where(Assignment.tenant_id == tenant)
                .order_by(Assignment.created_at.desc())
            )
        )
        submissions = list(
            self.session.scalars(select(Submission).where(Submission.tenant_id == tenant))
        )
        jobs = list(
            self.session.scalars(
                select(CorrectionJob).where(CorrectionJob.tenant_id == tenant)
            )
        )
        approvals = set(
            self.session.scalars(
                select(JobApproval.job_id).where(JobApproval.tenant_id == tenant)
            )
        )
        results = self.results.list_for_jobs(tenant, [job.id for job in jobs])
        results_by_job: dict[uuid.UUID, list[QuestionResult]] = defaultdict(list)
        for row in results:
            results_by_job[row.job_id].append(row)

        submissions_by_assignment: dict[uuid.UUID, int] = defaultdict(int)
        for submission in submissions:
            submissions_by_assignment[submission.assignment_id] += 1
        jobs_by_assignment: dict[uuid.UUID, list[CorrectionJob]] = defaultdict(list)
        for job in jobs:
            jobs_by_assignment[job.assignment_id].append(job)

        rows: list[ReportRow] = []
        for assignment in assignments:
            assignment_jobs = jobs_by_assignment.get(assignment.id, [])
            approved_jobs = [job for job in assignment_jobs if job.id in approvals]
            percentages: list[float] = []
            total_marks = 0
            for job in approved_jobs:
                job_results = results_by_job.get(job.id, [])
                possible = sum(row.max_marks for row in job_results)
                if possible <= 0:
                    continue
                total_marks = max(total_marks, possible)
                percentages.append(sum(row.awarded_marks for row in job_results) / possible * 100)
            rows.append(
                ReportRow(
                    assignment_id=assignment.id,
                    name=assignment.name,
                    submissions=submissions_by_assignment.get(assignment.id, 0),
                    jobs_completed=sum(
                        1
                        for job in assignment_jobs
                        if job.state == JobState.COMPLETED.value
                    ),
                    awaiting_review=sum(
                        1
                        for job in assignment_jobs
                        if job.state == JobState.REVIEW_REQUIRED.value
                    ),
                    failed=sum(1 for job in assignment_jobs if job.state in _FAILED_STATES),
                    approved=len(approved_jobs),
                    total_marks=total_marks,
                    mean_percent=(sum(percentages) / len(percentages)) if percentages else None,
                    state="OK" if percentages else "INSUFFICIENT_DATA",
                )
            )
        return rows

    # -- gradebook -------------------------------------------------------
    def gradebook(
        self,
        principal: Principal,
        workspace_id: uuid.UUID,
        assignment_id: uuid.UUID | None = None,
    ) -> GradebookRead:
        self._check(principal, workspace_id)
        tenant = principal.tenant_id
        statement = select(Assignment).where(Assignment.tenant_id == tenant)
        if assignment_id is not None:
            statement = statement.where(Assignment.id == assignment_id)
        assignments = list(
            self.session.scalars(statement.order_by(Assignment.created_at.asc()))
        )
        if assignment_id is not None and not assignments:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        assignment_ids = [assignment.id for assignment in assignments]
        if not assignment_ids:
            return GradebookRead(
                assignments=[],
                students=[],
                approved_jobs=0,
                provisional_jobs=0,
                mean_percent=None,
                state="INSUFFICIENT_DATA",
            )

        submissions = list(
            self.session.scalars(
                select(Submission).where(
                    Submission.tenant_id == tenant,
                    Submission.assignment_id.in_(assignment_ids),
                )
            )
        )
        # A refused run is not a result, so it is excluded here as well as on the
        # review screen: otherwise the newest refused run would become the cell a
        # teacher sees, and the paper's total would be taken from it.
        jobs = list(
            self.session.scalars(
                select(CorrectionJob)
                .where(
                    CorrectionJob.tenant_id == tenant,
                    CorrectionJob.assignment_id.in_(assignment_ids),
                    or_(
                        CorrectionJob.result_source.is_(None),
                        CorrectionJob.result_source != RESULT_SOURCE_REFUSED,
                    ),
                )
                .order_by(CorrectionJob.created_at.asc())
            )
        )
        approvals = set(
            self.session.scalars(
                select(JobApproval.job_id).where(JobApproval.tenant_id == tenant)
            )
        )
        results = self.results.list_for_jobs(tenant, [job.id for job in jobs])
        results_by_job: dict[uuid.UUID, list[QuestionResult]] = defaultdict(list)
        for row in results:
            results_by_job[row.job_id].append(row)

        # The assignment's total is the sum of its marked question maxima, which
        # is only knowable once a job has produced results.  Until then it stays
        # 0 rather than being guessed from an unrelated blueprint field.
        total_by_assignment: dict[uuid.UUID, int] = {
            assignment.id: 0 for assignment in assignments
        }
        for job in jobs:
            rows = results_by_job.get(job.id, [])
            possible = sum(row.max_marks for row in rows)
            if possible:
                total_by_assignment[job.assignment_id] = max(
                    total_by_assignment.get(job.assignment_id, 0), possible
                )

        latest_job: dict[tuple[uuid.UUID, uuid.UUID], CorrectionJob] = {}
        for job in jobs:
            latest_job[(job.assignment_id, job.submission_id)] = job

        submission_by_key: dict[tuple[uuid.UUID, str], Submission] = {}
        for submission in submissions:
            submission_by_key[(submission.assignment_id, submission.student_ref)] = submission

        students = sorted({submission.student_ref for submission in submissions})
        assignment_cards: list[GradebookAssignment] = []
        for assignment in assignments:
            assignment_jobs = [job for job in jobs if job.assignment_id == assignment.id]
            assignment_cards.append(
                GradebookAssignment(
                    id=assignment.id,
                    name=assignment.name,
                    total_marks=total_by_assignment.get(assignment.id, 0),
                    approved_jobs=sum(1 for job in assignment_jobs if job.id in approvals),
                    provisional_jobs=sum(
                        1
                        for job in assignment_jobs
                        if job.id not in approvals and job.state in _MARKED_STATES
                    ),
                )
            )

        student_rows: list[GradebookStudent] = []
        approved_jobs = 0
        provisional_jobs = 0
        percentages: list[float] = []
        for student_ref in students:
            cells: list[GradebookCell] = []
            approved_awarded = 0
            approved_possible = 0
            for assignment in assignments:
                submission = submission_by_key.get((assignment.id, student_ref))
                job = (
                    latest_job.get((assignment.id, submission.id))
                    if submission is not None
                    else None
                )
                rows = results_by_job.get(job.id, []) if job is not None else []
                # An undecided question has no mark: counting its placeholder
                # zero against the maximum would report a failure that never
                # happened.  The cell states the decided fraction instead.
                decided_rows = [
                    row
                    for row in rows
                    if row.status != "EXCLUDED"
                    and is_scoreable(
                        effective_state(
                            row.status,
                            row.processing_state,
                            review_required=bool(row.review_required),
                        )
                    )
                ]
                awarded = (
                    sum(row.awarded_marks for row in decided_rows)
                    if decided_rows
                    else None
                )
                possible = sum(row.max_marks for row in decided_rows)
                approved = job is not None and job.id in approvals
                if approved and possible:
                    approved_awarded += awarded or 0
                    approved_possible += possible
                cells.append(
                    GradebookCell(
                        assignment_id=assignment.id,
                        submission_id=submission.id if submission else None,
                        job_id=job.id if job else None,
                        job_state=job.state if job else None,
                        awarded=awarded,
                        total=possible,
                        approved=approved,
                        review_required=sum(1 for row in rows if row.review_required),
                    )
                )
            if approved_possible:
                percentages.append(approved_awarded / approved_possible * 100)
            student_rows.append(
                GradebookStudent(
                    student_ref=student_ref,
                    cells=cells,
                    approved_awarded=approved_awarded,
                    approved_possible=approved_possible,
                )
            )

        for job in jobs:
            if job.id in approvals:
                approved_jobs += 1
            elif job.state in _MARKED_STATES:
                provisional_jobs += 1

        return GradebookRead(
            assignments=assignment_cards,
            students=student_rows,
            approved_jobs=approved_jobs,
            provisional_jobs=provisional_jobs,
            mean_percent=(sum(percentages) / len(percentages)) if percentages else None,
            state="OK" if percentages else "INSUFFICIENT_DATA",
        )

    # -- notifications ---------------------------------------------------
    def notifications(
        self, principal: Principal, workspace_id: uuid.UUID, *, limit: int = 50
    ) -> list[NotificationRead]:
        """Real, addressable events — nothing is seeded and nothing is marked read."""
        self._check(principal, workspace_id)
        tenant = principal.tenant_id
        items: list[NotificationRead] = [
            NotificationRead(
                id=f"job:{item.id}",
                kind=item.kind,
                title=item.title,
                detail=item.detail,
                created_at=item.created_at,
                job_id=item.job_id,
                submission_id=item.submission_id,
            )
            for item in self.inbox(principal, workspace_id)
        ]

        # Pending invitations are only a manager's business; a reviewer is not
        # told which addresses the workspace is recruiting.
        if principal.role in {"OWNER", "ADMIN", "PLATFORM_OWNER"}:
            for invitation in InvitationRepository(self.session).list_for_tenant(
                tenant, status="PENDING", limit=limit
            ):
                items.append(
                    NotificationRead(
                        id=f"invitation:{invitation.id}",
                        kind="INVITATION_PENDING",
                        title="Invitation awaiting acceptance",
                        detail=(
                            f"{invitation.email} · {invitation.role} · "
                            f"expires {invitation.expires_at.isoformat()}"
                        ),
                        created_at=invitation.created_at,
                        invitation_id=invitation.id,
                    )
                )

        approvals = list(
            self.session.scalars(
                select(JobApproval)
                .where(JobApproval.tenant_id == tenant)
                .order_by(JobApproval.approved_at.desc())
                .limit(limit)
            )
        )
        for approval in approvals:
            items.append(
                NotificationRead(
                    id=f"approval:{approval.id}",
                    kind="RESULT_APPROVED",
                    title="Results approved",
                    detail=(
                        f"{approval.approved_marks} of {approval.total_marks} marks approved"
                        f" by {approval.approved_by_label or 'an engine account'}."
                    ),
                    created_at=approval.approved_at,
                    job_id=approval.job_id,
                )
            )

        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    # -- marking history -------------------------------------------------
    def marking_history(
        self,
        principal: Principal,
        workspace_id: uuid.UUID,
        *,
        limit: int = 25,
        offset: int = 0,
        state: str | None = None,
    ) -> MarkingHistoryPage:
        self._check(principal, workspace_id)
        tenant = principal.tenant_id
        conditions = [CorrectionJob.tenant_id == tenant]
        if state:
            conditions.append(CorrectionJob.state == state)

        total = int(
            self.session.scalar(
                select(func.count()).select_from(CorrectionJob).where(*conditions)
            )
            or 0
        )
        jobs = list(
            self.session.scalars(
                select(CorrectionJob)
                .where(*conditions)
                .order_by(CorrectionJob.updated_at.desc(), CorrectionJob.id.asc())
                .limit(limit)
                .offset(offset)
            )
        )
        if not jobs:
            return MarkingHistoryPage(items=[], total=total, limit=limit, offset=offset)

        job_ids = [job.id for job in jobs]
        assignments = {
            row.id: row.name
            for row in self.session.scalars(
                select(Assignment).where(
                    Assignment.tenant_id == tenant,
                    Assignment.id.in_([job.assignment_id for job in jobs]),
                )
            )
        }
        submissions = {
            row.id: row.student_ref
            for row in self.session.scalars(
                select(Submission).where(
                    Submission.tenant_id == tenant,
                    Submission.id.in_([job.submission_id for job in jobs]),
                )
            )
        }
        results_by_job: dict[uuid.UUID, list[QuestionResult]] = defaultdict(list)
        for row in self.results.list_for_jobs(tenant, job_ids):
            results_by_job[row.job_id].append(row)
        approvals = {
            row.job_id: row
            for row in self.session.scalars(
                select(JobApproval).where(
                    JobApproval.tenant_id == tenant, JobApproval.job_id.in_(job_ids)
                )
            )
        }

        items: list[MarkingHistoryRow] = []
        for job in jobs:
            rows = results_by_job.get(job.id, [])
            approval = approvals.get(job.id)
            items.append(
                MarkingHistoryRow(
                    job_id=job.id,
                    submission_id=job.submission_id,
                    assignment_id=job.assignment_id,
                    assignment_name=assignments.get(job.assignment_id),
                    student_ref=submissions.get(job.submission_id),
                    state=job.state,
                    progress=job.progress,
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                    error_code=job.error_code,
                    error_message=job.error_message,
                    awarded=sum(row.awarded_marks for row in rows),
                    total=sum(row.max_marks for row in rows),
                    review_required=sum(1 for row in rows if row.review_required),
                    approved=approval is not None,
                    approved_at=approval.approved_at if approval else None,
                    approved_by_label=approval.approved_by_label if approval else None,
                    updated_at=job.updated_at,
                )
            )
        return MarkingHistoryPage(items=items, total=total, limit=limit, offset=offset)

    # -- audit -----------------------------------------------------------
    def audit(
        self,
        principal: Principal,
        workspace_id: uuid.UUID,
        *,
        action: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEventRead]:
        self._check(principal, workspace_id)
        return self._audit_rows(
            tenant_id=principal.tenant_id,
            action=action,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
        )

    def platform_audit(
        self,
        principal: Principal,
        *,
        action: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEventRead]:
        if principal.role != "PLATFORM_OWNER":
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Platform audit is restricted to the platform operator.",
            )
        return self._audit_rows(
            tenant_id=None,
            action=action,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
        )

    def _audit_rows(
        self,
        *,
        tenant_id: uuid.UUID | None,
        action: str | None,
        entity_type: str | None,
        limit: int,
        offset: int,
    ) -> list[AuditEventRead]:
        statement = select(AuditEvent)
        if tenant_id is not None:
            statement = statement.where(AuditEvent.tenant_id == tenant_id)
        if action:
            statement = statement.where(AuditEvent.action == action)
        if entity_type:
            statement = statement.where(AuditEvent.entity_type == entity_type)
        rows = self.session.scalars(
            statement.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
        )
        # Audit rows are ORM instances, so they are read through attribute mode;
        # without it the audit routes answered 500 instead of listing events.
        return [AuditEventRead.model_validate(row, from_attributes=True) for row in rows]
