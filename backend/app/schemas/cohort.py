"""Question-level cohort intelligence reads.

Every figure here is derived from stored ``question_results`` for the latest
acceptable job of each submission.  The response names its population and
sample sizes so a screen cannot present a small or provisional sample as a
class-wide fact, and a missing mark is never represented as a zero.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MarkCount(BaseModel):
    marks: int
    count: int


class CohortQuestionRead(BaseModel):
    question_id: str
    #: The single maximum when every contributing result agrees, otherwise null.
    max_marks: int | None
    max_marks_min: int
    max_marks_max: int
    sample_size: int = Field(description="Decided question results in the population")
    approved_sample: int
    provisional_sample: int
    pending_count: int = Field(description="Rows not decided and not excluded")
    average_marks: float | None
    average_percent: float | None
    median_percent: float | None
    full_marks: int
    zero_marks: int
    partial_marks: int
    struggling_count: int
    struggling_percent: float | None
    distribution: list[MarkCount]
    state: str
    attention: bool


class CohortOverviewRead(BaseModel):
    eligible_submissions: int
    included_students: int
    completed_corrections: int
    pending_corrections: int
    approved_jobs: int
    provisional_jobs: int
    pending_reviews: int
    mean_percent: float | None
    approved_mean_percent: float | None
    questions_requiring_attention: int
    topics_requiring_attention: int | None
    state: str


class CohortStudentRead(BaseModel):
    student_ref: str
    job_id: UUID
    job_state: str
    approved: bool
    decided: int
    awarded: int
    possible: int
    percentage: float | None
    full_marks: int
    zero_marks: int
    low_question_ids: list[str]
    support_flagged: bool
    #: Why this student is flagged, or why they are not: never a bare label.
    evidence: str


class CohortTrendPointRead(BaseModel):
    assignment_id: UUID
    name: str
    created_at: datetime
    mean_percent: float | None
    included_students: int
    approved_jobs: int
    state: str


class CohortQuestionChangeRead(BaseModel):
    question_id: str
    max_marks: int
    previous_assignment_id: UUID
    previous_percent: float
    current_percent: float
    delta_percent: float


class CohortTrendsRead(BaseModel):
    state: str
    reason: str | None
    points: list[CohortTrendPointRead]
    question_changes: list[CohortQuestionChangeRead]


class CohortTopicItemRead(BaseModel):
    name: str
    sample_size: int
    average_percent: float | None


class CohortTopicsRead(BaseModel):
    state: str
    reason: str | None
    items: list[CohortTopicItemRead]


class CohortCompletenessRead(BaseModel):
    submissions_total: int
    excluded_submissions: int
    eligible_submissions: int
    with_marked_job: int
    pending_corrections: int
    decided_rows: int
    pending_rows: int
    excluded_rows: int
    approved_jobs: int
    provisional_jobs: int


class CohortAssignmentRead(BaseModel):
    id: UUID
    name: str
    class_name: str | None
    course_id: str | None
    scope: str


class CohortRead(BaseModel):
    assignment: CohortAssignmentRead
    overview: CohortOverviewRead
    questions: list[CohortQuestionRead]
    topics: CohortTopicsRead
    students: list[CohortStudentRead]
    trends: CohortTrendsRead
    completeness: CohortCompletenessRead
    #: The deterministic rules used for attention and support flags.
    rules: dict[str, str]
