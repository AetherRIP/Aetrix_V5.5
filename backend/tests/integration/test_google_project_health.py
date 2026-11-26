"""Quota report integration: durable samples, project separation and staleness.

These tests run against PostgreSQL because the report reads the real
``google_cloud_sync_runs``, ``provider_usage`` and ``service_heartbeats`` tables.
No Google request is made: the stored rows are the evidence under test.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.db.models import (
    GoogleCloudProject,
    GoogleCloudSyncRun,
    ProviderCredential,
    ProviderUsage,
    ServiceHeartbeat,
)
from app.services.google_quota import quota_report
from app.services.project_health import (
    MONITOR_HEARTBEAT,
    monitor_snapshot,
    record_monitor_heartbeat,
)


def _credential(db_session, template, project_id: str, fingerprint: str) -> ProviderCredential:
    row = ProviderCredential(
        id=uuid.uuid4(),
        pool_id=f"gemini-key-{uuid.uuid4()}",
        tenant_id=template.tenant_id,
        project_id=project_id,
        account_label=f"{project_id} key",
        key_fingerprint=fingerprint,
        encrypted_secret=template.encrypted_secret,
        model_access=[],
        health="HEALTHY",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _run(
    db_session,
    project_id: str,
    status: str,
    *,
    error_code: str | None = None,
    minutes_ago: int = 1,
) -> GoogleCloudSyncRun:
    started = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    row = GoogleCloudSyncRun(
        project_id=project_id,
        trigger="SCHEDULED",
        status=status,
        started_at=started,
        finished_at=started + timedelta(seconds=4),
        quota_infos=3,
        snapshots_written=0,
        api_calls=4,
        error_code=error_code,
        error_message="permission denied" if error_code else None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _usage(
    db_session,
    credential: ProviderCredential,
    *,
    success: bool,
    status: int | None,
    category: str | None = None,
    model: str = "gemini-3.6-flash",
) -> None:
    db_session.add(
        ProviderUsage(
            tenant_id=credential.tenant_id,
            credential_id=credential.id,
            job_id=None,
            project_id=credential.project_id,
            provider="google",
            model=model,
            purpose="marking",
            success=success,
            reported=False,
            http_status=status,
            error_category=category,
            latency_ms=700,
        )
    )


def _seed(db_session, provider_credential):
    healthy = provider_credential
    broken_project = _credential(db_session, healthy, "second-project", "f" * 32)
    db_session.add_all(
        [
            GoogleCloudProject(
                project_id="fixture-project", verification_status="VERIFIED"
            ),
            GoogleCloudProject(
                project_id="second-project", verification_status="VERIFIED"
            ),
        ]
    )
    db_session.flush()
    _run(db_session, "fixture-project", "SUCCEEDED")
    _run(db_session, "second-project", "FAILED", error_code="PERMISSION_DENIED")
    # Two keys in one project: one success and one 401.  The project stays healthy.
    _usage(db_session, healthy, success=True, status=200)
    _usage(db_session, healthy, success=False, status=401, category="authentication")
    _usage(db_session, broken_project, success=False, status=429, category="quota")
    db_session.add(
        ServiceHeartbeat(
            name=MONITOR_HEARTBEAT,
            last_seen_at=datetime.now(UTC),
            detail={"pid": 1, "duration_ms": 12},
        )
    )
    db_session.commit()
    return healthy, broken_project


def test_report_separates_project_health_from_individual_pools(
    db_session, provider_credential
) -> None:
    healthy, broken = _seed(db_session, provider_credential)

    report = quota_report(db_session, get_settings())
    projects = {row["project_id"]: row for row in report["projects"]}

    assert set(projects) == {"fixture-project", "second-project"}
    assert projects["fixture-project"]["health"]["state"] == "HEALTHY"
    # The 401 belongs to one pool; it is counted, but it does not make the project
    # an authentication failure.
    assert (
        projects["fixture-project"]["health"]["signals"]["counts"]["authentication"]
        == 1
    )
    assert projects["second-project"]["health"]["state"] == "PERMISSION_FAILURE"

    assert report["fleet"]["healthy_projects"] == 1
    assert report["fleet"]["degraded_projects"] == 1
    assert report["fleet"]["unknown_projects"] == 0
    assert report["fleet"]["quota_warnings"] == 1

    # One alert per continuing project incident, not one per key.
    kinds = [alert["kind"] for alert in report["alerts"]]
    assert kinds.count("project_permission_failure") == 1
    assert kinds.count("throttling") == 1
    assert healthy.project_id == "fixture-project"
    assert broken.project_id == "second-project"


def test_report_carries_monitor_freshness_and_hides_a_stale_sample(
    db_session, provider_credential
) -> None:
    _seed(db_session, provider_credential)
    report = quota_report(db_session, get_settings())
    assert report["monitor"]["state"] == "OK"

    heartbeat = db_session.get(ServiceHeartbeat, MONITOR_HEARTBEAT)
    assert heartbeat is not None
    heartbeat.last_seen_at = datetime.now(UTC) - timedelta(hours=4)
    db_session.commit()

    stale = monitor_snapshot(
        db_session, interval_seconds=get_settings().google_cloud.sync_interval_seconds
    )
    assert stale["state"] == "STALE"
    assert stale["age_seconds"] is not None and stale["age_seconds"] > stale["grace_seconds"]

    report = quota_report(db_session, get_settings())
    assert report["monitor"]["state"] == "STALE"
    assert any(alert["kind"] == "monitoring_stale" for alert in report["alerts"])


def test_heartbeat_write_is_idempotent(db_session) -> None:
    record_monitor_heartbeat(db_session, {"pid": 1, "duration_ms": 5})
    record_monitor_heartbeat(db_session, {"pid": 1, "duration_ms": 7})

    rows = list(db_session.query(ServiceHeartbeat).all())
    monitor_rows = [row for row in rows if row.name == MONITOR_HEARTBEAT]
    assert len(monitor_rows) == 1
    assert monitor_rows[0].detail["duration_ms"] == 7


def test_report_never_serialises_the_credential_secret(
    db_session, provider_credential
) -> None:
    _seed(db_session, provider_credential)
    payload = json.dumps(quota_report(db_session, get_settings()), default=str)

    assert provider_credential.encrypted_secret not in payload
    assert "encrypted_secret" not in payload
    assert "api_key" not in payload
