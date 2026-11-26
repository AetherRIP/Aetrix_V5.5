"""The submission pipeline: detect -> retrieve -> inspect -> decide -> queue.

The pipeline is deliberately synchronous and explicit.  Each version of a
student's work is downloaded once, inspected once (or served from the inspection
cache), assessed against the assignment, ingested through the existing
``DocumentService``, and only then handed to the existing ``JobService``.

It never contacts a marking provider.  A Google failure parks the assignment
with a typed error; a provider outage leaves the submission ``READY`` and
queued, because those are separate problems.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import content_hash, sha256_hex, utcnow
from ..core.security import Principal
from ..db.models import (
    Assignment,
    ClassroomInspectionCache,
    ClassroomMonitorConfig,
    ClassroomSubmissionAttachment,
    ClassroomSubmissionLink,
    ClassroomSubmissionVersion,
    CorrectionJob,
    ExamBlueprintVersion,
    MarkSchemeVersion,
    Submission,
    User,
)
from ..db.repositories import SubmissionRepository
from ..documents.service import DocumentService
from ..jobs.service import JobService
from ..schemas.api import CorrectionCreate
from ..services.classroom_google import (
    ClassroomUpstreamError,
    SubmissionRecord,
    UpstreamKind,
    download_drive_file,
    export_drive_file,
)
from ..storage.base import Storage, StorageError
from .attachments import (
    AttachmentRejected,
    ClassifiedAttachment,
    Inspection,
    assemble_images_to_pdf,
    classify_attachments,
    inspect_bytes,
    inspection_from_findings,
    safe_filename,
)
from .relevance import (
    INSUFFICIENT_EVIDENCE,
    POSSIBLY_UNRELATED,
    RelevanceAssessment,
    assess,
)
from .states import (
    CorrectionState,
    SubmissionState,
    correction_state_for,
    set_correction_state,
    transition,
)

#: States that mean the current fingerprint has already been handled.
HOLD_STATES = frozenset({"READY", "NEEDS_TEACHER", "IGNORED"})
#: States a restarted worker may safely resume in place.
RESUME_STATES = frozenset({"DETECTED", "DOWNLOADING", "INSPECTING"})
MAX_ATTEMPTS = 3
#: Attachment statuses whose bytes were stored and can be marked.
USABLE_STATUSES = frozenset({"DOWNLOADED", "CONVERTED"})


@dataclass(slots=True)
class Retrieved:
    row: ClassroomSubmissionAttachment
    classified: ClassifiedAttachment
    status: str
    reason: str | None = None
    mime: str | None = None
    sha256: str | None = None
    inspection: Inspection | None = None
    cached: bool = False


@dataclass(slots=True)
class Outcome:
    result: str
    detail: dict[str, Any] = field(default_factory=dict)


def _reason(code: str, message: str, severity: str = "BLOCKER") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


class SubmissionMonitoringPipeline:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        storage: Storage,
        *,
        transport: object | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.transport = transport
        self.audit = AuditService(session)
        self.submissions = SubmissionRepository(session)

    # -- identity --------------------------------------------------------
    @staticmethod
    def fingerprint(record: SubmissionRecord) -> str:
        parts = [record.state or "", str(record.late), record.update_time or ""]
        for attachment in record.attachments:
            parts.extend(
                [
                    attachment.kind,
                    attachment.drive_file_id or "",
                    attachment.title or "",
                    attachment.mime_type or "",
                ]
            )
        return content_hash(*parts)

    def _latest(self, link_id: uuid.UUID) -> ClassroomSubmissionVersion | None:
        return self.session.scalar(
            select(ClassroomSubmissionVersion)
            .where(ClassroomSubmissionVersion.submission_link_id == link_id)
            .order_by(ClassroomSubmissionVersion.version.desc())
            .limit(1)
        )

    def _new_version(
        self,
        link: ClassroomSubmissionLink,
        record: SubmissionRecord,
        fingerprint: str,
    ) -> ClassroomSubmissionVersion:
        highest = self.session.scalar(
            select(func.max(ClassroomSubmissionVersion.version)).where(
                ClassroomSubmissionVersion.submission_link_id == link.id
            )
        )
        previous = self.session.scalars(
            select(ClassroomSubmissionVersion).where(
                ClassroomSubmissionVersion.submission_link_id == link.id,
                ClassroomSubmissionVersion.superseded_at.is_(None),
            )
        )
        now = utcnow()
        for row in previous:
            row.superseded_at = now
            if row.state != SubmissionState.SUPERSEDED.value:
                transition(row, SubmissionState.SUPERSEDED)
        version = ClassroomSubmissionVersion(
            tenant_id=link.tenant_id,
            submission_link_id=link.id,
            version=int(highest or 0) + 1,
            google_update_time=record.update_time,
            google_state=record.state,
            source_fingerprint=fingerprint,
            state=SubmissionState.DETECTED.value,
            correction_state=CorrectionState.NOT_QUEUED.value,
            eligibility="PENDING",
            relevance="UNASSESSED",
            decision_reasons=[],
            inspection_summary={},
        )
        self.session.add(version)
        self.session.flush()
        return version

    # -- entry point -----------------------------------------------------
    def process(
        self,
        link: ClassroomSubmissionLink,
        record: SubmissionRecord,
        config: ClassroomMonitorConfig,
        access_token: str,
    ) -> Outcome:
        fingerprint = self.fingerprint(record)
        latest = self._latest(link.id)

        if latest is not None and latest.source_fingerprint == fingerprint:
            if latest.state in HOLD_STATES:
                self.sync_correction(latest, link)
                return Outcome("unchanged")
            if latest.state not in RESUME_STATES:
                # FAILED or SUPERSEDED with identical metadata waits for an
                # explicit retry; polling must not loop over the same failure.
                return Outcome("unchanged")
            version = latest
        else:
            version = self._new_version(link, record, fingerprint)

        version.attempts += 1
        if version.attempts > MAX_ATTEMPTS and version.state in RESUME_STATES:
            version.state = SubmissionState.FAILED.value
            version.last_error_code = "ATTEMPTS_EXHAUSTED"
            version.last_error = (
                "The submission could not be inspected after "
                f"{MAX_ATTEMPTS} attempts; it needs a teacher's attention."
            )
            self._audit(
                link,
                "classroom.monitoring.submission_failed",
                {"reason": version.last_error, "attempts": version.attempts},
            )
            self.session.commit()
            return Outcome("failed")

        try:
            return self._run(link, version, record, config, access_token)
        except AppError as error:
            if error.code in {
                ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
                ErrorCode.CLASSROOM_SCOPE_MISSING,
                ErrorCode.CLASSROOM_NOT_CONNECTED,
                ErrorCode.CLASSROOM_NOT_CONFIGURED,
            }:
                # The whole assignment cannot be polled: let the monitor record
                # the failure and back off, rather than marking every student's
                # work as unusable.
                self.session.rollback()
                raise
            self._fail(link, version, error.code, error.message)
            return Outcome("failed")

    def _fail(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        code: str,
        message: str,
    ) -> None:
        version.last_error_code = str(code)[:80]
        version.last_error = " ".join(message.split())[:500]
        if version.state in RESUME_STATES:
            version.state = SubmissionState.FAILED.value
        link.ingest_error = version.last_error
        self._audit(
            link,
            "classroom.monitoring.submission_failed",
            {"error_code": str(code), "reason": version.last_error},
        )
        self.session.commit()

    # -- run -------------------------------------------------------------
    def _run(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        record: SubmissionRecord,
        config: ClassroomMonitorConfig,
        access_token: str,
    ) -> Outcome:
        if version.state == SubmissionState.DETECTED.value:
            transition(version, SubmissionState.DOWNLOADING)
            self.session.commit()

        rows = self._attachment_rows(link, version, record)
        retrieved = self._retrieve_all(link, version, rows, config, access_token)

        if version.state in {
            SubmissionState.DETECTED.value,
            SubmissionState.DOWNLOADING.value,
        }:
            transition(version, SubmissionState.INSPECTING)
            self.session.commit()

        return self._decide_and_finish(link, version, config, retrieved)

    def _attachment_rows(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        record: SubmissionRecord,
    ) -> list[Retrieved]:
        existing = {
            row.position: row
            for row in self.session.scalars(
                select(ClassroomSubmissionAttachment)
                .where(ClassroomSubmissionAttachment.version_id == version.id)
                .order_by(ClassroomSubmissionAttachment.position.asc())
            )
        }
        raw = [
            {
                "kind": attachment.kind,
                "title": attachment.title,
                "drive_file_id": attachment.drive_file_id,
                "alternate_link": attachment.alternate_link,
                "mime_type": attachment.mime_type,
            }
            for attachment in record.attachments
        ]
        classified = classify_attachments(raw)
        if not existing:
            for item in classified:
                row = ClassroomSubmissionAttachment(
                    tenant_id=link.tenant_id,
                    version_id=version.id,
                    position=item.position,
                    kind=item.kind,
                    google_file_id=item.google_file_id,
                    title=(item.title or None) and item.title[:300],
                    declared_mime=item.declared_mime,
                    status=(
                        "PENDING"
                        if item.action in {"DOWNLOAD", "EXPORT_PDF"}
                        else ("IGNORED" if item.action == "IGNORE" else "UNSUPPORTED")
                    ),
                    reason=item.reason,
                    inspection={},
                )
                self.session.add(row)
            self.session.flush()
            existing = {
                row.position: row
                for row in self.session.scalars(
                    select(ClassroomSubmissionAttachment).where(
                        ClassroomSubmissionAttachment.version_id == version.id
                    )
                )
            }
        by_position = {item.position: item for item in classified}
        rows: list[Retrieved] = []
        for position in sorted(existing):
            row = existing[position]
            item = by_position.get(position) or ClassifiedAttachment(
                position=position,
                kind=row.kind,
                title=row.title,
                google_file_id=row.google_file_id,
                declared_mime=row.declared_mime,
                action="UNSUPPORTED",
                reason=row.reason,
            )
            rows.append(Retrieved(row=row, classified=item, status=row.status, reason=row.reason))
        return rows

    # -- retrieval -------------------------------------------------------
    def _retrieve_all(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        rows: list[Retrieved],
        config: ClassroomMonitorConfig,
        access_token: str,
    ) -> list[Retrieved]:
        ingestion = self.settings.ingestion
        done: list[Retrieved] = []
        for item in rows:
            if item.classified.action == "IGNORE":
                item.status = "IGNORED"
                item.row.status = "IGNORED"
                done.append(item)
                continue
            if item.classified.action == "UNSUPPORTED":
                item.status = "UNSUPPORTED"
                item.row.status = "UNSUPPORTED"
                item.reason = item.classified.reason
                item.row.reason = item.classified.reason
                done.append(item)
                continue
            if item.row.status in USABLE_STATUSES and item.row.sha256:
                inspection = self._inspection_from_row(item.row)
                item.status = item.row.status
                item.sha256 = item.row.sha256
                item.mime = item.row.detected_mime
                item.inspection = inspection
                done.append(item)
                continue
            if item.row.status == "REJECTED":
                item.status = "REJECTED"
                item.inspection = self._inspection_from_row(item.row)
                done.append(item)
                continue

            data: bytes | None = None
            mime = item.classified.declared_mime
            fetch = (
                export_drive_file if item.classified.action == "EXPORT_PDF" else download_drive_file
            )
            try:
                data, mime = fetch(
                    self.settings.classroom,
                    access_token,
                    str(item.classified.google_file_id),
                    transport=self.transport,  # type: ignore[arg-type]
                )
                if item.classified.action == "EXPORT_PDF":
                    mime = mime or "application/pdf"
            except ClassroomUpstreamError as error:
                item.status = "FAILED"
                item.reason = self._safe(error.message)
                item.row.status = "FAILED"
                item.row.reason = item.reason
                self._audit(
                    link,
                    "classroom.monitoring.attachment_failed",
                    {
                        "position": item.row.position,
                        "error_code": error.kind,
                        "status_code": error.status_code,
                    },
                )
                if error.kind in {
                    UpstreamKind.RECONNECT_REQUIRED,
                    UpstreamKind.SCOPE_MISSING,
                    UpstreamKind.CONFIGURATION,
                }:
                    self.session.commit()
                    raise upstream_error(error) from error
                done.append(item)
                continue

            minimum = self.settings.classroom.monitor_min_bytes
            if len(data) < minimum:
                item.status = "REJECTED"
                item.reason = f"The attachment is only {len(data)} bytes."
                item.row.status = "REJECTED"
                item.row.reason = item.reason
                done.append(item)
                continue

            digest = sha256_hex(data)
            inspection = self._cached_inspection(link.tenant_id, digest)
            cached = inspection is not None
            if inspection is None:
                try:
                    inspection = inspect_bytes(
                        data,
                        settings=ingestion,
                        max_pages=self.settings.classroom.monitor_max_pages,
                    )
                except AttachmentRejected as error:
                    item.status = "REJECTED"
                    item.reason = self._safe(error.message)
                    item.row.status = "REJECTED"
                    item.row.reason = item.reason
                    item.row.sha256 = digest
                    item.row.size_bytes = len(data)
                    self._audit(
                        link,
                        "classroom.monitoring.attachment_rejected",
                        {
                            "position": item.row.position,
                            "error_code": error.code,
                        },
                    )
                    done.append(item)
                    continue
                self._cache_inspection(link.tenant_id, digest, inspection)

            storage_key = self._store(link, version, item, data, inspection.mime_type, digest)
            item.row.status = (
                "CONVERTED" if item.classified.action == "EXPORT_PDF" else "DOWNLOADED"
            )
            item.row.sha256 = digest
            item.row.size_bytes = len(data)
            item.row.detected_mime = inspection.mime_type
            item.row.page_count = inspection.page_count
            item.row.storage_key = storage_key
            item.row.inspection = inspection.as_findings()
            item.row.reason = None
            item.status = item.row.status
            item.sha256 = digest
            item.mime = inspection.mime_type
            item.inspection = inspection
            item.cached = cached
            done.append(item)
        self.session.flush()
        return done

    def _inspection_from_row(self, row: ClassroomSubmissionAttachment) -> Inspection | None:
        findings = row.inspection or {}
        if not findings:
            return None
        return inspection_from_findings(findings)

    def _store(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        item: Retrieved,
        data: bytes,
        mime: str,
        digest: str,
    ) -> str:
        suffix = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}[mime]
        key = (
            f"tenants/{link.tenant_id}/classroom/{version.id}/"
            f"{item.row.position:03d}-{digest}{suffix}"
        )
        try:
            self.storage.put(key, data, mime)
        except StorageError:
            # Storage is the document pipeline's own requirement; a failure here
            # is reported as a download failure rather than losing the record.
            item.status = "FAILED"
            item.row.status = "FAILED"
            item.row.reason = "The attachment could not be stored safely."
            raise AppError(
                ErrorCode.SERVICE_NOT_READY,
                "A Classroom attachment could not be stored.",
            ) from None
        return key

    # -- inspection cache ------------------------------------------------
    def _cached_inspection(self, tenant_id: uuid.UUID, digest: str) -> Inspection | None:
        row = self.session.scalar(
            select(ClassroomInspectionCache).where(
                ClassroomInspectionCache.tenant_id == tenant_id,
                ClassroomInspectionCache.content_sha256 == digest,
            )
        )
        if row is None:
            return None
        return inspection_from_findings(row.findings or {})

    def _cache_inspection(self, tenant_id: uuid.UUID, digest: str, inspection: Inspection) -> None:
        self.session.add(
            ClassroomInspectionCache(
                tenant_id=tenant_id,
                content_sha256=digest,
                mime_type=inspection.mime_type,
                size_bytes=inspection.size_bytes,
                page_count=inspection.page_count,
                readable=inspection.readable,
                findings=inspection.as_findings(),
            )
        )
        self.session.flush()

    # -- decision --------------------------------------------------------
    def _decide_and_finish(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        config: ClassroomMonitorConfig,
        retrieved: list[Retrieved],
    ) -> Outcome:
        usable = [item for item in retrieved if item.status in USABLE_STATUSES]
        ignored = [item for item in retrieved if item.status == "IGNORED"]
        unsupported = [item for item in retrieved if item.status == "UNSUPPORTED"]
        rejected = [item for item in retrieved if item.status == "REJECTED"]
        failed = [item for item in retrieved if item.status == "FAILED"]

        reasons: list[dict[str, str]] = []
        for item in retrieved:
            if item.reason:
                reasons.append(
                    _reason(
                        f"ATTACHMENT_{item.status}",
                        f"Attachment {item.row.position}: {item.reason}",
                        "INFO" if item.status in {"IGNORED", "UNSUPPORTED"} else "BLOCKER",
                    )
                )

        if not retrieved:
            return self._finish(
                link,
                version,
                state=SubmissionState.IGNORED,
                eligibility="BLOCKED",
                relevance="INSUFFICIENT_EVIDENCE",
                reasons=[
                    _reason("NO_ATTACHMENT", "Google reports no attachment for this submission.")
                ],
                summary={"attachments": 0},
                detail={"result": "no_attachment"},
            )

        if not usable:
            if failed:
                return self._finish(
                    link,
                    version,
                    state=SubmissionState.FAILED,
                    eligibility="BLOCKED",
                    relevance="CANNOT_DETERMINE",
                    reasons=[
                        *reasons,
                        _reason("DOWNLOAD_FAILED", "No attachment could be downloaded."),
                    ],
                    summary=self._summary(retrieved),
                    detail={"result": "download_failed"},
                )
            if rejected:
                return self._finish(
                    link,
                    version,
                    state=SubmissionState.NEEDS_TEACHER,
                    eligibility="BLOCKED",
                    relevance="CANNOT_DETERMINE",
                    reasons=[
                        *reasons,
                        _reason(
                            "ALL_ATTACHMENTS_REJECTED", "Every attachment was unreadable or unsafe."
                        ),
                    ],
                    summary=self._summary(retrieved),
                    detail={"result": "rejected"},
                )
            if unsupported and not ignored:
                return self._finish(
                    link,
                    version,
                    state=SubmissionState.NEEDS_TEACHER,
                    eligibility="BLOCKED",
                    relevance="CANNOT_DETERMINE",
                    reasons=[
                        *reasons,
                        _reason("UNSUPPORTED_ONLY", "Only unsupported attachments were submitted."),
                    ],
                    summary=self._summary(retrieved),
                    detail={"result": "unsupported"},
                )
            return self._finish(
                link,
                version,
                state=SubmissionState.IGNORED,
                eligibility="BLOCKED",
                relevance="INSUFFICIENT_EVIDENCE",
                reasons=[
                    *reasons,
                    _reason(
                        "EXTERNAL_LINK_ONLY",
                        "Only external links were submitted; nothing was fetched.",
                    ),
                ],
                summary=self._summary(retrieved),
                detail={"result": "ignored"},
            )

        page_count, readable_pages, text = self._inspection_totals(usable)
        warnings: list[dict[str, str]] = []
        for item in usable:
            if item.inspection:
                for issue in item.inspection.issues:
                    if issue.get("severity") == "WARNING":
                        warnings.append(
                            _reason(
                                str(issue.get("code")),
                                f"Attachment {item.row.position}: {issue.get('message')}",
                                "WARNING",
                            )
                        )

        digest = content_hash(
            "classroom-v1",
            *[f"{item.row.position}:{item.sha256}" for item in usable],
        )
        other = self.session.scalar(
            select(ClassroomSubmissionVersion).where(
                ClassroomSubmissionVersion.tenant_id == link.tenant_id,
                ClassroomSubmissionVersion.submission_link_id == link.id,
                ClassroomSubmissionVersion.content_hash == digest,
                ClassroomSubmissionVersion.id != version.id,
            )
        )
        if other is not None:
            version.content_hash = None
            version.superseded_at = utcnow()
            transition(version, SubmissionState.SUPERSEDED)
            self._audit(
                link,
                "classroom.monitoring.duplicate_content",
                {"identical_to_version": other.version},
            )
            self.session.commit()
            return Outcome("duplicate")

        version.content_hash = digest

        assignment = self.session.scalar(
            select(Assignment).where(
                Assignment.id == link.assignment_id,
                Assignment.tenant_id == link.tenant_id,
            )
        )
        if assignment is None:
            return self._finish(
                link,
                version,
                state=SubmissionState.NEEDS_TEACHER,
                eligibility="BLOCKED",
                relevance="CANNOT_DETERMINE",
                reasons=[_reason("ASSIGNMENT_MISSING", "The Aetrix assignment no longer exists.")],
                summary=self._summary(retrieved),
                detail={"result": "assignment_missing"},
            )

        blueprint, _scheme, gate = self._assignment_gate(assignment)
        expected_questions = self._expected_questions(blueprint)
        relevance = assess(
            text=text,
            page_count=page_count,
            readable_pages=readable_pages,
            assignment_name=assignment.name,
            assignment_description=None,
            expected_questions=expected_questions,
            policy=config.relevance_policy,
            has_attachments=True,
        )
        warnings.extend(
            _reason(str(item.get("code")), str(item.get("message")), "WARNING")
            for item in relevance.warnings
        )

        shared = self._shared_file_warning(link, digest)
        if shared:
            warnings.append(shared)

        ordering_warning = None
        if len(usable) > 1:
            if any(item.mime != "image/png" and item.mime != "image/jpeg" for item in usable):
                ordering_warning = _reason(
                    "MULTIPLE_DOCUMENTS",
                    "More than one document was submitted and their combined "
                    "order cannot be proven.",
                )
            else:
                ordering_warning = _reason(
                    "ATTACHMENT_ORDER_UNVERIFIED",
                    "Several images were submitted; they were combined in "
                    "Google's order, which cannot be independently verified.",
                    "WARNING",
                )
                warnings.append(ordering_warning)

        if ordering_warning is not None and ordering_warning["severity"] == "BLOCKER":
            return self._finish(
                link,
                version,
                state=SubmissionState.NEEDS_TEACHER,
                eligibility="NEEDS_TEACHER",
                relevance=relevance.relevance,
                reasons=[*reasons, *warnings, ordering_warning],
                summary=self._summary(retrieved, relevance),
                detail={"result": "order_ambiguous"},
            )

        if relevance.relevance in {
            POSSIBLY_UNRELATED,
            INSUFFICIENT_EVIDENCE,
            "CANNOT_DETERMINE",
        }:
            return self._finish(
                link,
                version,
                state=SubmissionState.NEEDS_TEACHER,
                eligibility="NEEDS_TEACHER",
                relevance=relevance.relevance,
                reasons=[
                    *reasons,
                    *warnings,
                    _reason(
                        "RELEVANCE_REQUIRES_REVIEW",
                        "A teacher must confirm this work belongs to the assignment.",
                    ),
                ],
                summary=self._summary(retrieved, relevance),
                detail={"result": "needs_teacher"},
                ingest=True,
            )

        if gate is not None:
            return self._finish(
                link,
                version,
                state=SubmissionState.NEEDS_TEACHER,
                eligibility="NEEDS_TEACHER",
                relevance=relevance.relevance,
                reasons=[*reasons, *warnings, gate],
                summary=self._summary(retrieved, relevance),
                detail={"result": "not_ready"},
                ingest=True,
            )

        outcome = self._finish(
            link,
            version,
            state=SubmissionState.READY,
            eligibility="ELIGIBLE",
            relevance=relevance.relevance,
            reasons=[*reasons, *warnings],
            summary=self._summary(retrieved, relevance),
            detail={"result": "ready"},
            ingest=True,
        )
        if config.enabled and config.auto_queue:
            self._queue(link, version, config)
        else:
            self._audit(
                link,
                "classroom.monitoring.not_queued",
                {"reason": "automatic queueing is disabled for this coursework"},
            )
        self.sync_correction(version, link)
        return outcome

    # -- assignment gates ------------------------------------------------
    def _assignment_gate(
        self, assignment: Assignment
    ) -> tuple[ExamBlueprintVersion | None, MarkSchemeVersion | None, dict[str, str] | None]:
        if assignment.blueprint_version_id is None:
            return (
                None,
                None,
                _reason("MISSING_BLUEPRINT", "The assignment has no approved blueprint."),
            )
        if assignment.scheme_version_id is None:
            return (
                None,
                None,
                _reason("MISSING_SCHEME", "The assignment has no approved mark scheme."),
            )
        blueprint = self.session.scalar(
            select(ExamBlueprintVersion).where(
                ExamBlueprintVersion.id == assignment.blueprint_version_id,
                ExamBlueprintVersion.tenant_id == assignment.tenant_id,
            )
        )
        scheme = self.session.scalar(
            select(MarkSchemeVersion).where(
                MarkSchemeVersion.id == assignment.scheme_version_id,
                MarkSchemeVersion.tenant_id == assignment.tenant_id,
            )
        )
        if blueprint is None:
            return None, None, _reason("MISSING_BLUEPRINT", "The assignment blueprint is missing.")
        if blueprint.status != "APPROVED":
            return (
                blueprint,
                scheme,
                _reason(
                    "BLUEPRINT_NOT_APPROVED",
                    "The assignment blueprint is no longer approved.",
                ),
            )
        if scheme is None:
            return (
                blueprint,
                None,
                _reason("MISSING_SCHEME", "The assignment mark scheme is missing."),
            )
        if scheme.status != "APPROVED":
            return (
                blueprint,
                scheme,
                _reason(
                    "SCHEME_NOT_APPROVED",
                    "The assignment mark scheme is no longer approved.",
                ),
            )
        if scheme.criteria_approved_at is None:
            return (
                blueprint,
                scheme,
                _reason(
                    "CRITERIA_NOT_APPROVED",
                    "The mark scheme criteria have not been approved against this blueprint.",
                ),
            )
        return blueprint, scheme, None

    @staticmethod
    def _expected_questions(blueprint: ExamBlueprintVersion | None) -> list[str]:
        if blueprint is None:
            return []
        structure = blueprint.structure or {}
        questions: list[str] = []
        for raw in structure.get("questions") or []:
            if not isinstance(raw, dict):
                continue
            identifier = raw.get("question_id")
            if isinstance(identifier, str) and identifier:
                questions.append(identifier)
            for sub in raw.get("subquestions") or []:
                if isinstance(sub, dict) and isinstance(sub.get("question_id"), str):
                    questions.append(sub["question_id"])
        return questions

    def _shared_file_warning(
        self, link: ClassroomSubmissionLink, digest: str
    ) -> dict[str, str] | None:
        other = self.session.scalar(
            select(ClassroomSubmissionVersion.id).where(
                ClassroomSubmissionVersion.tenant_id == link.tenant_id,
                ClassroomSubmissionVersion.content_hash == digest,
                ClassroomSubmissionVersion.submission_link_id != link.id,
            )
        )
        if other is None:
            return None
        return _reason(
            "POSSIBLE_SHARED_FILE",
            "An identical file was submitted by another student. This is flagged for "
            "a teacher, not treated as misconduct.",
            "WARNING",
        )

    # -- ingest ----------------------------------------------------------
    @staticmethod
    def _inspection_totals(usable: list[Retrieved]) -> tuple[int, int, str]:
        """Pages, non-blank pages and extractable text across the usable work."""

        inspections = [item.inspection for item in usable if item.inspection]
        return (
            sum(found.page_count for found in inspections),
            sum(len([page for page in found.pages if not page.blank]) for found in inspections),
            "\n".join(found.text_excerpt for found in inspections),
        )

    def _usable_bytes(self, usable: list[Retrieved]) -> tuple[bytes, str, str] | None:
        if len(usable) == 1:
            item = usable[0]
            data = self._bytes_for(item.row)
            if data is None:
                return None
            mime = item.mime or "application/pdf"
            suffix = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}.get(
                mime, ".pdf"
            )
            return data, mime, safe_filename(item.classified.title, suffix=suffix)
        if all(item.mime in {"image/png", "image/jpeg"} for item in usable):
            frames = [self._bytes_for(item.row) for item in usable]
            if any(frame is None for frame in frames):
                return None
            try:
                assembled = assemble_images_to_pdf([frame for frame in frames if frame])
            except AttachmentRejected as error:
                raise AppError(ErrorCode.DOCUMENT_REJECTED, error.message) from error
            return assembled, "application/pdf", safe_filename("classroom-scan", suffix=".pdf")
        return None

    def _bytes_for(self, row: ClassroomSubmissionAttachment) -> bytes | None:
        if not row.storage_key:
            return None
        try:
            return self.storage.read(row.storage_key)
        except (StorageError, FileNotFoundError):
            return None

    def _ingest(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        usable: list[Retrieved],
        principal: Principal,
        digest: str,
    ) -> None:
        payload = self._usable_bytes(usable)
        if payload is None:
            raise AppError(
                ErrorCode.DOCUMENT_REJECTED,
                "The attachments could not be combined into a single readable document.",
            )
        data, mime, filename = payload
        submission = self.session.scalar(
            select(Submission).where(
                Submission.tenant_id == link.tenant_id,
                Submission.assignment_id == link.assignment_id,
                Submission.content_hash == digest,
            )
        )
        if submission is None:
            submission = self.submissions.create(
                tenant_id=link.tenant_id,
                assignment_id=link.assignment_id,
                student_ref=link.google_user_id,
                content_hash=digest,
            )
        document = DocumentService(self.session, self.settings, self.storage).ingest_for_submission(
            principal,
            submission.id,
            filename=filename,
            declared_mime=mime,
            data=data,
        )
        version.aetrix_submission_id = submission.id
        version.document_id = document.id
        link.submission_id = submission.id
        link.document_id = document.id
        link.content_hash = digest
        for item in usable:
            item.row.document_id = document.id

    # -- queue -----------------------------------------------------------
    def _actor(self, config: ClassroomMonitorConfig) -> Principal | None:
        if config.enabled_by_user_id is None:
            return None
        user = self.session.get(User, config.enabled_by_user_id)
        if user is None or user.tenant_id != config.tenant_id:
            return None
        return Principal(
            user_id=user.id,
            tenant_id=user.tenant_id,
            subject=user.subject,
            role=user.role,
        )

    def _queue(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        config: ClassroomMonitorConfig,
    ) -> None:
        principal = self._actor(config)
        if principal is None:
            version.eligibility = "NEEDS_TEACHER"
            version.decision_reasons = [
                *(version.decision_reasons or []),
                _reason(
                    "MONITOR_OWNER_MISSING",
                    "The teacher who enabled monitoring is no longer available, so the "
                    "work cannot be queued automatically.",
                ),
            ]
            if version.state == SubmissionState.READY.value:
                transition(version, SubmissionState.NEEDS_TEACHER)
            return
        if version.document_id is None or version.aetrix_submission_id is None:
            version.eligibility = "NEEDS_TEACHER"
            return
        key = f"classroom:{link.google_submission_id}:{version.content_hash}"[:200]
        try:
            creation = JobService(self.session, self.settings).create(
                principal,
                CorrectionCreate(
                    assignment_id=link.assignment_id,
                    submission_id=version.aetrix_submission_id,
                    idempotency_key=key,
                ),
            )
        except AppError as error:
            # Missing or withdrawn scheme, or an unapproved blueprint: a hard
            # blocker that a teacher can resolve.  Nothing is marked.
            version.eligibility = "NEEDS_TEACHER"
            version.decision_reasons = [
                *(version.decision_reasons or []),
                _reason(str(error.code), error.message),
            ]
            if version.state == SubmissionState.READY.value:
                transition(version, SubmissionState.NEEDS_TEACHER)
            self._audit(
                link,
                "classroom.monitoring.queue_refused",
                {"error_code": str(error.code), "reason": error.message},
            )
            return

        version.correction_job_id = creation.job.id
        version.queued_at = utcnow()
        set_correction_state(version, correction_state_for(creation.job.state))
        link.correction_job_id = creation.job.id
        link.state = "CORRECTING"
        self._audit(
            link,
            "classroom.monitoring.correction_queued",
            {
                "job_id": str(creation.job.id),
                "created": creation.created,
                "content_hash": version.content_hash,
                "submission_id": str(version.aetrix_submission_id),
            },
        )

    # -- finishing -------------------------------------------------------
    def _summary(
        self,
        retrieved: list[Retrieved],
        relevance: RelevanceAssessment | None = None,
    ) -> dict[str, Any]:
        usable = [item for item in retrieved if item.status in USABLE_STATUSES]
        page_count, readable_pages, _ = self._inspection_totals(usable)
        summary: dict[str, Any] = {
            "attachment_count": len(retrieved),
            "usable_attachments": len(usable),
            "page_count": page_count,
            "readable_pages": readable_pages,
            "blank_pages": [
                {"position": item.row.position, "page_index": index}
                for item in usable
                if item.inspection
                for index in item.inspection.blank_pages
            ],
            "has_text": any(item.inspection.has_text for item in usable if item.inspection),
            "attachment_order": "GOOGLE_API" if len(usable) <= 1 else "UNVERIFIED",
            "attachments": [
                {
                    "position": item.row.position,
                    "kind": item.classified.kind,
                    "title": item.classified.title,
                    "status": item.status,
                    "mime_type": item.mime,
                    "sha256": item.sha256,
                    "page_count": item.inspection.page_count if item.inspection else None,
                    "reason": item.reason,
                    "issues": item.inspection.issues if item.inspection else [],
                }
                for item in retrieved
            ],
        }
        if relevance is not None:
            summary["relevance"] = relevance.relevance
            summary["relevance_evidence"] = relevance.evidence
            summary["relevance_warnings"] = relevance.warnings
            summary["missing_expected_questions"] = relevance.missing_expected
        return summary

    def _finish(
        self,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
        *,
        state: SubmissionState,
        eligibility: str,
        relevance: str,
        reasons: list[dict[str, str]],
        summary: dict[str, Any],
        detail: dict[str, Any],
        ingest: bool = False,
    ) -> Outcome:
        version.eligibility = eligibility
        version.relevance = relevance
        version.decision_reasons = reasons
        version.inspection_summary = summary
        version.inspected_at = utcnow()
        blocker = next((reason for reason in reasons if reason.get("severity") == "BLOCKER"), None)
        version.last_error = blocker["message"][:500] if blocker else None
        version.last_error_code = blocker["code"] if blocker else None

        if ingest:
            principal = self._actor_or_none(link)
            if principal is None:
                version.eligibility = "NEEDS_TEACHER"
                version.decision_reasons = [
                    *reasons,
                    _reason(
                        "MONITOR_OWNER_MISSING",
                        "The teacher who enabled monitoring is no longer available.",
                    ),
                ]
                state = SubmissionState.NEEDS_TEACHER
            else:
                usable = [
                    item for item in self._rows_for(version) if item.status in USABLE_STATUSES
                ]
                try:
                    self._ingest(link, version, usable, principal, str(version.content_hash))
                except AppError as error:
                    version.eligibility = "BLOCKED"
                    version.decision_reasons = [
                        *version.decision_reasons,
                        _reason(str(error.code), error.message),
                    ]
                    version.last_error_code = str(error.code)
                    version.last_error = self._safe(error.message)
                    state = SubmissionState.NEEDS_TEACHER

        if version.state != state.value:
            transition(version, state)
        self._summarise_link(link, version)
        self._audit(
            link,
            f"classroom.monitoring.submission_{state.value.lower()}",
            {
                "version": version.version,
                "eligibility": version.eligibility,
                "relevance": version.relevance,
                "content_hash": version.content_hash,
                "codes": [reason.get("code") for reason in version.decision_reasons],
            },
        )
        self.session.commit()
        return Outcome(str(detail.get("result", "processed")), detail)

    def _rows_for(self, version: ClassroomSubmissionVersion) -> list[Retrieved]:
        rows = self.session.scalars(
            select(ClassroomSubmissionAttachment)
            .where(ClassroomSubmissionAttachment.version_id == version.id)
            .order_by(ClassroomSubmissionAttachment.position.asc())
        )
        return [
            Retrieved(
                row=row,
                classified=ClassifiedAttachment(
                    position=row.position,
                    kind=row.kind,
                    title=row.title,
                    google_file_id=row.google_file_id,
                    declared_mime=row.declared_mime,
                    action="DOWNLOAD",
                ),
                status=row.status,
                reason=row.reason,
                mime=row.detected_mime,
                sha256=row.sha256,
                inspection=self._inspection_from_row(row),
            )
            for row in rows
        ]

    def _actor_or_none(self, link: ClassroomSubmissionLink) -> Principal | None:
        config = self.session.scalar(
            select(ClassroomMonitorConfig).where(
                ClassroomMonitorConfig.tenant_id == link.tenant_id,
                ClassroomMonitorConfig.coursework_link_id == link.coursework_link_id,
            )
        )
        if config is None:
            return None
        return self._actor(config)

    def _summarise_link(
        self, link: ClassroomSubmissionLink, version: ClassroomSubmissionVersion
    ) -> None:
        link.last_synced_at = utcnow()
        if version.state == SubmissionState.READY.value:
            link.state = "INGESTED"
            link.ingest_error = None
        elif version.state == SubmissionState.NEEDS_TEACHER.value:
            link.state = "INGEST_FAILED" if version.document_id is None else "INGESTED"
            link.ingest_error = version.last_error
        elif version.state == SubmissionState.IGNORED.value:
            link.state = "DISCOVERED"
            link.ingest_error = version.last_error
        elif version.state == SubmissionState.FAILED.value:
            link.state = "INGEST_FAILED"
            link.ingest_error = version.last_error

    # -- correction projection -------------------------------------------
    def sync_correction(
        self, version: ClassroomSubmissionVersion, link: ClassroomSubmissionLink
    ) -> None:
        if version.correction_job_id is None:
            return
        job = self.session.get(CorrectionJob, version.correction_job_id)
        if job is None:
            return
        set_correction_state(version, correction_state_for(job.state))
        if job.state == "COMPLETED":
            link.state = "CORRECTED"
        elif job.state in {"REVIEW_REQUIRED"}:
            link.state = "CORRECTING"
        elif job.state == "FAILED":
            link.state = "INGESTED"

    # -- helpers ---------------------------------------------------------
    def _audit(self, link: ClassroomSubmissionLink, action: str, detail: dict[str, Any]) -> None:
        self.audit.record(
            tenant_id=link.tenant_id,
            action=action,
            entity_type="classroom_submission_link",
            entity_id=link.id,
            actor_type="SYSTEM",
            detail={
                "course_id": link.course_id,
                "coursework_id": link.coursework_id,
                "google_submission_id": link.google_submission_id,
                **detail,
            },
        )

    @staticmethod
    def _safe(value: str) -> str:
        return " ".join((value or "").split())[:500]


def upstream_error(error: ClassroomUpstreamError) -> AppError:
    """Map a Google failure to the typed error the API reports."""

    if error.kind == UpstreamKind.RECONNECT_REQUIRED:
        return AppError(ErrorCode.CLASSROOM_RECONNECT_REQUIRED, error.message)
    if error.kind == UpstreamKind.SCOPE_MISSING:
        return AppError(ErrorCode.CLASSROOM_SCOPE_MISSING, error.message)
    if error.kind == UpstreamKind.CONFIGURATION:
        return AppError(ErrorCode.CLASSROOM_NOT_CONFIGURED, error.message)
    return AppError(ErrorCode.CLASSROOM_UPSTREAM_ERROR, error.message)


__all__ = [
    "Outcome",
    "Retrieved",
    "SubmissionMonitoringPipeline",
    "upstream_error",
]
