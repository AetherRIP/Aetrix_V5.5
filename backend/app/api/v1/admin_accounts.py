"""Platform account administration endpoints.

Every route is a platform capability: the gate is the verified
``app_metadata.aetrix_role`` claim, resolved on the server, never a header, a
query parameter or the browser's opinion.  A workspace administrator gets 403
here — their authority stops at their own tenant.

If the Supabase administrative credential is absent, the read routes answer
``503 ADMIN_NOT_CONFIGURED`` with the reason.  They never fall back to workspace
members, and they never invent rows.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.admin_accounts import (
    AccountActionRead,
    AccountCapabilityRead,
    AccountDeletion,
    AccountPage,
    AccountQuery,
    AccountRoleUpdate,
    AccountStatusUpdate,
    PlatformAccountDetail,
    PlatformAccountRole,
    PlatformAccountStatus,
)
from ...services.platform_accounts import (
    PlatformAccountService,
    ensure_platform_admin,
)
from ..deps import get_principal

router = APIRouter(prefix="/admin/accounts", tags=["platform accounts"])


def get_platform_accounts(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> PlatformAccountService:
    return PlatformAccountService(session, settings.platform_admin)


def require_platform_admin(
    principal: Principal = Depends(get_principal),
) -> Principal:
    ensure_platform_admin(principal)
    return principal


@router.get("/capability", response_model=AccountCapabilityRead)
def capability(
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> AccountCapabilityRead:
    return service.capability()


@router.get("", response_model=AccountPage)
def list_accounts(
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
    q: Annotated[str | None, Query(max_length=200)] = None,
    role: PlatformAccountRole | None = None,
    status: PlatformAccountStatus | None = None,
    joined: Literal["yes", "no"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AccountPage:
    return service.list_accounts(
        principal,
        AccountQuery(
            q=q,
            role=role,
            status=status,
            joined=joined,
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/{account_id}", response_model=PlatformAccountDetail)
def get_account(
    account_id: str,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> PlatformAccountDetail:
    if not account_id.strip():
        raise AppError(ErrorCode.NOT_FOUND, "That account does not exist.")
    return service.get_account(principal, account_id.strip())


@router.patch("/{account_id}/role", response_model=PlatformAccountDetail)
def update_role(
    account_id: str,
    payload: AccountRoleUpdate,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> PlatformAccountDetail:
    return service.update_role(principal, account_id.strip(), payload)


@router.patch("/{account_id}/status", response_model=PlatformAccountDetail)
def update_status(
    account_id: str,
    payload: AccountStatusUpdate,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> PlatformAccountDetail:
    return service.set_status(principal, account_id.strip(), payload)


@router.post("/{account_id}/recovery", response_model=AccountActionRead)
def request_recovery(
    account_id: str,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> AccountActionRead:
    return service.request_recovery(principal, account_id.strip())


@router.post("/{account_id}/invitation", response_model=AccountActionRead)
def resend_invitation(
    account_id: str,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> AccountActionRead:
    return service.resend_invitation(principal, account_id.strip())


@router.post("/{account_id}/revoke-sessions", response_model=AccountActionRead)
def revoke_sessions(
    account_id: str,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> AccountActionRead:
    return service.revoke_sessions(principal, account_id.strip())


@router.delete("/{account_id}", response_model=AccountActionRead)
def delete_account(
    account_id: str,
    payload: AccountDeletion,
    principal: Principal = Depends(require_platform_admin),
    service: PlatformAccountService = Depends(get_platform_accounts),
) -> AccountActionRead:
    return service.delete_account(principal, account_id.strip(), payload)
