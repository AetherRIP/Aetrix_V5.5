"""Uploaded-script retention.

The engine stores two kinds of bytes per student script: the uploaded file and
one rendered image per page.  Everything derived from them — page text, quality
verdicts, mapping, the correction job, its evidence, its marks and its approval —
lives in database rows.  Retention therefore removes the stored bytes and marks
the rows as purged; it never deletes a document row, a page row, a job, a result
or an approval.

Eligibility is deliberately conservative:

* only ``STUDENT`` documents (mark schemes and question papers are reference
  material, not uploaded scripts);
* only documents attached to a submission (a student document with no submission
  is an unknown provenance and is kept);
* only documents older than the configured window;
* never a document whose submission has a correction job in an active state
  (queued, leased, processing, review, retry-suspended);
* never a document whose submission has an approved job, because approved grades
  must keep their supporting material;
* never a document already purged, so a repeated sweep is idempotent.

The sweep is operator-triggered and bound to the policy that was previewed.  It
is not scheduled: deleting student work is destructive, and no administrator has
approved an automatic deletion schedule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, exists, func, select
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..db.models import CorrectionJob, Document, DocumentPage, JobApproval
from ..jobs.states import ACTIVE_STATES
from ..storage.base import Storage, StorageError

_ACTIVE_STATES = tuple(state.value for state in ACTIVE_STATES)


def _active_job_for(document: Document) -> Any:
    return exists(
        select(CorrectionJob.id).where(
            CorrectionJob.tenant_id == Document.tenant_id,
            CorrectionJob.submission_id == Document.submission_id,
            CorrectionJob.state.in_(_ACTIVE_STATES),
        )
    )


def _approved_job_for(document: Document) -> Any:
    return exists(
        select(CorrectionJob.id)
        .join(JobApproval, JobApproval.job_id == CorrectionJob.id)
        .where(
            CorrectionJob.tenant_id == Document.tenant_id,
            CorrectionJob.submission_id == Document.submission_id,
        )
    )


@dataclass
class RetentionPreview:
    retention_days: int
    cutoff: datetime
    scanned_at: datetime
    eligible_documents: int = 0
    eligible_pages: int = 0
    eligible_bytes: int = 0
    already_purged_documents: int = 0
    protected: dict[str, int] = field(default_factory=dict)


@dataclass
class RetentionOutcome:
    purged_documents: int = 0
    purged_pages: int = 0
    purged_bytes: int = 0
    failed_documents: int = 0
    retention_days: int = 0
    cutoff: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class RetentionService:
    def __init__(self, session: Session, storage: Storage) -> None:
        self.session = session
        self.storage = storage
        self.audit = AuditService(session)

    # -- eligibility ----------------------------------------------------
    def _age_days(self) -> int:
        from .platform_settings import PlatformSettingsService

        return PlatformSettingsService(self.session).ensure().uploaded_script_retention_days

    def _cutoff(self, retention_days: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=retention_days)

    def _candidates(self, cutoff: datetime) -> Select[tuple[Document]]:
        return select(Document).where(
            Document.kind == "STUDENT",
            Document.storage_purged_at.is_(None),
            Document.created_at <= cutoff,
        )

    def _protected_condition(self) -> Any:
        return and_(
            Document.submission_id.is_not(None),
            ~_active_job_for(Document),
            ~_approved_job_for(Document),
        )

    def preview(self) -> RetentionPreview:
        days = self._age_days()
        cutoff = self._cutoff(days)
        preview = RetentionPreview(
            retention_days=days, cutoff=cutoff, scanned_at=datetime.now(UTC)
        )

        base = self._candidates(cutoff).subquery()
        eligible = select(
            func.count(base.c.id),
            func.coalesce(func.sum(base.c.page_count), 0),
            func.coalesce(func.sum(base.c.size_bytes), 0),
        ).where(
            base.c.submission_id.is_not(None),
            ~exists(
                select(CorrectionJob.id).where(
                    CorrectionJob.tenant_id == base.c.tenant_id,
                    CorrectionJob.submission_id == base.c.submission_id,
                    CorrectionJob.state.in_(_ACTIVE_STATES),
                )
            ),
            ~exists(
                select(CorrectionJob.id)
                .join(JobApproval, JobApproval.job_id == CorrectionJob.id)
                .where(
                    CorrectionJob.tenant_id == base.c.tenant_id,
                    CorrectionJob.submission_id == base.c.submission_id,
                )
            ),
        )
        documents, pages, size = self.session.execute(eligible).one()
        preview.eligible_documents = int(documents or 0)
        preview.eligible_pages = int(pages or 0)
        preview.eligible_bytes = int(size or 0)

        counts: dict[str, int] = {}
        for reason, condition in (
            ("no submission", base.c.submission_id.is_(None)),
            (
                "active correction job",
                exists(
                    select(CorrectionJob.id).where(
                        CorrectionJob.tenant_id == base.c.tenant_id,
                        CorrectionJob.submission_id == base.c.submission_id,
                        CorrectionJob.state.in_(_ACTIVE_STATES),
                    )
                ),
            ),
            (
                "approved grades",
                exists(
                    select(CorrectionJob.id)
                    .join(JobApproval, JobApproval.job_id == CorrectionJob.id)
                    .where(
                        CorrectionJob.tenant_id == base.c.tenant_id,
                        CorrectionJob.submission_id == base.c.submission_id,
                    )
                ),
            ),
        ):
            count = self.session.scalar(
                select(func.count()).select_from(base).where(condition)
            )
            if count:
                counts[reason] = int(count)
        preview.protected = counts

        preview.already_purged_documents = int(
            self.session.scalar(
                select(func.count(Document.id)).where(
                    Document.kind == "STUDENT",
                    Document.storage_purged_at.is_not(None),
                )
            )
            or 0
        )
        return preview

    # -- apply ----------------------------------------------------------
    def sweep(
        self, principal: Principal, *, limit: int, expected_retention_days: int
    ) -> RetentionOutcome:
        days = self._age_days()
        outcome = RetentionOutcome(
            retention_days=days,
            cutoff=self._cutoff(days),
            completed_at=datetime.now(UTC),
        )
        if days != expected_retention_days:
            raise AppError(
                ErrorCode.CONFLICT,
                "The retention window changed after this preview. Preview the "
                "policy again before purging.",
            )

        candidates = self.session.scalars(
            self._candidates(outcome.cutoff)
            .where(self._protected_condition())
            .order_by(Document.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()

        for document in candidates:
            pages = self.session.scalars(
                select(DocumentPage).where(DocumentPage.document_id == document.id)
            ).all()
            keys = [document.storage_key, *(page.storage_key for page in pages)]
            try:
                for key in keys:
                    self.storage.delete(key)
            except StorageError:
                # The bytes may have been removed outside the engine, or the
                # store may be unavailable.  Leaving the row unmarked keeps the
                # document eligible so the next sweep retries it.
                outcome.failed_documents += 1
                self.audit.record(
                    tenant_id=document.tenant_id,
                    action="document.storage_purge_failed",
                    entity_type="document",
                    entity_id=document.id,
                    actor_type="USER",
                    actor_id=principal.user_id,
                    detail={
                        "document_id": str(document.id),
                        "retention_days": days,
                        "reason": "storage delete failed",
                    },
                )
                continue

            purged_at = datetime.now(UTC)
            document.storage_purged_at = purged_at
            for page in pages:
                page.storage_purged_at = purged_at
            outcome.purged_documents += 1
            outcome.purged_pages += len(pages)
            outcome.purged_bytes += document.size_bytes
            self.audit.record(
                tenant_id=document.tenant_id,
                action="document.storage_purged",
                entity_type="document",
                entity_id=document.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "document_id": str(document.id),
                    "kind": document.kind,
                    "created_at": document.created_at.isoformat(),
                    "retention_days": days,
                    "pages_purged": len(pages),
                    "size_bytes": document.size_bytes,
                    "sha256": document.sha256,
                },
            )
        self.session.flush()
        outcome.completed_at = datetime.now(UTC)
        self.audit.record(
            tenant_id=None,
            action="platform.retention.swept",
            entity_type="platform_settings",
            entity_id="uploaded_script_retention_days",
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "retention_days": days,
                "cutoff": outcome.cutoff.isoformat(),
                "purged_documents": outcome.purged_documents,
                "failed_documents": outcome.failed_documents,
                "limit": limit,
            },
        )
        return outcome
