"""Unit tests for platform-wide aggregates.

No database and no network: the session is a scalar stub and the identity
census is either a fake loader or a monkeypatched Supabase read.  The tests pin
the definitions that matter — suspended and unconfirmed accounts are excluded,
one identity is counted once, zero is a measured zero, and a missing credential
is unavailable rather than zero.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.core.config import PlatformAdminSettings
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal
from app.services.platform_accounts import account_role, account_status
from app.services.platform_overview import (
    PlatformOverviewService,
    RoleCensus,
    active_role_census,
    reset_census_cache,
)
from sqlalchemy.exc import SQLAlchemyError


def _principal(platform_role: str = "PLATFORM_OWNER", role: str = "OWNER") -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        subject="actor-subject",
        role=role,
        platform_role=platform_role,
    )


def _settings(ttl: int = 60) -> PlatformAdminSettings:
    return PlatformAdminSettings(
        supabase_url="https://project.supabase.co",
        service_role_key="service-role-key",
        census_ttl_seconds=ttl,
    )


class ScalarSession:
    def __init__(self, values: list[int], *, error: Exception | None = None) -> None:
        self.values = iter(values)
        self.error = error

    def scalar(self, statement: Any) -> int:
        if self.error is not None:
            raise self.error
        return next(self.values)


def _census(teachers: int, assistants: int, total: int = 0) -> RoleCensus:
    return RoleCensus(
        counts={"supervisor": teachers, "assistant": assistants},
        active_total=total or teachers + assistants,
        captured_at=datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
        cached=False,
    )


def _metric_payload(**counts: int) -> dict[str, Any]:
    service = PlatformOverviewService(
        ScalarSession([counts["workspaces"], counts["allocations"]]),
        _settings(),
        census_loader=lambda settings, refresh: _census(
            counts["teachers"], counts["assistants"]
        ),
    )
    return service.overview(_principal()).model_dump()


def test_metrics_use_live_workspaces_and_active_identities() -> None:
    payload = _metric_payload(workspaces=3, allocations=7, teachers=4, assistants=2)
    metrics = {metric["key"]: metric for metric in payload["metrics"]}

    assert metrics["teacher_workspaces"]["value"] == 3
    assert metrics["active_class_allocations"]["value"] == 7
    assert metrics["teachers"]["value"] == 4
    assert metrics["assistant_accounts"]["value"] == 2
    assert all(metric["state"] == "available" for metric in metrics.values())
    assert "non-demo" in metrics["teacher_workspaces"]["definition"]
    assert "Supabase" in metrics["teachers"]["source"]


def test_zero_is_a_measured_zero_not_unavailable() -> None:
    payload = _metric_payload(workspaces=0, allocations=0, teachers=0, assistants=0)
    for metric in payload["metrics"]:
        assert metric["value"] == 0
        assert metric["state"] == "no_records"
        assert metric["reason"] is None


def test_missing_credential_makes_identity_metrics_unavailable_but_keeps_workspaces() -> None:
    def unavailable(settings: PlatformAdminSettings, *, refresh: bool = False) -> RoleCensus:
        raise AppError(ErrorCode.ADMIN_NOT_CONFIGURED, "No service-role key is configured.")

    service = PlatformOverviewService(
        ScalarSession([2, 5]), _settings(), census_loader=unavailable
    )
    payload = service.overview(_principal()).model_dump()
    metrics = {metric["key"]: metric for metric in payload["metrics"]}

    assert metrics["teacher_workspaces"]["value"] == 2
    assert metrics["active_class_allocations"]["value"] == 5
    assert metrics["teachers"]["value"] is None
    assert metrics["teachers"]["state"] == "unavailable"
    assert metrics["teachers"]["reason"] == "No service-role key is configured."
    assert metrics["assistant_accounts"]["state"] == "unavailable"
    assert payload["account_census"]["available"] is False


def test_upstream_failure_is_unavailable_not_a_zero() -> None:
    def failed(settings: PlatformAdminSettings, *, refresh: bool = False) -> RoleCensus:
        raise AppError(ErrorCode.ADMIN_UPSTREAM_ERROR, "Supabase refused the read.")

    service = PlatformOverviewService(
        ScalarSession([1, 1]), _settings(), census_loader=failed
    )
    metrics = {
        metric.key: metric for metric in service.overview(_principal()).metrics
    }
    assert metrics["teachers"].value is None
    assert metrics["teachers"].state == "unavailable"
    assert metrics["teachers"].reason == "Supabase refused the read."


def test_workspace_owner_has_no_platform_overview() -> None:
    with pytest.raises(AppError) as error:
        PlatformOverviewService(
            ScalarSession([]), _settings(), census_loader=lambda settings, refresh: _census(0, 0)
        ).overview(_principal(platform_role="", role="OWNER"))
    assert error.value.code is ErrorCode.FORBIDDEN


def test_database_failure_propagates_to_the_error_handler() -> None:
    service = PlatformOverviewService(
        ScalarSession([], error=SQLAlchemyError("database is down")),
        _settings(),
        census_loader=lambda settings, refresh: _census(0, 0),
    )
    with pytest.raises(SQLAlchemyError):
        service.overview(_principal())


def _user(
    account_id: str,
    role: str | None,
    *,
    confirmed: bool = True,
    banned_until: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if role is not None:
        metadata["aetrix_role"] = role
    return {
        "id": account_id,
        "email": f"{account_id}@example.test",
        "app_metadata": metadata,
        "email_confirmed_at": "2026-01-02T03:05:00Z" if confirmed else None,
        "banned_until": banned_until,
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_census_cache()
    yield
    reset_census_cache()


def test_census_counts_active_roles_once_and_excludes_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = [
        _user("one", "supervisor"),
        _user("one", "supervisor"),  # the same identity on a second page
        _user("banned-teacher", "supervisor", banned_until="2126-01-01T00:00:00Z"),
        _user("unconfirmed-teacher", "supervisor", confirmed=False),
        _user("assistant", "assistant"),
        _user("banned-assistant", "assistant", banned_until="2126-01-01T00:00:00Z"),
        _user("viewer", "viewer"),
        _user("unassigned", None),
    ]

    def fake_fetch(settings, *, client_factory=None):
        return users, False

    monkeypatch.setattr(
        "app.services.platform_overview.fetch_all_accounts", fake_fetch
    )
    census = active_role_census(_settings())

    assert census.counts["supervisor"] == 1
    assert census.counts["assistant"] == 1
    assert census.active_total == 4  # teacher, assistant, viewer, unassigned


def test_census_uses_the_cache_until_a_forced_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def fake_fetch(settings, *, client_factory=None):
        calls["count"] += 1
        return [_user("one", "supervisor")], False

    monkeypatch.setattr(
        "app.services.platform_overview.fetch_all_accounts", fake_fetch
    )
    first = active_role_census(_settings())
    second = active_role_census(_settings())

    assert calls["count"] == 1
    assert first.cached is False
    assert second.cached is True

    forced = active_role_census(_settings(), refresh=True)
    assert calls["count"] == 2
    assert forced.cached is False


def test_census_can_disable_caching(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_fetch(settings, *, client_factory=None):
        calls["count"] += 1
        return [], False

    monkeypatch.setattr(
        "app.services.platform_overview.fetch_all_accounts", fake_fetch
    )
    active_role_census(_settings(ttl=0))
    active_role_census(_settings(ttl=0))
    assert calls["count"] == 2


def test_census_without_a_credential_is_not_zero() -> None:
    with pytest.raises(AppError) as error:
        active_role_census(PlatformAdminSettings())
    assert error.value.code is ErrorCode.ADMIN_NOT_CONFIGURED


def test_shared_interpretation_matches_account_management() -> None:
    """The overview and account management read the same fields the same way."""

    assert account_role({"aetrix_role": "supervisor"}) == "supervisor"
    assert account_role({"aetrix_role": "assistant"}) == "assistant"
    assert account_role({"aetrix_role": "owner"}) == "owner"
    assert account_status(_user("x", "supervisor")) == "ACTIVE"
    assert account_status(_user("x", "supervisor", confirmed=False)) == "UNCONFIRMED"
    stale = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert account_status(_user("x", "supervisor", banned_until=stale)) == "ACTIVE"
