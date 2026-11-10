"""Platform-wide aggregates for the owner dashboard.

Two sources, kept deliberately separate:

* workspace and class-allocation counts are PostgreSQL aggregates over active,
  non-demo workspaces.  ``classes.tenant_id`` is the allocation: a class belongs
  to exactly one workspace, and classes carry no separate release state, so an
  active allocation is a class in an active workspace;
* teacher and assistant counts come from Supabase Auth, because a platform role
  lives in ``app_metadata.aetrix_role`` and is not duplicated in Aetrix's
  membership rows.  One identity is counted once, and only when it is ACTIVE —
  suspended and unconfirmed accounts are not teaching anyone.

The identity census is cached in-process for a short TTL: reading every account
pages the Supabase admin API, which a dashboard refresh must not do each time.
Only aggregates leave this module; individual accounts never do.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import PlatformAdminSettings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import Principal
from ..db.models import ClassroomAllocation, Tenant
from ..schemas.platform_overview import (
    AccountCensusRead,
    OverviewMetricRead,
    PlatformOverviewRead,
)
from .platform_accounts import (
    account_role,
    account_status,
    ensure_platform_admin,
    fetch_all_accounts,
)

ROLE_SUPERVISOR = "supervisor"
ROLE_ASSISTANT = "assistant"

WRITE_WORKSPACES = "PostgreSQL · tenants"
WRITE_CLASSES = "PostgreSQL · classroom_allocations"
WRITE_IDENTITIES = "Supabase Auth · app_metadata.aetrix_role"

DEFINITIONS: dict[str, str] = {
    "teacher_workspaces": (
        "Active, non-demo workspaces. A suspended workspace and the demo workspace "
        "are not counted."
    ),
    "teachers": (
        "Distinct platform accounts whose role is supervisor (shown as Teacher in "
        "account management) and whose account is ACTIVE. Suspended, unconfirmed "
        "and workspace-less identities are not counted; each identity counts once, "
        "however many memberships it holds."
    ),
    "assistant_accounts": (
        "Distinct platform accounts whose role is assistant and whose account is "
        "ACTIVE. Teachers, viewers and platform roles are excluded, as are "
        "suspended and unconfirmed identities."
    ),
    "active_class_allocations": (
        "Rows in classroom_allocations with status ACTIVE whose workspace is "
        "active and non-demo. A released row is history and is not counted, and "
        "an allocation to a suspended workspace is excluded."
    ),
}

_CACHE: dict[str, tuple[datetime, dict[str, int], int, datetime]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class RoleCensus:
    counts: Mapping[str, int]
    active_total: int
    captured_at: datetime
    cached: bool


def reset_census_cache() -> None:
    """Test helper: forget the in-process identity census."""

    with _CACHE_LOCK:
        _CACHE.clear()


def active_role_census(
    settings: PlatformAdminSettings,
    *,
    refresh: bool = False,
    client_factory: Callable[[], Any] | None = None,
) -> RoleCensus:
    """Count active teachers and assistants from Supabase Auth.

    Raises ``ADMIN_NOT_CONFIGURED`` when no service-role credential is present
    and ``ADMIN_UPSTREAM_ERROR`` when Supabase refuses the read; the caller
    reports those as unavailable metrics.
    """

    key = (settings.supabase_url or "").rstrip("/")
    now = utcnow()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and not refresh and cached[0] > now:
            _expires, counts, total, captured = cached
            return RoleCensus(dict(counts), total, captured, True)

    users, _ = fetch_all_accounts(settings, client_factory=client_factory)
    counts = {ROLE_SUPERVISOR: 0, ROLE_ASSISTANT: 0}
    seen: set[str] = set()
    active_total = 0
    for user in users:
        account_id = str(user.get("id") or "")
        if not account_id or account_id in seen:
            continue
        seen.add(account_id)
        if account_status(user) != "ACTIVE":
            continue
        active_total += 1
        role = account_role(user.get("app_metadata"))
        if role in counts:
            counts[role] += 1

    captured_at = utcnow()
    if settings.census_ttl_seconds > 0:
        with _CACHE_LOCK:
            _CACHE[key] = (
                captured_at + timedelta(seconds=settings.census_ttl_seconds),
                dict(counts),
                active_total,
                captured_at,
            )
    return RoleCensus(counts, active_total, captured_at, False)


CensusLoader = Callable[..., RoleCensus]


class PlatformOverviewService:
    def __init__(
        self,
        session: Session,
        settings: PlatformAdminSettings,
        *,
        census_loader: CensusLoader = active_role_census,
    ) -> None:
        self.session = session
        self.settings = settings
        self._census_loader = census_loader

    def _count(self, statement: Any) -> int:
        return int(self.session.scalar(statement) or 0)

    def _workspace_counts(self) -> tuple[int, int]:
        live_workspaces = (
            Tenant.is_active.is_(True),
            Tenant.is_demo.is_(False),
        )
        workspaces = self._count(
            select(func.count()).select_from(Tenant).where(*live_workspaces)
        )
        allocations = self._count(
            select(func.count(ClassroomAllocation.id))
            .join(Tenant, ClassroomAllocation.workspace_id == Tenant.id)
            .where(
                *live_workspaces,
                ClassroomAllocation.status == "ACTIVE",
            )
        )
        return workspaces, allocations

    @staticmethod
    def _metric(
        key: str,
        label: str,
        value: int | None,
        definition: str,
        source: str,
        reason: str | None = None,
    ) -> OverviewMetricRead:
        if value is None:
            state = "unavailable"
        elif value == 0:
            state = "no_records"
        else:
            state = "available"
        return OverviewMetricRead(
            key=key,  # type: ignore[arg-type]
            label=label,
            value=value,
            state=state,
            definition=definition,
            source=source,
            reason=reason,
        )

    def overview(
        self, principal: Principal, *, refresh: bool = False
    ) -> PlatformOverviewRead:
        ensure_platform_admin(principal)
        workspaces, allocations = self._workspace_counts()

        try:
            census = self._census_loader(self.settings, refresh=refresh)
            census_read = AccountCensusRead(
                available=True,
                captured_at=census.captured_at,
                cached=census.cached,
                active_accounts=census.active_total,
            )
            teacher_value: int | None = int(
                census.counts.get(ROLE_SUPERVISOR, 0)
            )
            assistant_value: int | None = int(
                census.counts.get(ROLE_ASSISTANT, 0)
            )
        except AppError as error:
            if error.code not in {
                ErrorCode.ADMIN_NOT_CONFIGURED,
                ErrorCode.ADMIN_UPSTREAM_ERROR,
            }:
                raise
            census_read = AccountCensusRead(
                available=False,
                reason=error.message,
            )
            teacher_value = None
            assistant_value = None

        metrics = [
            self._metric(
                "teacher_workspaces",
                "Teacher workspaces",
                workspaces,
                DEFINITIONS["teacher_workspaces"],
                WRITE_WORKSPACES,
            ),
            self._metric(
                "teachers",
                "Teachers",
                teacher_value,
                DEFINITIONS["teachers"],
                WRITE_IDENTITIES,
                census_read.reason if teacher_value is None else None,
            ),
            self._metric(
                "assistant_accounts",
                "Assistant accounts",
                assistant_value,
                DEFINITIONS["assistant_accounts"],
                WRITE_IDENTITIES,
                census_read.reason if assistant_value is None else None,
            ),
            self._metric(
                "active_class_allocations",
                "Active class allocations",
                allocations,
                DEFINITIONS["active_class_allocations"],
                WRITE_CLASSES,
            ),
        ]
        return PlatformOverviewRead(
            generated_at=utcnow(),
            metrics=metrics,
            account_census=census_read,
        )
