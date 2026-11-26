"""Worker process entry point.

Run with ``aetrix-worker`` or ``python -m app.worker``.  The process is separate
from the API and claims jobs with a lease; SIGINT/SIGTERM stop claiming new work
and then wait for the current job to reach a safe boundary.
"""

from __future__ import annotations

import argparse
import signal
import socket
import threading
import time
from datetime import UTC, datetime
from os import getpid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .core.config import Settings, get_settings
from .core.logging import configure_logging, get_logger
from .db.models import ServiceHeartbeat
from .db.session import get_session_factory
from .jobs.pipeline import build_pipeline
from .jobs.runner import JobRunner

log = get_logger("aetrix.worker")

#: Must match the key ``GET /status`` reads (``status.WORKER_HEARTBEAT``).
HEARTBEAT_NAME = "worker"


def stamp_heartbeat(session_factory: Any, settings: Settings) -> None:
    """Record that this process is alive.

    The API cannot see the worker's process table, so liveness is evidenced by a
    row the worker renews.  A failed write is retried on the next beat; it must
    never stop the worker from claiming jobs, and a missing table (before
    migration 0013) is reported by ``/status`` as unknown rather than as a lie.
    """

    with session_factory() as session:
        session.merge(
            ServiceHeartbeat(
                name=HEARTBEAT_NAME,
                last_seen_at=datetime.now(UTC),
                detail={
                    "pid": getpid(),
                    "host": socket.gethostname(),
                    "concurrency": settings.worker.concurrency,
                },
            )
        )
        session.commit()


def _start_heartbeat(
    session_factory: Any, settings: Settings, stop: threading.Event
) -> threading.Thread:
    def loop() -> None:
        warned = False
        while True:
            try:
                stamp_heartbeat(session_factory, settings)
                warned = False
            except Exception:
                if not warned:
                    log.warning(
                        "worker heartbeat failed; status will report the worker as unknown",
                        exc_info=True,
                    )
                    warned = True
            if stop.wait(settings.worker.heartbeat_seconds):
                return

    thread = threading.Thread(target=loop, name="aetrix-worker-heartbeat", daemon=True)
    thread.start()
    return thread



def _start_google_quota_sync(
    session_factory: Any, settings: Settings, stop: threading.Event
) -> threading.Thread | None:
    """Run scheduled Google quota sync beside the job workers.

    The sync is read-only and isolated from correction: it has its own thread,
    its own session and a PostgreSQL advisory lock, so a slow or unavailable
    Google Cloud never delays a marking job and two worker processes cannot run
    the same sweep concurrently.  A failure is logged and retried on the next
    interval; it is never raised into the worker loop.
    """

    if not settings.google_cloud.configured:
        log.info(
            "google cloud quota sync is not configured; scheduled sync is disabled"
        )
        return None
    if not settings.google_cloud.enabled:
        log.info("google cloud quota sync is disabled by configuration")
        return None

    from .services.google_quota import sync_projects

    lock_key = 20261110

    def loop() -> None:
        while not stop.is_set():
            cycle_started = time.monotonic()
            try:
                with session_factory() as lock_session:
                    connection = lock_session.connection()
                    locked = connection.execute(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
                    ).scalar()
                    if locked:
                        try:
                            with Session(bind=connection) as session:
                                report = sync_projects(
                                    session, settings, trigger="SCHEDULED"
                                )
                            fleet = report["fleet"]
                            log.info(
                                "google cloud quota sync finished",
                                extra={
                                    "extra_fields": {
                                        "projects": fleet["declared_projects"],
                                        "verified": fleet["verified_projects"],
                                        "quotas": fleet["quotas_total"],
                                        "usage_observed": fleet["usage_observed"],
                                    }
                                },
                            )
                        finally:
                            connection.execute(
                                text("SELECT pg_advisory_unlock(:key)"),
                                {"key": lock_key},
                            )
                            connection.commit()
                    else:
                        log.info(
                            "google cloud quota sync skipped; another worker holds the lock"
                        )
            except Exception:
                log.warning(
                    "scheduled google cloud quota sync failed; will retry",
                    exc_info=True,
                )
            try:
                from .services.project_health import record_monitor_heartbeat

                with session_factory() as heartbeat_session:
                    record_monitor_heartbeat(
                        heartbeat_session,
                        {
                            "pid": getpid(),
                            "duration_ms": int((time.monotonic() - cycle_started) * 1000),
                            "interval_seconds": settings.google_cloud.sync_interval_seconds,
                        },
                    )
            except Exception:
                # A heartbeat write must never stop the monitor from sampling.
                log.warning("google cloud monitor heartbeat failed", exc_info=True)
            if stop.wait(settings.google_cloud.sync_interval_seconds):
                return

    thread = threading.Thread(
        target=loop, name="aetrix-google-quota-sync", daemon=True
    )
    thread.start()
    log.info(
        "google cloud quota sync scheduled",
        extra={
            "extra_fields": {
                "interval_seconds": settings.google_cloud.sync_interval_seconds,
                "service": settings.google_cloud.service,
            }
        },
    )
    return thread


def _start_classroom_monitoring(
    session_factory: Any, settings: Settings, stop: threading.Event
) -> threading.Thread | None:
    """Poll monitored Classroom assignments beside the marking workers.

    It is a separate thread with its own session and a PostgreSQL advisory lock,
    so a slow Google call never delays a marking job and two worker processes
    cannot poll the same assignment at once.  It makes no provider call: eligible
    work is only queued for the existing worker.
    """

    if not settings.classroom.monitoring_enabled:
        log.info("classroom submission monitoring is disabled by configuration")
        return None
    if not settings.classroom.configured():
        log.info(
            "classroom submission monitoring needs the Classroom OAuth client; "
            "scheduled monitoring is disabled"
        )
        return None

    from .classroom_monitoring.monitor import ClassroomMonitorService
    from .storage import build_storage

    storage = build_storage(settings)
    lock_key = 20261126

    def loop() -> None:
        while not stop.is_set():
            try:
                with session_factory() as lock_session:
                    connection = lock_session.connection()
                    locked = connection.execute(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
                    ).scalar()
                    if locked:
                        try:
                            with Session(bind=connection) as session:
                                counts = ClassroomMonitorService(
                                    session, settings, storage
                                ).cycle()
                            log.info(
                                "classroom monitoring cycle finished",
                                extra={"extra_fields": counts},
                            )
                        finally:
                            connection.execute(
                                text("SELECT pg_advisory_unlock(:key)"),
                                {"key": lock_key},
                            )
                            connection.commit()
                    else:
                        log.info(
                            "classroom monitoring skipped; another worker holds the lock"
                        )
            except Exception:
                log.warning(
                    "scheduled classroom monitoring failed; will retry",
                    exc_info=True,
                )
            if stop.wait(settings.classroom.monitor_tick_seconds):
                return

    thread = threading.Thread(
        target=loop, name="aetrix-classroom-monitoring", daemon=True
    )
    thread.start()
    log.info(
        "classroom submission monitoring scheduled",
        extra={
            "extra_fields": {
                "tick_seconds": settings.classroom.monitor_tick_seconds,
                "max_per_cycle": settings.classroom.monitor_max_per_cycle,
            }
        },
    )
    return thread


def run(settings: Settings | None = None) -> int:
    resolved = settings or get_settings()
    configure_logging("DEBUG" if resolved.debug else "INFO", json_output=True)
    if not resolved.features.live_provider:
        log.warning(
            "live provider is disabled; a job that reaches a provider call will "
            "park as PROVIDER_UNAVAILABLE rather than producing a simulated mark"
        )

    stop = threading.Event()

    def _signal(signum: int, _frame: object) -> None:
        log.info("shutdown requested", extra={"extra_fields": {"signal": signum}})
        stop.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _signal)
        signal.signal(signal.SIGTERM, _signal)

    session_factory = get_session_factory(resolved)
    pipeline = build_pipeline(resolved)
    host = socket.gethostname()
    heartbeat = _start_heartbeat(session_factory, resolved, stop)
    quota_sync = _start_google_quota_sync(session_factory, resolved, stop)
    classroom_monitor = _start_classroom_monitoring(session_factory, resolved, stop)

    threads: list[threading.Thread] = []
    for index in range(resolved.worker.concurrency):
        worker_id = f"{host}-{getpid()}-{index}"
        runner = JobRunner(
            session_factory=session_factory,
            pipeline=pipeline,
            settings=resolved,
            worker_id=worker_id,
            stop_event=stop,
        )
        thread = threading.Thread(
            target=runner.run_forever, name=f"aetrix-worker-{index}", daemon=False
        )
        threads.append(thread)

    for thread in threads:
        thread.start()
    log.info(
        "worker started",
        extra={
            "extra_fields": {
                "concurrency": resolved.worker.concurrency,
                "pipeline": pipeline.name,
            }
        },
    )

    for thread in threads:
        thread.join()
    heartbeat.join(timeout=2.0)
    if quota_sync is not None:
        quota_sync.join(timeout=2.0)
    if classroom_monitor is not None:
        classroom_monitor.join(timeout=2.0)
    log.info("worker process stopped")
    return 0


def run_once(settings: Settings | None = None) -> int:
    """Claim at most one job, run it, and exit.

    A supervised pilot needs one bounded execution, not a resident worker: with
    no heartbeat loop and no quota scheduler this process either finishes the one
    job it claimed or finds nothing runnable.  The pipeline, the lease and the
    state machine are the same ones the resident worker uses, so nothing about
    the marking path differs.

    Exit code 0 means a job was claimed and executed (whatever state it ended
    in); 3 means nothing was runnable, so a wrapper can tell a finished run from
    one that never started.
    """

    resolved = settings or get_settings()
    configure_logging("DEBUG" if resolved.debug else "INFO", json_output=True)
    if not resolved.features.live_provider:
        log.warning(
            "live provider is disabled; the job will park as PROVIDER_UNAVAILABLE "
            "rather than producing a simulated mark"
        )

    session_factory = get_session_factory(resolved)
    pipeline = build_pipeline(resolved)
    runner = JobRunner(
        session_factory=session_factory,
        pipeline=pipeline,
        settings=resolved,
        worker_id=f"{socket.gethostname()}-{getpid()}-once",
    )
    processed = runner.run_once()
    log.info(
        "single run finished",
        extra={"extra_fields": {"job_id": str(processed) if processed else None}},
    )
    return 0 if processed else 3


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aetrix-worker",
        description=(
            "Run the correction worker.  With --once it claims at most one job "
            "and exits (0 = a job ran, 3 = nothing was runnable)."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="claim and run one job, then exit instead of polling for work",
    )
    arguments = parser.parse_args()
    raise SystemExit(run_once() if arguments.once else run())


if __name__ == "__main__":
    main()
