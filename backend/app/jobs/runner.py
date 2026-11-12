"""Worker runner.

One claim, one heartbeat, one terminal transition.  The lease is renewed on a
separate session while the pipeline runs; if the process dies, the lease
expires and another worker reclaims the job.  The pipeline itself must be
idempotent at its own checkpoints before Phase 5 relies on this for partial
work — Phase 1 only guarantees that a crashed job is reclaimed, not that a
partially-marked paper is reused.
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..audit.service import AuditService
from ..core.config import Settings
from ..core.logging import get_logger, log_context
from ..db.models import CorrectionJob
from ..db.repositories import JobRepository
from .pipeline import (
    CorrectionPipeline,
    PipelineUnavailable,
    RetryablePipelineError,
)
from .service import JobService
from .states import JobState

log = get_logger("aetrix.worker")


class JobRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        pipeline: CorrectionPipeline,
        settings: Settings,
        worker_id: str,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._pipeline = pipeline
        self._settings = settings
        self.worker_id = worker_id
        self._stop = stop_event or threading.Event()
        self._heartbeat_stop = threading.Event()

    def run_once(self) -> str | None:
        with self._session_factory() as session:
            repository = JobRepository(session)
            job = repository.claim_next(
                worker_id=self.worker_id,
                lease_seconds=self._settings.worker.lease_seconds,
            )
            if job is None:
                return None
            tenant_id = job.tenant_id
            job_id = job.id
            state = job.state
            attempts = job.attempts
            #: Either the engine this job was created for or the engine that has
            #: already marked part of it.  Both must match this worker.
            recorded_engine = job.requested_engine_name or job.engine_name
            #: Captured at claim time.  A write is only applied if the job has
            #: not moved on since; that is what stops a worker whose lease
            #: lapsed from overwriting the work of the worker that replaced it.
            claimed_version = job.record_version

        with log_context(tenant_id=str(tenant_id), job_id=str(job_id)):
            log.info("job claimed", extra={"extra_fields": {"state": state, "attempt": attempts}})
            if recorded_engine and recorded_engine != self._pipeline.name:
                log.warning(
                    "job was created for a different engine; refusing to mark it",
                    extra={
                        "extra_fields": {
                            "recorded_engine": recorded_engine,
                            "worker_engine": self._pipeline.name,
                        }
                    },
                )
                self._refuse_engine_mismatch(
                    tenant_id,
                    job_id,
                    recorded_engine,
                    claimed_version=claimed_version,
                )
                return str(job_id)
            heartbeat = self._start_heartbeat(job_id)
            try:
                if self._cancel_requested(tenant_id, job_id):
                    self._finalize_cancel(tenant_id, job_id)
                    return str(job_id)
                with self._new_session() as run_session:
                    outcome = self._pipeline.run(job, run_session, self._settings)
                if self._cancel_requested(tenant_id, job_id):
                    self._finalize_cancel(tenant_id, job_id)
                    return str(job_id)
                self._apply_outcome(
                    tenant_id,
                    job_id,
                    outcome.state,
                    outcome.detail,
                    claimed_version=claimed_version,
                )
                return str(job_id)
            except PipelineUnavailable as error:
                log.warning("marking pipeline unavailable; parking job")
                self._fail(
                    tenant_id,
                    job_id,
                    code="PIPELINE_UNAVAILABLE",
                    message=str(error),
                    retryable=True,
                    claimed_version=claimed_version,
                )
                return str(job_id)
            except RetryablePipelineError as error:
                log.warning("retryable pipeline failure")
                self._fail(
                    tenant_id,
                    job_id,
                    code="PROVIDER_UNAVAILABLE",
                    message=str(error),
                    retryable=True,
                    claimed_version=claimed_version,
                )
                return str(job_id)
            except Exception as error:
                log.exception("unexpected pipeline failure")
                self._fail(
                    tenant_id,
                    job_id,
                    code="PIPELINE_ERROR",
                    message=f"{type(error).__name__}: {error}",
                    retryable=True,
                    claimed_version=claimed_version,
                )
                return str(job_id)
            finally:
                self._heartbeat_stop.set()
                heartbeat.join(timeout=2.0)
                self._clear_lease(tenant_id, job_id)

    def _new_session(self) -> Session:
        return self._session_factory()

    def _start_heartbeat(self, job_id: Any) -> threading.Thread:
        self._heartbeat_stop.clear()
        interval = self._settings.worker.heartbeat_seconds
        lease = self._settings.worker.lease_seconds

        def beat() -> None:
            while not self._heartbeat_stop.wait(interval):
                try:
                    with self._session_factory() as session:
                        alive = JobRepository(session).heartbeat(job_id, self.worker_id, lease)
                    if not alive:
                        log.warning("lease lost while running")
                        return
                except Exception:
                    log.exception("heartbeat failed")

        thread = threading.Thread(target=beat, name=f"heartbeat-{job_id}", daemon=True)
        thread.start()
        return thread

    def _reload(self, tenant_id: Any, job_id: Any) -> tuple[Session, JobService, CorrectionJob]:
        session = self._session_factory()
        service = JobService(session, self._settings)
        job = service.jobs.get(tenant_id, job_id)
        if job is None:
            session.close()
            raise RuntimeError("the claimed job disappeared")
        return session, service, job

    def _cancel_requested(self, tenant_id: Any, job_id: Any) -> bool:
        with self._session_factory() as session:
            job = JobRepository(session).get(tenant_id, job_id)
            return bool(job and job.cancel_requested)

    def _finalize_cancel(self, tenant_id: Any, job_id: Any) -> None:
        session, service, job = self._reload(tenant_id, job_id)
        try:
            if JobState(job.state) not in {
                JobState.CANCELLED,
                JobState.COMPLETED,
                JobState.FAILED,
            }:
                job.cancel_requested = True
                service.jobs.transition(
                    job,
                    JobState.CANCELLED,
                    detail={"reason": "cancelled during execution"},
                    actor=f"worker:{self.worker_id}",
                )
                job.lease_owner = None
                job.lease_expires_at = None
                session.commit()
        finally:
            session.close()

    def _apply_outcome(
        self,
        tenant_id: Any,
        job_id: Any,
        state: JobState,
        detail: dict[str, Any],
        *,
        claimed_version: int,
    ) -> None:
        session, service, job = self._reload(tenant_id, job_id)
        try:
            if self._refuse_stale_write(session, job, claimed_version):
                return
            if JobState(job.state) is JobState.CANCELLED:
                return
            if state is JobState.COMPLETED or state is JobState.FINALIZING:
                service.finish(job, actor=f"worker:{self.worker_id}")
            elif JobState(job.state) != state:
                service.jobs.transition(
                    job,
                    state,
                    detail=detail,
                    actor=f"worker:{self.worker_id}",
                )
                job.lease_owner = None
                job.lease_expires_at = None
                session.commit()
        finally:
            session.close()

    def _fail(
        self,
        tenant_id: Any,
        job_id: Any,
        *,
        code: str,
        message: str,
        retryable: bool,
        claimed_version: int,
    ) -> None:
        session, service, job = self._reload(tenant_id, job_id)
        try:
            if self._refuse_stale_write(session, job, claimed_version):
                return
            if JobState(job.state) in {JobState.CANCELLED, JobState.COMPLETED}:
                return
            service.mark_failed(
                job,
                code=code,
                message=message,
                retryable=retryable,
                actor=f"worker:{self.worker_id}",
            )
        finally:
            session.close()

    def _refuse_stale_write(
        self, session: Session, job: CorrectionJob, claimed_version: int
    ) -> bool:
        """Refuse to write over a job that moved on after this worker claimed it.

        Two facts must still hold: the lease is this worker's, and the record
        version is the one captured at claim time.  A worker whose lease lapsed
        has no claim on the row any more, and writing its outcome would replace
        the work of the worker that took over.

        The refusal is audited rather than logged only, because a silently
        dropped result is indistinguishable from a bug.
        """

        lease_owner = job.lease_owner
        if lease_owner in (None, self.worker_id) and job.record_version == claimed_version:
            return False
        log.warning(
            "refusing a stale write",
            extra={
                "extra_fields": {
                    "job_id": str(job.id),
                    "claimed_version": claimed_version,
                    "current_version": job.record_version,
                    "lease_owner": lease_owner,
                    "worker": self.worker_id,
                }
            },
        )
        AuditService(session).record(
            tenant_id=job.tenant_id,
            action="job.stale_write_refused",
            entity_type="correction_job",
            entity_id=job.id,
            detail={
                "worker": self.worker_id,
                "claimed_version": claimed_version,
                "current_version": job.record_version,
                "lease_owner": lease_owner,
            },
        )
        session.commit()
        return True

    def _refuse_engine_mismatch(
        self,
        tenant_id: Any,
        job_id: Any,
        recorded: str | None,
        *,
        claimed_version: int,
    ) -> None:
        """Fail a job created for an engine this worker does not run.

        The job is not marked and is not retried automatically: switching
        methodology has to be an explicit decision, never a fallback.
        """

        session, service, job = self._reload(tenant_id, job_id)
        try:
            if self._refuse_stale_write(session, job, claimed_version):
                return
            service.mark_failed(
                job,
                code="ENGINE_MISMATCH",
                message=(
                    f"This job was created for {recorded!r}, but this worker runs "
                    f"{self._pipeline.name!r}. It was not marked."
                ),
                retryable=False,
                actor=f"worker:{self.worker_id}",
            )
            AuditService(session).record(
                tenant_id=tenant_id,
                action="job.engine_mismatch_refused",
                entity_type="correction_job",
                entity_id=job_id,
                detail={
                    "recorded_engine": recorded,
                    "worker_engine": self._pipeline.name,
                },
            )
            session.commit()
        finally:
            session.close()

    def _clear_lease(self, tenant_id: Any, job_id: Any) -> None:
        try:
            with self._session_factory() as session:
                job = JobRepository(session).get(tenant_id, job_id)
                if job is not None and job.lease_owner == self.worker_id:
                    job.lease_owner = None
                    job.lease_expires_at = None
                    session.commit()
        except Exception:
            log.exception("could not clear lease")

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop = stop_event or self._stop
        with self._session_factory() as session:
            reaped = JobRepository(session).reap_expired(
                max_attempts=self._settings.worker.max_attempts
            )
        if reaped:
            log.warning("reaped expired leases", extra={"extra_fields": {"count": reaped}})
        while not stop.is_set():
            try:
                processed = self.run_once()
            except Exception:
                log.exception("worker loop error")
                processed = None
            if processed is None:
                stop.wait(self._settings.worker.poll_interval_seconds)
            elif stop.is_set():
                break
        log.info("worker stopped", extra={"extra_fields": {"worker": self.worker_id}})
