"""Mocked tests for the read-only Google Cloud quota integration.

No test reaches Google and none needs PostgreSQL.  The transport is a
``httpx.MockTransport`` and the credential is generated in-process, so the
service-account signing path is exercised without a real key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import jwt
import pytest
from app.core.config import GoogleCloudSettings
from app.services.google_cloud import (
    AISTUDIO_AVAILABLE,
    ALLOCATION_USAGE,
    QUOTA_EXCEEDED,
    TOKEN_URI,
    GoogleCloudClient,
    GoogleCloudError,
    QuotaDimension,
    QuotaInfo,
    ServiceAccountCredentials,
    ServiceAccountTokenProvider,
    StaticTokenProvider,
    UsageSeries,
    build_client,
    credential_source,
    is_verifiable_project_id,
    load_service_account,
    parse_rfc3339,
)
from app.services.google_quota import (
    COVERAGE_UNAVAILABLE,
    UNLIMITED_SENTINEL,
    _match_series,
    build_snapshots,
    is_stale,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

SERVICE = "generativelanguage.googleapis.com"
METRIC = "generativelanguage.googleapis.com/generate_content_requests"


def _keypair() -> tuple[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return private, key.public_key()


def _credentials() -> tuple[ServiceAccountCredentials, object]:
    private, public = _keypair()
    return (
        ServiceAccountCredentials(
            client_email="quota-reader@example.iam.gserviceaccount.com",
            private_key=private,
            private_key_id="key-1",
        ),
        public,
    )


def _client(handler, *, sleep=None, max_attempts: int = 3) -> GoogleCloudClient:
    return GoogleCloudClient(
        StaticTokenProvider("access-token"),
        transport=httpx.MockTransport(handler),
        sleep=sleep or (lambda _seconds: None),
        max_attempts=max_attempts,
        backoff_seconds=1.0,
    )


def _quota_info(quota_id: str, model: str, value: str) -> dict[str, object]:
    return {
        "quotaId": quota_id,
        "metric": METRIC,
        "service": SERVICE,
        "metricDisplayName": "Generate content requests",
        "quotaDisplayName": f"Generate content requests for {model}",
        "unit": "1/min/{project}/{model}",
        "refreshInterval": "minute",
        "containerType": "PROJECT",
        "isPrecise": True,
        "dimensions": ["model"],
        "dimensionsInfos": [
            {
                "dimensions": {"model": model},
                "details": {
                    "quotaValue": value,
                    "resetTime": "2026-11-11T00:00:00Z",
                },
            }
        ],
    }


def test_service_account_assertion_is_signed_with_the_configured_scopes() -> None:
    credentials, public = _credentials()
    provider = ServiceAccountTokenProvider(
        credentials, clock=lambda: 1_800_000_000.0, sleep=lambda _seconds: None
    )

    assertion = provider._assertion()
    claims = jwt.decode(
        assertion,
        public,  # type: ignore[arg-type]
        algorithms=["RS256"],
        audience=TOKEN_URI,
        options={"verify_exp": False, "verify_iat": False},
    )

    assert claims["iss"] == credentials.client_email
    assert claims["exp"] - claims["iat"] == 3600
    assert "monitoring.read" in claims["scope"]
    assert "cloud-platform" in claims["scope"]
    assert jwt.get_unverified_header(assertion)["kid"] == "key-1"


def test_token_is_cached_until_shortly_before_expiry() -> None:
    credentials, _ = _credentials()
    now = [1_800_000_000.0]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"access_token": "token-1", "expires_in": 3600})

    provider = ServiceAccountTokenProvider(
        credentials,
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
        sleep=lambda _seconds: None,
    )

    assert provider.token() == "token-1"
    assert provider.token() == "token-1"
    assert len(calls) == 1
    assert calls[0].url == httpx.URL(TOKEN_URI)
    assert b"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in calls[0].content

    now[0] += 3500
    assert provider.token() == "token-1"
    assert len(calls) == 2


def test_missing_credentials_are_reported_without_echoing_a_secret() -> None:
    with pytest.raises(GoogleCloudError) as caught:
        load_service_account(GoogleCloudSettings())

    assert caught.value.code == "NOT_CONFIGURED"
    assert "SERVICE_ACCOUNT_FILE" in caught.value.message
    assert credential_source(GoogleCloudSettings()) == "NOT_CONFIGURED"


def test_inline_json_that_is_not_a_service_account_is_rejected() -> None:
    settings = GoogleCloudSettings(
        service_account_json=SecretStr('{"type":"authorized_user","secret":"do-not-echo"}')
    )

    with pytest.raises(GoogleCloudError) as caught:
        load_service_account(settings)

    assert caught.value.code == "INVALID_CREDENTIALS"
    assert "do-not-echo" not in caught.value.message
    assert credential_source(settings) == "SERVICE_ACCOUNT_JSON"


def test_verify_project_returns_google_identity_and_rejects_a_mismatch() -> None:
    def verified(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "projectId": "aetrix-prod",
                "projectNumber": "123456789",
                "name": "Aetrix production",
                "lifecycleState": "ACTIVE",
            },
        )

    identity = _client(verified).verify_project("aetrix-prod")
    assert identity.project_number == "123456789"
    assert identity.lifecycle_state == "ACTIVE"

    def mismatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"projectId": "someone-else"})

    with pytest.raises(GoogleCloudError) as caught:
        _client(mismatch).verify_project("aetrix-prod")
    assert caught.value.code == "PROJECT_MISMATCH"
    assert "not verified" in caught.value.message


def test_permission_denied_is_actionable_and_not_retried() -> None:
    calls: list[httpx.Request] = []

    def denied(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            403,
            json={"error": {"message": "Permission monitoring.timeSeries.list denied"}},
        )

    client = _client(denied)
    with pytest.raises(GoogleCloudError) as caught:
        client.list_usage_series("aetrix-prod", SERVICE)

    assert caught.value.code == "PERMISSION_DENIED"
    assert "monitoring.timeSeries.list" in caught.value.message
    assert len(calls) == 1


def test_rate_limit_is_retried_with_exponential_backoff() -> None:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def throttled(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"message": "quota exceeded"}})
        return httpx.Response(200, json={"quotaInfos": []})

    client = _client(throttled, sleep=sleeps.append)
    assert client.list_quota_infos("aetrix-prod", SERVICE) == []
    assert len(calls) == 2
    assert sleeps == [1.0]


def test_timeouts_are_retried_and_then_reported() -> None:
    calls: list[httpx.Request] = []

    def timeout(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    client = _client(timeout, sleep=lambda _seconds: None, max_attempts=3)
    with pytest.raises(GoogleCloudError) as caught:
        client.verify_project("aetrix-prod")

    assert caught.value.code == "TIMEOUT"
    assert len(calls) == 3


def test_quota_infos_paginate_and_keep_per_dimension_limits() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params.get("pageToken") is None:
            return httpx.Response(
                200,
                json={
                    "quotaInfos": [_quota_info("rpm-pro", "gemini-2.5-pro", "10")],
                    "nextPageToken": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={"quotaInfos": [_quota_info("rpm-flash", "gemini-2.5-flash", "15")]},
        )

    infos = _client(handler).list_quota_infos("aetrix-prod", SERVICE)

    assert len(calls) == 2
    assert [info.quota_id for info in infos] == ["rpm-pro", "rpm-flash"]
    assert infos[0].dimension_values[0].values == {"model": "gemini-2.5-pro"}
    assert infos[0].dimension_values[0].quota_value == 10.0
    assert infos[0].dimension_values[0].reset_time == "2026-11-11T00:00:00Z"
    assert infos[0].is_precise is True


def test_usage_series_parse_and_convert_any_offset_to_utc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if ALLOCATION_USAGE in (request.url.params.get("filter") or ""):
            return httpx.Response(
                200,
                json={
                    "timeSeries": [
                        {
                            "metric": {
                                "type": ALLOCATION_USAGE,
                                "labels": {
                                    "quota_metric": METRIC,
                                    "limit_name": "Requests per minute",
                                    "model": "gemini-2.5-pro",
                                },
                            },
                            "resource": {
                                "type": "consumer_quota",
                                "labels": {"project_id": "aetrix-prod"},
                            },
                            "unit": "1",
                            "points": [
                                {
                                    "interval": {"endTime": "2026-11-10T12:00:00+02:00"},
                                    "value": {"int64Value": "4"},
                                }
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"timeSeries": []})

    series = _client(handler).list_usage_series("aetrix-prod", SERVICE)

    usage = next(item for item in series if item.metric_type == ALLOCATION_USAGE)
    assert usage.value == 4.0
    assert usage.observed_at == datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
    assert usage.quota_metric == METRIC
    assert usage.metric_labels["model"] == "gemini-2.5-pro"


def test_timestamp_without_an_offset_is_refused() -> None:
    assert parse_rfc3339("2026-11-10T12:00:00Z") == datetime(
        2026, 11, 10, 12, 0, tzinfo=UTC
    )
    with pytest.raises(GoogleCloudError) as caught:
        parse_rfc3339("2026-11-10T12:00:00")
    assert caught.value.code == "INVALID_RESPONSE"


def test_snapshots_match_the_model_dimension_and_never_invent_usage() -> None:
    infos = [
        QuotaInfo(
            quota_id="rpm-pro",
            metric=METRIC,
            service=SERVICE,
            metric_display_name="Generate content requests",
            quota_display_name="Requests per minute",
            unit="1/min",
            refresh_interval="minute",
            container_type="PROJECT",
            is_precise=True,
            dimensions=("model",),
            dimension_values=(
                QuotaDimension({"model": "gemini-2.5-pro"}, 10.0),
                QuotaDimension({"model": "gemini-2.5-flash"}, 15.0),
            ),
            default_quota_value=None,
        )
    ]
    series = [
        UsageSeries(
            metric_type=ALLOCATION_USAGE,
            quota_metric=METRIC,
            limit_name="Requests per minute",
            metric_labels={"model": "gemini-2.5-pro"},
            resource_labels={"project_id": "aetrix-prod"},
            value=4.0,
            unit="1",
            observed_at=datetime(2026, 11, 10, 10, 0, tzinfo=UTC),
            point_count=1,
        )
    ]

    rows = build_snapshots(
        "aetrix-prod", infos, series, datetime(2026, 11, 10, 10, 1, tzinfo=UTC)
    )

    assert len(rows) == 2
    pro = next(row for row in rows if row["dimensions"]["model"] == "gemini-2.5-pro")
    flash = next(
        row for row in rows if row["dimensions"]["model"] == "gemini-2.5-flash"
    )
    assert pro["limit_value"] == Decimal("10.0")
    assert pro["limit_source"] == "CLOUD_QUOTAS"
    assert pro["usage_value"] == Decimal("4.0")
    assert pro["usage_source"] == "CLOUD_MONITORING"
    assert flash["usage_value"] is None
    assert flash["usage_source"] == "NOT_EXPOSED"
    assert flash["limit_value"] == Decimal("15.0")


def test_conflicting_model_labels_are_not_attributed() -> None:
    series = UsageSeries(
        metric_type=ALLOCATION_USAGE,
        quota_metric=METRIC,
        limit_name=None,
        metric_labels={"model": "gemini-2.5-flash"},
        resource_labels={},
        value=99.0,
        unit="1",
        observed_at=None,
        point_count=1,
    )

    assert _match_series(METRIC, {"model": "gemini-2.5-pro"}, [series]) is None
    assert _match_series(METRIC, {}, [series]) is series


def test_unlimited_sentinel_and_exceeded_are_preserved() -> None:
    infos = [
        QuotaInfo(
            quota_id="tokens",
            metric=METRIC,
            service=SERVICE,
            metric_display_name=None,
            quota_display_name=None,
            unit="1",
            refresh_interval=None,
            container_type=None,
            is_precise=False,
            dimensions=(),
            dimension_values=(QuotaDimension({}, UNLIMITED_SENTINEL),),
            default_quota_value=None,
        )
    ]
    exceeded = UsageSeries(
        metric_type=QUOTA_EXCEEDED,
        quota_metric=METRIC,
        limit_name=None,
        metric_labels={},
        resource_labels={},
        value=2.0,
        unit="1",
        observed_at=None,
        point_count=1,
    )

    row = build_snapshots(
        "aetrix-prod", infos, [exceeded], datetime(2026, 11, 10, tzinfo=UTC)
    )[0]

    assert row["limit_value"] == Decimal("-1.0")
    assert row["exceeded_value"] == Decimal("2.0")


def test_staleness_is_explicit_for_never_synced_and_old_data() -> None:
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

    assert is_stale(None, now, 3600) is True
    assert is_stale(now - timedelta(minutes=20), now, 3600) is False
    assert is_stale(now - timedelta(hours=2), now, 3600) is True


def test_synthetic_pool_ids_are_never_sent_to_google() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls.append(request)
        return httpx.Response(200, json={})

    client = _client(handler)
    with pytest.raises(GoogleCloudError) as caught:
        client.verify_project("legacy-key-1")

    assert caught.value.code == "INVALID_PROJECT_ID"
    assert calls == []
    assert not is_verifiable_project_id("unattributed")
    assert is_verifiable_project_id("aetrix-prod")


def test_ai_studio_is_reported_as_unavailable_not_guessed() -> None:
    assert AISTUDIO_AVAILABLE is False
    assert "no public API" in COVERAGE_UNAVAILABLE[0]
    assert "AI Studio" in COVERAGE_UNAVAILABLE[0]


def test_unconfigured_build_client_raises_without_a_request() -> None:
    with pytest.raises(GoogleCloudError) as caught:
        build_client(GoogleCloudSettings())
    assert caught.value.code == "NOT_CONFIGURED"
    assert "service-account" in caught.value.message.lower()
