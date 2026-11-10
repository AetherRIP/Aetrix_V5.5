"""Component health: deployment, operation and readiness are separate facts.

These tests need PostgreSQL because the status route reads the heartbeat table,
the provider usage ledger and the job table.  They never call Google: provider
availability must come from recorded evidence, and the test records that
evidence itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.models import ProviderUsage, ServiceHeartbeat


def _status(client) -> dict:
    response = client.get("/status")
    assert response.status_code == 200
    return response.json()


def _component(payload: dict, name: str) -> dict:
    return next(component for component in payload["components"] if component["name"] == name)


def _heartbeat(db_session) -> None:
    db_session.add(
        ServiceHeartbeat(
            name="worker",
            last_seen_at=datetime.now(UTC),
            detail={"test": True},
        )
    )
    db_session.commit()


def test_status_reports_each_component_separately(client, db_session):
    _heartbeat(db_session)

    payload = _status(client)
    api = _component(payload, "HTTP API")
    database = _component(payload, "PostgreSQL")
    worker = _component(payload, "Background worker")
    provider = _component(payload, "AI provider")

    assert (api["deployment"], api["operational"], api["readiness"]) == (
        "deployed",
        "available",
        "ready",
    )
    assert (database["deployment"], database["operational"], database["readiness"]) == (
        "deployed",
        "available",
        "ready",
    )
    assert (worker["deployment"], worker["operational"]) == ("deployed", "available")
    # A running worker is still not ready to produce a mark.
    assert worker["readiness"] == "not_ready"
    assert "unproven" in worker["diagnostic"]

    # No credential is registered, so the provider is not configured — it is not
    # reported as down, and it is never reported as available.
    assert provider["deployment"] == "not_configured"
    assert provider["readiness"] == "not_ready"
    assert provider["last_success_at"] is None


def test_no_heartbeat_is_reported_as_not_deployed(client):
    worker = _component(_status(client), "Background worker")

    assert worker["deployment"] == "not_deployed"
    assert worker["operational"] == "unavailable"
    assert worker["last_success_at"] is None


def test_a_recorded_live_call_verifies_reachability_not_marking(client, db_session):
    _heartbeat(db_session)
    db_session.add(
        ProviderUsage(
            tenant_id=None,
            credential_id=None,
            job_id=None,
            project_id="test-project",
            provider="google",
            model="gemini-3.6-flash",
            purpose="validate",
            success=True,
            reported=False,
            http_status=200,
            latency_ms=900,
        )
    )
    db_session.commit()

    provider = _component(_status(client), "AI provider")
    if not get_settings().features.live_provider:
        assert provider["deployment"] == "not_configured"
        return

    assert provider["deployment"] == "deployed"
    assert provider["operational"] == "available"
    # Reachability is not accuracy: the provider is still not ready to mark.
    assert provider["readiness"] == "not_ready"
    assert provider["last_success_at"] is not None
    assert "UNVERIFIED" in provider["diagnostic"]


def test_a_recorded_failure_degrades_the_provider(client, db_session):
    _heartbeat(db_session)
    db_session.add(
        ProviderUsage(
            tenant_id=None,
            credential_id=None,
            job_id=None,
            project_id="test-project",
            provider="google",
            model="gemini-3.6-flash",
            purpose="validate",
            success=False,
            reported=False,
            http_status=503,
            error_class="ProviderTransientError",
        )
    )
    db_session.commit()

    provider = _component(_status(client), "AI provider")
    if not get_settings().features.live_provider:
        assert provider["deployment"] == "not_configured"
        return

    assert provider["operational"] == "degraded"
    assert provider["last_failure"] is not None
    assert "503" in provider["last_failure"]
