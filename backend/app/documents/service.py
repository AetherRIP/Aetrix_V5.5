"""Document ingestion.

The ingestion pipeline is synchronous and explicit: validate, store the
original, render every page, assess quality/order, persist all pages, and mark
the document ``PROCESSED``.  A rejected file becomes a rejected ``documents``
row with typed reasons; it is never silently discarded.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import sha256_hex, utcnow
from ..core.security import Principal, ensure_uploader
from ..db.models import Document, DocumentPage, Submission
from ..db.repositories import (
    AssignmentRepository,
    DocumentRepository,
    ExamRepository,
    SubmissionRepository,
)
from ..storage.base import Storage, StorageError
from .rendering import render_document
from .types import DocumentRejected
from .validation import validate_upload


class DocumentService:
    def __init__(self, session: Session, settings: Settings, storage: Storage) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.documents = DocumentRepository(session)
        self.submissions = SubmissionRepository(session)
        self.assignments = AssignmentRepository(session)
        self.exams = ExamRepository(session)
        self.audit = AuditService(session)

    def _submission_and_exam(
        self, principal: Principal, submission_id: uuid.UUID
    ) -> tuple[Submission, uuid.UUID]:
        submission = self.submissions.get(principal.tenant_id, submission_id)
        if submission is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
        assignment = self.assignments.get(principal.tenant_id, submission.assignment_id)
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")
        return submission, assignment.exam_id

    def ingest_for_submission(
        self,
        principal: Principal,
        submission_id: uuid.UUID,
        *,
        filename: str,
        declared_mime: str,
        data: bytes,
    ) -> Document:
        ensure_uploader(principal)
        submission, exam_id = self._submission_and_exam(principal, submission_id)
        return self._ingest(
            principal,
            exam_id=exam_id,
            submission_id=submission.id,
            kind="STUDENT",
            filename=filename,
            declared_mime=declared_mime,
            data=data,
        )

    def ingest_for_exam(
        self,
        principal: Principal,
        exam_id: uuid.UUID,
        *,
        kind: str,
        filename: str,
        declared_mime: str,
        data: bytes,
    ) -> Document:
        ensure_uploader(principal)
        if kind not in {"MARK_SCHEME", "QUESTION_PAPER"}:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Unsupported document kind.")
        if self.exams.get(principal.tenant_id, exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        return self._ingest(
            principal,
            exam_id=exam_id,
            submission_id=None,
            kind=kind,
            filename=filename,
            declared_mime=declared_mime,
            data=data,
        )

    def _ingest(
        self,
        principal: Principal,
        *,
        exam_id: uuid.UUID,
        submission_id: uuid.UUID | None,
        kind: str,
        filename: str,
        declared_mime: str,
        data: bytes,
    ) -> Document:
        safe_name = Path(filename or "document").name[:255]
        digest = sha256_hex(data)
        document_id = uuid.uuid4()
        try:
            upload = validate_upload(
                filename=safe_name,
                declared_mime=declared_mime,
                data=data,
                settings=self.settings,
            )
        except DocumentRejected as error:
            document = Document(
                id=document_id,
                tenant_id=principal.tenant_id,
                exam_id=exam_id,
                submission_id=submission_id,
                kind=kind,
                storage_key="",
                original_filename=safe_name,
                sha256=digest,
                mime_type=(declared_mime or "application/octet-stream")[:120],
                size_bytes=len(data),
                page_count=0,
                status="REJECTED",
                validation_errors=error.reasons,
                error_code=error.code,
                processed_at=utcnow(),
            )
            self.session.add(document)
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="document.rejected",
                entity_type="document",
                entity_id=document.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={"code": error.code, "reasons": error.reasons},
            )
            self.session.commit()
            raise AppError(
                ErrorCode.DOCUMENT_REJECTED,
                str(error),
                details={"document_id": str(document.id), "reasons": error.reasons},
            ) from error

        storage_key = (
            f"tenants/{principal.tenant_id}/documents/{document_id}/original{upload.extension}"
        )
        try:
            self.storage.put(storage_key, data, upload.mime_type)
        except StorageError as error:
            raise AppError(
                ErrorCode.SERVICE_NOT_READY,
                "The document could not be stored.",
            ) from error

        document = Document(
            id=document_id,
            tenant_id=principal.tenant_id,
            exam_id=exam_id,
            submission_id=submission_id,
            kind=kind,
            storage_key=storage_key,
            original_filename=safe_name,
            sha256=digest,
            mime_type=upload.mime_type,
            size_bytes=len(data),
            page_count=0,
            status="UPLOADED",
            ordering_status="UNVERIFIED",
            mapping_status="UNMAPPED",
        )
        self.session.add(document)
        self.session.flush()

        try:
            rendered = render_document(data, upload, self.settings)
        except DocumentRejected as error:
            document.status = "REJECTED"
            document.validation_errors = error.reasons
            document.error_code = error.code
            document.processed_at = utcnow()
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="document.rejected",
                entity_type="document",
                entity_id=document.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={"code": error.code, "reasons": error.reasons},
            )
            self.session.commit()
            raise AppError(
                ErrorCode.DOCUMENT_REJECTED,
                str(error),
                details={"document_id": str(document.id), "reasons": error.reasons},
            ) from error

        page_ids: dict[int, uuid.UUID] = {}
        for page in rendered.pages:
            page_key = (
                f"tenants/{principal.tenant_id}/documents/{document.id}/"
                f"pages/{page.page_index:03d}.png"
            )
            self.storage.put(page_key, page.png, "image/png")
            duplicate_id = (
                page_ids.get(page.duplicate_of_index)
                if page.duplicate_of_index is not None
                else None
            )
            row = DocumentPage(
                tenant_id=principal.tenant_id,
                document_id=document.id,
                page_index=page.page_index,
                storage_key=page_key,
                width=page.width,
                height=page.height,
                quality_status=page.quality_status.value,
                quality_reasons=page.quality_reasons,
                ordering_reasons=rendered.page_ordering_reasons.get(page.page_index, []),
                printed_page_number=page.printed_page_number,
                text_excerpt=(page.text[:4000] or None),
                rotation_degrees=page.rotation_degrees,
                checksum=page.checksum,
                duplicate_of_page_id=duplicate_id,
            )
            self.session.add(row)
            self.session.flush()
            page_ids[page.page_index] = row.id

        document.page_count = rendered.page_count
        document.ordering_status = rendered.ordering_status.value
        document.ordering_reasons = rendered.ordering_reasons
        document.status = "PROCESSED"
        document.processed_at = utcnow()
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="document.ingested",
            entity_type="document",
            entity_id=document.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "kind": kind,
                "page_count": rendered.page_count,
                "ordering_status": rendered.ordering_status.value,
                "page_issues": sum(len(page.quality_reasons) for page in rendered.pages),
            },
        )
        self.session.commit()
        return document

    def get(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = self.documents.get(tenant_id, document_id)
        if document is None:
            raise AppError(ErrorCode.NOT_FOUND, "Document not found.")
        return document

    def pages(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> list[DocumentPage]:
        self.get(tenant_id, document_id)
        return self.documents.pages(tenant_id, document_id)

    def page_images(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID
    ) -> list[tuple[DocumentPage, bytes]]:
        pages = self.pages(tenant_id, document_id)
        images: list[tuple[DocumentPage, bytes]] = []
        for page in pages:
            try:
                images.append((page, self.storage.read(page.storage_key)))
            except StorageError as error:
                raise AppError(
                    ErrorCode.SERVICE_NOT_READY,
                    f"A rendered page is missing from storage (page {page.page_index}).",
                ) from error
        return images
