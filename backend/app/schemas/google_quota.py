"""Contracts for the read-only Google Cloud quota dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Verification = Literal[
    "VERIFIED",
    "NOT_FOUND",
    "PERMISSION_DENIED",
    "ERROR",
    "UNVERIFIABLE",
    "UNVERIFIED",
    "OPERATOR_DECLARED",
]


class GoogleQuotaValueRead(BaseModel):
    quota_id: str
    metric: str
    service: str
    metric_display_name: str | None
    quota_display_name: str | None
    unit: str | None
    refresh_interval: str | None
    reset_time: str | None
    container_type: str | None
    is_precise: bool | None
    dimensions: dict[str, str]
    limit: float | None
    is_unlimited: bool
    limit_source: Literal["CLOUD_QUOTAS", "CLOUD_MONITORING", "UNAVAILABLE"]
    usage: float | None
    usage_source: Literal["CLOUD_MONITORING", "NOT_EXPOSED"]
    usage_metric: str | None
    usage_observed_at: datetime | None
    exceeded: float | None
    observed_at: datetime


class GoogleQuotaRunRead(BaseModel):
    id: UUID
    trigger: Literal["MANUAL", "SCHEDULED"]
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    started_at: datetime
    finished_at: datetime | None
    quota_infos: int
    snapshots_written: int
    api_calls: int
    error_code: str | None
    error_message: str | None


class GoogleProjectModelHealthRead(BaseModel):
    model: str
    requests: int
    successes: int
    failures: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_http_status: int | None
    #: AVAILABLE needs an observed success; FAILING only failures; UNKNOWN no
    #: traffic.  This is Aetrix telemetry, never a Google quota statement.
    state: Literal["AVAILABLE", "FAILING", "UNKNOWN"]


class GoogleProjectSignalsRead(BaseModel):
    counts: dict[str, int]
    models: list[GoogleProjectModelHealthRead]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    average_latency_ms: float | None
    confidence: Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]


class GoogleProjectHealthRead(BaseModel):
    state: Literal[
        "HEALTHY",
        "DEGRADED",
        "OUTAGE",
        "AUTH_FAILURE",
        "PERMISSION_FAILURE",
        "RATE_LIMITED",
        "QUOTA_EXHAUSTED",
        "UNKNOWN",
    ]
    state_confidence: Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]
    reason: str
    quota_status: Literal["KNOWN", "WARNING", "EXHAUSTED", "UNKNOWN"]
    quota_confidence: Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]
    quota_reason: str
    last_sample_at: datetime | None
    sample_stale: bool
    last_attempt_at: datetime | None
    last_status: str | None
    last_error_code: str | None
    recovered: bool
    signals: GoogleProjectSignalsRead


class GoogleProjectAlertRead(BaseModel):
    id: str
    kind: str
    severity: Literal["critical", "warning", "info"]
    project_id: str | None
    title: str
    detail: str
    since: datetime | None


class GoogleMonitorRead(BaseModel):
    state: Literal["OK", "STALE", "UNAVAILABLE", "UNKNOWN"]
    last_cycle_at: datetime | None
    age_seconds: int | None
    interval_seconds: int
    grace_seconds: int
    detail: str
    last_cycle: dict[str, object] = Field(default_factory=dict)


class GoogleQuotaProjectRead(BaseModel):
    project_id: str
    verification: Verification
    verified: bool
    project_number: str | None
    display_name: str | None
    lifecycle_state: str | None
    last_attempt_at: datetime | None
    last_verified_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    stale: bool
    quota_count: int
    usage_observed: int
    quotas: list[GoogleQuotaValueRead]
    runs: list[GoogleQuotaRunRead]
    health: GoogleProjectHealthRead


class GoogleQuotaFleetRead(BaseModel):
    configured: bool
    credential_source: str
    scheduled_sync_enabled: bool
    sync_interval_seconds: int
    stale_after_seconds: int
    declared_projects: int
    verified_projects: int
    healthy_projects: int
    degraded_projects: int
    unknown_projects: int
    quota_warnings: int
    quotas_total: int
    usage_observed: int
    stale_projects: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_failure_message: str | None


class GoogleApiRequirementRead(BaseModel):
    service: str
    name: str
    permission: str
    used_for: str
    enabled: bool | None


class GoogleAIStudioRead(BaseModel):
    available: bool
    reason: str
    source: str


class GoogleQuotaCoverageRead(BaseModel):
    supported: list[str]
    unavailable: list[str]


class GoogleQuotaSyncResultRead(BaseModel):
    project_id: str
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    run_id: UUID | None
    verification: Verification
    quota_infos: int
    snapshots: int
    error_code: str | None
    message: str | None


class GoogleQuotaReportRead(BaseModel):
    observed_at: datetime
    service: str
    fleet: GoogleQuotaFleetRead
    projects: list[GoogleQuotaProjectRead]
    monitor: GoogleMonitorRead
    alerts: list[GoogleProjectAlertRead]
    apis: list[GoogleApiRequirementRead]
    ai_studio: GoogleAIStudioRead
    coverage: GoogleQuotaCoverageRead
    note: str
    sync_results: list[GoogleQuotaSyncResultRead] = Field(default_factory=list)


class GoogleQuotaSyncRequest(BaseModel):
    #: One project, or every declared project when omitted.
    project_id: str | None = Field(default=None, min_length=1, max_length=100)
