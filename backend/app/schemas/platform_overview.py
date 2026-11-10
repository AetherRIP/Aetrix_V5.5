"""Contracts for the platform-wide overview.

Each metric carries its own state, definition and source.  A value of ``None``
means the metric could not be read; ``0`` is a real, measured zero.  The
interface must render the two differently, so they are different states here
rather than one nullable number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MetricState = Literal["available", "no_records", "unavailable"]


class OverviewMetricRead(BaseModel):
    key: Literal[
        "teacher_workspaces",
        "teachers",
        "assistant_accounts",
        "active_class_allocations",
    ]
    label: str
    value: int | None
    state: MetricState
    definition: str
    source: str
    reason: str | None = None


class AccountCensusRead(BaseModel):
    """The Supabase identity census behind the teacher and assistant counts."""

    available: bool
    captured_at: datetime | None = None
    cached: bool = False
    active_accounts: int | None = None
    reason: str | None = None


class PlatformOverviewRead(BaseModel):
    generated_at: datetime
    metrics: list[OverviewMetricRead] = Field(default_factory=list)
    account_census: AccountCensusRead
