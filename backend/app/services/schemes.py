"""Mark-scheme upload and approval.

Upload creates a DRAFT version.  A scheme becomes usable by an assignment only
after an explicit approval, mirroring the blueprint gate.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.security import Principal, ensure_exam_manager, ensure_uploader
from ..db.models import MarkScheme, MarkSchemeVersion
from ..db.repositories import ExamRepository, MarkSchemeRepository
from ..documents.service import DocumentService
from ..storage.base import Storage


class SchemeService:
    def __init__(self, session: Session, settings: Settings, storage: Storage) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.exams = ExamRepository(session)
        self.schemes = MarkSchemeRepository(session)
        self.audit = AuditService(session)

    def upload(
        self,
        principal: Principal,
        exam_id: uuid.UUID,
        *,
        title: str,
        filename: str,
        declared_mime: str,
        data: bytes,
    ) -> tuple[MarkScheme, MarkSchemeVersion]:
        # Uploading is open to reviewers; approving the version below is not.
        ensure_uploader(principal)
        if self.exams.get(principal.tenant_id, exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        clean_title = title.strip()
        if not clean_title:
            raise AppError(ErrorCode.VALIDATION_ERROR, "A scheme title is required.")
        document = DocumentService(self.session, self.settings, self.storage).ingest_for_exam(
            principal,
            exam_id,
            kind="MARK_SCHEME",
            filename=filename,
            declared_mime=declared_mime,
            data=data,
        )
        scheme = self.schemes.create_scheme(
            tenant_id=principal.tenant_id,
            exam_id=exam_id,
            title=clean_title[:300],
            document_id=document.id,
        )
        version = self.schemes.create_version(
            tenant_id=principal.tenant_id,
            mark_scheme_id=scheme.id,
            content_hash=document.sha256,
            status="DRAFT",
            source="UPLOAD",
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme.uploaded",
            entity_type="mark_scheme_version",
            entity_id=version.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "exam_id": str(exam_id),
                "document_id": str(document.id),
                "version": version.version,
            },
        )
        self.session.commit()
        return scheme, version

    def get_version(self, tenant_id: uuid.UUID, version_id: uuid.UUID) -> MarkSchemeVersion:
        version = self.schemes.get_version(tenant_id, version_id)
        if version is None:
            raise AppError(ErrorCode.NOT_FOUND, "Mark-scheme version not found.")
        return version

    def list_versions(
        self, tenant_id: uuid.UUID, exam_id: uuid.UUID
    ) -> list[MarkSchemeVersion]:
        if self.exams.get(tenant_id, exam_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Exam not found.")
        from sqlalchemy import select

        return list(
            self.session.scalars(
                select(MarkSchemeVersion)
                .join(MarkScheme, MarkScheme.id == MarkSchemeVersion.mark_scheme_id)
                .where(
                    MarkSchemeVersion.tenant_id == tenant_id,
                    MarkScheme.exam_id == exam_id,
                )
                .order_by(MarkSchemeVersion.created_at.desc())
            )
        )

    def approve(
        self, principal: Principal, version_id: uuid.UUID, reason: str
    ) -> MarkSchemeVersion:
        ensure_exam_manager(principal)
        version = self.get_version(principal.tenant_id, version_id)
        version = self.schemes.approve_version(version)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="scheme.approved",
            entity_type="mark_scheme_version",
            entity_id=version.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"reason": reason.strip(), "version": version.version},
        )
        self.session.commit()
        return version
