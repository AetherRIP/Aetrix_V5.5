"""Read-only Google Cloud clients for quota and usage synchronisation.

The module deliberately does not depend on ``google-auth`` or any Google SDK:
the service-account JWT grant is small, and keeping it here makes the exact
scopes and endpoints auditable.  Nothing in this module mutates Google Cloud.
It only calls:

* Resource Manager ``projects.get`` — establish project identity;
* Cloud Quotas ``quotaInfos.list`` — authoritative quota limits;
* Cloud Monitoring ``timeSeries.list`` — consumer-quota usage;
* Service Usage ``services.list`` — which required APIs are enabled.

Secrets never leave the credential object: ``repr`` hides the private key, error
messages contain Google's own status text, and no token or key is logged.

The Cloud Quotas API only accepts the ``cloud-platform`` OAuth scope, so the
token requests it alongside ``monitoring.read``.  Least privilege is enforced by
the IAM roles on the service account (``roles/cloudquotas.viewer``,
``roles/monitoring.viewer``, ``roles/serviceusage.serviceUsageViewer``,
``roles/browser``), not by narrowing the scope string.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import jwt

from ..core.config import GoogleCloudSettings

TOKEN_URI = "https://oauth2.googleapis.com/token"
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/token"
)
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
MONITORING_READ_SCOPE = "https://www.googleapis.com/auth/monitoring.read"
SERVICE_ACCOUNT_SCOPES = (MONITORING_READ_SCOPE, CLOUD_PLATFORM_SCOPE)

RESOURCE_MANAGER_PROJECTS = "https://cloudresourcemanager.googleapis.com/v1/projects"
CLOUD_QUOTAS_QUOTA_INFOS = "https://cloudquotas.googleapis.com/v1"
MONITORING_TIME_SERIES = "https://monitoring.googleapis.com/v3"
SERVICE_USAGE_SERVICES = "https://serviceusage.googleapis.com/v1"

ALLOCATION_USAGE = "serviceruntime.googleapis.com/quota/allocation/usage"
RATE_NET_USAGE = "serviceruntime.googleapis.com/quota/rate/net_usage"
QUOTA_LIMIT = "serviceruntime.googleapis.com/quota/limit"
QUOTA_EXCEEDED = "serviceruntime.googleapis.com/quota/exceeded"

#: ``aligner`` is the Cloud Monitoring per-series aligner for the latest value.
USAGE_METRICS: tuple[tuple[str, str], ...] = (
    (ALLOCATION_USAGE, "ALIGN_MAX"),
    (RATE_NET_USAGE, "ALIGN_MAX"),
    (QUOTA_LIMIT, "ALIGN_MAX"),
    (QUOTA_EXCEEDED, "ALIGN_SUM"),
)

REQUIRED_APIS: tuple[dict[str, str], ...] = (
    {
        "service": "cloudresourcemanager.googleapis.com",
        "name": "Cloud Resource Manager API",
        "permission": "resourcemanager.projects.get",
        "used_for": "Verify that a declared project exists and is accessible.",
    },
    {
        "service": "cloudquotas.googleapis.com",
        "name": "Cloud Quotas API",
        "permission": "cloudquotas.quotas.get",
        "used_for": "Read quota definitions and limits, including model dimensions.",
    },
    {
        "service": "monitoring.googleapis.com",
        "name": "Cloud Monitoring API",
        "permission": "monitoring.timeSeries.list",
        "used_for": "Read consumer-quota usage and exceeded counters.",
    },
    {
        "service": "serviceusage.googleapis.com",
        "name": "Service Usage API",
        "permission": "serviceusage.services.list",
        "used_for": "Report whether the required APIs are enabled.",
    },
    {
        "service": "generativelanguage.googleapis.com",
        "name": "Gemini API",
        "permission": "(enabled service)",
        "used_for": "The service whose quotas are observed.",
    },
)

#: Google documents the Gemini API's active rate limits in AI Studio only.  No
#: public endpoint returns the per-model RPM/RPD/TPM table or AI Studio usage, so
#: this value is reported as unavailable rather than guessed.
AISTUDIO_AVAILABLE = False
AISTUDIO_SOURCE = "https://ai.google.dev/gemini-api/docs/rate-limits"
AISTUDIO_REASON = (
    "Google AI Studio displays active Gemini API rate limits and usage in its "
    "console, but publishes no public API for them. Aetrix therefore cannot "
    "read AI Studio usage or the per-model RPM/RPD/TPM table programmatically; "
    "only quotas Google exposes through Cloud Quotas and Cloud Monitoring are "
    "synchronised. Verify AI Studio figures manually in the Google Cloud console."
)

PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
#: Pool ids the fleet uses for keys with no real Google project.  They are
#: preserved in the dashboard but never sent to Google as a project lookup.
SYNTHETIC_PROJECT_PREFIXES = ("legacy-",)


class GoogleCloudError(RuntimeError):
    """A classified Google Cloud failure with an actionable, secret-free message."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


def is_verifiable_project_id(project_id: str) -> bool:
    """Return whether ``project_id`` has the shape of a Google Cloud project id.

    Synthetic pool ids (``legacy-*``, ``unattributed``) are preserved in the
    fleet but never sent to Google: a request for a name that cannot exist only
    produces a misleading permission error.
    """

    candidate = project_id.strip()
    if candidate == "unattributed" or candidate.startswith(
        SYNTHETIC_PROJECT_PREFIXES
    ):
        return False
    return bool(PROJECT_ID_PATTERN.fullmatch(candidate))


def _normalise_fraction(value: str) -> str:
    """Keep at most six fractional digits so ``fromisoformat`` accepts Google's nanos."""

    match = re.search(r"\.(\d{6})\d+", value)
    if match:
        return value[: match.start(1) + 6] + value[match.end() :]
    return value


def parse_rfc3339(value: str) -> datetime:
    """Parse a Google timestamp as an aware UTC instant.

    A timestamp without an offset is rejected: silently treating it as local
    time would shift a quota observation across the daily reset boundary.
    """

    text = _normalise_fraction(value.strip())
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GoogleCloudError(
            "INVALID_RESPONSE", "Google returned a timestamp Aetrix cannot read."
        ) from exc
    if parsed.tzinfo is None:
        raise GoogleCloudError(
            "INVALID_RESPONSE",
            "Google returned a timestamp without a timezone; refusing to guess UTC.",
        )
    return parsed.astimezone(UTC)


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


@dataclass(frozen=True, repr=False)
class ServiceAccountCredentials:
    client_email: str
    private_key: str = field(repr=False)
    private_key_id: str | None = field(default=None, repr=False)
    token_uri: str = TOKEN_URI

    def __repr__(self) -> str:
        return f"ServiceAccountCredentials(client_email={self.client_email!r})"


@dataclass(frozen=True, repr=False)
class QuotaDimension:
    values: dict[str, str]
    quota_value: float | None
    reset_time: str | None = None

    def __repr__(self) -> str:
        return f"QuotaDimension(values={self.values!r}, quota_value={self.quota_value!r})"


@dataclass(frozen=True)
class QuotaInfo:
    quota_id: str
    metric: str
    service: str
    metric_display_name: str | None
    quota_display_name: str | None
    unit: str | None
    refresh_interval: str | None
    container_type: str | None
    is_precise: bool | None
    dimensions: tuple[str, ...]
    dimension_values: tuple[QuotaDimension, ...]
    default_quota_value: float | None


@dataclass(frozen=True)
class UsageSeries:
    metric_type: str
    quota_metric: str | None
    limit_name: str | None
    metric_labels: dict[str, str]
    resource_labels: dict[str, str]
    value: float | None
    unit: str | None
    observed_at: datetime | None
    point_count: int


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str
    project_number: str | None
    display_name: str | None
    lifecycle_state: str | None


class TokenProvider(Protocol):
    def token(self) -> str:  # pragma: no cover - protocol
        ...


class StaticTokenProvider:
    """Test/automation provider; never reads a credential."""

    def __init__(self, value: str = "test-token") -> None:
        self._value = value

    def token(self) -> str:
        return self._value


def _status_error(
    status: int,
    payload: Any,
    *,
    operation: str,
    permission: str | None,
) -> GoogleCloudError:
    message = ""
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = str(error.get("message") or "").strip()
    message = message[:400]
    detail = f"{operation}: {message}" if message else operation
    if status == 401:
        return GoogleCloudError(
            "INVALID_CREDENTIALS",
            f"Google rejected the service-account token. {detail}",
            status=status,
        )
    if status == 403:
        needed = f" Grant {permission} to the service account." if permission else ""
        return GoogleCloudError(
            "PERMISSION_DENIED",
            f"Google refused the read (403).{needed} {detail}".strip(),
            status=status,
        )
    if status == 404:
        return GoogleCloudError(
            "NOT_FOUND",
            f"Google Cloud did not find the requested resource. {detail}",
            status=status,
        )
    if status == 429:
        return GoogleCloudError(
            "RATE_LIMITED",
            f"Google rate-limited the read. {detail}",
            status=status,
            retryable=True,
        )
    if status in {500, 502, 503, 504}:
        return GoogleCloudError(
            "UPSTREAM_ERROR",
            f"Google returned a server error ({status}). {detail}",
            status=status,
            retryable=True,
        )
    return GoogleCloudError(
        "INVALID_REQUEST",
        f"Google rejected the read ({status}). {detail}",
        status=status,
    )


class ServiceAccountTokenProvider:
    """Exchange a service-account assertion for an access token and cache it."""

    def __init__(
        self,
        credentials: ServiceAccountCredentials,
        *,
        scopes: Iterable[str] = SERVICE_ACCOUNT_SCOPES,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._credentials = credentials
        self._scopes = tuple(scopes)
        self._transport = transport
        self._timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0

    def _assertion(self) -> str:
        issued = int(self._clock())
        claims = {
            "iss": self._credentials.client_email,
            "scope": " ".join(self._scopes),
            "aud": self._credentials.token_uri,
            "iat": issued,
            "exp": issued + 3600,
        }
        headers = {"alg": "RS256", "typ": "JWT"}
        if self._credentials.private_key_id:
            headers["kid"] = self._credentials.private_key_id
        try:
            return jwt.encode(
                claims, self._credentials.private_key, algorithm="RS256", headers=headers
            )
        except Exception as exc:
            raise GoogleCloudError(
                "INVALID_CREDENTIALS",
                "The Google service-account private key could not sign a token. "
                "Check that the JSON file is complete and not corrupted.",
            ) from exc

    def token(self) -> str:
        with self._lock:
            now = self._clock()
            if self._token and now < self._expires_at:
                return self._token
            assertion = self._assertion()
            last: GoogleCloudError | None = None
            for attempt in range(2):
                try:
                    with httpx.Client(
                        timeout=self._timeout,
                        transport=self._transport,
                        follow_redirects=False,
                    ) as client:
                        response = client.post(
                            self._credentials.token_uri,
                            data={
                                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                "assertion": assertion,
                            },
                            headers={"accept": "application/json"},
                        )
                except httpx.TimeoutException as exc:
                    last = GoogleCloudError(
                        "TIMEOUT",
                        "The Google token endpoint timed out.",
                        retryable=True,
                    )
                    if attempt == 0:
                        self._sleep(1.0)
                        continue
                    raise last from exc
                except httpx.HTTPError as exc:
                    last = GoogleCloudError(
                        "NETWORK_ERROR",
                        "The Google token endpoint could not be reached.",
                        retryable=True,
                    )
                    if attempt == 0:
                        self._sleep(1.0)
                        continue
                    raise last from exc
                if response.status_code != 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = None
                    last = _status_error(
                        response.status_code,
                        payload,
                        operation="service-account token exchange",
                        permission=None,
                    )
                    if last.retryable and attempt == 0:
                        self._sleep(1.0)
                        continue
                    raise last
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise GoogleCloudError(
                        "INVALID_RESPONSE",
                        "The Google token endpoint returned an unreadable response.",
                    ) from exc
                access = payload.get("access_token") if isinstance(payload, Mapping) else None
                if not isinstance(access, str) or not access:
                    raise GoogleCloudError(
                        "INVALID_RESPONSE",
                        "The Google token endpoint did not return an access token.",
                    )
                expires = to_float(payload.get("expires_in")) or 3600.0
                self._token = access
                self._expires_at = now + max(expires - 120.0, 30.0)
                return access
            raise last or GoogleCloudError(
                "NETWORK_ERROR", "The Google token endpoint could not be reached."
            )


class MetadataTokenProvider:
    """Application Default Credentials from the GCE/Cloud Run metadata server."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._transport = transport
        self._timeout = timeout
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0

    def token(self) -> str:
        with self._lock:
            now = time.time()
            if self._token and now < self._expires_at:
                return self._token
            try:
                with httpx.Client(
                    timeout=self._timeout,
                    transport=self._transport,
                    follow_redirects=False,
                ) as client:
                    response = client.get(
                        METADATA_TOKEN_URL,
                        headers={"Metadata-Flavor": "Google", "accept": "application/json"},
                    )
            except httpx.HTTPError as exc:
                raise GoogleCloudError(
                    "NOT_CONFIGURED",
                    "The metadata server is not reachable. Set a service-account "
                    "file or disable AETRIX_GOOGLE_CLOUD__USE_METADATA.",
                ) from exc
            if response.status_code != 200:
                raise GoogleCloudError(
                    "NOT_CONFIGURED",
                    "The metadata server refused a token; the workload identity may "
                    "lack the Cloud Monitoring scope.",
                    status=response.status_code,
                )
            payload = response.json()
            access = payload.get("access_token") if isinstance(payload, Mapping) else None
            if not isinstance(access, str) or not access:
                raise GoogleCloudError(
                    "INVALID_RESPONSE",
                    "The metadata server did not return an access token.",
                )
            expires = to_float(payload.get("expires_in")) or 300.0
            self._token = access
            self._expires_at = now + max(expires - 60.0, 30.0)
            return access


def _read_credentials_document(settings: GoogleCloudSettings) -> tuple[str, str] | None:
    if settings.service_account_json is not None:
        return settings.service_account_json.get_secret_value(), "SERVICE_ACCOUNT_JSON"
    path_text: str | None = None
    source = "SERVICE_ACCOUNT_FILE"
    if settings.service_account_file is not None:
        path_text = str(settings.service_account_file)
    else:
        import os

        fallback = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if fallback:
            path_text = fallback
            source = "APPLICATION_DEFAULT_CREDENTIALS"
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        return path.read_text(encoding="utf-8"), source
    except OSError as exc:
        raise GoogleCloudError(
            "NOT_CONFIGURED",
            f"The Google Cloud credential file could not be read ({path}).",
        ) from exc


def _service_account_from_document(raw: str) -> ServiceAccountCredentials:
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise GoogleCloudError(
            "INVALID_CREDENTIALS",
            "The Google Cloud credential is not valid JSON.",
        ) from exc
    if not isinstance(payload, Mapping):
        raise GoogleCloudError(
            "INVALID_CREDENTIALS", "The Google Cloud credential is not a JSON object."
        )
    if payload.get("type") != "service_account":
        raise GoogleCloudError(
            "INVALID_CREDENTIALS",
            "Only a service-account JSON credential is supported here; external "
            "account and authorised-user credentials are not.",
        )
    client_email = payload.get("client_email")
    private_key = payload.get("private_key")
    if not isinstance(client_email, str) or not client_email.strip():
        raise GoogleCloudError(
            "INVALID_CREDENTIALS", "The service-account credential has no client_email."
        )
    if not isinstance(private_key, str) or "PRIVATE KEY" not in private_key:
        raise GoogleCloudError(
            "INVALID_CREDENTIALS", "The service-account credential has no private key."
        )
    token_uri = payload.get("token_uri") or TOKEN_URI
    if not isinstance(token_uri, str) or not token_uri.startswith("https://"):
        raise GoogleCloudError(
            "INVALID_CREDENTIALS",
            "The service-account token_uri must be an https URL.",
        )
    key_id = payload.get("private_key_id")
    return ServiceAccountCredentials(
        client_email=client_email.strip(),
        private_key=private_key,
        private_key_id=key_id.strip() if isinstance(key_id, str) and key_id else None,
        token_uri=token_uri,
    )


def load_service_account(settings: GoogleCloudSettings) -> ServiceAccountCredentials:
    document = _read_credentials_document(settings)
    if document is None:
        raise GoogleCloudError(
            "NOT_CONFIGURED",
            "No Google Cloud monitoring credential is configured. Set "
            "AETRIX_GOOGLE_CLOUD__SERVICE_ACCOUNT_FILE to a service-account JSON "
            "file outside the repository, or enable the metadata server.",
        )
    return _service_account_from_document(document[0])


def credential_source(settings: GoogleCloudSettings) -> str:
    if settings.use_metadata:
        return "METADATA_SERVER"
    if settings.service_account_json is not None:
        return "SERVICE_ACCOUNT_JSON"
    if settings.service_account_file is not None:
        return "SERVICE_ACCOUNT_FILE"
    import os

    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
        return "APPLICATION_DEFAULT_CREDENTIALS"
    return "NOT_CONFIGURED"


def create_token_provider(
    settings: GoogleCloudSettings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> TokenProvider:
    if settings.use_metadata:
        return MetadataTokenProvider(transport=transport)
    return ServiceAccountTokenProvider(
        load_service_account(settings),
        transport=transport,
        timeout=settings.request_timeout_seconds,
    )


def _parse_quota_info(payload: Mapping[str, Any], service: str) -> QuotaInfo | None:
    quota_id = payload.get("quotaId")
    metric = payload.get("metric")
    if not isinstance(quota_id, str) or not quota_id.strip():
        return None
    if not isinstance(metric, str) or not metric.strip():
        return None
    dimension_values: list[QuotaDimension] = []
    for item in payload.get("dimensionsInfos") or []:
        if not isinstance(item, Mapping):
            continue
        details = item.get("details")
        details_map = details if isinstance(details, Mapping) else {}
        dimension_values.append(
            QuotaDimension(
                values=_string_map(item.get("dimensions")),
                quota_value=to_float(
                    details_map.get("quotaValue", details_map.get("value"))
                ),
                reset_time=(
                    str(details_map["resetTime"])
                    if details_map.get("resetTime") is not None
                    else None
                ),
            )
        )
    dimensions = payload.get("dimensions") or []
    return QuotaInfo(
        quota_id=quota_id.strip(),
        metric=metric.strip(),
        service=str(payload.get("service") or service),
        metric_display_name=(
            str(payload["metricDisplayName"]) if payload.get("metricDisplayName") else None
        ),
        quota_display_name=(
            str(payload["quotaDisplayName"]) if payload.get("quotaDisplayName") else None
        ),
        unit=str(payload["unit"]) if payload.get("unit") else None,
        refresh_interval=(
            str(payload["refreshInterval"]) if payload.get("refreshInterval") else None
        ),
        container_type=(
            str(payload["containerType"]) if payload.get("containerType") else None
        ),
        is_precise=(
            bool(payload["isPrecise"]) if isinstance(payload.get("isPrecise"), bool) else None
        ),
        dimensions=tuple(str(item) for item in dimensions if str(item).strip()),
        dimension_values=tuple(dimension_values),
        default_quota_value=to_float(payload.get("quotaValue")),
    )


def _parse_usage_series(payload: Mapping[str, Any]) -> UsageSeries:
    metric = payload.get("metric") if isinstance(payload.get("metric"), Mapping) else {}
    resource = (
        payload.get("resource") if isinstance(payload.get("resource"), Mapping) else {}
    )
    metric_labels = _string_map(metric.get("labels") if isinstance(metric, Mapping) else {})
    resource_labels = _string_map(
        resource.get("labels") if isinstance(resource, Mapping) else {}
    )
    points = payload.get("points") if isinstance(payload.get("points"), list) else []
    value: float | None = None
    observed_at: datetime | None = None
    if points:
        first = points[0] if isinstance(points[0], Mapping) else {}
        typed = first.get("value") if isinstance(first.get("value"), Mapping) else {}
        value = to_float(typed.get("int64Value"))
        if value is None:
            value = to_float(typed.get("doubleValue"))
        interval = first.get("interval") if isinstance(first.get("interval"), Mapping) else {}
        end = interval.get("endTime")
        if isinstance(end, str) and end.strip():
            observed_at = parse_rfc3339(end)
    metric_type = metric.get("type") if isinstance(metric, Mapping) else None
    return UsageSeries(
        metric_type=str(metric_type or ""),
        quota_metric=metric_labels.get("quota_metric"),
        limit_name=metric_labels.get("limit_name"),
        metric_labels=metric_labels,
        resource_labels=resource_labels,
        value=value,
        unit=str(payload["unit"]) if payload.get("unit") else None,
        observed_at=observed_at,
        point_count=len(points),
    )


class GoogleCloudClient:
    """Read-only API surface with retry, timeout and error classification."""

    def __init__(
        self,
        token_provider: TokenProvider,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._tokens = token_provider
        self._transport = transport
        self._timeout = timeout
        self._max_attempts = max(1, max_attempts)
        self._backoff = max(0.0, backoff_seconds)
        self._sleep = sleep
        self.request_count = 0

    def _get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        operation: str,
        permission: str,
    ) -> Any:
        last: GoogleCloudError | None = None
        for attempt in range(self._max_attempts):
            token = self._tokens.token()
            self.request_count += 1
            try:
                with httpx.Client(
                    timeout=self._timeout,
                    transport=self._transport,
                    follow_redirects=False,
                ) as client:
                    response = client.get(
                        url,
                        params=params,
                        headers={
                            "authorization": f"Bearer {token}",
                            "accept": "application/json",
                        },
                    )
            except httpx.TimeoutException as exc:
                last = GoogleCloudError(
                    "TIMEOUT", f"{operation} timed out.", retryable=True
                )
                if attempt + 1 < self._max_attempts:
                    self._sleep(self._backoff * (2**attempt))
                    continue
                raise last from exc
            except httpx.HTTPError as exc:
                last = GoogleCloudError(
                    "NETWORK_ERROR",
                    f"{operation} could not reach Google Cloud.",
                    retryable=True,
                )
                if attempt + 1 < self._max_attempts:
                    self._sleep(self._backoff * (2**attempt))
                    continue
                raise last from exc

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise GoogleCloudError(
                        "INVALID_RESPONSE", f"{operation} returned unreadable JSON."
                    ) from exc

            try:
                payload = response.json()
            except ValueError:
                payload = None
            last = _status_error(
                response.status_code,
                payload,
                operation=operation,
                permission=permission,
            )
            if last.retryable and attempt + 1 < self._max_attempts:
                self._sleep(self._backoff * (2**attempt))
                continue
            raise last
        raise last or GoogleCloudError("UPSTREAM_ERROR", f"{operation} failed.")

    def verify_project(self, project_id: str) -> ProjectIdentity:
        if not is_verifiable_project_id(project_id):
            raise GoogleCloudError(
                "INVALID_PROJECT_ID",
                f"{project_id!r} is not a Google Cloud project id, so Google "
                "cannot confirm it. The declared identifier is preserved.",
            )
        payload = self._get(
            f"{RESOURCE_MANAGER_PROJECTS}/{quote(project_id, safe='')}",
            params={},
            operation=f"verifying project {project_id}",
            permission="resourcemanager.projects.get",
        )
        if not isinstance(payload, Mapping):
            raise GoogleCloudError(
                "INVALID_RESPONSE", "Resource Manager returned an unreadable project."
            )
        returned = payload.get("projectId")
        if not isinstance(returned, str) or returned.lower() != project_id.lower():
            raise GoogleCloudError(
                "PROJECT_MISMATCH",
                f"Google returned project {returned!r} for the declared id "
                f"{project_id!r}; the assignment is not verified.",
            )
        number = payload.get("projectNumber")
        return ProjectIdentity(
            project_id=returned,
            project_number=str(number) if number is not None else None,
            display_name=str(payload["name"]) if payload.get("name") else None,
            lifecycle_state=(
                str(payload["lifecycleState"]) if payload.get("lifecycleState") else None
            ),
        )

    def list_quota_infos(
        self, project_id: str, service: str, *, max_infos: int = 2000
    ) -> list[QuotaInfo]:
        base = (
            f"{CLOUD_QUOTAS_QUOTA_INFOS}/projects/{quote(project_id, safe='')}"
            f"/locations/global/services/{quote(service, safe='')}/quotaInfos"
        )
        rows: list[QuotaInfo] = []
        page_token: str | None = None
        for _page in range(20):
            params: dict[str, str | int] = {"pageSize": min(1000, max_infos)}
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(
                base,
                params=params,
                operation=f"reading quota definitions for {project_id}",
                permission="cloudquotas.quotas.get",
            )
            if not isinstance(payload, Mapping):
                raise GoogleCloudError(
                    "INVALID_RESPONSE", "Cloud Quotas returned an unreadable response."
                )
            for item in payload.get("quotaInfos") or []:
                if not isinstance(item, Mapping):
                    continue
                parsed = _parse_quota_info(item, service)
                if parsed is not None:
                    rows.append(parsed)
                if len(rows) >= max_infos:
                    return rows
            token = payload.get("nextPageToken")
            if not isinstance(token, str) or not token:
                break
            page_token = token
        return rows

    def list_usage_series(
        self,
        project_id: str,
        service: str,
        *,
        window_minutes: int = 15,
        now: datetime | None = None,
    ) -> list[UsageSeries]:
        end = (now or datetime.now(UTC)).astimezone(UTC)
        start = end - timedelta(minutes=window_minutes)
        base = (
            f"{MONITORING_TIME_SERIES}/projects/{quote(project_id, safe='')}/timeSeries"
        )
        series: list[UsageSeries] = []
        for metric_type, aligner in USAGE_METRICS:
            filter_text = (
                f'metric.type="{metric_type}" AND resource.type="consumer_quota" '
                f'AND resource.label.service="{service}"'
            )
            page_token: str | None = None
            for _page in range(5):
                params: dict[str, str | int] = {
                    "filter": filter_text,
                    "interval.startTime": start.isoformat().replace("+00:00", "Z"),
                    "interval.endTime": end.isoformat().replace("+00:00", "Z"),
                    "aggregation.alignmentPeriod": f"{window_minutes * 60}s",
                    "aggregation.perSeriesAligner": aligner,
                    "view": "FULL",
                    "pageSize": 1000,
                }
                if page_token:
                    params["pageToken"] = page_token
                payload = self._get(
                    base,
                    params=params,
                    operation=f"reading quota usage for {project_id}",
                    permission="monitoring.timeSeries.list",
                )
                if not isinstance(payload, Mapping):
                    raise GoogleCloudError(
                        "INVALID_RESPONSE",
                        "Cloud Monitoring returned an unreadable response.",
                    )
                for item in payload.get("timeSeries") or []:
                    if isinstance(item, Mapping):
                        series.append(_parse_usage_series(item))
                token = payload.get("nextPageToken")
                if not isinstance(token, str) or not token:
                    break
                page_token = token
        return series

    def list_enabled_services(self, project_id: str) -> list[str]:
        base = (
            f"{SERVICE_USAGE_SERVICES}/projects/{quote(project_id, safe='')}/services"
        )
        enabled: list[str] = []
        page_token: str | None = None
        for _page in range(5):
            params: dict[str, str | int] = {
                "filter": "state:ENABLED",
                "pageSize": 200,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(
                base,
                params=params,
                operation=f"reading enabled services for {project_id}",
                permission="serviceusage.services.list",
            )
            if not isinstance(payload, Mapping):
                raise GoogleCloudError(
                    "INVALID_RESPONSE", "Service Usage returned an unreadable response."
                )
            for item in payload.get("services") or []:
                if not isinstance(item, Mapping):
                    continue
                config = item.get("config")
                name = config.get("name") if isinstance(config, Mapping) else None
                if isinstance(name, str) and name:
                    enabled.append(name)
            token = payload.get("nextPageToken")
            if not isinstance(token, str) or not token:
                break
            page_token = token
        return sorted(set(enabled))


def build_client(settings: GoogleCloudSettings) -> GoogleCloudClient:
    return GoogleCloudClient(
        create_token_provider(settings),
        timeout=settings.request_timeout_seconds,
        max_attempts=settings.max_attempts,
        backoff_seconds=settings.backoff_seconds,
    )
