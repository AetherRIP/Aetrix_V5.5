"""Synchronise Google-reported quota and usage into the fleet dashboard.

The service is read-only by construction: it calls ``get``/``list`` endpoints and
writes only Aetrix's own observation tables.  Every project is synced in its own
transaction, so one project's missing IAM permission never hides another's data.

Three distinctions are preserved throughout:

* **Declared vs verified** — the operator's project id is never rewritten; Google
  verifies it through Resource Manager, and a failure is a stored state.
* **Limit source vs usage source** — a limit from Cloud Quotas and usage from
  Cloud Monitoring are labelled separately, and either can be unavailable.
* **Last success vs last failure** — a failed run keeps the previous snapshots
  (with their original observation timestamps) instead of deleting them or
  pretending they are current.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.ids import utcnow
from ..db.models import (
    GoogleCloudProject,
    GoogleCloudQuotaSnapshot,
    GoogleCloudSyncRun,
    ProviderCredential,
)
from .google_cloud import (
    AISTUDIO_AVAILABLE,
    AISTUDIO_REASON,
    AISTUDIO_SOURCE,
    ALLOCATION_USAGE,
    QUOTA_EXCEEDED,
    QUOTA_LIMIT,
    RATE_NET_USAGE,
    REQUIRED_APIS,
    GoogleCloudClient,
    GoogleCloudError,
    ProjectIdentity,
    QuotaDimension,
    QuotaInfo,
    UsageSeries,
    build_client,
    credential_source,
    is_verifiable_project_id,
)

SyncTrigger = Literal["MANUAL", "SCHEDULED"]

#: Google uses ``-1`` for an unlimited allocation; Aetrix preserves the value so
#: the dashboard can say "unlimited" rather than inventing a finite number.
UNLIMITED_SENTINEL = -1.0

#: Reported for a project no synchronisation has ever attempted.  The fleet
#: contract keeps this value separate from "operator declared" so a reader can
#: tell "not checked" from "checked and failed".
PROJECT_VERIFICATION_FALLBACK = "UNVERIFIED"

COVERAGE_SUPPORTED = [
    "Quota definitions, ids, units and declared dimensions from Cloud Quotas.",
    "Quota limits per dimension combination (for example per model) when Google "
    "returns dimensionsInfos.",
    "Consumer-quota usage from Cloud Monitoring allocation/usage and rate/net_usage.",
    "Quota-exceeded counters from Cloud Monitoring quota/exceeded.",
    "Project identity and lifecycle state from Cloud Resource Manager.",
    "Enabled-API state from Service Usage (when readable).",
]

COVERAGE_UNAVAILABLE = [
    AISTUDIO_REASON,
    "Google does not guarantee that every Gemini Developer API limit appears as a "
    "consumer_quota metric. A quota with no matching time series is shown as "
    "usage unavailable, never as zero.",
    "Spend-based rate limits are documented in AI Studio and are not read here.",
    "Quota reset times are reported only when Google includes them in the quota "
    "definition; Aetrix does not infer a reset instant from the daily timezone.",
]


class QuotaSyncUnavailable(RuntimeError):
    """The integration is not configured, so no request should be attempted."""


def is_stale(
    last_success_at: datetime | None,
    now: datetime,
    stale_after_seconds: int,
) -> bool:
    if last_success_at is None:
        return True
    return now - last_success_at > timedelta(seconds=stale_after_seconds)


def declared_project_ids(session: Session) -> list[str]:
    rows = session.execute(select(ProviderCredential.project_id).distinct()).scalars()
    return sorted({str(row) for row in rows if row})


def verification_summary(
    session: Session, project_ids: list[str]
) -> dict[str, GoogleCloudProject]:
    if not project_ids:
        return {}
    rows = session.execute(
        select(GoogleCloudProject).where(GoogleCloudProject.project_id.in_(project_ids))
    ).scalars()
    return {row.project_id: row for row in rows}


def _dimensions_key(values: dict[str, str]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _match_series(
    metric: str,
    dimensions: dict[str, str],
    candidates: list[UsageSeries],
) -> UsageSeries | None:
    """Pick the series that names this quota and agrees on every known dimension.

    Cloud Monitoring may omit a dimension that Cloud Quotas declares.  A missing
    label is unknown, not a conflict; a label that disagrees is a conflict and
    disqualifies the series.  This prevents usage for one model being attributed
    to another.
    """

    best: tuple[int, UsageSeries] | None = None
    for series in candidates:
        if series.quota_metric != metric or series.value is None:
            continue
        score = 0
        conflict = False
        for key, expected in dimensions.items():
            observed = series.metric_labels.get(key) or series.resource_labels.get(key)
            if observed is None:
                continue
            if observed != expected:
                conflict = True
                break
            score += 2
        if conflict:
            continue
        if best is None or score > best[0]:
            best = (score, series)
    return best[1] if best else None


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def build_snapshots(
    project_id: str,
    infos: list[QuotaInfo],
    series: list[UsageSeries],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    """Turn Google responses into snapshot rows without inventing values.

    One row is emitted per dimension combination Google declares.  A limit is
    ``None`` only when Google returned none; usage is ``None`` only when no
    matching time series exists.  Neither is replaced with zero.
    """

    usage_candidates = [
        item
        for item in series
        if item.metric_type in {ALLOCATION_USAGE, RATE_NET_USAGE}
    ]
    exceeded_candidates = [
        item for item in series if item.metric_type == QUOTA_EXCEEDED
    ]
    limit_candidates = [item for item in series if item.metric_type == QUOTA_LIMIT]

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for info in infos:
        dimension_rows = list(info.dimension_values) or [
            QuotaDimension({}, info.default_quota_value)
        ]
        for dimension in dimension_rows:
            values = dict(dimension.values)
            key = _dimensions_key(values)
            if key in seen:
                continue
            seen.add(key)
            usage = _match_series(info.metric, values, usage_candidates)
            exceeded = _match_series(info.metric, values, exceeded_candidates)
            limit = dimension.quota_value
            limit_source = "CLOUD_QUOTAS" if limit is not None else "UNAVAILABLE"
            if limit is None:
                fallback = _match_series(info.metric, values, limit_candidates)
                if fallback is not None:
                    limit = fallback.value
                    limit_source = "CLOUD_MONITORING"
            rows.append(
                {
                    "project_id": project_id,
                    "quota_id": info.quota_id,
                    "metric": info.metric,
                    "service": info.service,
                    "metric_display_name": info.metric_display_name,
                    "quota_display_name": info.quota_display_name,
                    "unit": info.unit or (usage.unit if usage else None),
                    "refresh_interval": info.refresh_interval,
                    "reset_time": dimension.reset_time,
                    "container_type": info.container_type,
                    "is_precise": info.is_precise,
                    "dimensions": values,
                    "dimensions_key": key,
                    "limit_value": _decimal(limit),
                    "limit_source": limit_source,
                    "usage_value": _decimal(usage.value if usage else None),
                    "usage_metric": usage.metric_type if usage else None,
                    "usage_source": (
                        "CLOUD_MONITORING" if usage is not None else "NOT_EXPOSED"
                    ),
                    "usage_observed_at": usage.observed_at if usage else None,
                    "exceeded_value": _decimal(exceeded.value if exceeded else None),
                    "observed_at": observed_at,
                }
            )
    return rows


def _truncate(value: str | None, limit: int = 500) -> str | None:
    if value is None:
        return None
    return value.strip()[:limit] or None


def _verification_status(error: GoogleCloudError) -> str:
    if error.code == "NOT_FOUND":
        return "NOT_FOUND"
    if error.code in {"PERMISSION_DENIED", "INVALID_CREDENTIALS"}:
        return "PERMISSION_DENIED"
    if error.code in {"INVALID_PROJECT_ID", "PROJECT_MISMATCH"}:
        return "UNVERIFIABLE"
    return "ERROR"


def _carry_forward_usage(
    session: Session,
    project_id: str,
    snapshots: list[dict[str, Any]],
) -> None:
    """Keep the last observed usage when only the Monitoring call failed.

    The carried value keeps its original ``usage_observed_at``; the run is stored
    as PARTIAL, so the dashboard never presents it as a fresh Google reading.
    """

    previous = {
        (row.quota_id, row.dimensions_key): row
        for row in session.execute(
            select(GoogleCloudQuotaSnapshot).where(
                GoogleCloudQuotaSnapshot.project_id == project_id
            )
        ).scalars()
    }
    for snapshot in snapshots:
        if snapshot["usage_value"] is not None:
            continue
        old = previous.get((snapshot["quota_id"], snapshot["dimensions_key"]))
        if old is None or old.usage_value is None:
            continue
        snapshot["usage_value"] = old.usage_value
        snapshot["usage_metric"] = old.usage_metric
        snapshot["usage_source"] = old.usage_source
        snapshot["usage_observed_at"] = old.usage_observed_at
        snapshot["exceeded_value"] = old.exceeded_value


def _sync_project(
    session: Session,
    settings: Settings,
    client: GoogleCloudClient,
    project_id: str,
    trigger: SyncTrigger,
) -> dict[str, Any]:
    started = utcnow()
    project = session.get(GoogleCloudProject, project_id)
    if project is None:
        project = GoogleCloudProject(project_id=project_id)
        session.add(project)
    project.last_attempt_at = started
    project.last_error_code = None
    project.last_error_message = None

    run = GoogleCloudSyncRun(
        project_id=project_id,
        trigger=trigger,
        status="FAILED",
        started_at=started,
        quota_infos=0,
        snapshots_written=0,
        api_calls=0,
    )
    session.add(run)
    session.flush()
    before_calls = client.request_count

    def finish(
        status: str,
        *,
        error_code: str | None = None,
        message: str | None = None,
        quota_infos: int = 0,
        snapshots: int = 0,
    ) -> dict[str, Any]:
        project.last_error_code = error_code
        project.last_error_message = _truncate(message)
        run.status = status
        run.finished_at = utcnow()
        run.quota_infos = quota_infos
        run.snapshots_written = snapshots
        run.error_code = error_code
        run.error_message = _truncate(message)
        run.api_calls = max(client.request_count - before_calls, 0)
        session.flush()
        return {
            "project_id": project_id,
            "status": status,
            "run_id": run.id,
            "verification": project.verification_status,
            "quota_infos": quota_infos,
            "snapshots": snapshots,
            "error_code": error_code,
            "message": _truncate(message),
        }

    if not is_verifiable_project_id(project_id):
        project.verification_status = "UNVERIFIABLE"
        return finish(
            "FAILED",
            error_code="INVALID_PROJECT_ID",
            message=(
                f"{project_id!r} is not a Google Cloud project id; it is preserved "
                "as a synthetic pool and cannot be verified."
            ),
        )

    try:
        identity = client.verify_project(project_id)
    except GoogleCloudError as exc:
        project.verification_status = _verification_status(exc)
        project.last_verified_at = None
        return finish("FAILED", error_code=exc.code, message=exc.message)
    except Exception:
        project.verification_status = "ERROR"
        return finish(
            "FAILED",
            error_code="INTERNAL_ERROR",
            message="Project verification failed unexpectedly.",
        )

    _apply_identity(project, identity, utcnow())

    services_error: GoogleCloudError | None = None
    try:
        project.enabled_services = client.list_enabled_services(project_id)
        project.services_checked_at = utcnow()
    except GoogleCloudError as exc:
        project.enabled_services = None
        project.services_checked_at = utcnow()
        services_error = exc

    try:
        infos = client.list_quota_infos(
            project_id,
            settings.google_cloud.service,
            max_infos=settings.google_cloud.max_quota_infos,
        )
    except GoogleCloudError as exc:
        project.quota_count = 0
        return finish("FAILED", error_code=exc.code, message=exc.message)
    except Exception:
        return finish(
            "FAILED",
            error_code="INTERNAL_ERROR",
            message="Reading quota definitions failed unexpectedly.",
        )

    usage_error: GoogleCloudError | None = None
    try:
        series = client.list_usage_series(
            project_id,
            settings.google_cloud.service,
            window_minutes=settings.google_cloud.usage_window_minutes,
        )
    except GoogleCloudError as exc:
        series = []
        usage_error = exc
    except Exception:
        series = []
        usage_error = GoogleCloudError(
            "INTERNAL_ERROR", "Reading quota usage failed unexpectedly."
        )

    observed = utcnow()
    snapshots = build_snapshots(project_id, infos, series, observed)
    if usage_error is not None:
        _carry_forward_usage(session, project_id, snapshots)

    session.execute(
        delete(GoogleCloudQuotaSnapshot).where(
            GoogleCloudQuotaSnapshot.project_id == project_id
        )
    )
    for row in snapshots:
        session.add(GoogleCloudQuotaSnapshot(**row))

    project.quota_count = len(snapshots)
    project.last_success_at = observed
    if services_error is not None:
        project.last_error_code = services_error.code
        project.last_error_message = _truncate(services_error.message)

    if usage_error is not None:
        return finish(
            "PARTIAL",
            error_code=usage_error.code,
            message=(
                f"Quota limits synchronised; Cloud Monitoring usage is unavailable. "
                f"{usage_error.message}"
            ),
            quota_infos=len(infos),
            snapshots=len(snapshots),
        )
    return finish(
        "SUCCEEDED",
        quota_infos=len(infos),
        snapshots=len(snapshots),
    )


def _apply_identity(
    project: GoogleCloudProject, identity: ProjectIdentity, verified_at: datetime
) -> None:
    project.verification_status = "VERIFIED"
    project.project_number = identity.project_number
    project.display_name = identity.display_name
    project.lifecycle_state = identity.lifecycle_state
    project.last_verified_at = verified_at


def sync_projects(
    session: Session,
    settings: Settings,
    *,
    project_ids: list[str] | None = None,
    trigger: SyncTrigger = "MANUAL",
    client: GoogleCloudClient | None = None,
) -> dict[str, Any]:
    """Sync each project independently and return the refreshed report.

    A failure is committed for that project alone; later projects still run.  The
    integration never raises because Google is down, except when it is not
    configured at all — there is nothing honest to sync in that case.
    """

    if not settings.google_cloud.configured:
        raise QuotaSyncUnavailable(
            "Google Cloud quota synchronisation is not configured. Set a "
            "service-account JSON file outside the repository (or enable the "
            "metadata server) before syncing."
        )
    if project_ids is None:
        targets = declared_project_ids(session)
    else:
        targets = sorted({item.strip() for item in project_ids if item and item.strip()})
    if trigger == "SCHEDULED" and not settings.google_cloud.enabled:
        return quota_report(session, settings)

    active = client
    if active is None:
        try:
            active = build_client(settings.google_cloud)
        except GoogleCloudError as exc:
            raise QuotaSyncUnavailable(exc.message) from exc

    results: list[dict[str, Any]] = []
    for project_id in targets:
        try:
            results.append(
                _sync_project(session, settings, active, project_id, trigger)
            )
        except Exception:
            session.rollback()
            results.append(
                {
                    "project_id": project_id,
                    "status": "FAILED",
                    "run_id": None,
                    "verification": "ERROR",
                    "quota_infos": 0,
                    "snapshots": 0,
                    "error_code": "INTERNAL_ERROR",
                    "message": "The synchronisation failed unexpectedly.",
                }
            )
        session.commit()

    report = quota_report(session, settings)
    report["sync_results"] = results
    return report


def _run_read(run: GoogleCloudSyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "quota_infos": run.quota_infos,
        "snapshots_written": run.snapshots_written,
        "api_calls": run.api_calls,
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


def _snapshot_read(row: GoogleCloudQuotaSnapshot) -> dict[str, Any]:
    limit = float(row.limit_value) if row.limit_value is not None else None
    usage = float(row.usage_value) if row.usage_value is not None else None
    exceeded = float(row.exceeded_value) if row.exceeded_value is not None else None
    return {
        "quota_id": row.quota_id,
        "metric": row.metric,
        "service": row.service,
        "metric_display_name": row.metric_display_name,
        "quota_display_name": row.quota_display_name,
        "unit": row.unit,
        "refresh_interval": row.refresh_interval,
        "reset_time": row.reset_time,
        "container_type": row.container_type,
        "is_precise": row.is_precise,
        "dimensions": dict(row.dimensions or {}),
        "limit": limit,
        "is_unlimited": limit is not None and limit <= UNLIMITED_SENTINEL,
        "limit_source": row.limit_source,
        "usage": usage,
        "usage_source": row.usage_source,
        "usage_metric": row.usage_metric,
        "usage_observed_at": row.usage_observed_at,
        "exceeded": exceeded,
        "observed_at": row.observed_at,
    }


def quota_report(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    stale_after = settings.google_cloud.stale_after_seconds
    declared = declared_project_ids(session)
    projects_by_id = verification_summary(session, declared)

    projects: list[dict[str, Any]] = []
    total_quotas = 0
    usage_observed = 0
    stale_projects = 0
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_failure_message: str | None = None
    services_by_project: dict[str, list[str]] = {}

    for project_id in declared:
        project = projects_by_id.get(project_id)
        quotas = list(
            session.execute(
                select(GoogleCloudQuotaSnapshot)
                .where(GoogleCloudQuotaSnapshot.project_id == project_id)
                .order_by(
                    GoogleCloudQuotaSnapshot.quota_id,
                    GoogleCloudQuotaSnapshot.dimensions_key,
                )
            ).scalars()
        )
        runs = list(
            session.execute(
                select(GoogleCloudSyncRun)
                .where(GoogleCloudSyncRun.project_id == project_id)
                .order_by(GoogleCloudSyncRun.started_at.desc())
                .limit(5)
            ).scalars()
        )
        success_at = project.last_success_at if project else None
        stale = is_stale(success_at, observed, stale_after)
        if success_at is not None and (last_success is None or success_at > last_success):
            last_success = success_at
        failure_run = next((run for run in runs if run.status != "SUCCEEDED"), None)
        if failure_run is not None:
            failure_at = failure_run.finished_at or failure_run.started_at
            if last_failure is None or failure_at > last_failure:
                last_failure = failure_at
                last_failure_message = failure_run.error_message or (
                    f"{project_id}: {failure_run.status}"
                )
        if stale:
            stale_projects += 1
        total_quotas += len(quotas)
        usage_observed += sum(1 for row in quotas if row.usage_value is not None)
        if project is not None and project.enabled_services is not None:
            services_by_project[project_id] = list(project.enabled_services)
        projects.append(
            {
                "project_id": project_id,
                "verification": (
                    project.verification_status if project else "UNVERIFIED"
                ),
                "verified": bool(project and project.verification_status == "VERIFIED"),
                "project_number": project.project_number if project else None,
                "display_name": project.display_name if project else None,
                "lifecycle_state": project.lifecycle_state if project else None,
                "last_attempt_at": project.last_attempt_at if project else None,
                "last_verified_at": project.last_verified_at if project else None,
                "last_success_at": success_at,
                "last_error_code": project.last_error_code if project else None,
                "last_error_message": project.last_error_message if project else None,
                "stale": stale,
                "quota_count": len(quotas),
                "usage_observed": sum(1 for row in quotas if row.usage_value is not None),
                "quotas": [_snapshot_read(row) for row in quotas],
                "runs": [_run_read(run) for run in runs],
            }
        )

    apis = []
    for requirement in REQUIRED_APIS:
        service = requirement["service"]
        if service == "generativelanguage.googleapis.com":
            enabled: bool | None = None
        elif not services_by_project:
            enabled = None
        else:
            enabled = all(service in values for values in services_by_project.values())
        apis.append({**requirement, "enabled": enabled})

    return {
        "observed_at": observed,
        "service": settings.google_cloud.service,
        "fleet": {
            "configured": settings.google_cloud.configured,
            "credential_source": credential_source(settings.google_cloud),
            "scheduled_sync_enabled": settings.google_cloud.enabled,
            "sync_interval_seconds": settings.google_cloud.sync_interval_seconds,
            "stale_after_seconds": stale_after,
            "declared_projects": len(declared),
            "verified_projects": sum(
                1
                for row in projects
                if row["verification"] == "VERIFIED"
            ),
            "quotas_total": total_quotas,
            "usage_observed": usage_observed,
            "stale_projects": stale_projects,
            "last_success_at": last_success,
            "last_failure_at": last_failure,
            "last_failure_message": last_failure_message,
        },
        "projects": projects,
        "apis": apis,
        "ai_studio": {
            "available": AISTUDIO_AVAILABLE,
            "reason": AISTUDIO_REASON,
            "source": AISTUDIO_SOURCE,
        },
        "coverage": {
            "supported": COVERAGE_SUPPORTED,
            "unavailable": COVERAGE_UNAVAILABLE,
        },
        "note": (
            "Limits come from Cloud Quotas and usage from Cloud Monitoring, each "
            "with its own observation timestamp. Aetrix policy estimates remain "
            "separate on the Overview tab. Nothing here is a Google figure unless "
            "its source says so; missing metrics are unavailable, not zero."
        ),
        "sync_results": [],
    }
