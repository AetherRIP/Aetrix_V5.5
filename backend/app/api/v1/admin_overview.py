"""Platform-wide overview aggregates.

The route is authorized from the verified platform claim, like account
management.  It returns counts only: no individual account, workspace or class
is exposed.  Workspace figures remain available even when the Supabase
administrative credential is absent; the teacher and assistant metrics then
report themselves unavailable instead of showing a fabricated zero.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.platform_overview import PlatformOverviewRead
from ...services.platform_overview import PlatformOverviewService
from .admin_accounts import require_platform_admin

router = APIRouter(prefix="/admin/overview", tags=["platform overview"])


def get_platform_overview(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> PlatformOverviewService:
    return PlatformOverviewService(session, settings.platform_admin)


@router.get("", response_model=PlatformOverviewRead)
def overview(
    refresh: bool = False,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformOverviewService = Depends(get_platform_overview),
) -> PlatformOverviewRead:
    return service.overview(principal, refresh=refresh)
