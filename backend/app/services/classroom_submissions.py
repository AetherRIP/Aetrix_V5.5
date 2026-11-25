"""Retrieving Classroom submissions into the existing Aetrix ingestion pipeline.

A submission is the external work; an Aetrix ``Submission`` and its ``Document``
are the internal record.  The link row keeps both, so a re-synchronization
updates the metadata of work already ingested instead of ingesting it again.

Ingestion reuses ``DocumentService``: the same validation, the same PDF/PNG/JPEG
support, the same rejection reasons.  A format the pipeline cannot read is
recorded as an actionable ``INGEST_FAILED`` message; it is never skipped quietly
and never replaced by a fabricated document.

Marking is a separate, explicit step.  Retrieving work never starts a correction
job, and a submission already processed is not re-marked by a synchronization.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import sha256_hex, utcnow
from ..core.security import Principal
from ..db.models import (
    Assignment,
    ClassroomCourseworkLink,
    ClassroomRosterEntry,
    ClassroomSubmissionLink,
    ClassroomSyncRun,
    Submission,
)
from ..db.repositories import SubmissionRepository
from ..documents.service import DocumentService
from ..jobs.service import JobService
from ..schemas.api import CorrectionCreate
from ..schemas.classroom_integration import (
    CorrectionStartRead,
    SubmissionRead,
    SubmissionSyncRead,
    SubmissionSyncRequest,
)
from ..storage.base import Storage, StorageError
from .classroom_access import ensure_teaching, require_allocation
from .classroom_google import (
    ClassroomUpstreamError,
    UpstreamKind,
    download_drive_file,
    list_submissions,
)
from .classroom_oauth import ClassroomOAuthService

#: The formats the ingestion pipeline validates.  Anything else is refused with
#: an explicit reason rather than being passed through.
SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
}

_EXTENSION_BY_MIME = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
}


def _safe_message(value: str) -> str:
    return " ".join(value.split())[:500]


class ClassroomSubmissionService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        storage: Storage,
        *,
        oauth: ClassroomOAuthService | None = None,
        transport: object | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.oauth = oauth or ClassroomOAuthService(
            session, settings, transport=transport
        )
        self.submissions = SubmissionRepository(session)
        self.audit = AuditService(session)

    # -- reads -----------------------------------------------------------
    @staticmethod
    def _read(
        link: ClassroomSubmissionLink,
        student_ref: str,
        student_name: str | None,
        correction_state: str | None,
        publication_state: str | None,
    ) -> SubmissionRead:
        return SubmissionRead(
            id=link.id,
            coursework_link_id=link.coursework_link_id,
            assignment_id=link.assignment_id,
            google_submission_id=link.google_submission_id,
            google_user_id=link.google_user_id,
            student_id=link.student_id,
            student_ref=student_ref,
            student_name=student_name,
            state=link.state,
            submission_state=link.submission_state,
            late=link.late,
            submission_id=link.submission_id,
            document_id=link.document_id,
            attachments=list(link.attachments or []),
            content_hash=link.content_hash,
            last_synced_at=link.last_synced_at,
            ingest_error=link.ingest_error,
            correction_job_id=link.correction_job_id,
            correction_state=correction_state,
            approved_total=link.approved_total,
            approved_max=link.approved_max,
            approved_at=link.approved_at,
            last_publication_state=publication_state,
            created_at=link.created_at,
        )

    def _rows(self, tenant_id: uuid.UUID, coursework_link_id: uuid.UUID) -> list[Any]:
        from ..db.models import ClassroomGradePublication, CorrectionJob, Student

        rows = list(
            self.session.execute(
                select(
                    ClassroomSubmissionLink,
                    Student.student_ref,
                    Student.display_name,
                    CorrectionJob.state,
                )
                .join(Student, ClassroomSubmissionLink.student_id == Student.id)
                .outerjoin(
                    CorrectionJob,
                    ClassroomSubmissionLink.correction_job_id == CorrectionJob.id,
                )
                .where(
                    ClassroomSubmissionLink.tenant_id == tenant_id,
                    ClassroomSubmissionLink.coursework_link_id == coursework_link_id,
                )
                .order_by(
                    Student.student_ref.asc(), ClassroomSubmissionLink.id.asc()
                )
            ).all()
        )
        link_ids = [row[0].id for row in rows]
        latest: dict[uuid.UUID, str] = {}
        if link_ids:
            for link_id, state in self.session.execute(
                select(
                    ClassroomGradePublication.submission_link_id,
                    ClassroomGradePublication.state,
                )
                .where(
                    ClassroomGradePublication.tenant_id == tenant_id,
                    ClassroomGradePublication.submission_link_id.in_(link_ids),
                )
                .order_by(ClassroomGradePublication.created_at.desc())
            ).all():
                latest.setdefault(link_id, state)
        return [(*row, latest.get(row[0].id)) for row in rows]

    def list(
        self, principal: Principal, coursework_link_id: uuid.UUID
    ) -> list[SubmissionRead]:
        link = self._coursework(principal.tenant_id, coursework_link_id)
        require_allocation(
            self.session, principal.tenant_id, course_id=link.course_id
        )
        return [
            self._read(sub, ref, name, job_state, publication_state)
            for sub, ref, name, job_state, publication_state in self._rows(
                principal.tenant_id, coursework_link_id
            )
        ]

    def _coursework(
        self, tenant_id: uuid.UUID, link_id: uuid.UUID
    ) -> ClassroomCourseworkLink:
        link = self.session.scalar(
            select(ClassroomCourseworkLink).where(
                ClassroomCourseworkLink.id == link_id,
                ClassroomCourseworkLink.tenant_id == tenant_id,
            )
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Coursework link not found.")
        return link

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

    def read(self, principal: Principal, link_id: uuid.UUID) -> SubmissionRead:
        link = self._link(principal.tenant_id, link_id)
        rows = self._rows(principal.tenant_id, link.coursework_link_id)
        for sub, ref, name, job_state, publication_state in rows:
            if sub.id == link.id:
                return self._read(sub, ref, name, job_state, publication_state)
        raise AppError(ErrorCode.NOT_FOUND, "Submission link not found.")

    # -- ingestion -------------------------------------------------------
    def _choose_attachment(
        self, attachments: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """The first ingestible Drive file, or the reason none is available."""

        unsupported: list[str] = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            if item.get("kind") != "DRIVE_FILE":
                unsupported.append(str(item.get("kind") or "unknown"))
                continue
            mime = str(item.get("mime_type") or "").lower()
            if not item.get("drive_file_id"):
                unsupported.append("DRIVE_FILE without an id")
                continue
            if mime and mime not in SUPPORTED_MIME_TYPES:
                unsupported.append(mime)
                continue
            return item, None
        if not attachments:
            return None, "Google reports no attachment for this submission."
        return None, (
            "No attachment is in a format the ingestion pipeline accepts "
            f"(supported: PDF, PNG, JPEG). Found: {', '.join(unsupported) or 'none'}."
        )

    def _submission_for(
        self,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        student_ref: str,
        content_hash: str,
    ) -> Submission:
        existing = self.session.scalar(
            select(Submission).where(
                Submission.tenant_id == tenant_id,
                Submission.assignment_id == assignment_id,
                Submission.student_ref == student_ref,
                Submission.content_hash == content_hash,
            )
        )
        if existing is not None:
            return existing
        return self.submissions.create(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            student_ref=student_ref,
            content_hash=content_hash,
        )

    def ingest(self, principal: Principal, link_id: uuid.UUID) -> SubmissionRead:
        ensure_teaching(principal)
        link = self._link(principal.tenant_id, link_id)
        require_allocation(
            self.session, principal.tenant_id, course_id=link.course_id
        )
        self._ingest(principal, link)
        self.session.commit()
        return self.read(principal, link_id)

    def _ingest(
        self, principal: Principal, link: ClassroomSubmissionLink
    ) -> None:
        if link.state in {"INGESTED", "CORRECTING", "CORRECTED"}:
            return

        attachment, refusal = self._choose_attachment(list(link.attachments or []))
        if attachment is None:
            link.state = "INGEST_FAILED"
            link.ingest_error = _safe_message(refusal or "No usable attachment.")
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="classroom.submission.ingest_refused",
                entity_type="classroom_submission_link",
                entity_id=link.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "course_id": link.course_id,
                    "google_submission_id": link.google_submission_id,
                    "reason": link.ingest_error,
                },
            )
            return

        access_token = self.oauth.access_token()
        file_id = str(attachment.get("drive_file_id"))
        try:
            data, content_type = download_drive_file(
                self.settings.classroom,
                access_token,
                file_id,
                transport=self.oauth.transport,  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            link.state = "INGEST_FAILED"
            link.ingest_error = _safe_message(
                f"The attachment could not be downloaded: {error.message}"
            )
            if error.kind in {
                UpstreamKind.RECONNECT_REQUIRED,
                UpstreamKind.SCOPE_MISSING,
            }:
                self.audit.record(
                    tenant_id=principal.tenant_id,
                    action="classroom.submission.ingest_failed",
                    entity_type="classroom_submission_link",
                    entity_id=link.id,
                    actor_type="USER",
                    actor_id=principal.user_id,
                    detail={
                        "google_submission_id": link.google_submission_id,
                        "error_code": error.kind,
                    },
                )
                self.oauth._raise_upstream(error)
            return

        declared = (attachment.get("mime_type") or content_type or "").lower()
        if declared not in SUPPORTED_MIME_TYPES:
            link.state = "INGEST_FAILED"
            link.ingest_error = _safe_message(
                f"Google returned {declared or 'an unknown type'}, which the "
                "ingestion pipeline does not accept (supported: PDF, PNG, JPEG)."
            )
            return

        digest = sha256_hex(data)
        if link.submission_id is not None and link.content_hash == digest:
            # The same bytes: nothing changed since the last successful ingest.
            if link.state != "INGEST_FAILED":
                link.state = "INGESTED"
            return
        if link.submission_id is not None and link.state == "CORRECTED":
            # Never replace the work behind an approved result automatically.
            link.ingest_error = _safe_message(
                "The student's work changed after it was corrected. An explicit "
                "re-mark is required before this new version is used."
            )
            return

        title = str(attachment.get("title") or "").strip()
        extension = _EXTENSION_BY_MIME.get(declared, "")
        filename = title or f"{link.google_submission_id}{extension}"
        if extension and not filename.lower().endswith(extension):
            filename = f"{filename}{extension}"

        try:
            submission = self._submission_for(
                principal.tenant_id,
                link.assignment_id,
                link.google_user_id,
                digest,
            )
            document = DocumentService(
                self.session, self.settings, self.storage
            ).ingest_for_submission(
                principal,
                submission.id,
                filename=filename,
                declared_mime=declared,
                data=data,
            )
        except AppError as error:
            link.state = "INGEST_FAILED"
            link.ingest_error = _safe_message(
                f"The document was rejected: {error.message}"
            )
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="classroom.submission.ingest_failed",
                entity_type="classroom_submission_link",
                entity_id=link.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "google_submission_id": link.google_submission_id,
                    "error_code": str(error.code),
                    "reasons": error.details.get("reasons"),
                },
            )
            return
        except (SQLAlchemyError, StorageError) as error:
            link.state = "INGEST_FAILED"
            link.ingest_error = _safe_message(
                f"Ingestion failed: {type(error).__name__}."
            )
            return

        link.submission_id = submission.id
        link.document_id = document.id
        link.content_hash = digest
        link.state = "INGESTED"
        link.ingest_error = None
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.submission.ingested",
            entity_type="classroom_submission_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "course_id": link.course_id,
                "coursework_id": link.coursework_id,
                "google_submission_id": link.google_submission_id,
                "submission_id": str(submission.id),
                "document_id": str(document.id),
                "document_status": document.status,
                "content_hash": digest,
            },
        )

    # -- synchronisation --------------------------------------------------
    def sync(
        self, principal: Principal, payload: SubmissionSyncRequest
    ) -> SubmissionSyncRead:
        ensure_teaching(principal)
        link = self._coursework(principal.tenant_id, payload.coursework_link_id)
        if link.state != "PUBLISHED" or not link.coursework_id:
            raise AppError(
                ErrorCode.CLASSROOM_ASSIGNMENT_NOT_PUBLISHED,
                "Submissions can only be read for coursework published to "
                "Google Classroom.",
            )
        require_allocation(
            self.session, principal.tenant_id, course_id=link.course_id
        )

        roster: dict[str, ClassroomRosterEntry] = {
            entry.google_user_id: entry
            for entry in self.session.scalars(
                select(ClassroomRosterEntry).where(
                    ClassroomRosterEntry.tenant_id == principal.tenant_id,
                    ClassroomRosterEntry.course_id == link.course_id,
                    ClassroomRosterEntry.status == "ACTIVE",
                )
            )
        }
        if not roster:
            raise AppError(
                ErrorCode.CLASSROOM_ROSTER_INCOMPLETE,
                "Synchronise the course roster first: a submission cannot be "
                "attached to a student until their Google identity is known.",
            )

        access_token = self.oauth.access_token()
        try:
            listing = list_submissions(
                self.settings.classroom,
                access_token,
                link.course_id,
                link.coursework_id,
                max_submissions=self.settings.classroom.max_submissions,
                states=("TURNED_IN", "RETURNED") if payload.only_turned_in else None,
                transport=self.oauth.transport,  # type: ignore[arg-type]
            )
        except ClassroomUpstreamError as error:
            self._record_run(
                principal,
                coursework_link_id=link.id,
                course_id=link.course_id,
                status="FAILED",
                counts={"discovered": 0},
                problems=[error.message],
            )
            self.session.commit()
            self.oauth._raise_upstream(error)

        counts = {
            "discovered": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "ingested": 0,
            "ingest_failed": 0,
            "without_student": 0,
        }
        problems: list[str] = []
        now = utcnow()

        for record in listing.submissions:
            counts["discovered"] += 1
            entry = roster.get(record.user_id)
            if entry is None:
                counts["without_student"] += 1
                problems.append(
                    f"Google user {record.user_id} is not on the synchronized "
                    "roster; their work was not imported."
                )
                continue

            existing = self.session.scalar(
                select(ClassroomSubmissionLink).where(
                    ClassroomSubmissionLink.tenant_id == principal.tenant_id,
                    ClassroomSubmissionLink.google_submission_id
                    == record.submission_id,
                )
            )
            attachments = [
                {
                    "kind": item.kind,
                    "title": item.title,
                    "drive_file_id": item.drive_file_id,
                    "alternate_link": item.alternate_link,
                    "mime_type": item.mime_type,
                }
                for item in record.attachments
            ]
            if existing is not None:
                existing.attachments = attachments
                existing.submission_state = record.state
                existing.late = record.late
                existing.last_synced_at = now
                if record.state == "RECLAIMED_BY_STUDENT":
                    existing.state = "WITHDRAWN"
                    counts["unchanged"] += 1
                    continue
                if existing.state in {"INGESTED", "CORRECTING", "CORRECTED"}:
                    counts["unchanged"] += 1
                    continue
                counts["updated"] += 1
                link_row = existing
            else:
                link_row = ClassroomSubmissionLink(
                    tenant_id=principal.tenant_id,
                    coursework_link_id=link.id,
                    assignment_id=link.assignment_id,
                    course_id=link.course_id,
                    coursework_id=link.coursework_id or "",
                    google_submission_id=record.submission_id,
                    google_user_id=record.user_id,
                    student_id=entry.student_id,
                    state="DISCOVERED",
                    submission_state=record.state,
                    late=record.late,
                    attachments=attachments,
                    last_synced_at=now,
                )
                self.session.add(link_row)
                self.session.flush()
                counts["created"] += 1

            # ``_ingest`` delegates to ``DocumentService``, which commits its
            # own work and with it this session's pending rows.  A savepoint
            # around that commit cannot survive: SQLAlchemy closes it with the
            # transaction, so a failed ingest must be recorded on the link row
            # rather than rolled back into a dead savepoint.
            try:
                self._ingest(principal, link_row)
                self.session.flush()
            except AppError as error:
                link_row.state = "INGEST_FAILED"
                link_row.ingest_error = _safe_message(error.message)
                problems.append(
                    f"Submission {record.submission_id}: {error.message}"
                )
            except SQLAlchemyError as error:
                problems.append(
                    f"Submission {record.submission_id} could not be recorded: "
                    f"{type(error).__name__}."
                )
                continue
            if link_row.state == "INGESTED":
                counts["ingested"] += 1
            elif link_row.state == "INGEST_FAILED":
                counts["ingest_failed"] += 1
                if link_row.ingest_error:
                    problems.append(
                        f"Submission {record.submission_id}: {link_row.ingest_error}"
                    )

        status = "PARTIAL" if (listing.truncated or problems) else "SUCCEEDED"
        self._record_run(
            principal,
            coursework_link_id=link.id,
            course_id=link.course_id,
            status=status,
            counts=counts,
            problems=problems,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.submissions.synchronized",
            entity_type="classroom_coursework_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={**counts, "truncated": listing.truncated},
        )
        self.session.commit()

        return SubmissionSyncRead(
            status=status,
            coursework_link_id=link.id,
            counts=counts,
            truncated=listing.truncated,
            submissions=[
                self._read(sub, ref, name, job_state, publication_state)
                for sub, ref, name, job_state, publication_state in self._rows(
                    principal.tenant_id, link.id
                )
            ],
            problems=problems,
        )

    def _record_run(
        self,
        principal: Principal,
        *,
        coursework_link_id: uuid.UUID,
        course_id: str,
        status: str,
        counts: dict[str, int],
        problems: list[str],
    ) -> None:
        now = utcnow()
        self.session.add(
            ClassroomSyncRun(
                tenant_id=principal.tenant_id,
                kind="SUBMISSIONS",
                status=status,
                course_id=course_id,
                coursework_link_id=coursework_link_id,
                actor_subject=principal.subject,
                counts=counts,
                error_code=None if status == "SUCCEEDED" else "PARTIAL_SUBMISSIONS",
                error_message="; ".join(problems)[:500] or None,
                started_at=now,
                finished_at=now,
            )
        )

    # -- correction -------------------------------------------------------
    def start_correction(
        self, principal: Principal, link_id: uuid.UUID
    ) -> CorrectionStartRead:
        ensure_teaching(principal)
        link = self._link(principal.tenant_id, link_id)
        if link.state == "INGEST_FAILED":
            raise AppError(
                ErrorCode.CONFLICT,
                "This submission's attachment was not ingested, so it cannot be "
                "marked. Resolve the ingestion error first.",
            )
        if link.submission_id is None:
            raise AppError(
                ErrorCode.CONFLICT,
                "This submission has not been ingested yet.",
            )
        assignment = self.session.scalar(
            select(Assignment).where(
                Assignment.id == link.assignment_id,
                Assignment.tenant_id == principal.tenant_id,
            )
        )
        if assignment is None:
            raise AppError(ErrorCode.NOT_FOUND, "Assignment not found.")

        # The key includes the external submission id, so a retried
        # synchronization or a double click returns the same job.
        key = f"classroom:{principal.tenant_id}:{link.google_submission_id}"[:200]
        creation = JobService(self.session, self.settings).create(
            principal,
            CorrectionCreate(
                assignment_id=link.assignment_id,
                submission_id=link.submission_id,
                idempotency_key=key,
            ),
        )
        link.correction_job_id = creation.job.id
        if link.state != "CORRECTED":
            link.state = "CORRECTING"
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.submission.correction_started",
            entity_type="classroom_submission_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "job_id": str(creation.job.id),
                "created": creation.created,
                "google_submission_id": link.google_submission_id,
            },
        )
        self.session.commit()
        return CorrectionStartRead(
            submission_link_id=link.id,
            job_id=creation.job.id,
            job_state=creation.job.state,
            created=creation.created,
        )
