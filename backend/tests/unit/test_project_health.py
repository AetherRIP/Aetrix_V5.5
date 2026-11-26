"""Project health classification from stored samples and real traffic.

No provider is called here.  Every input below is a durable row Aetrix already
writes: a Cloud API sync run, a quota snapshot, or a Gemini call in the usage
ledger.  The tests pin the distinctions the dashboard must not blur:

* one invalid key is a credential signal, not project ill-health;
* a bare 429 is throttling, not proof of exhausted quota;
* UNKNOWN is never rendered as healthy or as zero;
* an incident id is stable, so a continuing incident is not repeated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.project_health import (
    AUTH_FAILURE,
    CONFIRMED,
    DEGRADED,
    ESTIMATED,
    HEALTHY,
    PERMISSION_FAILURE,
    QUOTA_EXHAUSTED,
    UNKNOWN,
    QuotaView,
    RunView,
    UsageSignal,
    build_health,
    classify_usage,
    project_alerts,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _run(
    status: str = "SUCCEEDED",
    error_code: str | None = None,
    *,
    minutes_ago: int = 1,
) -> RunView:
    started = NOW - timedelta(minutes=minutes_ago)
    return RunView(
        id=f"run-{status}-{error_code}-{minutes_ago}",
        status=status,
        error_code=error_code,
        started_at=started,
        finished_at=started + timedelta(seconds=2),
    )


def _signal(
    *,
    success: bool = True,
    status: int | None = 200,
    category: str | None = None,
    model: str = "gemini-3.6-flash",
    minutes_ago: int = 1,
) -> UsageSignal:
    return UsageSignal(
        model=model,
        success=success,
        http_status=status,
        error_category=category,
        created_at=NOW - timedelta(minutes=minutes_ago),
        latency_ms=800,
    )


def _health(
    runs: list[RunView] | None = None,
    quotas: list[QuotaView] | None = None,
    usage: list[UsageSignal] | None = None,
    *,
    stale_after: int = 3600,
):
    return build_health(
        "project-a",
        runs if runs is not None else [_run()],
        quotas or [],
        usage or [],
        now=NOW,
        stale_after_seconds=stale_after,
    )


def test_one_invalid_key_does_not_make_the_project_ill() -> None:
    """A 401 is a credential signal; the project's Cloud APIs still answered."""

    health = _health(
        usage=[_signal(success=False, status=401, category="authentication")]
    )

    assert health["state"] == HEALTHY
    assert health["signals"]["counts"]["authentication"] == 1
    assert health["state_confidence"] == CONFIRMED


def test_project_auth_failure_comes_from_the_monitor_credential() -> None:
    health = _health(runs=[_run("FAILED", "INVALID_CREDENTIALS")])

    assert health["state"] == AUTH_FAILURE
    assert "monitor's credential" in health["reason"]


def test_permission_failure_is_not_collapsed_into_invalid_credentials() -> None:
    health = _health(runs=[_run("FAILED", "PERMISSION_DENIED")])

    assert health["state"] == PERMISSION_FAILURE
    assert "403" in health["reason"]


def test_a_bare_429_is_throttling_not_confirmed_exhaustion() -> None:
    health = _health(
        usage=[_signal(success=False, status=429, category="quota")]
    )

    assert health["state"] == DEGRADED
    assert health["quota_status"] == "WARNING"
    assert health["quota_confidence"] == ESTIMATED
    assert health["signals"]["counts"]["rate_limited"] == 1
    assert health["signals"]["counts"]["quota_refused"] == 0
    assert "not proof" in health["quota_reason"]


def test_an_exceeded_counter_confirms_exhaustion() -> None:
    health = _health(
        quotas=[QuotaView(limit_value=100, limit_source="CLOUD_QUOTAS", exceeded_value=1)],
        usage=[_signal(success=False, status=429, category="quota")],
    )

    assert health["quota_status"] == QUOTA_EXHAUSTED
    assert health["quota_confidence"] == CONFIRMED
    assert health["signals"]["counts"]["quota_refused"] == 1


def test_provider_server_and_network_failures_are_separate() -> None:
    signals = classify_usage(
        [
            _signal(success=False, status=503, category="provider_server"),
            _signal(success=False, status=None, category="network"),
            _signal(success=False, status=500, category="provider_server"),
        ],
        quota_exceeded=False,
    )

    assert signals["counts"]["provider_server"] == 2
    assert signals["counts"]["network"] == 1
    assert signals["counts"]["authentication"] == 0


def test_model_unavailability_is_model_specific() -> None:
    health = _health(
        usage=[
            _signal(
                success=False,
                status=404,
                category="unsupported_model",
                model="gemini-missing",
            ),
            _signal(model="gemini-3.6-flash"),
        ]
    )

    models = {row["model"]: row for row in health["signals"]["models"]}
    assert models["gemini-missing"]["state"] == "FAILING"
    assert models["gemini-missing"]["last_http_status"] == 404
    assert models["gemini-3.6-flash"]["state"] == "AVAILABLE"
    assert health["state"] == HEALTHY
    assert health["signals"]["counts"]["model_not_found"] == 1


def test_no_telemetry_means_unknown_quota_not_zero() -> None:
    health = _health()

    assert health["quota_status"] == UNKNOWN
    assert health["quota_confidence"] == "UNKNOWN"
    assert health["signals"]["confidence"] == "UNKNOWN"
    assert health["signals"]["counts"]["requests"] == 0
    assert health["signals"]["average_latency_ms"] is None


def test_a_google_limit_is_confirmed_but_remaining_quota_is_not_claimed() -> None:
    health = _health(
        quotas=[QuotaView(limit_value=1500, limit_source="CLOUD_QUOTAS", exceeded_value=0)]
    )

    assert health["quota_status"] == "KNOWN"
    assert health["quota_confidence"] == CONFIRMED
    assert "not the\n" not in health["quota_reason"]
    assert "remaining amount" in health["quota_reason"]


def test_a_stale_sample_is_labelled_and_alerted() -> None:
    health = _health(runs=[_run(minutes_ago=180)], stale_after=3600)
    alerts = project_alerts("project-a", health)

    assert health["sample_stale"] is True
    stale = [alert for alert in alerts if alert["kind"] == "sample_stale"]
    assert len(stale) == 1
    assert stale[0]["id"] == "project-a:sample_stale"


def test_a_continuing_incident_has_one_stable_alert() -> None:
    health = _health(runs=[_run("FAILED", "PERMISSION_DENIED")])

    first = project_alerts("project-a", health)
    second = project_alerts("project-a", health)

    assert [alert["id"] for alert in first] == [alert["id"] for alert in second]
    assert len([alert for alert in first if alert["kind"] == "project_permission_failure"]) == 1


def test_recovery_is_reported_once_for_the_recovering_sample() -> None:
    health = _health(
        runs=[
            _run("SUCCEEDED", minutes_ago=1),
            _run("FAILED", "PERMISSION_DENIED", minutes_ago=16),
        ]
    )

    assert health["recovered"] is True
    recovered = [
        alert
        for alert in project_alerts("project-a", health)
        if alert["kind"] == "recovered"
    ]
    assert len(recovered) == 1
    assert recovered[0]["severity"] == "info"


def test_health_is_per_project_not_per_key() -> None:
    """Two keys sharing a project produce one health object and one sum of traffic."""

    usage = [_signal(minutes_ago=1), _signal(minutes_ago=2)]
    health = _health(usage=usage)

    assert health["signals"]["counts"]["requests"] == 2
    assert health["signals"]["counts"]["successes"] == 2


def test_identity_failure_is_unknown_not_a_quota_claim() -> None:
    health = _health(runs=[_run("FAILED", "NOT_FOUND")])

    assert health["state"] == UNKNOWN
    assert health["quota_status"] == UNKNOWN
    assert "No Gemini quota figure is implied" in health["reason"]


def test_alert_text_never_contains_a_credential() -> None:
    health = _health(runs=[_run("FAILED", "INVALID_CREDENTIALS")])
    rendered = " ".join(str(alert) for alert in project_alerts("project-a", health))

    assert "private_key" not in rendered
    assert "Bearer" not in rendered
    assert "AIza" not in rendered
