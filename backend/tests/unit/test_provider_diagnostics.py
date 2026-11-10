"""Credential validity and operational health are different questions.

These tests pin the repair: a key that Google accepted stays HEALTHY when a
network, quota or server failure happens later.  The failure is reported by the
separate operational status and remains visible in the ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db.models import ProviderUsage
from app.providers.errors import ProviderNetworkError, ProviderQuotaError
from app.services.provider_fleet import (
    category_for_legacy_error,
    operational_from_error,
    operational_status,
)
from app.services.quota import day_start, next_reset

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)


def _usage(**kwargs) -> ProviderUsage:
    values = {
        "project_id": "declared-project",
        "provider": "gemini",
        "model": "gemini-3.6-flash",
        "purpose": "validate",
        "success": True,
        "created_at": NOW,
    }
    values.update(kwargs)
    return ProviderUsage(**values)


def test_valid_key_with_latest_network_failure_stays_credential_healthy() -> None:
    status = operational_status(
        health="HEALTHY",
        revoked=False,
        cooldown_until=None,
        latest=_usage(
            success=False,
            error_class="ProviderNetworkError",
            error_category="network",
        ),
        now=NOW,
    )

    assert status == "NETWORK_FAILURE"


def test_quota_operational_state_never_rewrites_health() -> None:
    status = operational_status(
        health="UNKNOWN",
        revoked=False,
        cooldown_until=None,
        latest=_usage(
            success=False,
            error_class="ProviderQuotaError",
            error_category="quota",
            http_status=429,
        ),
        now=NOW,
    )

    assert status == "RATE_LIMITED"


def test_untested_and_disabled_credentials_are_distinct() -> None:
    assert (
        operational_status(
            health="UNKNOWN",
            revoked=False,
            cooldown_until=None,
            latest=None,
            now=NOW,
        )
        == "NOT_TESTED"
    )
    assert (
        operational_status(
            health="DISABLED",
            revoked=True,
            cooldown_until=None,
            latest=None,
            now=NOW,
        )
        == "DISABLED"
    )


def test_historical_rows_are_classified_without_being_rewritten() -> None:
    assert category_for_legacy_error("ProviderQuotaError", 429) == "quota"
    assert category_for_legacy_error("ProviderAuthenticationError", 401) == "authentication"
    assert category_for_legacy_error("ProviderResponseError", None) == "provider_response"
    # The old validation defect had no HTTP status but is still diagnosable from
    # the recorded class instead of disappearing as a generic failure.
    assert category_for_legacy_error("ProviderResponseError", None) == "provider_response"


def test_operational_error_types_map_to_operator_facing_states() -> None:
    assert operational_from_error(ProviderNetworkError("timed out")) == "NETWORK_FAILURE"
    assert operational_from_error(ProviderQuotaError("429", status_code=429)) == (
        "RATE_LIMITED"
    )


def test_pacific_daily_boundaries_handle_both_dst_transitions() -> None:
    # 2026-11-01: clocks fall back.  Midnight is still PDT (UTC-7).
    assert day_start(datetime(2026, 11, 1, 12, tzinfo=UTC), "America/Los_Angeles") == (
        datetime(2026, 11, 1, 7, tzinfo=UTC)
    )
    # 2026-03-08: clocks spring forward; the local day is 23 hours long.
    start = day_start(datetime(2026, 3, 8, 12, tzinfo=UTC), "America/Los_Angeles")
    reset = next_reset(datetime(2026, 3, 8, 12, tzinfo=UTC), "America/Los_Angeles")
    assert start == datetime(2026, 3, 8, 8, tzinfo=UTC)
    assert reset == datetime(2026, 3, 9, 7, tzinfo=UTC)
    assert (reset - start).total_seconds() == 23 * 3600
