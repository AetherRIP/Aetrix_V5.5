"""Identity, membership and invitation endpoints.

``/me`` is the single source of truth the interface uses for the signed-in
user's workspace role and capabilities.  The Supabase metadata is a routing hint;
this endpoint is the authorization answer.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.errors import AppError, ErrorCode
from ...core.security import (
    Principal,
    extract_display_name,
    extract_subject,
)
from ...db.session import get_db_session
from ...schemas.identity import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberRead,
    MemberRoleUpdate,
    MeRead,
)
from ...services.identity import IdentityService
from ..deps import get_claims, get_principal

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeRead)
def get_me(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MeRead:
    return IdentityService(session).me(principal)


@router.post(
    "/invitations/accept", response_model=MeRead, status_code=status.HTTP_201_CREATED
)
def accept_invitation(
    payload: InvitationAccept,
    claims: dict[str, Any] = Depends(get_claims),
    session: Session = Depends(get_db_session),
) -> MeRead:
    subject = extract_subject(claims)
    service = IdentityService(session)
    user = service.provision_with_code(
        subject=subject,
        code=payload.code,
        display_name=extract_display_name(claims),
    )
    principal = Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        subject=user.subject,
        role=user.role,
    )
    return service.me(principal)


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberRead])
def list_members(
    workspace_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[MemberRead]:
    if workspace_id != principal.tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
    return [
        MemberRead.model_validate(member)
        for member in IdentityService(session).list_members(principal)
    ]


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}", response_model=MemberRead
)
def update_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRoleUpdate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MemberRead:
    if workspace_id != principal.tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
    member = IdentityService(session).update_member_role(principal, user_id, payload)
    return MemberRead.model_validate(member)


@router.get("/invitations", response_model=list[InvitationRead])
def list_invitations(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[InvitationRead]:
    return [
        InvitationRead.model_validate(row)
        for row in IdentityService(session).list_invitations(principal)
    ]


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    workspace_id: uuid.UUID,
    payload: InvitationCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> InvitationCreated:
    if workspace_id != principal.tenant_id:
        raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
    invitation, code = IdentityService(session).create_invitation(principal, payload)
    # The acceptance code is generated once and never stored, so it cannot come
    # from the ORM row; the response is the only place it ever appears.
    read = InvitationRead.model_validate(invitation)
    return InvitationCreated(**read.model_dump(), acceptance_code=code)


@router.post("/invitations/{invitation_id}/revoke", response_model=InvitationRead)
def revoke_invitation(
    invitation_id: uuid.UUID,
    reason: str | None = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> InvitationRead:
    invitation = IdentityService(session).revoke_invitation(
        principal, invitation_id, reason
    )
    return InvitationRead.model_validate(invitation)
