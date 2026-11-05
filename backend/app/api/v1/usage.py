"""Usage and provider health.

Usage is read from the append-only provider ledger.  A tenant with no usage sees
zeros, not an error and not invented numbers.  Credential health exposes only
the non-secret fingerprint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.security import Principal
from ...db.repositories import CredentialRepository, UsageRepository
from ...db.session import get_db_session
from ...schemas.api import ProviderHealthRead, UsageSummaryRead
from ..deps import get_principal

router = APIRouter(tags=["usage"])


@router.get("/usage", response_model=UsageSummaryRead)
def usage(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> UsageSummaryRead:
    return UsageSummaryRead(**UsageRepository(session).summary(principal.tenant_id))


@router.get("/providers/health", response_model=list[ProviderHealthRead])
def provider_health(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[ProviderHealthRead]:
    credentials = CredentialRepository(session).list_for_tenant(principal.tenant_id)
    return [
        ProviderHealthRead(
            id=credential.id,
            account_label=credential.account_label,
            key_fingerprint=credential.key_fingerprint,
            health=credential.health,
            cooldown_until=credential.cooldown_until,
            last_success_at=credential.last_success_at,
            last_error=credential.last_error,
        )
        for credential in credentials
    ]
