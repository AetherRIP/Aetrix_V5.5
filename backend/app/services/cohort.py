"""Question-level cohort intelligence from stored marking results.

The population is explicit and conservative:

* only submissions that are not ``FAILED`` are eligible;
* for each submission the latest job that is neither cancelled nor refused is
  used, so an older run never double-counts a student;
* only jobs that reached ``COMPLETED`` or ``REVIEW_REQUIRED`` contribute;
* a question is decided only when the existing processing-state rules say it is
  scoreable, so an unmarked question is never a zero;
* ``EXCLUDED`` rows are counted and left out of every denominator.

Approved and provisional results are both reported, with separate sample counts.
Topic analysis is reported as unavailable because no blueprint, scheme or result
row carries topic metadata; inventing a classification would be worse than
saying so.
"""

from __future__ import annotations

import re
import statistics
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..correction.guard import RESULT_SOURCE_REFUSED
from ..correction.processing import effective_state, is_scoreable
from ..db.models import (
    Assignment,
    ClassroomAllocation,
    ClassroomClassAssignment,
    CorrectionJob,
    JobApproval,
    QuestionResult,
    Submission,
)
from ..jobs.states import JobState
from ..schemas.cohort import (
    CohortAssignmentRead,
    CohortCompletenessRead,
    CohortOverviewRead,
    CohortQuestionChangeRead,
    CohortQuestionRead,
    CohortRead,
    CohortStudentRead,
    CohortTopicsRead,
    CohortTrendPointRead,
    CohortTrendsRead,
    MarkCount,
)
from .classroom_access import ASSIGNABLE_ROLES, is_class_manager

#: Below this many decided results a question or student is not characterised.
MIN_SAMPLE = 3
#: A question below this average is flagged for attention (with a large sample).
ATTENTION_PERCENT = 50.0
#: A student below this overall percentage is flagged for support.
SUPPORT_PERCENT = 50.0
#: How many earlier assignments of the same class a trend reads.
TREND_LIMIT = 5
#: The only job states whose rows may stand as a paper's result.
_MARKED_STATES = {JobState.COMPLETED.value, JobState.REVIEW_REQUIRED.value}


def _order(question_id: str) -> tuple[tuple[int, object], ...]:
    """Natural order for question ids such as 1, 1a, 1b, 2, 10."""

    parts = re.split(r"(\d+)", question_id)
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part)


def _pct(awarded: int, maximum: int) -> float | None:
    return (awarded / maximum * 100.0) if maximum > 0 else None


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


@dataclass
class _Question:
    sample: int = 0
    approved: int = 0
    provisional: int = 0
    pending: int = 0
    maxima: set[int] = field(default_factory=set)
    awards: list[int] = field(default_factory=list)
    percentages: list[float] = field(default_factory=list)
    full: int = 0
    zero: int = 0
    partial: int = 0
    struggling: int = 0
    distribution: Counter[int] = field(default_factory=Counter)


@dataclass
class _Student:
    submission: Submission
    job: CorrectionJob
    approved: bool
    awarded: int
    possible: int
    decided: int
    full: int
    zero: int
    low: list[str]

    @property
    def percentage(self) -> float | None:
        return _pct(self.awarded, self.possible)

    @property
    def flagged(self) -> bool:
        percentage = self.percentage
        return (
            self.decided >= MIN_SAMPLE
            and percentage is not None
            and percentage < SUPPORT_PERCENT
        )


@dataclass
class _AssignmentData:
    assignment: Assignment
    submissions: list[Submission]
    jobs: dict[uuid.UUID, CorrectionJob]
    approvals: set[uuid.UUID]
    rows: dict[uuid.UUID, list[QuestionResult]] = field(default_factory=dict)
    students: list[_Student] = field(default_factory=list)
    questions: dict[str, _Question] = field(default_factory=dict)

    @property
    def eligible(self) -> list[Submission]:
        return [item for item in self.submissions if item.status != "FAILED"]

    @property
    def included(self) -> list[_Student]:
        return self.students


class CohortService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- authorisation ---------------------------------------------------
    def _assignment(self, principal: Principal, workspace_id: uuid.UUID, assignment_id: uuid.UUID):
        if workspace_id != principal.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        assignment = self.session.scalar(
            select(Assignment).where(
                Assignment.tenant_id == principal.tenant_id,
                Assignment.id == assignment_id,
            )
        )
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        return assignment

    def _scope(self, principal: Principal, assignment: Assignment) -> str:
        """Class access when the assignment names one, workspace otherwise.

        A released allocation behaves like an absent assignment rather than a
        forbidden one, so a teacher cannot learn that another workspace holds it.
        """

        if assignment.classroom_allocation_id is None:
            return "WORKSPACE"
        allocation = self.session.get(ClassroomAllocation, assignment.classroom_allocation_id)
        if (
            allocation is None
            or allocation.workspace_id != principal.tenant_id
            or allocation.status != "ACTIVE"
        ):
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        if is_class_manager(principal):
            return "CLASS"
        if principal.role not in ASSIGNABLE_ROLES:
            raise AppError(ErrorCode.NOT_FOUND, "That class is not assigned to you.")
        assigned = self.session.scalar(
            select(ClassroomClassAssignment.id).where(
                ClassroomClassAssignment.allocation_id == allocation.id,
                ClassroomClassAssignment.workspace_id == principal.tenant_id,
                ClassroomClassAssignment.user_id == principal.user_id,
            )
        )
        if assigned is None:
            raise AppError(ErrorCode.NOT_FOUND, "That class is not assigned to you.")
        return "CLASS"

    # -- bulk reads ------------------------------------------------------
    def _collect(
        self, tenant_id: uuid.UUID, assignments: list[Assignment]
    ) -> list[_AssignmentData]:
        """Read every assignment's evidence in a bounded number of queries."""

        if not assignments:
            return []
        ids = [assignment.id for assignment in assignments]
        submissions = list(
            self.session.scalars(
                select(Submission).where(
                    Submission.tenant_id == tenant_id,
                    Submission.assignment_id.in_(ids),
                )
            )
        )
        jobs = list(
            self.session.scalars(
                select(CorrectionJob)
                .where(
                    CorrectionJob.tenant_id == tenant_id,
                    CorrectionJob.assignment_id.in_(ids),
                    CorrectionJob.state != JobState.CANCELLED.value,
                    or_(
                        CorrectionJob.result_source.is_(None),
                        CorrectionJob.result_source != RESULT_SOURCE_REFUSED,
                    ),
                )
                .order_by(CorrectionJob.created_at.asc())
            )
        )
        latest: dict[tuple[uuid.UUID, uuid.UUID], CorrectionJob] = {}
        for job in jobs:
            latest[(job.assignment_id, job.submission_id)] = job

        job_ids = [job.id for job in latest.values() if job.state in _MARKED_STATES]
        approvals: set[uuid.UUID] = set()
        rows: list[QuestionResult] = []
        if job_ids:
            approvals = set(
                self.session.scalars(
                    select(JobApproval.job_id).where(
                        JobApproval.tenant_id == tenant_id,
                        JobApproval.job_id.in_(job_ids),
                    )
                )
            )
            rows = list(
                self.session.scalars(
                    select(QuestionResult).where(
                        QuestionResult.tenant_id == tenant_id,
                        QuestionResult.job_id.in_(job_ids),
                    )
                )
            )

        submissions_by_assignment: dict[uuid.UUID, list[Submission]] = defaultdict(list)
        for submission in submissions:
            submissions_by_assignment[submission.assignment_id].append(submission)
        rows_by_job: dict[uuid.UUID, list[QuestionResult]] = defaultdict(list)
        for row in rows:
            rows_by_job[row.job_id].append(row)

        result: list[_AssignmentData] = []
        for assignment in assignments:
            data = _AssignmentData(
                assignment=assignment,
                submissions=submissions_by_assignment.get(assignment.id, []),
                jobs={
                    submission_id: job
                    for (assignment_id, submission_id), job in latest.items()
                    if assignment_id == assignment.id
                },
                approvals=approvals,
                rows={job_id: rows_by_job.get(job_id, []) for job_id in rows_by_job},
            )
            self._summarise(data)
            result.append(data)
        return result

    def _summarise(self, data: _AssignmentData) -> None:
        questions: dict[str, _Question] = defaultdict(_Question)
        for submission in data.eligible:
            job = data.jobs.get(submission.id)
            if job is None or job.state not in _MARKED_STATES:
                continue
            approved = job.id in data.approvals
            decided_rows: list[QuestionResult] = []
            for row in data.rows.get(job.id, []):
                if row.status == "EXCLUDED":
                    continue
                state = effective_state(
                    row.status,
                    row.processing_state,
                    review_required=bool(row.review_required),
                )
                if not is_scoreable(state):
                    questions[row.question_id].pending += 1
                    continue
                decided_rows.append(row)
                bucket = questions[row.question_id]
                bucket.sample += 1
                bucket.approved += int(approved)
                bucket.provisional += int(not approved)
                bucket.maxima.add(row.max_marks)
                bucket.awards.append(row.awarded_marks)
                bucket.distribution[row.awarded_marks] += 1
                percentage = _pct(row.awarded_marks, row.max_marks)
                if percentage is not None:
                    bucket.percentages.append(percentage)
                    if percentage < ATTENTION_PERCENT:
                        bucket.struggling += 1
                if row.awarded_marks == row.max_marks:
                    bucket.full += 1
                elif row.awarded_marks == 0:
                    bucket.zero += 1
                else:
                    bucket.partial += 1
            if decided_rows:
                possible = sum(row.max_marks for row in decided_rows)
                awarded = sum(row.awarded_marks for row in decided_rows)
                data.students.append(
                    _Student(
                        submission=submission,
                        job=job,
                        approved=approved,
                        awarded=awarded,
                        possible=possible,
                        decided=len(decided_rows),
                        full=sum(
                            1 for row in decided_rows if row.awarded_marks == row.max_marks
                        ),
                        zero=sum(1 for row in decided_rows if row.awarded_marks == 0),
                        low=[
                            row.question_id
                            for row in decided_rows
                            if (_pct(row.awarded_marks, row.max_marks) or 0.0)
                            < ATTENTION_PERCENT
                        ],
                    )
                )
        data.questions = dict(questions)
        data.students.sort(
            key=lambda item: (
                not item.flagged,
                item.percentage if item.percentage is not None else 101.0,
                item.submission.student_ref,
            )
        )

    # -- response --------------------------------------------------------
    def _question_read(self, question_id: str, bucket: _Question) -> CohortQuestionRead:
        single_max = next(iter(bucket.maxima)) if len(bucket.maxima) == 1 else None
        average_percent = (
            statistics.fmean(bucket.percentages) if bucket.percentages else None
        )
        state = (
            "NO_RESULTS"
            if bucket.sample == 0
            else "INSUFFICIENT_SAMPLE"
            if bucket.sample < MIN_SAMPLE
            else "OK"
        )
        return CohortQuestionRead(
            question_id=question_id,
            max_marks=single_max,
            max_marks_min=min(bucket.maxima) if bucket.maxima else 0,
            max_marks_max=max(bucket.maxima) if bucket.maxima else 0,
            sample_size=bucket.sample,
            approved_sample=bucket.approved,
            provisional_sample=bucket.provisional,
            pending_count=bucket.pending,
            average_marks=_round(
                statistics.fmean(bucket.awards) if bucket.awards else None
            ),
            average_percent=_round(average_percent),
            median_percent=_round(
                statistics.median(bucket.percentages) if bucket.percentages else None
            ),
            full_marks=bucket.full,
            zero_marks=bucket.zero,
            partial_marks=bucket.partial,
            struggling_count=bucket.struggling,
            struggling_percent=_round(
                bucket.struggling / bucket.sample * 100.0 if bucket.sample else None
            ),
            distribution=[
                MarkCount(marks=marks, count=count)
                for marks, count in sorted(bucket.distribution.items())
            ],
            state=state,
            attention=(
                state == "OK"
                and average_percent is not None
                and average_percent < ATTENTION_PERCENT
            ),
        )

    def _student_read(self, student: _Student) -> CohortStudentRead:
        percentage = _round(student.percentage)
        if student.flagged:
            low = ", ".join(student.low[:5]) if student.low else "none"
            evidence = (
                f"{student.decided} decided question(s), {percentage}% overall; "
                f"{len(student.low)} below {ATTENTION_PERCENT:.0f}% ({low})."
            )
        else:
            evidence = (
                f"{student.decided} decided question(s), {percentage}% overall; "
                f"at least {MIN_SAMPLE} decided questions and below "
                f"{SUPPORT_PERCENT:.0f}% are required to flag support."
            )
        return CohortStudentRead(
            student_ref=student.submission.student_ref,
            job_id=student.job.id,
            job_state=student.job.state,
            approved=student.approved,
            decided=student.decided,
            awarded=student.awarded,
            possible=student.possible,
            percentage=percentage,
            full_marks=student.full,
            zero_marks=student.zero,
            low_question_ids=student.low,
            support_flagged=student.flagged,
            evidence=evidence,
        )

    def _trends(
        self,
        current: _AssignmentData,
        peers: list[_AssignmentData],
    ) -> CohortTrendsRead:
        timeline = sorted(
            [*peers, current], key=lambda item: item.assignment.created_at
        )
        points: list[CohortTrendPointRead] = []
        for data in timeline:
            percentages = [
                student.percentage
                for student in data.students
                if student.percentage is not None
            ]
            mean = statistics.fmean(percentages) if percentages else None
            approved = sum(1 for student in data.students if student.approved)
            points.append(
                CohortTrendPointRead(
                    assignment_id=data.assignment.id,
                    name=data.assignment.name,
                    created_at=data.assignment.created_at,
                    mean_percent=_round(mean),
                    included_students=len(data.students),
                    approved_jobs=approved,
                    state=(
                        "OK"
                        if percentages and approved
                        else "PROVISIONAL"
                        if percentages
                        else "INSUFFICIENT_DATA"
                    ),
                )
            )

        if len(points) < 2:
            return CohortTrendsRead(
                state="INSUFFICIENT_DATA",
                reason=(
                    "This class has only one assignment with stored results, so no "
                    "assignment-to-assignment comparison exists yet."
                ),
                points=points,
                question_changes=[],
            )

        # Compare only the nearest earlier assignment, and only a question whose
        # identifier and maximum marks both match.  Anything else is a broader
        # trend, which the point list already reports.
        earlier = [
            data
            for data in timeline
            if data.assignment.created_at < current.assignment.created_at
        ]
        changes: list[CohortQuestionChangeRead] = []
        previous = earlier[-1] if earlier else None
        if previous is not None:
            for question_id, bucket in current.questions.items():
                old = previous.questions.get(question_id)
                if old is None or old.sample < MIN_SAMPLE or bucket.sample < MIN_SAMPLE:
                    continue
                if len(bucket.maxima) != 1 or bucket.maxima != old.maxima:
                    continue
                old_percent = (
                    statistics.fmean(old.percentages) if old.percentages else None
                )
                new_percent = (
                    statistics.fmean(bucket.percentages) if bucket.percentages else None
                )
                if old_percent is None or new_percent is None:
                    continue
                changes.append(
                    CohortQuestionChangeRead(
                        question_id=question_id,
                        max_marks=next(iter(bucket.maxima)),
                        previous_assignment_id=previous.assignment.id,
                        previous_percent=_round(old_percent) or 0.0,
                        current_percent=_round(new_percent) or 0.0,
                        delta_percent=round(new_percent - old_percent, 2),
                    )
                )
        return CohortTrendsRead(
            state="OK",
            reason=None,
            points=points,
            question_changes=sorted(changes, key=lambda item: item.delta_percent),
        )

    def analyse(
        self,
        principal: Principal,
        workspace_id: uuid.UUID,
        assignment_id: uuid.UUID,
    ) -> CohortRead:
        assignment = self._assignment(principal, workspace_id, assignment_id)
        scope = self._scope(principal, assignment)
        tenant = principal.tenant_id

        peer_statement = select(Assignment).where(
            Assignment.tenant_id == tenant,
            Assignment.id != assignment.id,
        )
        if assignment.classroom_allocation_id is not None:
            peer_statement = peer_statement.where(
                Assignment.classroom_allocation_id == assignment.classroom_allocation_id
            )
        elif assignment.course_id is not None:
            peer_statement = peer_statement.where(Assignment.course_id == assignment.course_id)
        else:
            peer_statement = peer_statement.where(
                Assignment.classroom_allocation_id.is_(None),
                Assignment.course_id.is_(None),
            )
        peer_assignments = list(
            self.session.scalars(
                peer_statement.order_by(Assignment.created_at.desc()).limit(TREND_LIMIT)
            )
        )
        collected = {
            data.assignment.id: data
            for data in self._collect(tenant, [assignment, *peer_assignments])
        }
        current = collected[assignment.id]
        peers = [collected[item.id] for item in peer_assignments if item.id in collected]

        questions = [
            self._question_read(question_id, current.questions[question_id])
            for question_id in sorted(current.questions, key=_order)
        ]
        students = [self._student_read(student) for student in current.students]
        percentages = [item.percentage for item in students if item.percentage is not None]
        approved_students = [
            item for item in students if item.approved and item.percentage is not None
        ]
        approved_percentages = [
            item.percentage for item in approved_students if item.percentage is not None
        ]
        approved_jobs = sum(1 for student in current.students if student.approved)
        provisional_jobs = len(current.students) - approved_jobs
        attention = [item for item in questions if item.attention]
        overview_state = (
            "OK"
            if current.students and approved_jobs
            else "PROVISIONAL"
            if current.students
            else "INSUFFICIENT_DATA"
        )

        decided_rows = 0
        pending_rows = 0
        excluded_rows = 0
        for job in current.jobs.values():
            if job.state not in _MARKED_STATES:
                continue
            for row in current.rows.get(job.id, []):
                if row.status == "EXCLUDED":
                    excluded_rows += 1
                    continue
                state = effective_state(
                    row.status,
                    row.processing_state,
                    review_required=bool(row.review_required),
                )
                if is_scoreable(state):
                    decided_rows += 1
                else:
                    pending_rows += 1

        included_ids = {student.submission.id for student in current.students}
        pending_corrections = sum(
            1 for submission in current.eligible if submission.id not in included_ids
        )
        pending_reviews = sum(
            1
            for submission in current.eligible
            if (job := current.jobs.get(submission.id)) is not None
            and job.state == JobState.REVIEW_REQUIRED.value
        )

        return CohortRead(
            assignment=CohortAssignmentRead(
                id=assignment.id,
                name=assignment.name,
                class_name=assignment.class_name,
                course_id=assignment.course_id,
                scope=scope,
            ),
            overview=CohortOverviewRead(
                eligible_submissions=len(current.eligible),
                included_students=len(current.students),
                completed_corrections=sum(
                    1
                    for job in current.jobs.values()
                    if job.state in _MARKED_STATES
                ),
                pending_corrections=pending_corrections,
                approved_jobs=approved_jobs,
                provisional_jobs=provisional_jobs,
                pending_reviews=pending_reviews,
                mean_percent=_round(
                    statistics.fmean(percentages) if percentages else None
                ),
                approved_mean_percent=_round(
                    statistics.fmean(approved_percentages)
                    if approved_percentages
                    else None
                ),
                questions_requiring_attention=len(attention),
                topics_requiring_attention=None,
                state=overview_state,
            ),
            questions=questions,
            topics=CohortTopicsRead(
                state="unavailable",
                reason=(
                    "Question results, blueprints and mark schemes store no topic, "
                    "subtopic, skill or learning-objective field, so a topic aggregate "
                    "cannot be computed without inventing metadata."
                ),
                items=[],
            ),
            students=students,
            trends=self._trends(current, peers),
            completeness=CohortCompletenessRead(
                submissions_total=len(current.submissions),
                excluded_submissions=len(current.submissions) - len(current.eligible),
                eligible_submissions=len(current.eligible),
                with_marked_job=len(current.students),
                pending_corrections=pending_corrections,
                decided_rows=decided_rows,
                pending_rows=pending_rows,
                excluded_rows=excluded_rows,
                approved_jobs=approved_jobs,
                provisional_jobs=provisional_jobs,
            ),
            rules={
                "population": (
                    "Latest non-cancelled, non-refused job per non-FAILED submission, "
                    "only when the job is COMPLETED or REVIEW_REQUIRED."
                ),
                "missing_data": (
                    "A missing or undecided question is excluded from the denominator; "
                    "it is never recorded as a zero."
                ),
                "attention": (
                    f"A question is flagged only with at least {MIN_SAMPLE} decided "
                    f"results and an average below {ATTENTION_PERCENT:.0f}%."
                ),
                "support": (
                    f"A student is flagged only with at least {MIN_SAMPLE} decided "
                    f"questions and an overall percentage below {SUPPORT_PERCENT:.0f}%."
                ),
                "topics": (
                    "Unavailable: no stored topic or skill metadata exists to aggregate."
                ),
            },
        )
