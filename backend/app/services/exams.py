"""Exam, blueprint, assignment and submission services.

The blueprint rules live here: a version is immutable once approved, approval
can only promote the exact draft the teacher last saved, and an assignment can
only reference an approved blueprint and an approved scheme.  Those rules are
why the marking pipeline can treat the blueprint as canonical rather than
best-effort.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.ids import content_hash
from ..core.security import Principal, ensure_exam_manager, ensure_uploader
from ..db.models import (
    Assignment,
    Exam,
    ExamBlueprintVersion,
    Submission,
)
from ..db.repositories import (
    AssignmentRepository,
    BlueprintRepository,
    ExamRepository,
    MarkSchemeRepository,
    SubmissionRepository,
)
from ..schemas.api import AssignmentCreate, ExamCreate, SubmissionCreate
from ..schemas.blueprint import BlueprintPut, BlueprintStructure
from .classroom_access import require_course_access
from .classroom_job_access import require_assignment_access
from .scheme_criteria import readiness_of_assignment


def structure_hash(structure: BlueprintStructure) -> str:
    return content_hash(structure.model_dump(mode="json"))


class ExamService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.exams = ExamRepository(session)
        self.audit = AuditService(session)

    def create(self, principal: Principal, payload: ExamCreate) -> Exam:
        ensure_exam_manager(principal)
        exam = self.exams.create(
            tenant_id=principal.tenant_id,
            title=payload.title.strip(),
            board=payload.board,
            paper_code=payload.paper_code,
            created_by=principal.user_id,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="exam.created",
            entity_type="exam",
            entity_id=exam.id,
            actor_type="USER",
            actor_id=principal.user_id,
            after={"title": exam.title, "board": exam.board, "paper_code": exam.paper_code},
        )
        self.session.commit()
        return exam

    def get_or_404(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> Exam:
        exam = self.exams.get(tenant_id, exam_id)
        if exam is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        return exam

    def list(self, tenant_id: uuid.UUID) -> list[Exam]:
        return self.exams.list(tenant_id)


class BlueprintService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.exams = ExamRepository(session)
        self.blueprints = BlueprintRepository(session)
        self.audit = AuditService(session)

    def get_latest(self, tenant_id: uuid.UUID, exam_id: uuid.UUID) -> ExamBlueprintVersion:
        if self.exams.get(tenant_id, exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        blueprint = self.blueprints.latest_approved(tenant_id, exam_id)
        if blueprint is None:
            blueprint = self.blueprints.latest(tenant_id, exam_id)
        if blueprint is None:
            raise AppError(ErrorCode.NOT_FOUND, "This exam has no blueprint yet.")
        return blueprint

    def get_version(
        self, tenant_id: uuid.UUID, blueprint_version_id: uuid.UUID
    ) -> ExamBlueprintVersion:
        blueprint = self.blueprints.get(tenant_id, blueprint_version_id)
        if blueprint is None:
            raise AppError(ErrorCode.NOT_FOUND, "Blueprint version not found.")
        return blueprint

    def create_extracted_draft(
        self,
        principal: Principal,
        exam_id: uuid.UUID,
        structure: BlueprintStructure,
        *,
        source_document_id: uuid.UUID | None,
        extraction_metadata: dict,
    ) -> ExamBlueprintVersion:
        """Create a DRAFT from extraction; deliberately no approval path here."""
        ensure_exam_manager(principal)
        if self.exams.get(principal.tenant_id, exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        digest = structure_hash(structure)
        blueprint = self.blueprints.create_version(
            tenant_id=principal.tenant_id,
            exam_id=exam_id,
            structure=structure.model_dump(mode="json"),
            total_marks=structure.total_marks,
            content_hash=digest,
            created_by=principal.user_id,
            status="DRAFT",
            source="EXTRACTED",
            source_document_id=source_document_id,
            extraction_metadata=extraction_metadata,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="blueprint.extracted_draft",
            entity_type="exam_blueprint_version",
            entity_id=blueprint.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "exam_id": str(exam_id),
                "version": blueprint.version,
                "source_document_id": str(source_document_id) if source_document_id else None,
                "content_hash": digest,
                "status": blueprint.status,
            },
        )
        self.session.commit()
        return blueprint

    def put(
        self, principal: Principal, exam_id: uuid.UUID, payload: BlueprintPut
    ) -> ExamBlueprintVersion:
        ensure_exam_manager(principal)
        if self.exams.get(principal.tenant_id, exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")

        digest = structure_hash(payload.structure)
        structure = payload.structure.model_dump(mode="json")

        if payload.approve:
            draft = self.blueprints.latest(principal.tenant_id, exam_id)
            if draft is None or draft.status != "DRAFT":
                raise AppError(
                    ErrorCode.CONFLICT,
                    "There is no draft blueprint to approve. Save a draft first.",
                )
            if draft.content_hash != digest:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "The submitted structure does not match the stored draft. "
                    "Save the draft first, then approve that exact version.",
                )
            blueprint = self.blueprints.approve(
                draft, actor_id=principal.user_id, reason=(payload.reason or "").strip()
            )
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="blueprint.approved",
                entity_type="exam_blueprint_version",
                entity_id=blueprint.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "exam_id": str(exam_id),
                    "version": blueprint.version,
                    "reason": blueprint.approval_reason,
                },
            )
            self.session.commit()
            return blueprint

        latest = self.blueprints.latest(principal.tenant_id, exam_id)
        if latest is not None and latest.status == "DRAFT" and latest.content_hash == digest:
            return latest

        blueprint = self.blueprints.create_version(
            tenant_id=principal.tenant_id,
            exam_id=exam_id,
            structure=structure,
            total_marks=payload.structure.total_marks,
            content_hash=digest,
            created_by=principal.user_id,
            status="DRAFT",
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="blueprint.draft_created",
            entity_type="exam_blueprint_version",
            entity_id=blueprint.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "exam_id": str(exam_id),
                "version": blueprint.version,
                "total_marks": blueprint.total_marks,
                "content_hash": digest,
            },
        )
        self.session.commit()
        return blueprint


class AssignmentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.exams = ExamRepository(session)
        self.blueprints = BlueprintRepository(session)
        self.schemes = MarkSchemeRepository(session)
        self.assignments = AssignmentRepository(session)
        self.audit = AuditService(session)

    def create(
        self,
        principal: Principal,
        payload: AssignmentCreate,
        *,
        allow_unassigned: bool = False,
    ) -> Assignment:
        ensure_exam_manager(principal)
        # The class is resolved through the allocation the platform gave this
        # workspace, never from a bare course id.  That single lookup proves the
        # course belongs to this tenant, is still allocated, and is assigned to
        # a teacher or reviewer; a manager passes on role alone.
        allocation = None
        classroom = None
        if payload.course_id is None:
            if not allow_unassigned:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "Select the class this assignment belongs to.",
                )
        else:
            allocation, classroom = require_course_access(
                self.session, principal, course_id=payload.course_id
            )
            if classroom.course_state != "ACTIVE":
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "That Classroom course is not active, so it cannot receive an "
                    "assignment.",
                )
        if self.exams.get(principal.tenant_id, payload.exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        blueprint = self.blueprints.get(principal.tenant_id, payload.blueprint_version_id)
        if blueprint is None or blueprint.exam_id != payload.exam_id:
            raise AppError(ErrorCode.NOT_FOUND, "Blueprint version not found for this exam.")
        if blueprint.status != "APPROVED":
            raise AppError(
                ErrorCode.BLUEPRINT_NOT_APPROVED,
                "The assignment requires an approved blueprint version.",
            )
        scheme = self.schemes.get_version(principal.tenant_id, payload.scheme_version_id)
        if scheme is None:
            raise AppError(ErrorCode.NOT_FOUND, "Mark-scheme version not found.")
        # A scheme belongs to one paper.  Attaching a scheme from another exam
        # would pair marks for one paper with questions from another, and the
        # criteria check below could never be satisfied anyway.
        scheme_record = self.schemes.get_scheme(principal.tenant_id, scheme.mark_scheme_id)
        if scheme_record is None or scheme_record.exam_id != payload.exam_id:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "Mark-scheme version not found for this exam.",
            )
        if scheme.status != "APPROVED":
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "The assignment requires an approved mark-scheme version.",
            )
        # Approved status is about the uploaded document.  Marking needs the
        # scheme's own mark points, reviewed against this exact blueprint: a
        # scheme approved but never transcribed must not produce an assignment
        # that can only fail at marking time.
        readiness = readiness_of_assignment(
            self.session,
            tenant_id=principal.tenant_id,
            blueprint_version_id=blueprint.id,
            scheme_version_id=scheme.id,
        )
        if not readiness.ready:
            raise AppError(
                ErrorCode.ASSIGNMENT_NOT_READY,
                "This assignment could not be marked: the mark scheme has no "
                "approved criteria for this blueprint. Transcribe the scheme's "
                "criteria, review them, and approve them against this blueprint "
                "version first.",
                details={
                    "reason": readiness.reason,
                    "problems": list(readiness.problems)[:10],
                    "blueprint_version_id": str(blueprint.id),
                    "scheme_version_id": str(scheme.id),
                },
            )
        assignment = self.assignments.create(
            tenant_id=principal.tenant_id,
            exam_id=payload.exam_id,
            blueprint_version_id=blueprint.id,
            scheme_version_id=scheme.id,
            name=payload.name.strip(),
            completion_threshold=payload.completion_threshold,
            review_mode=payload.review_mode,
            created_by=principal.user_id,
            classroom_allocation_id=allocation.id if allocation is not None else None,
            course_id=allocation.course_id if allocation is not None else None,
            class_name=allocation.class_name if allocation is not None else None,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="assignment.created",
            entity_type="assignment",
            entity_id=assignment.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "exam_id": str(payload.exam_id),
                "blueprint_version_id": str(blueprint.id),
                "scheme_version_id": str(scheme.id),
                "classroom_allocation_id": (
                    str(allocation.id) if allocation is not None else None
                ),
                "course_id": allocation.course_id if allocation is not None else None,
            },
        )
        self.session.commit()
        return assignment


class SubmissionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignments = AssignmentRepository(session)
        self.submissions = SubmissionRepository(session)
        self.audit = AuditService(session)

    def create(self, principal: Principal, payload: SubmissionCreate) -> Submission:
        # Registering a script is part of manual ingestion, not exam management.
        ensure_uploader(principal)
        assignment = self.assignments.get(principal.tenant_id, payload.assignment_id)
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        # Registering a script against another class's assignment would hand the
        # uploader that class's work through the submission reads.
        require_assignment_access(self.session, principal, assignment.id)
        submission = self.submissions.create(
            tenant_id=principal.tenant_id,
            assignment_id=payload.assignment_id,
            student_ref=payload.student_ref.strip(),
            content_hash=payload.content_hash,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="submission.registered",
            entity_type="submission",
            entity_id=submission.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"assignment_id": str(payload.assignment_id)},
        )
        self.session.commit()
        return submission
