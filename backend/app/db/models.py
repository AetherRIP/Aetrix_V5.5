"""Phase 1 relational model.

Every tenant-owned table carries ``tenant_id``.  Enumerations are stored as
checked strings rather than PostgreSQL enum types: the vocabulary is part of
the API contract and a check constraint is easier to migrate than a type.

The schema deliberately separates *what was extracted* (blueprints, schemes),
*what the examiner produced* (question results, criteria, evidence), *what was
verified* (verification results), and *what was decided* (review decisions,
audit events).  Re-running a correction writes a new job; it never overwrites
the record of the previous one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..jobs.states import JobState
from .base import Base, TenantScoped, TimestampMixin, UUIDPrimaryKey

JOB_STATES_SQL = ", ".join(f"'{state.value}'" for state in JobState)


class Tenant(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: A demo workspace is a real tenant whose principals are refused every
    #: mutation, so the public demo can never reach production data.
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ServiceHeartbeat(Base):
    """Liveness evidence written by a long-lived process.

    The API cannot inspect the worker's process table, so "is the worker
    running?" had no honest answer and the interface guessed.  The worker renews
    this row and ``GET /status`` reads it; a missing or stale row is reported as
    unknown or unavailable, never as online.  It is not tenant data and carries
    no secret — only the process name, the time it was last seen and harmless
    detail such as the PID.
    """

    __tablename__ = "service_heartbeats"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class User(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject", name="uq_users_tenant_subject"),
        CheckConstraint(
            # PLATFORM_OWNER is platform ownership, not a fifth workspace role:
            # it keeps the workspace capabilities and adds the platform ones.
            "role IN ('OWNER','ADMIN','TEACHER','REVIEWER','VIEWER','PLATFORM_OWNER')",
            name="role",
        ),
        Index("ix_users_subject", "subject"),
    )

    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="TEACHER")
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Exam(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "exams"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    board: Mapped[str | None] = mapped_column(String(80), nullable=True)
    paper_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ExamBlueprintVersion(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "exam_blueprint_versions"
    __table_args__ = (
        UniqueConstraint("exam_id", "version", name="uq_blueprint_exam_version"),
        CheckConstraint("status IN ('DRAFT','APPROVED','SUPERSEDED')", name="status"),
        CheckConstraint("total_marks >= 0", name="total_marks_non_negative"),
        Index("ix_blueprint_exam_status", "exam_id", "status"),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    total_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class MarkScheme(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "mark_schemes"

    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    # Provenance only.  A foreign key here creates a table-creation cycle
    # (documents -> submissions -> assignments -> mark_scheme_versions ->
    # mark_schemes -> documents); the document id is retained as an audit
    # reference without pretending the cycle is free.
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)


class MarkSchemeVersion(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "mark_scheme_versions"
    __table_args__ = (
        UniqueConstraint("mark_scheme_id", "version", name="uq_scheme_version"),
        CheckConstraint("status IN ('DRAFT','APPROVED','SUPERSEDED')", name="status"),
    )

    mark_scheme_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mark_schemes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="UPLOAD")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class MarkingCriterion(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "marking_criteria"
    __table_args__ = (
        UniqueConstraint(
            "scheme_version_id", "question_id", "code", "ordinal", name="uq_criterion_identity"
        ),
        CheckConstraint("marks >= 0", name="marks_non_negative"),
    )

    scheme_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mark_scheme_versions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    marks: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_evidence: Mapped[str | None] = mapped_column(Text)
    dependencies: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    award_conditions: Mapped[str | None] = mapped_column(Text)
    withhold_conditions: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Assignment(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint("review_mode IN ('ECONOMY','BALANCED','ACCURACY')", name="review_mode"),
        CheckConstraint(
            "completion_threshold >= 0.0 AND completion_threshold <= 1.0",
            name="completion_threshold_range",
        ),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    blueprint_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exam_blueprint_versions.id", ondelete="SET NULL"), nullable=True
    )
    scheme_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mark_scheme_versions.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    completion_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    review_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="BALANCED")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Submission(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('REGISTERED','PROCESSING','PROCESSED','FAILED')", name="status"
        ),
        Index("ix_submissions_assignment", "assignment_id", "status"),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    student_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REGISTERED")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Document(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("kind IN ('STUDENT','MARK_SCHEME','QUESTION_PAPER')", name="kind"),
        CheckConstraint("status IN ('UPLOADED','VALIDATED','REJECTED','PROCESSED')", name="status"),
        CheckConstraint(
            "ordering_status IN ('ORDERED','ORDER_SUSPECT','UNVERIFIED')",
            name="ordering_status",
        ),
        CheckConstraint(
            "mapping_status IN ('UNMAPPED','MAPPED','PARTIAL','UNVERIFIED')",
            name="mapping_status",
        ),
        Index("ix_documents_exam_kind", "exam_id", "kind"),
    )

    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=True
    )
    exam_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UPLOADED")
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ordering_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNVERIFIED")
    ordering_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    mapping_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNMAPPED")
    mapping_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentPage(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_index", name="uq_page_document_index"),
        CheckConstraint(
            "quality_status IN ('READABLE','LOW_QUALITY','ROTATED','PARTIALLY_UNREADABLE',"
            "'UNREADABLE','EMPTY')",
            name="quality_status",
        ),
        CheckConstraint("page_index >= 1", name="page_index_positive"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    quality_status: Mapped[str] = mapped_column(String(30), nullable=False, default="READABLE")
    quality_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ordering_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    printed_page_number: Mapped[int | None] = mapped_column(Integer)
    text_excerpt: Mapped[str | None] = mapped_column(Text)
    rotation_degrees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    duplicate_of_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class PageQuestionMapping(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "page_question_mappings"
    __table_args__ = (
        UniqueConstraint(
            "page_id", "question_id", "blueprint_version_id", name="uq_page_question_blueprint"
        ),
        CheckConstraint("method IN ('TEXT_MATCH','MODEL')", name="method"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="confidence"),
        Index("ix_page_mapping_document", "document_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), nullable=False
    )
    blueprint_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_blueprint_versions.id", ondelete="RESTRICT"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="TEXT_MATCH")
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class BlueprintOverride(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "blueprint_overrides"
    __table_args__ = (Index("ix_blueprint_override_exam", "exam_id", "created_at"),)

    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_blueprint_versions.id", ondelete="RESTRICT"), nullable=False
    )
    result_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_blueprint_versions.id", ondelete="RESTRICT"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    patch: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ProviderProjectCooldown(Base):
    """A platform-level pause on one Google Cloud project.

    Shared free-tier quota is exhausted for the *project*, so every key under it
    has to stand down together.  A key-level cooldown would let the next key in
    rotation walk straight into the same 429.
    """

    __tablename__ = "provider_project_cooldowns"

    project_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    cooldown_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ProviderQuotaReservation(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "provider_quota_reservations"
    __table_args__ = (
        CheckConstraint("status IN ('RESERVED','CONSUMED','RELEASED')", name="status"),
        Index("ix_provider_reservation_credential", "credential_id", "created_at"),
        Index("ix_provider_reservation_project_model", "credential_id", "model", "created_at"),
    )

    credential_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_credentials.id", ondelete="CASCADE"), nullable=False
    )
    #: Gemini meters per project **and model**.  A reservation without the model
    #: cannot be counted against the right allowance and was the reason a flash
    #: call consumed the review model's budget.
    model: Mapped[str | None] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RESERVED")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class CorrectionJob(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "correction_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_job_idempotency"),
        CheckConstraint(f"state IN ({JOB_STATES_SQL})", name="state"),
        CheckConstraint("progress >= 0.0 AND progress <= 1.0", name="progress_range"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_jobs_state_created", "state", "created_at"),
        Index("ix_jobs_lease", "lease_expires_at"),
        Index("ix_jobs_submission", "submission_id"),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    blueprint_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_blueprint_versions.id", ondelete="RESTRICT"), nullable=False
    )
    scheme_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mark_scheme_versions.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False, default=JobState.CREATED)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    resume_state: Mapped[str | None] = mapped_column(String(30))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class JobEvent(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "event_seq", name="uq_job_event_seq"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    event_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actor: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class QuestionResult(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "question_results"
    __table_args__ = (
        UniqueConstraint("job_id", "question_id", name="uq_question_result_job_question"),
        CheckConstraint("awarded_marks >= 0", name="awarded_non_negative"),
        CheckConstraint("awarded_marks <= max_marks", name="awarded_within_max"),
        CheckConstraint(
            "status IN ('AWARDED','ZERO','UNMARKED','REVIEW_REQUIRED','EXCLUDED')",
            name="status",
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    max_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_marks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNMARKED")
    student_answer: Mapped[str | None] = mapped_column(Text)
    working_summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scheme_concerns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )


class CriterionResult(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "criterion_results"
    __table_args__ = (Index("ix_criterion_result_question", "question_result_id"),)

    question_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_results.id", ondelete="CASCADE"), nullable=False
    )
    criterion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marking_criteria.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    awarded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class MarkingEvidence(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "marking_evidence"

    question_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_results.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    quote: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class VerificationResult(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "verification_results"
    __table_args__ = (
        UniqueConstraint("job_id", "question_id", "kind", name="uq_verification_identity"),
        CheckConstraint("kind IN ('MATHEMATICAL','INTEGRITY')", name="kind"),
        CheckConstraint(
            "status IN ('EQUIVALENT','DIFFERENT','UNKNOWN','PASS','FAIL','REVIEW_REQUIRED')",
            name="status",
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ReviewDecision(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "review_decisions"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_reason: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="BALANCED")
    independent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_award: Mapped[int | None] = mapped_column(Integer)
    second_award: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(40))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ProviderContributor(UUIDPrimaryKey, TimestampMixin, Base):
    """An independent person who lent API keys to the platform.

    A contributor is not a tenant and not a role: the keys they lend belong to
    an external Google Cloud account, and the platform's job is to keep the
    contribution attributable, revocable and consent-bound.  ``user_id`` is the
    Aetrix account that may act on the contribution (register keys, withdraw
    them); it is nullable because a contributor can exist before they sign in.

    Status is the single source of truth for eligibility:

    * ``ACTIVE``    — keys may be leased.
    * ``SUSPENDED`` — keys are disabled but the ciphertext is kept, so the
      contribution can be reinstated without asking for the secret again.
    * ``WITHDRAWN`` — the contributor took the keys back.  Ciphertext is
      destroyed and status never returns to ACTIVE; a new contribution is a new
      row.
    """

    __tablename__ = "provider_contributors"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','SUSPENDED','WITHDRAWN')", name="status"),
        UniqueConstraint("user_id", name="uq_provider_contributor_user"),
        Index("ix_provider_contributor_status", "status"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    #: The agreement the contributor accepted, and when.  Consent is a record,
    #: not a checkbox that disappears with the form.
    consent_version: Mapped[str] = mapped_column(String(40), nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_reference: Mapped[str | None] = mapped_column(String(200))
    status_reason: Mapped[str | None] = mapped_column(String(300))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderCredential(UUIDPrimaryKey, TimestampMixin, Base):
    """One Gemini API key.

    ``project_id`` is the Google Cloud project the key bills against, and it is
    the unit of quota: keys sharing a project share one rate-limit pool.  It is
    never derived from the key itself — an operator supplies it, because several
    keys routinely belong to one project and a rotation must not look like a new
    pool.

    ``contributor_id`` is null for a key the platform owns itself; a null is an
    explicit "platform-provisioned", never an unattributed contribution.  The
    ownership chain the fleet is built on is
    contributor -> credential -> Google Cloud project -> model quota, and one
    contributor may appear in any number of those chains.
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (
        CheckConstraint(
            # This is credential validity only.  A timeout, quota rejection or
            # provider 5xx does not make a key invalid or healthy; those are
            # operational outcomes recorded in the usage ledger.
            "health IN ('HEALTHY','INVALID','DISABLED','UNKNOWN')",
            name="health",
        ),
        CheckConstraint("tier IN ('FREE','PAID','UNKNOWN')", name="tier"),
        CheckConstraint("auth_type IN ('api_key','oauth')", name="auth_type"),
        UniqueConstraint("key_fingerprint", name="uq_provider_credential_fingerprint"),
        Index("ix_provider_credential_project", "project_id"),
        Index("ix_provider_credential_project_health", "project_id", "health"),
        Index("ix_provider_credential_contributor", "contributor_id"),
    )

    contributor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_contributors.id", ondelete="SET NULL"), nullable=True
    )
    #: Set when a contributor withdraws a key or an administrator revokes it.
    #: The row is kept because the usage ledger must keep its provenance.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(300))

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: Google Cloud project id (or a synthetic pool id for legacy keys).
    project_id: Mapped[str] = mapped_column(String(100), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="api_key")
    #: FREE / PAID / UNKNOWN.  UNKNOWN is never upgraded by guessing.
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    account_label: Mapped[str] = mapped_column(String(120), nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    model_access: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_status: Mapped[int | None] = mapped_column(Integer)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(400))


class ProviderModelSelection(UUIDPrimaryKey, Base):
    """The model an operator chose for one correction role.

    Stored rather than read from the environment so a change is auditable and
    effective without a redeploy.  The row is platform-wide: which models a
    credential can reach is a Google Cloud project property, but which role the
    engine uses is not.  ``role`` is one of primary, review, lightweight.
    """

    __tablename__ = "provider_model_selections"
    __table_args__ = (
        CheckConstraint(
            "role IN ('primary','review','lightweight')", name="role"
        ),
        UniqueConstraint("role", name="uq_provider_model_selection_role"),
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(200))


class ProviderUsage(UUIDPrimaryKey, Base):
    """The append-only ledger of Aetrix-recorded provider calls.

    ``project_id`` is denormalised so a project's consumption can be aggregated
    without joining every credential, and so history survives a key being
    deleted.  ``contributor_id`` is denormalised for the same reason: a
    contribution statistic must survive the key being retired.  It is Aetrix's
    own record; Google's console remains the only authoritative source for what
    Google billed.
    """

    __tablename__ = "provider_usage"
    __table_args__ = (
        Index("ix_provider_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_provider_usage_job", "job_id"),
        Index("ix_provider_usage_project_created", "project_id", "created_at"),
        Index("ix_provider_usage_model_created", "model", "created_at"),
        Index("ix_provider_usage_contributor_created", "contributor_id", "created_at"),
    )

    contributor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_contributors.id", ondelete="SET NULL"), nullable=True
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_credentials.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("correction_jobs.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="google")
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True
    )
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    request_id: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_class: Mapped[str | None] = mapped_column(String(80))
    #: Diagnostic detail.  Historical rows keep nulls because the ledger is
    #: append-only; the API derives a category from error_class for those rows.
    error_category: Mapped[str | None] = mapped_column(String(40))
    provider_code: Mapped[str | None] = mapped_column(String(80))
    provider_message: Mapped[str | None] = mapped_column(String(300))
    reached_provider: Mapped[bool | None] = mapped_column(Boolean)
    finish_reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class AuditEvent(UUIDPrimaryKey, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
        CheckConstraint("actor_type IN ('USER','SYSTEM','WORKER')", name="actor_type"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(200))
    #: The actor's name as it was when the event was written. Auditors must still
    #: be able to read a decision after the person who made it has been removed.
    actor_label: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(200), nullable=False)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class PlatformAuditEvent(UUIDPrimaryKey, Base):
    """A platform-level administrative action, recorded outside any tenant.

    ``audit_events`` is tenant-scoped, and a platform account action has no
    single tenant: listing every account, changing a platform role or suspending
    an identity crosses workspaces.  This table is append-only at the database
    layer (migration 0016 adds the same update guard the tenant ledgers use), and
    it stores identifiers and decisions only — never a credential or a token.
    """

    __tablename__ = "platform_audit_events"
    __table_args__ = (
        Index("ix_platform_audit_target", "target_subject", "created_at"),
        Index("ix_platform_audit_created", "created_at"),
        Index("ix_platform_audit_action", "action", "created_at"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_platform_role: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    target_email: Mapped[str | None] = mapped_column(String(320))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class PromptVersion(UUIDPrimaryKey, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version", name="uq_prompt_identity"),)

    prompt_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    model_role: Mapped[str] = mapped_column(String(40), nullable=False, default="primary")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ModelVersion(UUIDPrimaryKey, Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("provider", "model_id", "role", name="uq_model_identity"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class CohortAnalysis(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "cohort_analyses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','INSUFFICIENT_COHORT')",
            name="status",
        ),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class LearningFeedback(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "learning_feedback"
    __table_args__ = (
        CheckConstraint("original_mark >= 0 AND revised_mark >= 0", name="marks_non_negative"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    criterion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marking_criteria.id", ondelete="SET NULL"), nullable=True
    )
    original_mark: Mapped[int] = mapped_column(Integer, nullable=False)
    revised_mark: Mapped[int] = mapped_column(Integer, nullable=False)
    original_explanation: Mapped[str | None] = mapped_column(Text)
    teacher_explanation: Mapped[str | None] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(120))
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class JobApproval(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    """A named person's decision that a job's marks are final.

    Approval is deliberately a separate record from the correction job: the
    engine finishing a marking run is not the same event as a teacher accepting
    its output, and the gradebook must be able to say which one happened.
    """

    __tablename__ = "job_approvals"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_job_approval_job"),
        CheckConstraint("approved_marks >= 0", name="approved_marks_non_negative"),
        CheckConstraint("total_marks >= 0", name="total_marks_non_negative"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: The approver as they were named at the time, so the record survives the
    #: account being removed.
    approved_by_label: Mapped[str | None] = mapped_column(String(320))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    total_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Invitation(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    """A deliberate grant of one workspace role to one verified email address.

    Provisioning is invitation-only.  An authenticated subject with no ``users``
    row is refused (``PROVISIONING_REQUIRED``) unless a live invitation matches
    the verified email claim, so no one can create a workspace membership by
    signing in.  ``PLATFORM_OWNER`` is deliberately absent from the vocabulary:
    platform ownership is assigned by the operator CLI, never by an invitation.

    ``token_hash`` stores a SHA-256 of a one-time acceptance code.  The code is
    returned exactly once, when the invitation is created, so an invitee whose
    Google address differs from the invited address can still accept it.  The
    plaintext is never stored.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint(
            "role IN ('OWNER','ADMIN','TEACHER','REVIEWER','VIEWER')", name="role"
        ),
        CheckConstraint(
            "status IN ('PENDING','ACCEPTED','REVOKED')", name="status"
        ),
        UniqueConstraint("token_hash", name="uq_invitation_token"),
        Index("ix_invitation_email_status", "email", "status"),
        Index("ix_invitation_tenant_status", "tenant_id", "status"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(String(300))


class SchoolClass(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    """A teaching group inside one workspace.

    Classes are workspace-owned records, not Google Classroom mirrors: the
    Classroom integration lists courses and does not import rosters into these
    rows, so nothing here claims a synced course.  A class name is unique within
    its workspace only.
    """

    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_classes_tenant_name"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    year_group: Mapped[str | None] = mapped_column(String(40))


class ClassroomClass(UUIDPrimaryKey, TimestampMixin, Base):
    """A Google Classroom course known to the platform.

    This is a platform-level inventory, not a workspace-owned class.  A course
    enters it either through an operator's explicit record or a connected
    workspace's successful Google Classroom course sync.  Only the sync path
    writes ``VERIFIED`` and ``synced_at``; an operator-recorded row remains
    ``UNVERIFIED`` until Google actually lists it.
    """

    __tablename__ = "classroom_classes"
    __table_args__ = (
        UniqueConstraint("course_id", name="uq_classroom_classes_course"),
        CheckConstraint(
            "course_state IN ('ACTIVE','ARCHIVED','DELETED')", name="course_state"
        ),
        CheckConstraint(
            "verification IN ('UNVERIFIED','VERIFIED')", name="verification"
        ),
    )

    course_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    section: Mapped[str | None] = mapped_column(String(200))
    course_state: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    verification: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNVERIFIED"
    )
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="operator_recorded"
    )
    owner_email: Mapped[str | None] = mapped_column(String(320))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)


class ClassroomAllocation(UUIDPrimaryKey, TimestampMixin, Base):
    """One workspace's ownership of one Classroom course, with its history.

    A release does not delete the row: the released allocation remains as the
    audit trail, and a reassignment creates a new row pointing at the one it
    replaced.  The partial unique index on ``classroom_class_id`` for ACTIVE rows
    is the database's guarantee that one course has at most one owner, even if
    two operators allocate it at the same moment.
    """

    __tablename__ = "classroom_allocations"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','RELEASED')", name="status"),
        CheckConstraint("origin IN ('ALLOCATE','REASSIGN')", name="origin"),
        CheckConstraint(
            "(status = 'ACTIVE' AND released_at IS NULL) OR "
            "(status = 'RELEASED' AND released_at IS NOT NULL)",
            name="released_state",
        ),
        Index(
            "uq_classroom_allocations_active_class",
            "classroom_class_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "ix_classroom_allocations_workspace_status",
            "workspace_id",
            "status",
        ),
        Index(
            "ix_classroom_allocations_class_allocated",
            "classroom_class_id",
            "allocated_at",
        ),
    )

    classroom_class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom_classes.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    #: Snapshots keep the history readable after a rename or workspace removal.
    course_id: Mapped[str] = mapped_column(String(200), nullable=False)
    class_name: Mapped[str] = mapped_column(String(300), nullable=False)
    workspace_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="ALLOCATE")
    allocated_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    allocated_by_label: Mapped[str | None] = mapped_column(String(320))
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    released_by_subject: Mapped[str | None] = mapped_column(String(200))
    released_by_label: Mapped[str | None] = mapped_column(String(320))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(500))
    reason: Mapped[str | None] = mapped_column(String(500))
    previous_allocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classroom_allocations.id", ondelete="SET NULL"), nullable=True
    )


class ClassroomConnection(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    """One workspace's Google Classroom OAuth connection.

    Both tokens are encrypted with the configured Fernet key; no API response,
    log or model representation returns them.  ``RECONNECT_REQUIRED`` is a real
    state: Google revoked or invalidated the grant, the ciphertext was discarded,
    and the workspace must authorize again.  A transient Google failure does not
    revoke the connection.
    """

    __tablename__ = "classroom_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_classroom_connections_tenant"),
        CheckConstraint(
            "status IN ('CONNECTED','RECONNECT_REQUIRED')", name="status"
        ),
        CheckConstraint(
            "last_sync_status IS NULL OR "
            "last_sync_status IN ('SUCCEEDED','FAILED')",
            name="last_sync_status",
        ),
    )

    encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: Fail closed: a row inserted without an explicit status must not look
    #: usable, so the default is the state that demands a new authorisation.
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="RECONNECT_REQUIRED"
    )
    connected_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(30))
    last_sync_counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(500))


class Student(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    """A roster entry belonging to one workspace.

    ``student_ref`` is the teacher's own identifier (admission number, class
    list position) and is unique per workspace.  ``class_id`` is nullable so a
    student survives their class being deleted rather than disappearing with it.
    """

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("tenant_id", "student_ref", name="uq_students_tenant_ref"),
        Index("ix_students_tenant_class", "tenant_id", "class_id"),
    )

    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"), nullable=True
    )
    student_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))


# -- Google Cloud quota synchronisation ------------------------------------
#
# These tables are platform infrastructure, not tenant data: a project's quota
# belongs to the fleet, and no workspace may read another workspace's provider
# accounts.  ``project_id`` is the operator-declared identifier, preserved
# verbatim; Google's own identity response is stored beside it, never used to
# rewrite it.  Snapshots hold only current observations, so a quota Google no
# longer exposes disappears on the next successful sync instead of lingering as
# a fabricated limit.


GOOGLE_PROJECT_STATUSES = (
    "'VERIFIED','NOT_FOUND','PERMISSION_DENIED','ERROR','UNVERIFIABLE','UNVERIFIED'"
)


class GoogleCloudProject(TimestampMixin, Base):
    __tablename__ = "google_cloud_projects"
    __table_args__ = (
        CheckConstraint(
            f"verification_status IN ({GOOGLE_PROJECT_STATUSES})",
            name="verification_status",
        ),
    )

    project_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    #: Google's project number and display name, read from Resource Manager.
    project_number: Mapped[str | None] = mapped_column(String(32))
    display_name: Mapped[str | None] = mapped_column(String(200))
    lifecycle_state: Mapped[str | None] = mapped_column(String(40))
    verification_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="UNVERIFIED"
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Last sync that read Cloud Quotas.  Verification alone does not set this.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    quota_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Service Usage reports which required APIs are enabled, when readable.
    #: ``None`` means "not checked", never "none enabled".
    enabled_services: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    services_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GoogleCloudQuotaSnapshot(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "google_cloud_quota_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "quota_id",
            "dimensions_key",
            name="uq_google_quota_snapshot",
        ),
        Index("ix_google_quota_snapshot_project", "project_id"),
        CheckConstraint(
            "limit_source IN ('CLOUD_QUOTAS','CLOUD_MONITORING','UNAVAILABLE')",
            name="limit_source",
        ),
        CheckConstraint(
            "usage_source IN ('CLOUD_MONITORING','NOT_EXPOSED')",
            name="usage_source",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("google_cloud_projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    quota_id: Mapped[str] = mapped_column(String(200), nullable=False)
    metric: Mapped[str] = mapped_column(String(300), nullable=False)
    service: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_display_name: Mapped[str | None] = mapped_column(String(300))
    quota_display_name: Mapped[str | None] = mapped_column(String(300))
    unit: Mapped[str | None] = mapped_column(String(80))
    refresh_interval: Mapped[str | None] = mapped_column(String(80))
    #: Only what Google returned; Aetrix never infers a reset instant.
    reset_time: Mapped[str | None] = mapped_column(String(80))
    container_type: Mapped[str | None] = mapped_column(String(40))
    is_precise: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Dimension names Google declares (for example ``model``) and the values
    #: this row describes.  ``-1`` limits are Google's "unlimited" sentinel.
    dimensions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    dimensions_key: Mapped[str] = mapped_column(String(32), nullable=False)
    limit_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 4), nullable=True)
    limit_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="UNAVAILABLE"
    )
    usage_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 4), nullable=True)
    usage_metric: Mapped[str | None] = mapped_column(String(300))
    usage_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="NOT_EXPOSED"
    )
    usage_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exceeded_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 4), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GoogleCloudSyncRun(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "google_cloud_sync_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('MANUAL','SCHEDULED')", name="trigger"),
        CheckConstraint(
            "status IN ('SUCCEEDED','PARTIAL','FAILED')", name="status"
        ),
        Index("ix_google_quota_run_project", "project_id", "started_at"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("google_cloud_projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quota_infos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshots_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
