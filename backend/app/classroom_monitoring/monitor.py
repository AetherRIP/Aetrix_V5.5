"""Scheduling, synchronisation and teacher controls for submission monitoring.

The Classroom API has no push notification for a student submission, so
monitoring is incremental polling with a due time per assignment, exponential
backoff on failure and a full re-list on every poll.  The full list is what makes
recovery real: an assignment that was not polled while Aetrix was offline is
reconciled on the next cycle, and a submission is never lost because one poll
was missed.

Polling never marks anything.  It records what Google reports and hands the work
to ``SubmissionMonitoringPipeline``, which inspects it and only then queues a job.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.logging import get_logger
from ..core.security import Principal, platform_authority
from ..db.models import (
    ClassroomCourseworkLink,
    ClassroomMonitorConfig,
    ClassroomMonitorRun,
    ClassroomRosterEntry,
    ClassroomSubmissionAttachment,
    ClassroomSubmissionLink,
    ClassroomSubmissionVersion,
    Student,
)
from ..services.classroom_access import ensure_teaching, require_course_access
from ..services.classroom_google import ClassroomUpstreamError, list_submissions
from ..services.classroom_oauth import ClassroomOAuthService
from ..services.classroom_submissions import (
    active_roster,
    is_ingestible,
    record_listing,
)
from ..storage.base import Storage
from .pipeline import SubmissionMonitoringPipeline, upstream_error
from .schemas import (
    MonitorAttachmentRead,
    MonitorIgnoreRequest,
    MonitorOverviewRead,
    MonitorResolveRequest,
    MonitorRetryRead,
    MonitorStateRead,
    MonitorSubmissionRead,
    MonitorSyncRead,
    MonitorToggleRequest,
)
from .states import CorrectionState, SubmissionState, transition

log = get_logger("aetrix.classroom.monitoring")

#: Google errors that mean no polling can succeed until a person reconnects.
_AUTH_CODES = frozenset(
    {
        ErrorCode.CLASSROOM_NOT_CONNECTED,
        ErrorCode.CLASSROOM_RECONNECT_REQUIRED,
        ErrorCode.CLASSROOM_SCOPE_MISSING,
        ErrorCode.CLASSROOM_NOT_CONFIGURED,
    }
)
#: The same codes as strings, for comparisons against stored error codes.
_AUTH_CODE_VALUES = frozenset(str(code) for code in _AUTH_CODES)


class ClassroomMonitorService:
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
            session,
            settings,
            transport=transport,  # type: ignore[arg-type]
        )
        self.transport = transport
        self.audit = AuditService(session)
        self.pipeline = SubmissionMonitoringPipeline(
            session, settings, storage, transport=transport
        )

    # -- lookups ---------------------------------------------------------
    def _coursework(self, principal: Principal, link_id: uuid.UUID) -> ClassroomCourseworkLink:
        link = self.session.scalar(
            select(ClassroomCourseworkLink).where(
                ClassroomCourseworkLink.id == link_id,
                ClassroomCourseworkLink.tenant_id == principal.tenant_id,
            )
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Coursework link not found.")
        require_course_access(self.session, principal, course_id=link.course_id)
        return link

    def _submission(self, principal: Principal, link_id: uuid.UUID) -> ClassroomSubmissionLink:
        link = self.session.scalar(
            select(ClassroomSubmissionLink).where(
                ClassroomSubmissionLink.id == link_id,
                ClassroomSubmissionLink.tenant_id == principal.tenant_id,
            )
        )
        if link is None:
            raise AppError(ErrorCode.NOT_FOUND, "Submission link not found.")
        require_course_access(self.session, principal, course_id=link.course_id)
        return link

    def _config(
        self, link: ClassroomCourseworkLink, *, create: bool = False
    ) -> ClassroomMonitorConfig | None:
        config = self.session.scalar(
            select(ClassroomMonitorConfig).where(
                ClassroomMonitorConfig.tenant_id == link.tenant_id,
                ClassroomMonitorConfig.coursework_link_id == link.id,
            )
        )
        if config is None and create:
            config = ClassroomMonitorConfig(
                tenant_id=link.tenant_id,
                coursework_link_id=link.id,
                assignment_id=link.assignment_id,
                enabled=False,
                paused=False,
                auto_queue=True,
                interval_seconds=self.settings.classroom.monitor_interval_seconds,
                relevance_policy="STRUCTURAL_ALLOW",
                last_counts={},
            )
            self.session.add(config)
            self.session.flush()
        return config

    # -- teacher configuration -------------------------------------------
    def update(
        self, principal: Principal, link_id: uuid.UUID, payload: MonitorToggleRequest
    ) -> MonitorStateRead:
        ensure_teaching(principal)
        link = self._coursework(principal, link_id)
        if link.state != "PUBLISHED" or not link.coursework_id:
            raise AppError(
                ErrorCode.CLASSROOM_ASSIGNMENT_NOT_PUBLISHED,
                "Only coursework published to Google Classroom can be monitored.",
            )
        config = self._config(link, create=True)
        assert config is not None
        now = utcnow()
        changed: dict[str, Any] = {}

        if payload.interval_seconds is not None:
            config.interval_seconds = payload.interval_seconds
            changed["interval_seconds"] = payload.interval_seconds
        if payload.relevance_policy is not None:
            config.relevance_policy = payload.relevance_policy
            changed["relevance_policy"] = payload.relevance_policy
        if payload.auto_queue is not None:
            config.auto_queue = payload.auto_queue
            changed["auto_queue"] = payload.auto_queue
        if payload.paused is not None:
            config.paused = payload.paused
            changed["paused"] = payload.paused
        if payload.enabled is not None:
            if payload.enabled and not config.enabled:
                config.enabled_by_user_id = principal.user_id
                config.enabled_by_subject = principal.subject
                config.monitoring_since = now
                config.consecutive_failures = 0
                config.backoff_until = None
            config.enabled = payload.enabled
            if not payload.enabled:
                config.next_poll_at = None
            changed["enabled"] = payload.enabled

        if config.enabled and not config.paused:
            config.next_poll_at = now
        else:
            config.next_poll_at = None

        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.monitoring.updated",
            entity_type="classroom_coursework_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "changes": changed,
                "reason": payload.reason,
                "actor_role": principal.role,
                "platform_role": platform_authority(principal),
            },
        )
        self.session.commit()
        return self.read_state(principal, link.id)

    # -- manual synchronisation ------------------------------------------
    def manual_sync(self, principal: Principal, link_id: uuid.UUID) -> MonitorSyncRead:
        ensure_teaching(principal)
        link = self._coursework(principal, link_id)
        if link.state != "PUBLISHED" or not link.coursework_id:
            raise AppError(
                ErrorCode.CLASSROOM_ASSIGNMENT_NOT_PUBLISHED,
                "Only coursework published to Google Classroom can be synchronised.",
            )
        config = self._config(link, create=True)
        assert config is not None
        status, counts, problems = self._poll(
            link, config, trigger="MANUAL", actor_subject=principal.subject
        )
        return MonitorSyncRead(
            status=status,
            coursework_link_id=link.id,
            counts=counts,
            problems=problems,
            state=self.read_state(principal, link.id),
        )

    # -- the poll --------------------------------------------------------
    def _poll(
        self,
        link: ClassroomCourseworkLink,
        config: ClassroomMonitorConfig,
        *,
        trigger: str,
        actor_subject: str,
    ) -> tuple[str, dict[str, int], list[str]]:
        run = ClassroomMonitorRun(
            tenant_id=link.tenant_id,
            coursework_link_id=link.id,
            trigger=trigger,
            status="RUNNING",
            counts={},
            actor_subject=actor_subject[:200],
            started_at=utcnow(),
        )
        self.session.add(run)
        self.session.commit()
        run_id = run.id

        counts = {
            "listed": 0,
            "discovered": 0,
            "created": 0,
            "not_turned_in": 0,
            "withdrawn": 0,
            "unchanged": 0,
            "ready": 0,
            "needs_teacher": 0,
            "ignored": 0,
            "failed": 0,
            "duplicate": 0,
            "without_student": 0,
        }
        problems: list[str] = []
        try:
            problems = self._reconcile(link, config, counts)
        except AppError as error:
            self._record_failure(link.id, error.code, error.message)
            self._finish_run(run_id, "FAILED", counts, problems, str(error.code), error.message)
            raise
        except ClassroomUpstreamError as error:
            app_error = upstream_error(error)
            self._record_failure(link.id, app_error.code, error.message)
            self._finish_run(run_id, "FAILED", counts, problems, str(app_error.code), error.message)
            raise app_error from error

        status = "PARTIAL" if problems else "SUCCEEDED"
        now = utcnow()
        config = self.session.get(ClassroomMonitorConfig, config.id)
        if config is not None:
            config.last_polled_at = now
            config.last_poll_status = status
            config.last_poll_error = "; ".join(problems)[:500] or None
            config.last_error_code = "PARTIAL" if problems else None
            config.last_counts = counts
            config.consecutive_failures = 0
            config.backoff_until = None
            config.next_poll_at = now + self._interval(config)
        self.session.commit()
        self._finish_run(run_id, status, counts, problems, None, None)
        return status, counts, problems

    def _reconcile(
        self,
        link: ClassroomCourseworkLink,
        config: ClassroomMonitorConfig,
        counts: dict[str, int],
    ) -> list[str]:
        problems: list[str] = []
        roster = active_roster(self.session, tenant_id=link.tenant_id, course_id=link.course_id)
        if not roster:
            raise AppError(
                ErrorCode.CLASSROOM_ROSTER_INCOMPLETE,
                "Synchronise the course roster before monitoring: a submission cannot "
                "be attached to a student whose Google identity is unknown.",
            )

        access_token = self.oauth.access_token()
        listing = list_submissions(
            self.settings.classroom,
            access_token,
            link.course_id,
            link.coursework_id or "",
            max_submissions=self.settings.classroom.max_submissions,
            # Every state is listed so a withdrawn submission is observed rather
            # than silently disappearing.  Only turned-in work enters the
            # pipeline.
            states=None,
            transport=self.oauth.transport,  # type: ignore[arg-type]
        )
        if listing.truncated:
            problems.append(
                "Google returned more submissions than the configured ceiling, so "
                "some students were not read this cycle."
            )

        now = utcnow()
        seen: set[str] = set()
        for record in listing.submissions:
            counts["listed"] += 1
            entry = roster.get(record.user_id)
            if entry is None:
                counts["without_student"] += 1
                problems.append(
                    f"Google user {record.user_id} is not on the roster; their work was "
                    "not imported."
                )
                continue
            seen.add(record.submission_id)
            withdraw = record.state == "RECLAIMED_BY_STUDENT"
            if withdraw or not is_ingestible(record.state):
                # Work that was never handed in is recorded only if it is already
                # known, so an untouched assignment does not grow a row per student.
                known = self.session.scalar(
                    select(ClassroomSubmissionLink.id).where(
                        ClassroomSubmissionLink.tenant_id == link.tenant_id,
                        ClassroomSubmissionLink.google_submission_id == record.submission_id,
                    )
                )
                if known is None:
                    counts["not_turned_in"] += 1
                    continue

            existing, created = record_listing(self.session, link, entry, record, now=now)
            if created:
                counts["created"] += 1
                self.audit.record(
                    tenant_id=link.tenant_id,
                    action="classroom.monitoring.submission_detected",
                    entity_type="classroom_submission_link",
                    entity_id=existing.id,
                    actor_type="SYSTEM",
                    detail={
                        "course_id": link.course_id,
                        "coursework_id": link.coursework_id,
                        "google_submission_id": record.submission_id,
                        "google_state": record.state,
                        "late": record.late,
                    },
                )

            counts["discovered"] += 1
            if withdraw:
                current = self.pipeline._latest(existing.id)
                if current is not None and current.state in {
                    SubmissionState.DETECTED.value,
                    SubmissionState.READY.value,
                    SubmissionState.NEEDS_TEACHER.value,
                }:
                    if current.state != SubmissionState.SUPERSEDED.value:
                        transition(current, SubmissionState.SUPERSEDED)
                    current.superseded_at = now
                existing.state = "WITHDRAWN"
                existing.ingest_error = "The student withdrew this submission in Google Classroom."
                counts["withdrawn"] += 1
                continue

            if not is_ingestible(record.state):
                counts["not_turned_in"] += 1
                continue

            outcome = self.pipeline.process(existing, record, config, access_token)
            key = outcome.result if outcome.result in counts else "unchanged"
            counts[key] += 1
            if outcome.result == "failed" and outcome.detail.get("result") == "download_failed":
                problems.append(
                    f"Submission {record.submission_id}: an attachment could not be downloaded."
                )

        # A submission Google no longer lists for a student still on the roster is
        # reported, never deleted: deletion may be a Google-side removal rather
        # than a withdrawal, and the teacher decides what it means.
        if not listing.truncated:
            stale = self.session.scalars(
                select(ClassroomSubmissionLink).where(
                    ClassroomSubmissionLink.tenant_id == link.tenant_id,
                    ClassroomSubmissionLink.coursework_link_id == link.id,
                    ClassroomSubmissionLink.google_submission_id.notin_(sorted(seen))
                    if seen
                    else True,
                    ClassroomSubmissionLink.state.notin_(("WITHDRAWN",)),
                )
            )
            for row in stale:
                if row.submission_state != "NOT_IN_LIST":
                    row.submission_state = "NOT_IN_LIST"
                    problems.append(
                        f"Submission {row.google_submission_id} is no longer listed by "
                        "Google; its Aetrix record is kept."
                    )
        self.session.commit()
        return problems

    # -- cycle -----------------------------------------------------------
    def due_configs(self, limit: int) -> list[ClassroomMonitorConfig]:
        now = utcnow()
        return list(
            self.session.scalars(
                select(ClassroomMonitorConfig)
                .where(
                    ClassroomMonitorConfig.enabled.is_(True),
                    ClassroomMonitorConfig.paused.is_(False),
                    or_(
                        ClassroomMonitorConfig.next_poll_at.is_(None),
                        ClassroomMonitorConfig.next_poll_at <= now,
                    ),
                    or_(
                        ClassroomMonitorConfig.backoff_until.is_(None),
                        ClassroomMonitorConfig.backoff_until <= now,
                    ),
                )
                .order_by(ClassroomMonitorConfig.next_poll_at.asc().nullsfirst())
                .limit(limit)
            )
        )

    def cycle(self, limit: int | None = None) -> dict[str, int]:
        """Poll every due assignment once.  Safe to call from a worker thread."""

        ceiling = limit or self.settings.classroom.monitor_max_per_cycle
        counts = {"polled": 0, "succeeded": 0, "partial": 0, "failed": 0}
        for config in self.due_configs(ceiling):
            counts["polled"] += 1
            link = self.session.get(ClassroomCourseworkLink, config.coursework_link_id)
            if link is None or link.state != "PUBLISHED":
                self._record_failure(
                    config.coursework_link_id,
                    ErrorCode.CLASSROOM_ASSIGNMENT_NOT_PUBLISHED,
                    "The coursework is no longer published to Google Classroom.",
                )
                counts["failed"] += 1
                continue
            try:
                status, _, _ = self._poll(
                    link, config, trigger="SCHEDULE", actor_subject="system:monitor"
                )
                counts["succeeded" if status == "SUCCEEDED" else "partial"] += 1
            except AppError as error:
                counts["failed"] += 1
                log.warning(
                    "classroom monitoring poll failed",
                    extra={
                        "extra_fields": {
                            "coursework_link_id": str(link.id),
                            "error_code": str(error.code),
                        }
                    },
                )
            except Exception:
                counts["failed"] += 1
                log.exception(
                    "classroom monitoring poll raised unexpectedly",
                    extra={"extra_fields": {"coursework_link_id": str(link.id)}},
                )
                self.session.rollback()
                self._record_failure(
                    link.id,
                    ErrorCode.INTERNAL_ERROR,
                    "The monitoring cycle failed unexpectedly.",
                )
        return counts

    def _interval(self, config: ClassroomMonitorConfig) -> timedelta:
        return timedelta(seconds=config.interval_seconds)

    def _record_failure(
        self, coursework_link_id: uuid.UUID, code: ErrorCode | str, message: str
    ) -> None:
        config = self.session.scalar(
            select(ClassroomMonitorConfig).where(
                ClassroomMonitorConfig.coursework_link_id == coursework_link_id
            )
        )
        if config is None:
            return
        config.consecutive_failures += 1
        config.last_poll_status = "FAILED"
        config.last_error_code = str(code)[:80]
        config.last_poll_error = " ".join((message or "").split())[:500] or None
        now = utcnow()
        base = max(config.interval_seconds, 60)
        attempts = min(config.consecutive_failures, 6)
        delay = min(base * (2**attempts), self.settings.classroom.monitor_max_backoff_seconds)
        if str(code) in _AUTH_CODE_VALUES:
            # Retrying a rejected grant cannot succeed, so wait the full ceiling
            # instead of polling Google every few minutes.
            delay = self.settings.classroom.monitor_max_backoff_seconds
        config.backoff_until = now + timedelta(seconds=delay)
        config.next_poll_at = config.backoff_until
        self.session.commit()
        self.audit.record(
            tenant_id=config.tenant_id,
            action="classroom.monitoring.poll_failed",
            entity_type="classroom_coursework_link",
            entity_id=config.coursework_link_id,
            actor_type="SYSTEM",
            detail={
                "error_code": str(code),
                "failures": config.consecutive_failures,
                "retry_in_seconds": delay,
            },
        )
        self.session.commit()

    def _finish_run(
        self,
        run_id: uuid.UUID,
        status: str,
        counts: dict[str, int],
        problems: list[str],
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        run = self.session.get(ClassroomMonitorRun, run_id)
        if run is None:
            return
        run.status = status
        run.counts = counts
        run.error_code = error_code
        run.error_message = "; ".join(problems) or error_message or None
        if run.error_message:
            run.error_message = run.error_message[:500]
        run.finished_at = utcnow()
        self.session.commit()

    # -- reads -----------------------------------------------------------
    def read_state(self, principal: Principal, coursework_link_id: uuid.UUID) -> MonitorStateRead:
        link = self._coursework(principal, coursework_link_id)
        return self._state_read(link, self._config(link))

    def overview(self, principal: Principal) -> MonitorOverviewRead:
        links = list(
            self.session.scalars(
                select(ClassroomCourseworkLink)
                .where(
                    ClassroomCourseworkLink.tenant_id == principal.tenant_id,
                    ClassroomCourseworkLink.state == "PUBLISHED",
                )
                .order_by(ClassroomCourseworkLink.title.asc())
            )
        )
        states: list[MonitorStateRead] = []
        for link in links:
            try:
                require_course_access(self.session, principal, course_id=link.course_id)
            except AppError:
                continue
            states.append(self._state_read(link, self._config(link)))
        runs = self.session.scalars(
            select(ClassroomMonitorRun)
            .where(ClassroomMonitorRun.tenant_id == principal.tenant_id)
            .order_by(ClassroomMonitorRun.started_at.desc())
            .limit(10)
        )
        return MonitorOverviewRead(
            workspace_id=principal.tenant_id,
            monitoring_enabled_on_server=self.settings.classroom.monitoring_enabled,
            states=states,
            recent_runs=[
                {
                    "id": str(run.id),
                    "coursework_link_id": str(run.coursework_link_id)
                    if run.coursework_link_id
                    else None,
                    "trigger": run.trigger,
                    "status": run.status,
                    "counts": run.counts,
                    "started_at": run.started_at.isoformat(),
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "error_message": run.error_message,
                }
                for run in runs
            ],
        )

    def _state_read(
        self,
        link: ClassroomCourseworkLink,
        config: ClassroomMonitorConfig | None,
    ) -> MonitorStateRead:
        expected = (
            self.session.scalar(
                select(func.count(ClassroomRosterEntry.id)).where(
                    ClassroomRosterEntry.tenant_id == link.tenant_id,
                    ClassroomRosterEntry.course_id == link.course_id,
                    ClassroomRosterEntry.status == "ACTIVE",
                )
            )
            or 0
        )
        submitted = (
            self.session.scalar(
                select(func.count(ClassroomSubmissionLink.id)).where(
                    ClassroomSubmissionLink.tenant_id == link.tenant_id,
                    ClassroomSubmissionLink.coursework_link_id == link.id,
                    ClassroomSubmissionLink.submission_state.in_(("TURNED_IN", "RETURNED")),
                )
            )
            or 0
        )
        versions = self._current_versions(link)
        states = [row.state for row in versions]
        corrections = [row.correction_state for row in versions]
        health = self._health(config)
        return MonitorStateRead(
            coursework_link_id=link.id,
            assignment_id=link.assignment_id,
            assignment_name=link.title,
            course_id=link.course_id,
            coursework_id=link.coursework_id,
            enabled=bool(config and config.enabled),
            paused=bool(config and config.paused),
            auto_queue=bool(config.auto_queue) if config else True,
            relevance_policy=config.relevance_policy if config else "STRUCTURAL_ALLOW",
            interval_seconds=config.interval_seconds
            if config
            else self.settings.classroom.monitor_interval_seconds,
            health=health,
            next_poll_at=config.next_poll_at if config else None,
            last_polled_at=config.last_polled_at if config else None,
            last_poll_status=config.last_poll_status if config else None,
            last_poll_error=config.last_poll_error if config else None,
            last_error_code=config.last_error_code if config else None,
            consecutive_failures=config.consecutive_failures if config else 0,
            last_counts=(config.last_counts if config else {}) or {},
            monitoring_since=config.monitoring_since if config else None,
            enabled_by_subject=config.enabled_by_subject if config else None,
            expected_students=int(expected),
            submitted_students=int(submitted),
            awaiting_review=states.count(SubmissionState.NEEDS_TEACHER.value),
            ready_submissions=states.count(SubmissionState.READY.value),
            queued_corrections=corrections.count(CorrectionState.QUEUED.value),
            processing_corrections=corrections.count(CorrectionState.PROCESSING.value),
            completed_corrections=corrections.count(CorrectionState.COMPLETED.value),
            failed_corrections=corrections.count(CorrectionState.FAILED.value),
        )

    @staticmethod
    def _health(config: ClassroomMonitorConfig | None) -> str:
        if config is None or not config.enabled:
            return "DISABLED"
        if config.paused:
            return "PAUSED"
        if config.consecutive_failures == 0 and config.last_poll_status == "SUCCEEDED":
            return "HEALTHY"
        if config.consecutive_failures == 0 and config.last_poll_status is None:
            return "UNKNOWN"
        if config.last_error_code in _AUTH_CODE_VALUES:
            return "BLOCKED"
        if config.consecutive_failures >= 3:
            return "BLOCKED"
        return "DEGRADED"

    def _current_versions(self, link: ClassroomCourseworkLink) -> list[ClassroomSubmissionVersion]:
        latest = (
            select(
                ClassroomSubmissionVersion.submission_link_id.label("link_id"),
                func.max(ClassroomSubmissionVersion.version).label("version"),
            )
            .join(
                ClassroomSubmissionLink,
                ClassroomSubmissionVersion.submission_link_id == ClassroomSubmissionLink.id,
            )
            .where(ClassroomSubmissionLink.coursework_link_id == link.id)
            .group_by(ClassroomSubmissionVersion.submission_link_id)
            .subquery()
        )
        return list(
            self.session.scalars(
                select(ClassroomSubmissionVersion).join(
                    latest,
                    (ClassroomSubmissionVersion.submission_link_id == latest.c.link_id)
                    & (ClassroomSubmissionVersion.version == latest.c.version),
                )
            )
        )

    def submissions(
        self, principal: Principal, coursework_link_id: uuid.UUID
    ) -> list[MonitorSubmissionRead]:
        link = self._coursework(principal, coursework_link_id)
        rows = self.session.execute(
            select(
                ClassroomSubmissionLink,
                Student.student_ref,
                Student.display_name,
            )
            .join(Student, ClassroomSubmissionLink.student_id == Student.id)
            .where(
                ClassroomSubmissionLink.tenant_id == principal.tenant_id,
                ClassroomSubmissionLink.coursework_link_id == link.id,
            )
            .order_by(Student.student_ref.asc())
        ).all()
        result: list[MonitorSubmissionRead] = []
        for row, student_ref, student_name in rows:
            versions = list(
                self.session.scalars(
                    select(ClassroomSubmissionVersion)
                    .where(ClassroomSubmissionVersion.submission_link_id == row.id)
                    .order_by(ClassroomSubmissionVersion.version.desc())
                )
            )
            if not versions:
                continue
            current = versions[0]
            attachments = self.session.scalars(
                select(ClassroomSubmissionAttachment)
                .where(ClassroomSubmissionAttachment.version_id == current.id)
                .order_by(ClassroomSubmissionAttachment.position.asc())
            )
            self.pipeline.sync_correction(current, row)
            result.append(
                MonitorSubmissionRead(
                    submission_link_id=row.id,
                    google_submission_id=row.google_submission_id,
                    google_user_id=row.google_user_id,
                    student_id=row.student_id,
                    student_ref=student_ref,
                    student_name=student_name,
                    google_state=current.google_state,
                    late=row.late,
                    detected_at=current.created_at,
                    last_synced_at=row.last_synced_at,
                    version=current.version,
                    version_count=len(versions),
                    state=current.state,
                    correction_state=current.correction_state,
                    eligibility=current.eligibility,
                    relevance=current.relevance,
                    decision_reasons=current.decision_reasons or [],
                    inspection=current.inspection_summary or {},
                    attachments=[
                        MonitorAttachmentRead(
                            position=item.position,
                            kind=item.kind,
                            title=item.title,
                            declared_mime=item.declared_mime,
                            detected_mime=item.detected_mime,
                            size_bytes=item.size_bytes,
                            status=item.status,
                            page_count=item.page_count,
                            sha256=item.sha256,
                            reason=item.reason,
                            issues=(item.inspection or {}).get("issues") or [],
                        )
                        for item in attachments
                    ],
                    correction_job_id=current.correction_job_id,
                    document_id=current.document_id,
                    last_error=current.last_error,
                    last_error_code=current.last_error_code,
                    superseded_at=current.superseded_at,
                    resolution_note=current.resolution_note,
                )
            )
        self.session.commit()
        return result

    # -- teacher actions -------------------------------------------------
    def retry(self, principal: Principal, link_id: uuid.UUID) -> MonitorRetryRead:
        ensure_teaching(principal)
        link = self._submission(principal, link_id)
        version = self.pipeline._latest(link.id)
        if version is None:
            raise AppError(
                ErrorCode.CLASSROOM_SUBMISSION_NOT_ELIGIBLE,
                "This submission has no inspected version to retry.",
            )
        if version.state not in {
            SubmissionState.FAILED.value,
            SubmissionState.NEEDS_TEACHER.value,
        }:
            raise AppError(
                ErrorCode.CLASSROOM_SUBMISSION_NOT_ELIGIBLE,
                "Only a failed or teacher-review submission can be retried.",
            )
        version.state = SubmissionState.DETECTED.value
        version.attempts = 0
        version.last_error = None
        version.last_error_code = None
        version.superseded_at = None
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.monitoring.submission_retry_requested",
            entity_type="classroom_submission_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"version": version.version},
        )
        self.session.commit()
        return MonitorRetryRead(
            submission_link_id=link.id,
            state=version.state,
            correction_state=version.correction_state,
            retried=True,
            message="The submission will be retrieved and inspected on the next poll.",
        )

    def ignore(
        self, principal: Principal, link_id: uuid.UUID, payload: MonitorIgnoreRequest
    ) -> MonitorSubmissionRead:
        ensure_teaching(principal)
        link = self._submission(principal, link_id)
        version = self.pipeline._latest(link.id)
        if version is None:
            raise AppError(ErrorCode.NOT_FOUND, "This submission has no version to ignore.")
        if version.correction_state in {
            CorrectionState.PROCESSING.value,
            CorrectionState.QUEUED.value,
        }:
            raise AppError(
                ErrorCode.CONFLICT,
                "A correction is already in progress; resolve it in the queue instead.",
            )
        if version.state != SubmissionState.SUPERSEDED.value:
            transition(version, SubmissionState.IGNORED)
        version.resolved_by_subject = principal.subject
        version.resolved_at = utcnow()
        version.resolution_note = payload.note
        link.state = "DISCOVERED"
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.monitoring.submission_ignored",
            entity_type="classroom_submission_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"version": version.version, "note": payload.note},
        )
        self.session.commit()
        return self._read_one(principal, link, version)

    def resolve(
        self, principal: Principal, link_id: uuid.UUID, payload: MonitorResolveRequest
    ) -> MonitorSubmissionRead:
        ensure_teaching(principal)
        link = self._submission(principal, link_id)
        version = self.pipeline._latest(link.id)
        if version is None:
            raise AppError(ErrorCode.NOT_FOUND, "This submission has no version to resolve.")
        if payload.action == "IGNORE":
            return self.ignore(principal, link_id, MonitorIgnoreRequest(note=payload.note))
        if payload.action == "REQUEUE":
            if version.state != SubmissionState.NEEDS_TEACHER.value:
                raise AppError(
                    ErrorCode.CLASSROOM_SUBMISSION_NOT_ELIGIBLE,
                    "Only a submission awaiting review can be accepted for correction.",
                )
            if version.content_hash is None:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "This submission has no inspected content to mark.",
                )
            version.state = SubmissionState.READY.value
            version.eligibility = "ELIGIBLE"
            config = self._config(
                self.session.get(ClassroomCourseworkLink, link.coursework_link_id),
                create=True,
            )
            assert config is not None
            self.pipeline._queue(link, version, config)
            version.resolved_by_subject = principal.subject
            version.resolved_at = utcnow()
            version.resolution_note = payload.note
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="classroom.monitoring.submission_accepted",
                entity_type="classroom_submission_link",
                entity_id=link.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={"version": version.version, "note": payload.note},
            )
            self.session.commit()
            return self._read_one(principal, link, version)
        version.resolved_by_subject = principal.subject
        version.resolved_at = utcnow()
        version.resolution_note = payload.note
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="classroom.monitoring.submission_reviewed",
            entity_type="classroom_submission_link",
            entity_id=link.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"version": version.version, "note": payload.note},
        )
        self.session.commit()
        return self._read_one(principal, link, version)

    def _read_one(
        self,
        principal: Principal,
        link: ClassroomSubmissionLink,
        version: ClassroomSubmissionVersion,
    ) -> MonitorSubmissionRead:
        rows = self.submissions(principal, link.coursework_link_id)
        for row in rows:
            if row.submission_link_id == link.id:
                return row
        raise AppError(ErrorCode.NOT_FOUND, "Submission link not found.")
