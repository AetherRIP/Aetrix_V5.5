"""Invitation-only provisioning and workspace membership.

The engine does not create accounts.  Supabase owns authentication; this service
owns the *authorization* record that a verified identity becomes: exactly one
``users`` row per (workspace, subject), created from a deliberate invitation.

Two provisioning paths exist and both resolve the tenant from the invitation —
never from the request body, and never from a token claim that a client could
set:

* a verified email address matching a live invitation, and
* a one-time acceptance code redeemed by an authenticated subject.

Nothing else provisions.  An authenticated stranger receives
``PROVISIONING_REQUIRED`` rather than an implicit membership.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.ids import sha256_hex, utcnow
from ..core.security import Principal
from ..db.models import Invitation, User
from ..db.repositories import InvitationRepository, TenantRepository, UserRepository
from ..schemas.identity import InvitationCreate, MemberRoleUpdate, MeRead

WORKSPACE_ROLES: tuple[str, ...] = ("OWNER", "ADMIN", "TEACHER", "REVIEWER", "VIEWER")

#: The shell's presentation vocabulary.  Derived here, not in the browser, so
#: one role vocabulary governs the API and the interface.
#: Platform ownership must not be presented as the administrator role:
#: ``PLATFORM_OWNER`` is the owner, ``ADMIN`` is the platform administrator, and
#: a workspace ``OWNER`` is a teacher, not a platform owner. The mapping is
#: exhaustive, so no role can silently fall through to a different account type.
UI_ROLE: dict[str, str] = {
    "PLATFORM_OWNER": "owner",
    "ADMIN": "platform_operator",
    "OWNER": "supervisor",
    "TEACHER": "supervisor",
    "REVIEWER": "assistant",
    "VIEWER": "viewer",
}

_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "VIEWER": ("read",),
    "REVIEWER": ("read", "review"),
    "TEACHER": ("read", "manage_exams", "review", "approve"),
    "ADMIN": ("read", "manage_exams", "review", "approve", "manage_members"),
    "OWNER": ("read", "manage_exams", "review", "approve", "manage_members"),
    "PLATFORM_OWNER": (
        "read",
        "manage_exams",
        "review",
        "approve",
        "manage_members",
        "platform_admin",
    ),
}

_MEMBER_MANAGERS = frozenset({"OWNER", "ADMIN", "PLATFORM_OWNER"})

_GRANTS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(WORKSPACE_ROLES),
    "ADMIN": frozenset({"TEACHER", "REVIEWER", "VIEWER"}),
    "PLATFORM_OWNER": frozenset(WORKSPACE_ROLES),
}


@dataclass(frozen=True, slots=True)
class Provisioning:
    user: User
    invitation: Invitation
    method: str


def ensure_member_manager(principal: Principal) -> None:
    if principal.role not in _MEMBER_MANAGERS:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Only a workspace owner or administrator may manage membership.",
        )


def capabilities_for(role: str) -> list[str]:
    return list(_CAPABILITIES.get(role, ("read",)))


class IdentityService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.invitations = InvitationRepository(session)
        self.tenants = TenantRepository(session)
        self.audit = AuditService(session)

    # -- provisioning ----------------------------------------------------
    def provision_from_claims(
        self,
        *,
        subject: str,
        email: str | None,
        email_verified: bool,
        display_name: str | None,
        tenant_hint: uuid.UUID | None,
    ) -> User:
        if not email:
            raise AppError(
                ErrorCode.PROVISIONING_REQUIRED,
                "The token carries no email address, so no invitation can be matched. "
                "Ask a workspace owner for an acceptance code.",
                details={"state": "EMAIL_REQUIRED"},
            )
        if not email_verified:
            raise AppError(
                ErrorCode.PROVISIONING_REQUIRED,
                "This email address is not verified by the identity provider, so an "
                "invitation cannot be matched to it.",
                details={"state": "EMAIL_UNVERIFIED"},
            )

        matches = self.invitations.find_pending_for_email(email, tenant_id=tenant_hint)
        if not matches:
            raise AppError(
                ErrorCode.PROVISIONING_REQUIRED,
                "This account has not been invited to a workspace. "
                "Ask a workspace owner to invite this address, or redeem an acceptance code.",
                details={"state": "INVITATION_REQUIRED"},
            )
        if len(matches) > 1:
            raise AppError(
                ErrorCode.CONFLICT,
                "This address has live invitations to more than one workspace. "
                "Redeem a specific acceptance code to choose one.",
                details={"state": "AMBIGUOUS_INVITATION"},
            )
        return self._provision(
            subject=subject,
            invitation=matches[0],
            email=email,
            display_name=display_name,
            method="verified_email",
        )

    def provision_with_code(
        self, *, subject: str, code: str, display_name: str | None = None
    ) -> User:
        invitation = self.invitations.get_by_token_hash(sha256_hex(code.strip()))
        if invitation is None:
            raise AppError(ErrorCode.NOT_FOUND, "This acceptance code is not valid.")
        if invitation.status == "REVOKED":
            raise AppError(ErrorCode.CONFLICT, "This invitation was revoked.")
        if invitation.status == "ACCEPTED":
            raise AppError(ErrorCode.CONFLICT, "This invitation has already been accepted.")
        if invitation.expires_at <= utcnow():
            raise AppError(ErrorCode.CONFLICT, "This invitation has expired.")
        tenant = self.tenants.get(invitation.tenant_id)
        if tenant is None or not tenant.is_active:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        return self._provision(
            subject=subject,
            invitation=invitation,
            email=invitation.email,
            display_name=display_name,
            method="acceptance_code",
        )

    def _provision(
        self,
        *,
        subject: str,
        invitation: Invitation,
        email: str | None,
        display_name: str | None,
        method: str,
    ) -> User:
        existing = self.users.get_by_subject(invitation.tenant_id, subject)
        if existing is not None:
            return existing

        try:
            user = self.users.create(
                tenant_id=invitation.tenant_id,
                subject=subject,
                role=invitation.role,
                email=(email or invitation.email).lower(),
                display_name=display_name,
            )
            invitation.status = "ACCEPTED"
            invitation.accepted_at = utcnow()
            invitation.accepted_by = user.id
            self.audit.record(
                tenant_id=invitation.tenant_id,
                action="member.provisioned",
                entity_type="user",
                entity_id=user.id,
                actor_type="SYSTEM",
                actor_id=subject,
                detail={
                    "invitation_id": str(invitation.id),
                    "role": invitation.role,
                    "method": method,
                },
            )
            self.session.commit()
            return user
        except IntegrityError:
            # Two concurrent first requests can both find no row.  The unique
            # constraint on (tenant_id, subject) makes one of them lose here,
            # and the loser must read the winner's row rather than adopt a
            # second identity.
            self.session.rollback()
            existing = self.users.get_by_subject(invitation.tenant_id, subject)
            if existing is None:
                raise
            return existing

    # -- identity --------------------------------------------------------
    def me(self, principal: Principal) -> MeRead:
        tenant = self.tenants.get(principal.tenant_id)
        if tenant is None:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        user = self.users.get(principal.tenant_id, principal.user_id)
        if user is None:
            raise AppError(ErrorCode.NOT_FOUND, "Account not found in this workspace.")
        return MeRead(
            user_id=user.id,
            subject=user.subject,
            email=user.email,
            display_name=user.display_name,
            tenant_id=tenant.id,
            workspace_name=tenant.name,
            workspace_slug=tenant.slug,
            role=user.role,
            ui_role=UI_ROLE.get(user.role, "viewer"),
            capabilities=capabilities_for(user.role),
            is_demo=tenant.is_demo,
        )

    # -- membership ------------------------------------------------------
    def list_members(self, principal: Principal) -> list[User]:
        tenant = self.tenants.get(principal.tenant_id)
        if tenant is None:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        return self.users.list_for_tenant(principal.tenant_id)

    def update_member_role(
        self, principal: Principal, user_id: uuid.UUID, payload: MemberRoleUpdate
    ) -> User:
        ensure_member_manager(principal)
        if user_id == principal.user_id:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "A member cannot change their own role. Ask another owner or administrator.",
            )
        target = self.users.get(principal.tenant_id, user_id)
        if target is None:
            raise AppError(ErrorCode.NOT_FOUND, "Account not found in this workspace.")
        if target.role == "PLATFORM_OWNER":
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Platform ownership is assigned by the platform operator, not as a "
                "workspace role.",
            )
        allowed = _GRANTS.get(principal.role, frozenset())
        if payload.role not in allowed:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Your role cannot grant that workspace role.",
                details={"grantable": sorted(allowed)},
            )
        previous = target.role
        if previous == payload.role:
            self.session.commit()
            return target
        target.role = payload.role
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="member.role_changed",
            entity_type="user",
            entity_id=target.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "previous_role": previous,
                "role": payload.role,
                "reason": payload.reason,
            },
            before={"role": previous},
            after={"role": payload.role},
        )
        self.session.commit()
        return target

    # -- invitations -----------------------------------------------------
    def create_invitation(
        self, principal: Principal, payload: InvitationCreate
    ) -> tuple[Invitation, str]:
        ensure_member_manager(principal)
        allowed = _GRANTS.get(principal.role, frozenset())
        if payload.role not in allowed:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Your role cannot invite someone at that workspace role.",
                details={"grantable": sorted(allowed)},
            )
        tenant = self.tenants.get(principal.tenant_id)
        if tenant is None:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")
        if not tenant.is_active:
            raise AppError(ErrorCode.CONFLICT, "This workspace is suspended.")

        email = payload.email.strip().lower()
        if self.users.get_by_email(principal.tenant_id, email) is not None:
            raise AppError(ErrorCode.CONFLICT, "That address already belongs to this workspace.")
        if self.invitations.find_pending_for_email(email, principal.tenant_id):
            raise AppError(
                ErrorCode.CONFLICT,
                "That address already has a live invitation. Revoke it before issuing another.",
            )

        code = secrets.token_urlsafe(24)
        invitation = self.invitations.create(
            tenant_id=principal.tenant_id,
            email=email,
            role=payload.role,
            token_hash=sha256_hex(code),
            invited_by=principal.user_id,
            expires_at=utcnow() + timedelta(days=payload.expires_in_days),
            note=payload.note,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="invitation.created",
            entity_type="invitation",
            entity_id=invitation.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"email": email, "role": payload.role},
        )
        self.session.commit()
        return invitation, code

    def list_invitations(self, principal: Principal) -> list[Invitation]:
        ensure_member_manager(principal)
        return self.invitations.list_for_tenant(principal.tenant_id)

    def revoke_invitation(
        self, principal: Principal, invitation_id: uuid.UUID, reason: str | None
    ) -> Invitation:
        ensure_member_manager(principal)
        invitation = self.invitations.get(principal.tenant_id, invitation_id)
        if invitation is None:
            raise AppError(ErrorCode.NOT_FOUND, "Invitation not found.")
        if invitation.status == "ACCEPTED":
            raise AppError(
                ErrorCode.CONFLICT,
                "An accepted invitation cannot be revoked; change the member's role instead.",
            )
        if invitation.status == "REVOKED":
            return invitation
        invitation.status = "REVOKED"
        invitation.revoked_at = utcnow()
        invitation.revoke_reason = (reason or "").strip()[:300] or None
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="invitation.revoked",
            entity_type="invitation",
            entity_id=invitation.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"email": invitation.email, "reason": invitation.revoke_reason},
        )
        self.session.commit()
        return invitation
