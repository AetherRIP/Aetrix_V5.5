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


class User(UUIDPrimaryKey, TenantScoped, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject", name="uq_users_tenant_subject"),
        CheckConstraint("role IN ('OWNER','ADMIN','TEACHER','REVIEWER','VIEWER')", name="role"),
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


class ProviderQuotaReservation(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "provider_quota_reservations"
    __table_args__ = (
        CheckConstraint("status IN ('RESERVED','CONSUMED','RELEASED')", name="status"),
        Index("ix_provider_reservation_credential", "credential_id", "created_at"),
    )

    credential_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider_credentials.id", ondelete="CASCADE"), nullable=False
    )
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


class ProviderCredential(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        CheckConstraint(
            "health IN ('HEALTHY','COOLDOWN','INVALID','DISABLED','UNKNOWN')", name="health"
        ),
        UniqueConstraint("key_fingerprint", name="uq_provider_credential_fingerprint"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    account_label: Mapped[str] = mapped_column(String(120), nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    model_access: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(400))


class ProviderUsage(UUIDPrimaryKey, Base):
    __tablename__ = "provider_usage"
    __table_args__ = (
        Index("ix_provider_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_provider_usage_job", "job_id"),
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
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="google")
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
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
