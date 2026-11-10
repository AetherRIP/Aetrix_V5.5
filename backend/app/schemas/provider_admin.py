"""Contracts for the platform's Gemini fleet administration.

The full secret is absent from every model in this module: an operator can see a
fingerprint, never a key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class QuotaWindowRead(BaseModel):
    limit: int | None
    used: int
    remaining: int | None
    used_share: float | None
    confidence: Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]


class QuotaEstimateRead(BaseModel):
    project_id: str
    model: str
    confidence: Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]
    requests_per_minute: QuotaWindowRead
    tokens_per_minute: QuotaWindowRead
    requests_per_day: QuotaWindowRead
    reset_at: datetime
    reset_timezone: str
    observed_at: datetime
    cooldown_until: datetime | None
    accounting: str
    exhausted: bool
    notes: list[str]


class ProjectRead(BaseModel):
    project_id: str
    #: The operator-declared id is preserved; Google verification is reported
    #: beside it.  ``UNVERIFIED`` means no verification has run, never that the
    #: project is believed valid.
    verification: Literal[
        "VERIFIED",
        "NOT_FOUND",
        "PERMISSION_DENIED",
        "ERROR",
        "UNVERIFIABLE",
        "UNVERIFIED",
        "OPERATOR_DECLARED",
    ]
    verified: bool
    project_number: str | None = None
    google_last_attempt_at: datetime | None = None
    google_quota_last_synced_at: datetime | None = None
    google_quota_stale: bool | None = None
    keys: int
    healthy: int
    unknown: int
    disabled: int
    invalid: int
    cooldown_until: datetime | None
    operational_status: str
    estimates: list[QuotaEstimateRead]


class KeyRead(BaseModel):
    id: UUID
    #: Null means the platform owns the key; a name means it was contributed.
    contributor_id: UUID | None = None
    contributor_name: str | None = None
    revoked_at: datetime | None = None
    project_id: str
    account_label: str
    key_fingerprint: str
    auth_type: str
    tier: str
    health: str
    operational_status: str
    project_verification: Literal["OPERATOR_DECLARED"]
    model_access: list[str]
    cooldown_until: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_failure_status: int | None
    last_failure_category: str | None
    last_failure_provider_code: str | None
    last_failure_message: str | None
    last_failure_reached_provider: bool | None
    last_usage_at: datetime | None
    last_validated_at: datetime | None
    last_error: str | None
    requests: int
    input_tokens: int
    output_tokens: int
    failures: int
    quota_failures: int


class KeyPage(BaseModel):
    items: list[KeyRead]
    total: int
    limit: int
    offset: int


class KeyCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=8, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    model_access: list[str] = Field(default_factory=list)
    tier: Literal["FREE", "PAID", "UNKNOWN"] = "UNKNOWN"
    auth_type: Literal["api_key", "oauth"] = "api_key"


class KeyImportEntry(BaseModel):
    project_id: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=8, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    model_access: list[str] = Field(default_factory=list)
    tier: Literal["FREE", "PAID", "UNKNOWN"] = "UNKNOWN"
    auth_type: Literal["api_key", "oauth"] = "api_key"


class KeyImportRequest(BaseModel):
    keys: list[KeyImportEntry] = Field(min_length=1, max_length=500)


class ImportOutcomeRead(BaseModel):
    index: int
    label: str
    project_id: str
    outcome: Literal["added", "duplicate", "rejected"]
    detail: str | None
    credential_id: UUID | None


class ValidationRead(BaseModel):
    """What the probe actually did, not just whether it passed.

    ``credential_id`` and ``key_fingerprint`` name the key that was tested, so a
    caller can never mistake a sibling's result for this one.  No field can
    carry the secret: the fingerprint is a truncated hash and every message is
    produced by the adapter, not by echoing the request.
    """

    credential_id: UUID
    health: str
    operational_status: str
    valid: bool
    detail: str | None
    #: A failure category, never a merged health verdict.
    category: Literal[
        "ok",
        "authentication",
        "permission",
        "quota",
        "configuration",
        "network",
        "provider_server",
        "provider_response",
        "invalid_request",
        "unsupported_model",
        "internal",
    ]
    http_status: int | None = None
    model: str
    checked_at: datetime
    provider_code: str | None = None
    provider_message: str | None = None
    reached_provider: bool | None = None
    recommendation: str | None = None
    latency_ms: int | None = None
    key_fingerprint: str
    project_id: str
    account_label: str


class EnabledRequest(BaseModel):
    enabled: bool


class FleetOverviewRead(BaseModel):
    keys_total: int
    keys_by_health: dict[str, int]
    projects: int
    declared_projects: int
    verified_projects: int
    project_verification: Literal["OPERATOR_DECLARED", "GOOGLE_CLOUD"]
    attempted_today: int
    requests_today: int
    successful_today: int
    input_tokens_today: int
    output_tokens_today: int
    failures_today: int
    reported_requests_today: int
    error_rate_today: float | None
    operational_status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_failure_category: str | None
    last_failure_message: str | None
    observed_at: datetime
    day_started_at: datetime
    reset_at: datetime
    reset_timezone: str
    quota_accounting: str
    projects_detail: list[ProjectRead]


class ModelUsageRead(BaseModel):
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    failures: int


class ProjectUsageRead(BaseModel):
    project_id: str
    requests: int
    input_tokens: int
    output_tokens: int
    failures: int
    quota_failures: int


class DailyUsageRead(BaseModel):
    day: datetime
    requests: int
    input_tokens: int
    output_tokens: int
    failures: int


class RecentProviderCallRead(BaseModel):
    id: UUID
    created_at: datetime
    credential_id: UUID | None
    credential_label: str | None
    project_id: str
    model: str
    purpose: str
    success: bool
    http_status: int | None
    error_class: str | None
    error_category: str | None
    provider_code: str | None
    provider_message: str | None
    reached_provider: bool | None
    input_tokens: int | None
    output_tokens: int | None
    request_id: str | None
    latency_ms: int | None


class UsageReportRead(BaseModel):
    since: datetime
    timezone: str
    daily: list[DailyUsageRead]
    by_model: list[ModelUsageRead]
    by_project: list[ProjectUsageRead]
    recent_calls: list[RecentProviderCallRead]


class AlertRead(BaseModel):
    severity: Literal["critical", "warning", "info"]
    kind: str
    project_id: str | None
    message: str
