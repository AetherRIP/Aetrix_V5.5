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
    observed_at: datetime
    cooldown_until: datetime | None
    exhausted: bool
    notes: list[str]


class ProjectRead(BaseModel):
    project_id: str
    keys: int
    healthy: int
    disabled: int
    invalid: int
    cooldown_until: datetime | None
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
    model_access: list[str]
    cooldown_until: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_failure_status: int | None
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
    credential_id: UUID
    health: str
    valid: bool
    detail: str | None


class EnabledRequest(BaseModel):
    enabled: bool


class FleetOverviewRead(BaseModel):
    keys_total: int
    keys_by_health: dict[str, int]
    projects: int
    requests_today: int
    input_tokens_today: int
    output_tokens_today: int
    failures_today: int
    error_rate_today: float | None
    observed_at: datetime
    day_started_at: datetime
    reset_at: datetime
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


class UsageReportRead(BaseModel):
    since: datetime
    daily: list[DailyUsageRead]
    by_model: list[ModelUsageRead]
    by_project: list[ProjectUsageRead]


class AlertRead(BaseModel):
    severity: Literal["critical", "warning", "info"]
    kind: str
    project_id: str | None
    message: str
