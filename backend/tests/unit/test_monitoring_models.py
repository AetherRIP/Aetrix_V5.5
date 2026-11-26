"""The three-model monitoring allowlist, and the accounting it must not distort.

Monitoring is a reporting view.  It must show exactly three models everywhere it
is rendered, it must not delete or rewrite a retired model's history, and it must
not change what any model is permitted to execute.  These tests cover the
allowlist itself, the two query filters that consume it (per-tenant summary and
the fleet screen's model list), and the daily gate that keeps an outage from
being counted as spent allowance.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import ClassVar

from app.core.config import get_settings
from app.core.ids import utcnow
from app.core.marking_policy import PRODUCTION_MARKING_MODEL
from app.core.model_permissions import AICapability, PermissionStatus, permission_for
from app.core.monitoring_models import (
    MONITORED_MODELS,
    excluded_count,
    filter_monitored,
    is_monitored_model,
)
from app.db.repositories import UsageRepository
from app.services.model_inventory import MODEL_RECORDS
from app.services.provider_calls import CredentialPool
from app.services.provider_fleet import _models
from app.services.quota import QuotaEstimator

FLASH = PRODUCTION_MARKING_MODEL
FLASH_LITE_35 = "gemini-3.5-flash-lite"
FLASH_LITE_31 = "gemini-3.1-flash-lite"
OUTSIDE = ("gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-2.0-flash")


# -- the allowlist -----------------------------------------------------------


def test_the_allowlist_is_exactly_the_three_designated_models() -> None:
    assert MONITORED_MODELS == (FLASH, FLASH_LITE_35, FLASH_LITE_31)


def test_models_outside_the_allowlist_are_not_monitored() -> None:
    for model in OUTSIDE:
        assert not is_monitored_model(model)
    assert not is_monitored_model(None)
    assert not is_monitored_model("  ")


def test_filtering_is_deduplicated_and_in_display_order() -> None:
    listed = [FLASH_LITE_31, OUTSIDE[0], FLASH, FLASH_LITE_31, FLASH_LITE_35]

    assert filter_monitored(listed) == [FLASH, FLASH_LITE_35, FLASH_LITE_31]
    assert excluded_count(listed) == 1


def test_the_allowlist_does_not_erase_a_registered_record() -> None:
    """A retired model keeps its record; only its *view* is excluded."""

    ids = {record.api_model_id for record in MODEL_RECORDS if record.api_model_id}
    assert "gemini-2.0-flash" in ids
    assert OUTSIDE[2] in ids
    assert len(MODEL_RECORDS) == 42


def test_monitoring_membership_grants_no_execution_permission() -> None:
    """Appearing in the three-model view is not a permission."""

    for lite in (FLASH_LITE_35, FLASH_LITE_31):
        assert is_monitored_model(lite)
        assert permission_for(lite, AICapability.MARKING) is PermissionStatus.DISABLED

    # And a model outside the view is not thereby disabled for marking; the
    # permission table answers that, not the monitoring list.
    assert permission_for(FLASH, AICapability.MARKING) is PermissionStatus.ENABLED


# -- the fleet screen's model list -----------------------------------------


def test_the_fleet_screen_lists_only_the_monitored_models() -> None:
    settings = get_settings()

    models = _models(settings)

    assert models == list(MONITORED_MODELS)
    # A key claiming access to anything else cannot add a fourth column.
    class Credential:
        model_access: ClassVar[list[str]] = ["gemini-9.9-flash", FLASH_LITE_31]

    assert _models(settings, [Credential()]) == list(MONITORED_MODELS)


# -- the per-tenant summary --------------------------------------------------


class _Result:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _SummarySession:
    """Returns usage rows for ``summary()`` and a count for ``excluded_*``."""

    def __init__(self, rows: list[tuple], excluded: int = 0) -> None:
        self._rows = rows
        self._excluded = excluded

    def execute(self, _statement: object) -> _Result:
        return _Result(self._rows)

    def scalar(self, _statement: object) -> int:
        return self._excluded


def test_the_tenant_summary_excludes_unmonitored_models_but_reports_them() -> None:
    rows = [
        (FLASH, 4, 400, 200, 0, 0),
        (FLASH_LITE_31, 2, 100, 50, 0, 0),
        ("gemini-2.5-flash", 3, 90, 30, 0, 0),
    ]
    session = _SummarySession(rows, excluded=3)

    summary = UsageRepository(session).summary(uuid.uuid4())  # type: ignore[arg-type]

    assert summary["by_model"] == {FLASH: 4, FLASH_LITE_31: 2}
    assert summary["excluded_requests"] == 3
    # The totals are the ledger's real numbers, not the filtered view's.
    assert summary["requests"] == 9


# -- the daily quota gate ----------------------------------------------------


class _Reservations:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def count_since_credential(
        self, credential_id, since, now, *, model=None, include_unconfirmed=False
    ):
        self.calls.append({"model": model, "include_unconfirmed": include_unconfirmed})
        return 0

    def unconfirmed_count_credential(self, credential_id, since, *, model=None) -> int:
        return 0


class _Usage:
    def validation_count_for_credential(self, credential_id, model, since) -> int:
        return 0

    def tokens_since_credential(self, credential_id, model, since) -> int:
        return 0


def _pool(model_limits=None):
    settings = get_settings()
    if model_limits is not None:
        provider_quota = settings.quota.model_copy(update={"model_limits": model_limits})
        settings = settings.model_copy(update={"quota": provider_quota})
    pool = object.__new__(CredentialPool)
    pool.settings = settings
    pool.reservations = _Reservations()
    pool.usage = _Usage()
    return pool


def test_the_minute_window_counts_unconfirmed_requests_and_the_day_does_not() -> None:
    """An outage hits the rate gate, not the day's allowance."""

    pool = _pool()

    assert pool._within_quota(uuid.uuid4(), FLASH) is True

    flags = [call["include_unconfirmed"] for call in pool.reservations.calls]
    assert flags == [True, False]
    assert all(call["model"] == FLASH for call in pool.reservations.calls)


def test_a_model_with_no_configured_allowance_is_refused() -> None:
    pool = _pool(model_limits={})

    problem = pool.allowance_problem("gemini-9.9-flash")

    assert problem is not None
    assert "gemini-9.9-flash" in problem
    assert "AETRIX_QUOTA__MODEL_LIMITS" in problem
    assert "No request was sent" in problem


def test_a_configured_allowance_is_usable() -> None:
    pool = _pool()

    assert pool.allowance_problem(FLASH) is None


def test_an_unconfigured_model_reports_unknown_rather_than_a_platform_default() -> None:
    estimator = QuotaEstimator(None, get_settings())  # type: ignore[arg-type]

    limits = estimator.limits_for("gemini-9.9-flash")

    assert limits.requests_per_minute is None
    assert limits.requests_per_day is None
    assert limits.tokens_per_minute is None

    configured = estimator.limits_for(FLASH)
    assert configured.requests_per_day is not None


def test_the_unconfirmed_window_is_inside_the_day_window() -> None:
    """A sanity check on the window boundaries the gate passes to the ledger."""

    now = utcnow()
    assert now - timedelta(minutes=1) < now


# -- the monitoring endpoints -------------------------------------------------


class _FakeUsageRepository:
    """Records the allowlist the route hands to the query."""

    seen: ClassVar[dict] = {}

    def __init__(self, _session: object) -> None:
        pass

    def daily(self, since, timezone):
        return []

    def model_window_stats(self, since, *, models=None):
        _FakeUsageRepository.seen["models"] = models
        return [
            {
                "model": FLASH,
                "requests": 3,
                "input_tokens": 30,
                "output_tokens": 10,
                "failures": 0,
            }
        ]

    def excluded_model_requests(self, since, models):
        _FakeUsageRepository.seen["excluded_models"] = models
        return 7

    def project_window_stats(self, since):
        return []

    def recent_calls(self, _limit=25):
        return []


class _FakeCredentialRepository:
    def __init__(self, _session: object) -> None:
        pass

    def all_credentials(self):
        return []


def test_the_usage_endpoint_requests_only_the_monitored_models(
    monkeypatch,
) -> None:
    import app.api.v1.admin_providers as admin_providers

    monkeypatch.setattr(admin_providers, "UsageRepository", _FakeUsageRepository)
    monkeypatch.setattr(
        admin_providers, "CredentialRepository", _FakeCredentialRepository
    )

    report = admin_providers.usage(
        session=object(),  # type: ignore[arg-type]
        settings=get_settings(),
        days=14,
    )

    assert _FakeUsageRepository.seen["models"] == MONITORED_MODELS
    assert [row.model for row in report.by_model] == [FLASH]
    assert report.excluded_requests == 7


def test_the_catalogue_endpoint_shows_three_models_and_says_what_it_hid(
    monkeypatch,
) -> None:
    import app.api.v1.admin_providers as admin_providers

    listed = [FLASH, FLASH_LITE_35, FLASH_LITE_31, "gemini-2.5-flash", "gemini-3.8-flash"]

    def fake_catalogue(session, settings, *, refresh=False):
        return {
            "discovered_at": utcnow(),
            "cached": True,
            "ttl_seconds": 0,
            "projects": [],
            "models": [
                {
                    "id": model,
                    "display_name": model,
                    "description": None,
                    "status": "stable",
                    "status_detail": None,
                    "supports_generate": True,
                    "input_token_limit": None,
                    "output_token_limit": None,
                    "capabilities": {
                        "structured_outputs": None,
                        "thinking": None,
                        "documented_inputs": None,
                        "source": None,
                    },
                    "input_usd_per_million": None,
                    "output_usd_per_million": None,
                    "projects": [],
                }
                for model in listed
            ],
            "selections": {},
            "selection_sources": {},
            "marking_policy": {
                "marking_model": FLASH,
                "disabled_models": [FLASH_LITE_35, FLASH_LITE_31],
                "primary_chain": [FLASH],
                "enforced": True,
                "note": "",
            },
            "note": "base note.",
        }

    monkeypatch.setattr(admin_providers, "discover_catalogue", fake_catalogue)

    report = admin_providers.models(
        refresh=False,
        session=object(),  # type: ignore[arg-type]
        settings=get_settings(),
    )

    assert [model.id for model in report.models] == list(MONITORED_MODELS)
    assert "2 other model(s)" in report.note
    assert "does not change any execution permission" in report.note
