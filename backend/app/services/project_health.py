"""Project-level health derived from durable evidence, never from a guess.

Two ledgers already exist and this module adds no parallel one:

* ``google_cloud_sync_runs`` — every Cloud Quotas / Monitoring / Resource Manager
  sample, with Google's own error code and timings.  This is the authoritative
  evidence that the *project's Cloud APIs* answered.
* ``provider_usage`` — the append-only Gemini call ledger, carrying the project,
  model, HTTP status, error category and latency of each real request.  This is
  Aetrix telemetry, not a Google quota measurement.

Health and quota are deliberately separate answers:

``health``
    Did the project's Cloud APIs answer, and with which failure?  A 401 on one
    Gemini key is *not* project ill-health; it is a credential signal and stays
    in the usage ledger.  Only the service-account sample (a sync run) can make
    the project itself ``AUTH_FAILURE``.
``quota_status``
    ``EXHAUSTED`` only when Cloud Monitoring reports an exceeded counter, or
    when Gemini traffic returned an explicit quota refusal.  A bare 429 is
    ``WARNING`` (throttling), never proof of exhausted remaining quota, and
    ``UNKNOWN`` when no authoritative limit exists.

Confidence follows the source: ``CONFIRMED`` for a Google answer, ``ESTIMATED``
for Aetrix telemetry, ``UNKNOWN`` when neither exists.  No percentage is ever
computed from a pool budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ProviderUsage, ServiceHeartbeat
from .google_cloud import GoogleCloudError  # noqa: F401  (documented vocabulary)

MONITOR_HEARTBEAT = "google_quota_monitor"
MONITOR_GRACE_MULTIPLIER = 3
SIGNAL_WINDOW = timedelta(hours=24)

#: Health states.  ``UNKNOWN`` means no sample, never "healthy by default".
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
OUTAGE = "OUTAGE"
AUTH_FAILURE = "AUTH_FAILURE"
PERMISSION_FAILURE = "PERMISSION_FAILURE"
RATE_LIMITED = "RATE_LIMITED"
QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
UNKNOWN = "UNKNOWN"

CONFIRMED = "CONFIRMED"
ESTIMATED = "ESTIMATED"

_AUTH_CODES = {"INVALID_CREDENTIALS"}
_PERMISSION_CODES = {"PERMISSION_DENIED"}
_RATE_CODES = {"RATE_LIMITED"}
_OUTAGE_CODES = {"UPSTREAM_ERROR", "TIMEOUT", "NETWORK_ERROR", "INTERNAL_ERROR"}
_IDENTITY_CODES = {"NOT_FOUND", "INVALID_PROJECT_ID", "PROJECT_MISMATCH"}


@dataclass(frozen=True)
class RunView:
    id: str
    status: str
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class QuotaView:
    limit_value: float | None
    limit_source: str
    exceeded_value: float | None


@dataclass(frozen=True)
class UsageSignal:
    model: str
    success: bool
    http_status: int | None
    error_category: str | None
    created_at: datetime
    latency_ms: int | None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def classify_run(status: str, error_code: str | None) -> tuple[str, str]:
    """The project-health state and a secret-free reason for one sync sample."""

    if status == "SUCCEEDED":
        return HEALTHY, "Google Cloud quota and usage reads succeeded."
    if status == "PARTIAL":
        return (
            DEGRADED,
            "Quota limits were read, but Cloud Monitoring usage was unavailable."
            " The limit is current; usage is not.",
        )
    if error_code in _AUTH_CODES:
        return (
            AUTH_FAILURE,
            "Google rejected the monitoring service-account token (401)."
            " This is the monitor's credential, not any individual Gemini key.",
        )
    if error_code in _PERMISSION_CODES:
        return (
            PERMISSION_FAILURE,
            "Google refused the monitoring read (403). The service account needs"
            " the quota, monitoring and service-usage viewer roles.",
        )
    if error_code in _RATE_CODES:
        return (
            RATE_LIMITED,
            "Google rate-limited the Cloud API read (429); this says nothing about"
            " Gemini generation quota.",
        )
    if error_code in _OUTAGE_CODES:
        return (
            OUTAGE,
            "Google Cloud did not complete the read (5xx, timeout or network"
            " failure). The project may still serve Gemini requests.",
        )
    if error_code in _IDENTITY_CODES:
        return (
            UNKNOWN,
            "Google could not confirm this project identity, so project health and"
            " allowance are unknown. No Gemini quota figure is implied.",
        )
    return DEGRADED, "The last monitoring sample failed; no health claim is made."


def classify_usage(
    rows: list[UsageSignal], *, quota_exceeded: bool
) -> dict[str, Any]:
    """Aggregate real Gemini traffic into signals, keeping failures distinct.

    A 401 marks a credential signal, not project ill-health.  A 429 is throttling
    unless an authoritative exceeded counter says otherwise.  A 404 marks one
    model unavailable, not the project.
    """

    counts = {
        "requests": 0,
        "successes": 0,
        "failures": 0,
        "authentication": 0,
        "permission": 0,
        "rate_limited": 0,
        "quota_refused": 0,
        "provider_server": 0,
        "network": 0,
        "model_not_found": 0,
        "other": 0,
    }
    latencies: list[int] = []
    models: dict[str, dict[str, Any]] = {}
    last_success: datetime | None = None
    last_failure: datetime | None = None

    for row in rows:
        counts["requests"] += 1
        created = _as_utc(row.created_at)
        category = (row.error_category or "").lower()
        status = row.http_status or 0
        model = models.setdefault(
            row.model,
            {
                "model": row.model,
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "last_success_at": None,
                "last_failure_at": None,
                "last_http_status": None,
                "state": "UNKNOWN",
            },
        )
        model["requests"] += 1
        if row.latency_ms is not None:
            latencies.append(row.latency_ms)

        if row.success:
            counts["successes"] += 1
            model["successes"] += 1
            if last_success is None or created > last_success:
                last_success = created
            prior = model["last_success_at"]
            if prior is None or created > prior:
                model["last_success_at"] = created
            model["state"] = "AVAILABLE"
            continue

        counts["failures"] += 1
        model["failures"] += 1
        if last_failure is None or created > last_failure:
            last_failure = created
        prior_failure = model["last_failure_at"]
        if prior_failure is None or created > prior_failure:
            model["last_failure_at"] = created
            model["last_http_status"] = row.http_status

        if status == 401 or category == "authentication":
            counts["authentication"] += 1
        elif status == 403 or category == "permission":
            counts["permission"] += 1
        elif status == 429 or category == "quota":
            # A response Google explicitly marked as quota exhaustion is stronger
            # evidence than a bare 429.  Without that wording it stays throttling.
            if quota_exceeded:
                counts["quota_refused"] += 1
            else:
                counts["rate_limited"] += 1
        elif status >= 500 or category == "provider_server":
            counts["provider_server"] += 1
        elif category == "network":
            # The ledger's ``network`` category includes DNS, connect, timeout
            # and transport failures.  It does not record which one, so Aetrix
            # reports one honest bucket rather than inventing a timeout count.
            counts["network"] += 1
        elif category == "unsupported_model" or status == 404:
            counts["model_not_found"] += 1
        else:
            counts["other"] += 1

    # Model availability needs a success to be AVAILABLE; failures alone make it
    # FAILING, and no traffic keeps UNKNOWN.  It is Aetrix telemetry, never a
    # Google statement that generation quota remains.
    for model in models.values():
        if model["state"] != "AVAILABLE":
            model["state"] = "FAILING" if model["failures"] else "UNKNOWN"

    return {
        "counts": counts,
        "models": sorted(models.values(), key=lambda item: item["model"]),
        "last_success_at": last_success,
        "last_failure_at": last_failure,
        "average_latency_ms": (
            round(sum(latencies) / len(latencies), 1) if latencies else None
        ),
        "confidence": ESTIMATED if rows else "UNKNOWN",
    }


def build_health(
    project_id: str,
    runs: list[RunView],
    quotas: list[QuotaView],
    usage: list[UsageSignal],
    *,
    now: datetime,
    stale_after_seconds: int,
) -> dict[str, Any]:
    """Compose one project's health without inventing a value for a gap."""

    latest = runs[0] if runs else None
    previous = runs[1] if len(runs) > 1 else None
    exceeded = any(
        quota.exceeded_value is not None and quota.exceeded_value > 0 for quota in quotas
    )
    limits_confirmed = any(
        quota.limit_source == "CLOUD_QUOTAS" and quota.limit_value is not None
        for quota in quotas
    )
    limits_any = any(quota.limit_value is not None for quota in quotas)

    if latest is None:
        state, reason = (
            UNKNOWN,
            "No Google Cloud sample exists for this project, so neither health nor"
            " quota is established.",
        )
        confidence = "UNKNOWN"
        sampled_at = None
        stale = True
    else:
        state, reason = classify_run(latest.status, latest.error_code)
        confidence = CONFIRMED
        sampled_at = latest.finished_at or latest.started_at
        stale = (
            sampled_at is None
            or now - _as_utc(sampled_at) > timedelta(seconds=stale_after_seconds)
        )

    signals = classify_usage(usage, quota_exceeded=exceeded)
    counts = signals["counts"]

    if exceeded:
        quota_status, quota_confidence = QUOTA_EXHAUSTED, CONFIRMED
        quota_reason = (
            "Cloud Monitoring reports a quota-exceeded counter for this project."
        )
    elif limits_confirmed:
        quota_status, quota_confidence = "KNOWN", CONFIRMED
        quota_reason = (
            "Google returned quota limits. This states the allowance, not the"
            " remaining amount; no remaining figure is exposed."
        )
    elif limits_any:
        quota_status, quota_confidence = "KNOWN", ESTIMATED
        quota_reason = (
            "A limit was available only from a secondary source; treat it as"
            " estimated, not a fresh Google statement of remaining quota."
        )
    elif counts["rate_limited"] or counts["quota_refused"]:
        quota_status, quota_confidence = "WARNING", ESTIMATED
        quota_reason = (
            "Aetrix observed Gemini throttling in its own traffic. A 429 is not"
            " proof that the project's remaining quota is exhausted."
        )
    else:
        quota_status, quota_confidence = UNKNOWN, "UNKNOWN"
        quota_reason = (
            "No authoritative remaining-quota measurement is available. AI Studio"
            " publishes no API, so Aetrix cannot read it."
        )

    # Provider throttling degrades the *service* signal, but it must not rewrite
    # an otherwise successful Cloud API sample as a project failure.
    if state == HEALTHY and (counts["provider_server"] or counts["rate_limited"]):
        state = DEGRADED
        reason = (
            "Cloud quota reads succeeded, but real Gemini traffic in the last 24"
            " hours includes throttling or provider errors."
        )

    recovered = bool(
        latest is not None
        and latest.status == "SUCCEEDED"
        and previous is not None
        and previous.status != "SUCCEEDED"
    )

    return {
        "state": state,
        "state_confidence": confidence,
        "reason": reason,
        "quota_status": quota_status,
        "quota_confidence": quota_confidence,
        "quota_reason": quota_reason,
        "last_sample_at": _iso(sampled_at),
        "sample_stale": stale,
        "last_attempt_at": _iso(latest.started_at) if latest else None,
        "last_status": latest.status if latest else None,
        "last_error_code": latest.error_code if latest else None,
        "recovered": recovered,
        "signals": signals,
    }


def project_alerts(project_id: str, health: dict[str, Any]) -> list[dict[str, Any]]:
    """Current incidents for one project, deduplicated by a stable id.

    These are read-time facts, not queued messages: a continuing incident
    yields the same id every read, so an operator screen cannot stack duplicates.
    Recovery is reported only for the sample in which the latest run succeeded
    after a failed one, and its id includes that run, so it cannot repeat.
    """

    state = health["state"]
    alerts: list[dict[str, Any]] = []
    mapping = {
        AUTH_FAILURE: ("project_auth_failure", "critical"),
        PERMISSION_FAILURE: ("project_permission_failure", "critical"),
        OUTAGE: ("project_outage", "critical"),
        RATE_LIMITED: ("project_rate_limited", "warning"),
        DEGRADED: ("project_degraded", "warning"),
    }
    if state in mapping:
        kind, severity = mapping[state]
        alerts.append(
            {
                "id": f"{project_id}:{kind}",
                "kind": kind,
                "severity": severity,
                "project_id": project_id,
                "title": kind.replace("_", " ").capitalize(),
                "detail": health["reason"],
                "since": health["last_attempt_at"],
            }
        )
    if health["quota_status"] == QUOTA_EXHAUSTED:
        alerts.append(
            {
                "id": f"{project_id}:quota_exhausted",
                "kind": "quota_exhausted",
                "severity": "critical",
                "project_id": project_id,
                "title": "Project quota exhausted",
                "detail": health["quota_reason"],
                "since": health["last_sample_at"],
            }
        )
    elif health["quota_status"] == "WARNING":
        alerts.append(
            {
                "id": f"{project_id}:throttling",
                "kind": "throttling",
                "severity": "warning",
                "project_id": project_id,
                "title": "Recent Gemini throttling",
                "detail": health["quota_reason"],
                "since": health["last_sample_at"],
            }
        )
    if health["sample_stale"] and health["last_attempt_at"] is not None:
        alerts.append(
            {
                "id": f"{project_id}:sample_stale",
                "kind": "sample_stale",
                "severity": "warning",
                "project_id": project_id,
                "title": "Project sample is stale",
                "detail": (
                    "The last stored sample is older than the configured freshness"
                    " window; it is not shown as current."
                ),
                "since": health["last_sample_at"],
            }
        )
    if health["recovered"]:
        alerts.append(
            {
                "id": f"{project_id}:recovered:{health['last_sample_at']}",
                "kind": "recovered",
                "severity": "info",
                "project_id": project_id,
                "title": "Monitoring recovered",
                "detail": "The latest Cloud API sample succeeded after a failed one.",
                "since": health["last_sample_at"],
            }
        )
    return alerts


def monitor_snapshot(
    session: Session,
    *,
    interval_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Whether the monitor itself is alive, fresh and keeping up."""

    observed = (now or datetime.now(UTC)).astimezone(UTC)
    grace = max(interval_seconds * MONITOR_GRACE_MULTIPLIER, 60)
    try:
        row = session.get(ServiceHeartbeat, MONITOR_HEARTBEAT)
    except Exception:
        session.rollback()
        return {
            "state": "UNKNOWN",
            "last_cycle_at": None,
            "age_seconds": None,
            "interval_seconds": interval_seconds,
            "grace_seconds": grace,
            "detail": "The heartbeat table is unavailable; monitoring cannot be observed.",
        }
    if row is None:
        return {
            "state": "UNAVAILABLE",
            "last_cycle_at": None,
            "age_seconds": None,
            "interval_seconds": interval_seconds,
            "grace_seconds": grace,
            "detail": "No monitoring cycle has recorded a heartbeat.",
        }
    seen = _as_utc(row.last_seen_at)
    age = int((observed - seen).total_seconds())
    state = "OK" if age <= grace else "STALE"
    detail = (
        f"Last cycle {age}s ago; a cycle every {interval_seconds}s is expected."
        if state == "OK"
        else f"Last cycle {age}s ago, beyond the {grace}s freshness window."
    )
    return {
        "state": state,
        "last_cycle_at": seen.isoformat(),
        "age_seconds": age,
        "interval_seconds": interval_seconds,
        "grace_seconds": grace,
        "detail": detail,
        "last_cycle": dict(row.detail or {}),
    }


def record_monitor_heartbeat(session: Session, detail: dict[str, Any]) -> None:
    """Record that one monitoring cycle ran, even when every sample failed."""

    row = session.get(ServiceHeartbeat, MONITOR_HEARTBEAT)
    if row is None:
        row = ServiceHeartbeat(name=MONITOR_HEARTBEAT, last_seen_at=datetime.now(UTC))
        session.add(row)
    row.last_seen_at = datetime.now(UTC)
    row.detail = detail
    session.commit()


def monitor_subsystem(
    session: Session, *, interval_seconds: int
) -> tuple[str, str, str | None]:
    """``(state, summary, detail)`` for the engine status feature."""

    snapshot = monitor_snapshot(session, interval_seconds=interval_seconds)
    if snapshot["state"] == "OK":
        return (
            "ok",
            "The quota monitor is recording cycles.",
            snapshot["detail"],
        )
    if snapshot["state"] == "STALE":
        return (
            "degraded",
            "The quota monitor has stopped recording cycles.",
            snapshot["detail"],
        )
    if snapshot["state"] == "UNAVAILABLE":
        return (
            "unavailable",
            "No quota monitoring cycle has run.",
            snapshot["detail"],
        )
    return ("unknown", "Quota monitoring cannot be observed.", snapshot["detail"])


def usage_signal_rows(
    session: Session, project_ids: list[str], *, since: datetime
) -> dict[str, list[UsageSignal]]:
    """One bulk read of the append-only ledger for every declared project."""

    if not project_ids:
        return {}
    rows = session.execute(
        select(ProviderUsage).where(
            ProviderUsage.project_id.in_(project_ids),
            ProviderUsage.created_at >= since,
        )
    ).scalars()
    grouped: dict[str, list[UsageSignal]] = {}
    for row in rows:
        grouped.setdefault(row.project_id, []).append(
            UsageSignal(
                model=row.model,
                success=bool(row.success),
                http_status=row.http_status,
                error_category=row.error_category,
                created_at=row.created_at,
                latency_ms=row.latency_ms,
            )
        )
    return grouped
