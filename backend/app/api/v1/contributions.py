"""A contributor's own record.

The platform decides who may administer the fleet; this router gives the person
who lent a key the one power that is theirs: taking it back.  It resolves the
contributor from the verified principal, never from a body or query parameter,
so one contributor cannot act on another's record.

Registering a key here doubles as the consent record: the agreement version is
required before the secret is stored.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from pydantic import SecretStr
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.models import ProviderContributor
from ...db.repositories import AuditRepository, ContributorRepository, CredentialRepository
from ...db.session import get_db_session
from ...schemas.contributions import (
    ContributionUsageRead,
    ContributorRead,
    MyContributionKeyRead,
    MyContributionRead,
    MyKeyCreate,
    StatusReasonRequest,
    WithdrawalRead,
)
from ...services.contributors import (
    contributor_keys,
    contributor_usage,
    ensure_contributor_for_user,
    register_key,
    revoke_credential,
    withdraw_contributor,
)
from ..deps import get_principal

router = APIRouter(prefix="/contributions", tags=["contributions"])


def _mine(session: Session, principal: Principal) -> ProviderContributor:
    contributor = ContributorRepository(session).get_for_user(principal.user_id)
    if contributor is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "This account has not contributed any keys.",
        )
    return contributor


def _key_read(credential: object) -> MyContributionKeyRead:
    return MyContributionKeyRead.model_validate(credential, from_attributes=True)


def _payload(
    session: Session,
    settings: Settings,
    contributor: ProviderContributor,
    principal: Principal,
    *,
    audit_action: str | None = None,
    audit_detail: dict[str, object] | None = None,
) -> MyContributionRead:
    window, today = contributor_usage(session, settings, contributor.id)
    if audit_action:
        AuditRepository(session).add(
            tenant_id=principal.tenant_id,
            actor_type="USER",
            actor_id=str(principal.user_id),
            action=audit_action,
            entity_type="provider_contributor",
            entity_id=str(contributor.id),
            detail=audit_detail or {},
        )
        session.commit()
    return MyContributionRead(
        contributor=ContributorRead.model_validate(contributor, from_attributes=True),
        keys=[_key_read(key) for key in contributor_keys(session, contributor)],
        window=ContributionUsageRead(**window),
        today=ContributionUsageRead(**today),
    )


@router.get("/me", response_model=MyContributionRead)
def read_my_contribution(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MyContributionRead:
    return _payload(session, settings, _mine(session, principal), principal)


@router.post(
    "/me/keys", response_model=MyContributionRead, status_code=status.HTTP_201_CREATED
)
def register_my_key(
    payload: MyKeyCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> MyContributionRead:
    contributor, created = ensure_contributor_for_user(
        session,
        user_id=principal.user_id,
        display_name=payload.display_name,
        contact_email=payload.contact_email,
        consent_version=payload.consent_version,
        consent_reference=payload.consent_reference,
    )
    credential = register_key(
        session,
        settings,
        contributor,
        project_id=payload.project_id,
        api_key=SecretStr(payload.api_key),
        label=payload.label,
        model_access=payload.model_access,
        tier=payload.tier,
        auth_type=payload.auth_type,
    )
    return _payload(
        session,
        settings,
        contributor,
        principal,
        audit_action="provider.key.contributed",
        audit_detail={
            "contributor_id": str(contributor.id),
            "contributor_created": created,
            "credential_id": str(credential.id),
            "project_id": credential.project_id,
            "fingerprint": credential.key_fingerprint,
        },
    )


@router.delete("/me/keys/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_key(
    credential_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    contributor = _mine(session, principal)
    credential = CredentialRepository(session).get(credential_id)
    # Another contributor's key must look exactly like a missing one.
    if credential is None or credential.contributor_id != contributor.id:
        raise AppError(ErrorCode.NOT_FOUND, "No such contributed key.")

    outcome = revoke_credential(
        session, settings, credential, reason="Withdrawn by its contributor."
    )
    AuditRepository(session).add(
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="provider.key.revoked",
        entity_type="provider_credential",
        entity_id=str(credential.id),
        detail={
            "contributor_id": str(contributor.id),
            "project_id": credential.project_id,
            "outcome": outcome,
        },
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/withdraw", response_model=WithdrawalRead)
def withdraw_my_contribution(
    payload: StatusReasonRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> WithdrawalRead:
    contributor = _mine(session, principal)
    revoked = withdraw_contributor(session, settings, contributor, reason=payload.reason)
    AuditRepository(session).add(
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action="provider.contributor.withdrawn",
        entity_type="provider_contributor",
        entity_id=str(contributor.id),
        detail={"keys_revoked": revoked, "reason": contributor.status_reason},
    )
    session.commit()
    return WithdrawalRead(
        contributor_id=contributor.id,
        status=contributor.status,
        keys_revoked=revoked,
    )
