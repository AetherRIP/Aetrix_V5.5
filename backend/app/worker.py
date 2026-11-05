"""Worker process entry point.

Run with ``aetrix-worker`` or ``python -m app.worker``.  The process is separate
from the API and claims jobs with a lease; SIGINT/SIGTERM stop claiming new work
and then wait for the current job to reach a safe boundary.
"""

from __future__ import annotations

import signal
import socket
import threading
from os import getpid

from .core.config import Settings, get_settings
from .core.logging import configure_logging, get_logger
from .db.session import get_session_factory
from .jobs.pipeline import build_pipeline
from .jobs.runner import JobRunner

log = get_logger("aetrix.worker")


def run(settings: Settings | None = None) -> int:
    resolved = settings or get_settings()
    configure_logging("DEBUG" if resolved.debug else "INFO", json_output=True)
    if not resolved.features.live_provider:
        log.warning(
            "live provider is disabled; jobs will park with PIPELINE_UNAVAILABLE "
            "rather than producing a simulated mark"
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
    log.info("worker process stopped")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
