"""Contracts for contributed Gemini keys.

No model in this module can carry key material: contributors and administrators
see a fingerprint, a status and a usage count, never a secret.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ContributorStatus = Literal["ACTIVE", "SUSPENDED", "WITHDRAWN"]
Confidence = Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]


class ContributorRead(BaseModel):
    id: UUID
    user_id: UUID | None
    display_name: str
    contact_email: str | None
    status: ContributorStatus
    consent_version: str
    consent_at: datetime
    consent_reference: str | None
    status_reason: str | None
    suspended_at: datetime | None
    withdrawn_at: datetime | None
    created_at: datetime


class ContributionUsageRead(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    failures: int
    quota_failures: int
    last_success_at: datetime | None


class ContributorRowRead(BaseModel):
    contributor: ContributorRead
    keys_total: int
    keys_eligible: int
    keys_revoked: int
    projects: list[str]
    window: ContributionUsageRead
    today: ContributionUsageRead


class CapacityProjectRead(BaseModel):
    project_id: str
    contributors: int
    keys: int
    requests_per_minute_remaining: int | None
    requests_per_day_remaining: int | None
    confidence: Confidence
    cooldown_until: datetime | None


class CapacityTotalsRead(BaseModel):
    projects: int
    requests_per_minute_remaining: int | None
    requests_per_day_remaining: int | None
    windows_measured: int
    windows_unknown: int
    confidence: Confidence


class CapacityModelRead(BaseModel):
    model: str
    projects: list[CapacityProjectRead]
    totals: CapacityTotalsRead


class CapacityRead(BaseModel):
    models: list[CapacityModelRead]
    note: str


class ContributionAggregateRead(BaseModel):
    contributors_total: int
    contributors_by_status: dict[str, int]
    keys_contributed: int
    keys_eligible: int
    keys_revoked: int
    platform_keys: int
    orphaned_contributor_keys: int
    projects: int
    shared_projects: int
    requests_in_window: int
    requests_today: int
    input_tokens_in_window: int
    output_tokens_in_window: int
    failures_in_window: int


class ContributionSummaryRead(BaseModel):
    observed_at: datetime
    window_started_at: datetime
    day_started_at: datetime
    aggregate: ContributionAggregateRead
    contributors: list[ContributorRowRead]
    capacity: CapacityRead


class ContributorCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    user_id: UUID | None = None
    #: Consent is mandatory: a contribution without a recorded agreement is not
    #: something the platform may use.
    consent_version: str = Field(min_length=1, max_length=40)
    consent_reference: str | None = Field(default=None, max_length=200)


class ContributorKeyCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=8, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    model_access: list[str] = Field(default_factory=list)
    tier: Literal["FREE", "PAID", "UNKNOWN"] = "UNKNOWN"
    auth_type: Literal["api_key", "oauth"] = "api_key"


class MyKeyCreate(ContributorKeyCreate):
    """First registration doubles as the consent record."""

    display_name: str = Field(min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    consent_version: str = Field(min_length=1, max_length=40)
    consent_reference: str | None = Field(default=None, max_length=200)


class StatusReasonRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class WithdrawalRead(BaseModel):
    contributor_id: UUID
    status: ContributorStatus
    keys_revoked: int


class MyContributionKeyRead(BaseModel):
    id: UUID
    project_id: str
    account_label: str
    key_fingerprint: str
    tier: str
    health: str
    model_access: list[str]
    revoked_at: datetime | None
    revoked_reason: str | None
    last_validated_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    created_at: datetime


class MyContributionRead(BaseModel):
    contributor: ContributorRead
    keys: list[MyContributionKeyRead]
    window: ContributionUsageRead
    today: ContributionUsageRead
