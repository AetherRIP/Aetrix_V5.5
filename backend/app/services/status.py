"""Build the truthful subsystem and component status the health screen renders.

``/health`` proves the API process is alive and ``/ready`` proves the database
answers.  Neither says anything about the worker or a provider, so this module
composes those observations and leaves the rest explicitly unknown.  The
feature registry reports what this build does not implement, so a screen can
explain a gap instead of implying the engine is somewhere else.

Two rules shape the evidence reads:

* a provider is never called while a status page is being read — availability
  comes from a *recorded* live call in the usage ledger, or it is unverified;
* every evidence read is best-effort.  A missing table or a failed query makes
  the answer ``unknown``; it never turns the status route into a 500.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import ENGINE_NAME, __version__
from ..core.config import Settings
from ..db.models import (
    CorrectionJob,
    ProviderCredential,
    ProviderUsage,
    ServiceHeartbeat,
)
from ..jobs.states import RUNNABLE_STATES, JobState
from ..schemas.status import (
    ComponentHealthRead,
    FeatureStatus,
    SubsystemStatus,
    SystemStatusRead,
)

#: The only process that writes a heartbeat today.  The name is the table key,
#: not a role, so another observable process can be added without a migration.
WORKER_HEARTBEAT = "worker"

#: The worker beats every ``worker.heartbeat_seconds``.  Three windows tolerate
#: two missed beats before the API calls it stopped; a shorter window would flake
#: on a slow database, a longer one would hide a dead worker.
WORKER_GRACE_MULTIPLIER = 3
WORKER_MIN_GRACE_SECONDS = 60

#: What this build genuinely does not do.  Kept here (not in the browser) so the
#: engine is the single source of "not implemented" and a UI cannot invent
#: availability for an unimplemented capability.
FEATURES: tuple[FeatureStatus, ...] = (
    FeatureStatus(
        name="Marking",
        state="available",
        reason=(
            "The worker marks every scoreable question through the provider and stores a "
            "question result with its criteria and quoted evidence. Live marking accuracy "
            "is UNVERIFIED, and a question the engine cannot settle stops the job at "
            "REVIEW_REQUIRED rather than producing a silent zero."
        ),
    ),
    FeatureStatus(
        name="SymPy verification",
        state="available",
        reason=(
            "Each award is checked for internal consistency, and where the script and the "
            "scheme both state an expression SymPy decides equivalence. A check SymPy "
            "cannot decide forces human review."
        ),
    ),
    FeatureStatus(
        name="Cohort intelligence",
        state="not_implemented",
        reason=(
            "The gradebook and reports aggregate stored marks, but question-level cohort "
            "analysis has no endpoint yet."
        ),
    ),
    FeatureStatus(
        name="Provider quota monitoring",
        state="not_implemented",
        reason="No monitor samples Gemini project health yet.",
    ),
    FeatureStatus(
        name="Object storage",
        state="not_implemented",
        reason="Documents are not written to Supabase Storage in this build.",
    ),
    FeatureStatus(
        name="Malware scanning",
        state="not_implemented",
        reason="An uploaded document is not scanned.",
    ),
    FeatureStatus(
        name="Rate limiting",
        state="not_implemented",
        reason="The API does not rate-limit requests.",
    ),
)


def _grace_seconds(settings: Settings) -> int:
    return max(
        WORKER_MIN_GRACE_SECONDS,
        settings.worker.heartbeat_seconds * WORKER_GRACE_MULTIPLIER,
    )


def _as_utc(value: datetime) -> datetime:
    """Treat a naive column value as UTC rather than crashing on subtraction."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _age_seconds(value: datetime, now: datetime) -> int:
    return int((now - _as_utc(value)).total_seconds())


def _iso(value: datetime | None) -> str:
    return _as_utc(value).isoformat() if value is not None else "never"


def _database(session: Session) -> SubsystemStatus:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        # The failed statement aborts the transaction; roll back so the caller
        # can still read the worker heartbeat from the same session.
        session.rollback()
        return SubsystemStatus(
            state="unavailable",
            summary="The database did not answer SELECT 1",
            detail=type(exc).__name__,
        )
    return SubsystemStatus(state="ok", summary="PostgreSQL answered a readiness query")


def _worker_observation(
    session: Session, settings: Settings
) -> tuple[SubsystemStatus, ServiceHeartbeat | None, bool]:
    """Return the worker's subsystem state, its heartbeat row and whether the
    heartbeat table is missing (which is *not* the same as a stopped worker)."""

    grace = _grace_seconds(settings)
    try:
        row = session.get(ServiceHeartbeat, WORKER_HEARTBEAT)
    except SQLAlchemyError:
        # The table was added by migration 0013.  Until it is applied the honest
        # answer is "not observable", not "offline" and certainly not "online".
        session.rollback()
        return (
            SubsystemStatus(
                state="unknown",
                summary="The worker cannot be observed from this build",
                detail="The service_heartbeats table is missing; apply the Alembic migrations.",
            ),
            None,
            True,
        )

    if row is None:
        return (
            SubsystemStatus(
                state="unknown",
                summary="No worker has recorded a heartbeat",
                detail="Start the worker process; the API never starts it.",
            ),
            None,
            False,
        )

    age = _age_seconds(row.last_seen_at, datetime.now(UTC))
    if age <= grace:
        return (
            SubsystemStatus(
                state="ok",
                summary="The worker process is renewing its heartbeat",
                detail=f"Last heartbeat {age}s ago; the grace window is {grace}s.",
            ),
            row,
            False,
        )
    return (
        SubsystemStatus(
            state="unavailable",
            summary="The worker stopped renewing its heartbeat",
            detail=f"Last heartbeat {age}s ago; the grace window is {grace}s.",
        ),
        row,
        False,
    )


# --------------------------------------------------------------------------
# Evidence.  Each read is best-effort: ``None`` means "not observed here", and
# no evidence read may raise out of the status route.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ProviderEvidence:
    credentials: int | None
    healthy_credentials: int | None
    last_success: ProviderUsage | None
    last_failure: ProviderUsage | None


@dataclass(frozen=True, slots=True)
class _JobEvidence:
    last_job: CorrectionJob | None
    last_failed: CorrectionJob | None
    runnable: int | None


def _safe_first(session: Session, statement: Any) -> Any:
    try:
        return session.scalars(statement).first()
    except Exception:
        session.rollback()
        return None


def _safe_count(session: Session, statement: Any) -> int | None:
    try:
        value = session.scalar(statement)
    except Exception:
        session.rollback()
        return None
    return 0 if value is None else int(value)


def _provider_evidence(session: Session) -> _ProviderEvidence:
    return _ProviderEvidence(
        credentials=_safe_count(
            session, select(func.count()).select_from(ProviderCredential)
        ),
        healthy_credentials=_safe_count(
            session,
            select(func.count())
            .select_from(ProviderCredential)
            .where(ProviderCredential.health == "HEALTHY"),
        ),
        last_success=_safe_first(
            session,
            select(ProviderUsage)
            .where(ProviderUsage.purpose == "validate", ProviderUsage.success.is_(True))
            .order_by(ProviderUsage.created_at.desc()),
        ),
        last_failure=_safe_first(
            session,
            select(ProviderUsage)
            .where(ProviderUsage.purpose == "validate", ProviderUsage.success.is_(False))
            .order_by(ProviderUsage.created_at.desc()),
        ),
    )


def _job_evidence(session: Session) -> _JobEvidence:
    runnable = [state.value for state in RUNNABLE_STATES]
    return _JobEvidence(
        last_job=_safe_first(
            session, select(CorrectionJob).order_by(CorrectionJob.updated_at.desc())
        ),
        last_failed=_safe_first(
            session,
            select(CorrectionJob)
            .where(CorrectionJob.error_code.is_not(None))
            .order_by(CorrectionJob.updated_at.desc()),
        ),
        runnable=_safe_count(
            session,
            select(func.count())
            .select_from(CorrectionJob)
            .where(CorrectionJob.state.in_(runnable)),
        ),
    )


# --------------------------------------------------------------------------
# Subsystem states
# --------------------------------------------------------------------------


def _provider_observation(
    settings: Settings, evidence: _ProviderEvidence
) -> SubsystemStatus:
    """A provider is not "available" because it is configured.

    Availability needs a recorded successful call.  Nothing here calls Google;
    it reads the usage ledger, so opening a status page costs no tokens.
    """

    if not settings.features.live_provider:
        return SubsystemStatus(
            state="unknown",
            summary="No live provider is enabled",
            detail=(
                "A job that reaches a provider call parks as PROVIDER_UNAVAILABLE rather than "
                "producing a simulated mark."
            ),
        )

    success = evidence.last_success
    failure = evidence.last_failure
    if success is not None and (failure is None or success.created_at >= failure.created_at):
        return SubsystemStatus(
            state="ok",
            summary="A recorded live provider call succeeded",
            detail=(
                f"{success.model} answered HTTP {success.http_status or 200} at "
                f"{_iso(success.created_at)}; this is recorded evidence, not a call made by "
                "this status read."
            ),
        )
    if failure is not None:
        return SubsystemStatus(
            state="degraded",
            summary="The most recent recorded provider call failed",
            detail=(
                f"{failure.error_class or 'provider error'} "
                f"(HTTP {failure.http_status or 'no status'}) at {_iso(failure.created_at)}."
            ),
        )
    return SubsystemStatus(
        state="unknown",
        summary="Live provider calls are enabled but unverified",
        detail=(
            "No recorded provider call exists yet, and no call is made while reading this "
            "status, so availability is not claimed."
        ),
    )


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------


def _api_component(now: datetime) -> ComponentHealthRead:
    return ComponentHealthRead(
        name="HTTP API",
        deployment="deployed",
        operational="available",
        readiness="ready",
        checked_at=now,
        last_success_at=now,
        diagnostic=f"{ENGINE_NAME} {__version__} answered this status request.",
    )


def _database_component(now: datetime, database: SubsystemStatus) -> ComponentHealthRead:
    healthy = database.state == "ok"
    return ComponentHealthRead(
        name="PostgreSQL",
        deployment="deployed",
        operational="available" if healthy else "unavailable",
        readiness="ready" if healthy else "unavailable",
        checked_at=now,
        last_success_at=now if healthy else None,
        last_failure_at=None if healthy else now,
        last_failure=None if healthy else (database.detail or database.summary),
        diagnostic=(
            "The readiness query SELECT 1 succeeded."
            if healthy
            else "The readiness query SELECT 1 failed; the API is still answering."
        ),
    )


def _worker_component(
    now: datetime,
    settings: Settings,
    row: ServiceHeartbeat | None,
    table_missing: bool,
    jobs: _JobEvidence,
) -> ComponentHealthRead:
    grace = _grace_seconds(settings)

    last_failure_at: datetime | None = None
    last_failure: str | None = None
    if jobs.last_failed is not None:
        last_failure_at = _as_utc(jobs.last_failed.updated_at)
        last_failure = (
            f"{jobs.last_failed.error_code}: {jobs.last_failed.error_message or 'no detail'}"
        )[:300]

    if jobs.runnable is None:
        job_text = "Job evidence is unavailable from this build."
    elif jobs.runnable == 0:
        job_text = "No runnable job is queued."
    else:
        job_text = f"{jobs.runnable} runnable job(s) are queued."
    if jobs.last_job is not None:
        job_text += (
            f" Last job {jobs.last_job.state} at {_iso(jobs.last_job.updated_at)}."
        )
    else:
        job_text += " No correction job has been enqueued."

    if table_missing:
        return ComponentHealthRead(
            name="Background worker",
            deployment="unknown",
            operational="unknown",
            readiness="unknown",
            checked_at=now,
            last_failure_at=last_failure_at,
            last_failure=last_failure,
            diagnostic=(
                "The service_heartbeats table is missing; apply the Alembic migrations "
                "before the worker can be observed."
            ),
        )

    if row is None:
        return ComponentHealthRead(
            name="Background worker",
            deployment="not_deployed",
            operational="unavailable",
            readiness="unknown",
            checked_at=now,
            last_failure_at=last_failure_at,
            last_failure=last_failure,
            diagnostic=(
                "No worker process has ever recorded a heartbeat. The stack script starts the "
                f"worker as its own process. {job_text}"
            ),
        )

    age = _age_seconds(row.last_seen_at, now)
    fresh = age <= grace
    last_job = jobs.last_job
    if last_job is not None and last_job.state == JobState.COMPLETED.value:
        readiness = "ready"
        pipeline_text = "The last job reached COMPLETED."
    elif last_job is not None and last_job.error_code == "PIPELINE_UNAVAILABLE":
        readiness = "not_ready"
        pipeline_text = (
            "The last job parked at PIPELINE_UNAVAILABLE, so no mark was produced."
        )
    elif last_job is not None and last_job.state == JobState.REVIEW_REQUIRED.value:
        readiness = "not_ready"
        pipeline_text = (
            "The last job stopped at REVIEW_REQUIRED, a human-review state: its question "
            "results are waiting for a person, not approved."
        )
    elif last_job is not None:
        readiness = "not_ready"
        pipeline_text = f"The last job stopped at {last_job.state}."
    else:
        readiness = "not_ready"
        pipeline_text = (
            "No job has been processed here, so readiness to produce a mark is unproven."
        )

    return ComponentHealthRead(
        name="Background worker",
        deployment="deployed",
        operational="available" if fresh else "unavailable",
        readiness=readiness,
        checked_at=now,
        last_success_at=_as_utc(row.last_seen_at) if fresh else None,
        last_failure_at=last_failure_at,
        last_failure=last_failure,
        diagnostic=(
            f"Last heartbeat {age}s ago (grace {grace}s). {job_text} {pipeline_text}"
            if fresh
            else f"Last heartbeat {age}s ago (grace {grace}s): the lease holder is gone and "
            f"expired leases are reclaimed on the next start. {job_text} {pipeline_text}"
        ),
    )


def _provider_component(
    now: datetime, settings: Settings, evidence: _ProviderEvidence
) -> ComponentHealthRead:
    success = evidence.last_success
    failure = evidence.last_failure
    last_failure_at: datetime | None = None
    last_failure: str | None = None
    if failure is not None:
        last_failure_at = _as_utc(failure.created_at)
        last_failure = (
            f"{failure.error_class or 'provider error'} "
            f"(HTTP {failure.http_status or 'no status'})"
        )

    if not settings.features.live_provider:
        return ComponentHealthRead(
            name="AI provider",
            deployment="not_configured",
            operational="unknown",
            readiness="not_ready",
            checked_at=now,
            last_failure_at=last_failure_at,
            last_failure=last_failure,
            diagnostic=(
                "Live provider calls are disabled in this build; a job that reaches a provider "
                "call parks as PROVIDER_UNAVAILABLE rather than producing a simulated mark."
            ),
        )

    if evidence.credentials is None:
        return ComponentHealthRead(
            name="AI provider",
            deployment="unknown",
            operational="unverified",
            readiness="not_ready",
            checked_at=now,
            last_failure_at=last_failure_at,
            last_failure=last_failure,
            diagnostic=(
                "The provider credential table could not be read, so configuration and "
                "availability are unverified."
            ),
        )

    credentials_text = (
        f"{evidence.credentials} credential(s) registered, "
        f"{evidence.healthy_credentials if evidence.healthy_credentials is not None else 0} "
        "HEALTHY"
    )

    if evidence.credentials == 0:
        return ComponentHealthRead(
            name="AI provider",
            deployment="not_configured",
            operational="unverified",
            readiness="not_ready",
            checked_at=now,
            last_failure_at=last_failure_at,
            last_failure=last_failure,
            diagnostic=(
                f"No provider credential is registered ({credentials_text}), so no live call "
                "can be made."
            ),
        )

    if success is not None and (failure is None or success.created_at >= failure.created_at):
        return ComponentHealthRead(
            name="AI provider",
            deployment="deployed",
            operational="available",
            readiness="not_ready",
            checked_at=now,
            last_success_at=_as_utc(success.created_at),
            last_failure_at=last_failure_at,
            last_failure=last_failure,
            diagnostic=(
                f"A recorded live call to {success.model} answered HTTP "
                f"{success.http_status or 200} in {success.latency_ms or '?'} ms "
                f"({credentials_text}). Reachability is verified; mathematical correction "
                "remains UNVERIFIED until certified benchmark evidence exists."
            ),
        )

    if failure is not None:
        return ComponentHealthRead(
            name="AI provider",
            deployment="deployed",
            operational="degraded",
            readiness="not_ready",
            checked_at=now,
            last_success_at=_as_utc(success.created_at) if success is not None else None,
            last_failure_at=last_failure_at,
            last_failure=last_failure,
            diagnostic=(
                "The most recent recorded provider call failed; the credentials are configured "
                f"but the last live call did not succeed ({credentials_text})."
            ),
        )

    return ComponentHealthRead(
        name="AI provider",
        deployment="deployed",
        operational="unverified",
        readiness="not_ready",
        checked_at=now,
        diagnostic=(
            f"Credentials are configured ({credentials_text}), but no live call has been "
            "recorded yet; availability is not claimed."
        ),
    )


def read_system_status(session: Session, settings: Settings) -> SystemStatusRead:
    """Compose every subsystem observation into one contract.

    The order matters: the database probe is rolled back on failure before the
    worker heartbeat is read, so a database outage is reported as a database
    outage rather than surfacing as an unrelated worker error.
    """

    now = datetime.now(UTC)
    database = _database(session)
    ready = database.state == "ok"
    worker, worker_row, heartbeat_table_missing = _worker_observation(session, settings)
    provider_evidence = _provider_evidence(session)
    job_evidence = _job_evidence(session)

    return SystemStatusRead(
        checked_at=now,
        service=ENGINE_NAME,
        version=__version__,
        environment=settings.env.value,
        api=SubsystemStatus(
            state="ok",
            summary="The API answered this request",
            detail=f"{ENGINE_NAME} {__version__}",
        ),
        engine=SubsystemStatus(
            state="ok",
            summary="The correction engine responded",
            detail="The process answering is this API; the worker is reported separately.",
        ),
        readiness=SubsystemStatus(
            state="ok" if ready else "unavailable",
            summary=(
                "Initialised and accepting correction jobs"
                if ready
                else "Not ready to accept correction jobs"
            ),
            detail=(
                "An accepted job is marked by the worker against an approved blueprint and "
                "scheme. Live marking accuracy is UNVERIFIED, and a question the engine "
                "cannot settle stops at REVIEW_REQUIRED."
                if ready
                else "Readiness requires a successful database query."
            ),
        ),
        database=database,
        worker=worker,
        provider=_provider_observation(settings, provider_evidence),
        components=[
            _api_component(now),
            _database_component(now, database),
            _worker_component(
                now,
                settings,
                worker_row,
                heartbeat_table_missing,
                job_evidence,
            ),
            _provider_component(now, settings, provider_evidence),
        ],
        features=list(FEATURES),
    )
