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


class GoogleQuotaFleetRead(BaseModel):
    configured: bool
    credential_source: str
    scheduled_sync_enabled: bool
    sync_interval_seconds: int
    stale_after_seconds: int
    declared_projects: int
    verified_projects: int
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
    apis: list[GoogleApiRequirementRead]
    ai_studio: GoogleAIStudioRead
    coverage: GoogleQuotaCoverageRead
    note: str
    sync_results: list[GoogleQuotaSyncResultRead] = Field(default_factory=list)


class GoogleQuotaSyncRequest(BaseModel):
    #: One project, or every declared project when omitted.
    project_id: str | None = Field(default=None, min_length=1, max_length=100)
