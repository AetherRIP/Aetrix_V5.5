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
    #: Requests in the day window whose consumption Google never confirmed (5xx
    #: or a lost connection).  They count against the per-minute gate but not
    #: the daily allowance, so they are reported beside it rather than folded
    #: into ``requests_per_day.used``.
    unconfirmed_requests: int = 0
    #: Whether the project id is an established Google Cloud project.  It decides
    #: whether Google-level capacity can be stated, not whether keys are leased.
    project_identity: Literal[
        "VERIFIED", "DECLARED", "PROJECT_IDENTITY_UNVERIFIED"
    ] = "PROJECT_IDENTITY_UNVERIFIED"
    #: ``KNOWN`` / ``EXHAUSTED`` / ``UNKNOWN``.  ``UNKNOWN`` whenever no project
    #: is established: this aggregate is Aetrix's record for a label, never
    #: Google's remaining count.
    google_quota_status: Literal["KNOWN", "EXHAUSTED", "UNKNOWN"] = "UNKNOWN"
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
    #: Credential pools under this label.  Each key is one Aetrix pool; the count
    #: is not a count of Google Cloud projects or of Google allowances.
    pools: int = 0
    #: Pools under this label that are enabled and not quarantined.
    routable_keys: int = 0
    identity: str | None = None
    google_quota_status: Literal["KNOWN", "EXHAUSTED", "UNKNOWN"] = "UNKNOWN"
    healthy: int
    unknown: int
    disabled: int
    invalid: int
    cooldown_until: datetime | None
    operational_status: str
    estimates: list[QuotaEstimateRead]


class KeyRead(BaseModel):
    id: UUID
    #: The Aetrix operational pool, ``gemini-key-{id}``.  Not a Google project.
    pool_id: str = ""
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
    #: ``VERIFIED`` (Google Resource Manager), ``DECLARED`` (audited operator
    #: assertion) or ``PROJECT_IDENTITY_UNVERIFIED`` (no identity established, so
    #: Google-level capacity is UNKNOWN; the key remains its own Aetrix pool).
    #: ``OPERATOR_DECLARED`` is the pre-identity spelling kept so an older client
    #: still parses the field.
    project_verification: Literal[
        "VERIFIED",
        "DECLARED",
        "PROJECT_IDENTITY_UNVERIFIED",
        "OPERATOR_DECLARED",
    ]
    project_identity_reason: str | None = None
    #: Whether the administrator's enable switch allows this pool.
    enabled: bool = True
    #: Whether this pool can be leased now: enabled and outside any quarantine.
    routable: bool = False
    #: What Aetrix can say about the Google allowance behind this key.
    google_quota_status: Literal["KNOWN", "EXHAUSTED", "UNKNOWN"] = "UNKNOWN"
    google_quota_note: str | None = None
    quarantined: bool = False
    quarantine_until: datetime | None = None
    quarantine_kind: Literal["QUOTA", "AUTH", "NONE"] = "NONE"
    quarantine_reason: str | None = None
    remaining_today: int | None = None
    remaining_minute: int | None = None
    #: Reservation rows in the pool's windows, separate from validation probes.
    reservations_today: int = 0
    reservations_minute: int = 0
    validations_today: int = 0
    last_quota_exhausted_at: datetime | None = None
    last_quota_reason: str | None = None
    consecutive_failures: int = 0
    #: Environments the caller can act on: pool accounting is never summed as
    #: Google capacity.
    pool_note: str | None = None
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


class ProjectIdentityDeclare(BaseModel):
    """An administrator's explicit assertion of a key's Google Cloud project.

    It is audited and labelled ``DECLARED``; Google verification is a separate,
    stronger state that only Resource Manager can grant.
    """

    project_id: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=200)


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
    #: How much of the fleet may actually be spent, and how many pools exist with
    #: an established Google Cloud project.
    routable_keys: int = 0
    identity_unverified_keys: int = 0
    authorised_projects: int = 0
    #: One Aetrix pool per credential.  ``pools_available`` excludes disabled and
    #: quarantined pools; neither count is a count of Google projects.
    credential_pools: int = 0
    pools_available: int = 0
    pools_quarantined: int = 0
    #: The credential every call is pinned to, or null when the lease chooses.
    pinned_credential_id: UUID | None = None
    pool_note: str | None = None
    #: Served by ``GET /admin/providers/projects`` so the fleet counts do not
    #: wait for per-project quota estimates.  Empty here, never a claim that no
    #: project label exists.
    projects_detail: list[ProjectRead] = Field(default_factory=list)


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
    #: Only the three monitored models appear in this table.
    by_model: list[ModelUsageRead]
    by_project: list[ProjectUsageRead]
    recent_calls: list[RecentProviderCallRead]
    #: Recorded requests for models outside the monitored view, so the filtered
    #: table still reconciles with ``daily``, which is the ledger's real total.
    excluded_requests: int = 0


class AlertRead(BaseModel):
    severity: Literal["critical", "warning", "info"]
    kind: str
    project_id: str | None
    #: The Aetrix pool an alert is about, when it is about one credential.
    pool_id: str | None = None
    message: str
