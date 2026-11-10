"""Platform administration of contributed keys.

These routes manage *relationships*: who contributes, which keys belong to them,
and whether that contribution may still be used.  They never return key material
and they never bypass the scheduler's eligibility rules — suspension and
withdrawal are the only ways to remove a contributor's keys from rotation.

Administrator-only.  A contributor manages their own record through
``app.api.v1.contributions``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import SecretStr
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.repositories import AuditRepository, CredentialRepository
from ...db.session import get_db_session
from ...schemas.contributions import (
    ContributionSummaryRead,
    ContributionUsageRead,
    ContributorCreate,
    ContributorKeyCreate,
    ContributorRead,
    ContributorRowRead,
    StatusReasonRequest,
    WithdrawalRead,
)
from ...schemas.provider_admin import KeyRead
from ...services.contributors import (
    contribution_summary,
    contributor_detail,
    create_contributor,
    get_contributor,
    register_key,
    reinstate_contributor,
    revoke_credential,
    suspend_contributor,
    withdraw_contributor,
)
from .admin_providers import key_read, require_fleet_admin

router = APIRouter(prefix="/admin/providers/contributions", tags=["contributions"])


def _contributor_read(row: object) -> ContributorRead:
    return ContributorRead.model_validate(row, from_attributes=True)


def _row_read(row: dict[str, object]) -> ContributorRowRead:
    contributor = row["contributor"]
    return ContributorRowRead(
        contributor=_contributor_read(contributor),
        keys_total=int(row["keys_total"]),
        keys_eligible=int(row["keys_eligible"]),
        keys_revoked=int(row["keys_revoked"]),
        projects=list(row["projects"]),
        window=ContributionUsageRead(**row["window"]),
        today=ContributionUsageRead(**row["today"]),
    )


def _audit(
    session: Session,
    principal: Principal,
    *,
    action: str,
    entity_id: str,
    detail: dict[str, object],
) -> None:
    AuditRepository(session).add(
        tenant_id=principal.tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action=action,
        entity_type="provider_contributor",
        entity_id=entity_id,
        detail=detail,
    )
    session.commit()


def _credential_or_404(
    session: Session, contributor_id: uuid.UUID, credential_id: uuid.UUID
):
    credential = CredentialRepository(session).get(credential_id)
    # A key of another contributor is indistinguishable from a missing one.
    if credential is None or credential.contributor_id != contributor_id:
        raise AppError(ErrorCode.NOT_FOUND, "No such contributed key.")
    return credential


@router.get("", response_model=ContributionSummaryRead)
def summary(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    window_days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> ContributionSummaryRead:
    payload = contribution_summary(session, settings, window_days=window_days)
    return ContributionSummaryRead(
        **{
            **payload,
            "contributors": [_row_read(row) for row in payload["contributors"]],
        }
    )


@router.post("", response_model=ContributorRead, status_code=status.HTTP_201_CREATED)
def add_contributor(
    payload: ContributorCreate,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
) -> ContributorRead:
    contributor = create_contributor(
        session,
        display_name=payload.display_name,
        contact_email=payload.contact_email,
        user_id=payload.user_id,
        consent_version=payload.consent_version,
        consent_reference=payload.consent_reference,
    )
    _audit(
        session,
        principal,
        action="provider.contributor.created",
        entity_id=str(contributor.id),
        detail={
            "consent_version": contributor.consent_version,
            "linked_user": str(contributor.user_id) if contributor.user_id else None,
        },
    )
    return _contributor_read(contributor)


@router.get("/{contributor_id}", response_model=ContributorRowRead)
def read_contributor(
    contributor_id: uuid.UUID,
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ContributorRowRead:
    return _row_read(contributor_detail(session, settings, contributor_id))


@router.post(
    "/{contributor_id}/keys",
    response_model=KeyRead,
    status_code=status.HTTP_201_CREATED,
)
def add_contributed_key(
    contributor_id: uuid.UUID,
    payload: ContributorKeyCreate,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> KeyRead:
    contributor = get_contributor(session, contributor_id)
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
    _audit(
        session,
        principal,
        action="provider.key.contributed",
        entity_id=str(credential.id),
        detail={
            "contributor_id": str(contributor.id),
            "project_id": credential.project_id,
            "fingerprint": credential.key_fingerprint,
        },
    )
    return key_read(credential, None)


@router.delete(
    "/{contributor_id}/keys/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_contributed_key(
    contributor_id: uuid.UUID,
    credential_id: uuid.UUID,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    credential = _credential_or_404(session, contributor_id, credential_id)
    outcome = revoke_credential(
        session, settings, credential, reason="Revoked by a platform administrator."
    )
    _audit(
        session,
        principal,
        action="provider.key.revoked",
        entity_id=str(credential.id),
        detail={
            "contributor_id": str(contributor_id),
            "project_id": credential.project_id,
            "outcome": outcome,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{contributor_id}/suspend", response_model=ContributorRead)
def suspend(
    contributor_id: uuid.UUID,
    payload: StatusReasonRequest,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
) -> ContributorRead:
    contributor = suspend_contributor(
        session, get_contributor(session, contributor_id), reason=payload.reason
    )
    _audit(
        session,
        principal,
        action="provider.contributor.suspended",
        entity_id=str(contributor.id),
        detail={"reason": contributor.status_reason},
    )
    return _contributor_read(contributor)


@router.post("/{contributor_id}/reinstate", response_model=ContributorRead)
def reinstate(
    contributor_id: uuid.UUID,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
) -> ContributorRead:
    contributor = reinstate_contributor(session, get_contributor(session, contributor_id))
    _audit(
        session,
        principal,
        action="provider.contributor.reinstated",
        entity_id=str(contributor.id),
        detail={},
    )
    return _contributor_read(contributor)


@router.post("/{contributor_id}/withdraw", response_model=WithdrawalRead)
def withdraw(
    contributor_id: uuid.UUID,
    payload: StatusReasonRequest,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> WithdrawalRead:
    contributor = get_contributor(session, contributor_id)
    revoked = withdraw_contributor(session, settings, contributor, reason=payload.reason)
    _audit(
        session,
        principal,
        action="provider.contributor.withdrawn",
        entity_id=str(contributor.id),
        detail={"keys_revoked": revoked, "reason": contributor.status_reason},
    )
    return WithdrawalRead(
        contributor_id=contributor.id,
        status=contributor.status,
        keys_revoked=revoked,
    )
