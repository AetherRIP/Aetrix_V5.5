"""Platform account administration contracts.

Accounts are Supabase identities; Aetrix stores only the workspace memberships
that reference them.  These models keep that split visible: ``role`` and
``status`` come from the identity provider, ``memberships`` from Aetrix's own
rows, and nothing is invented when the administrative credential is absent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

#: The product's platform vocabulary.  ``unassigned`` is a real state: an
#: account exists but no ``app_metadata.aetrix_role`` is set.
PlatformAccountRole = Literal[
    "owner", "platform_operator", "supervisor", "assistant", "viewer", "unassigned"
]

#: Roles this interface may grant.  ``owner`` is deliberately absent: platform
#: ownership is assigned by the identity-provider operator, never through the API.
ManageablePlatformRole = Literal[
    "platform_operator", "supervisor", "assistant", "viewer"
]

PlatformAccountStatus = Literal["ACTIVE", "SUSPENDED", "UNCONFIRMED"]


class AccountMembershipRead(BaseModel):
    tenant_id: str
    workspace_name: str
    workspace_slug: str
    role: str
    is_demo: bool
    user_row_id: str
    joined_at: datetime


class AccountInvitationRead(BaseModel):
    id: str
    email: str
    role: str
    status: str
    tenant_id: str
    workspace_name: str
    expires_at: datetime
    created_at: datetime


class AccountAuditRead(BaseModel):
    id: str
    action: str
    actor_subject: str
    actor_platform_role: str
    target_subject: str
    target_email: str | None
    detail: dict[str, Any]
    created_at: datetime


class PlatformAccountRead(BaseModel):
    id: str
    email: str | None
    display_name: str | None
    role: PlatformAccountRole
    status: PlatformAccountStatus
    created_at: datetime | None
    updated_at: datetime | None
    last_sign_in_at: datetime | None
    email_confirmed_at: datetime | None
    banned_until: datetime | None
    memberships: list[AccountMembershipRead] = Field(default_factory=list)
    workspace_count: int = 0
    has_workspace: bool = False
    pending_invitation_count: int = 0


class PlatformAccountDetail(PlatformAccountRead):
    invitations: list[AccountInvitationRead] = Field(default_factory=list)
    audit: list[AccountAuditRead] = Field(default_factory=list)


class AccountMembershipEffectRead(BaseModel):
    """One membership row a role change moved, or one it deliberately left.

    ``state`` is ``changed`` when the row now carries the new workspace role and
    ``skipped`` when it was left as it is; ``reason`` always says which, so an
    operator is never told only that the request succeeded.
    """

    state: Literal["changed", "skipped"]
    reason: str
    workspace_name: str | None = None
    workspace_slug: str | None = None
    user_row_id: str | None = None
    previous_role: str | None = None
    role: str | None = None


class AccountRoleChangeRead(BaseModel):
    """The role-change result: the account after the change, plus every row."""

    account: PlatformAccountDetail
    memberships: list[AccountMembershipEffectRead] = Field(default_factory=list)


class AccountPage(BaseModel):
    items: list[PlatformAccountRead]
    total: int
    page: int
    page_size: int
    #: Where the rows came from, so a screen cannot present Aetrix membership
    #: rows as if they were the platform's account list.
    source: str
    #: True when the configured account ceiling was reached: the list is
    #: incomplete and says so instead of looking exhaustive.
    truncated: bool = False


class AccountOperationRead(BaseModel):
    name: str
    supported: bool
    note: str


class AccountCapabilityRead(BaseModel):
    configured: bool
    reason: str
    operations: list[AccountOperationRead]


class AccountRoleUpdate(BaseModel):
    role: ManageablePlatformRole
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AccountStatusUpdate(BaseModel):
    status: Literal["ACTIVE", "SUSPENDED"]
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AccountDeletion(BaseModel):
    """Deletion is confirmed by re-typing the account's own address."""

    confirm_email: str = Field(min_length=3, max_length=320)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("confirm_email", "reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class AccountActionRead(BaseModel):
    status: str
    message: str


class AccountQuery(BaseModel):
    q: str | None = None
    role: PlatformAccountRole | None = None
    status: PlatformAccountStatus | None = None
    joined: Literal["yes", "no"] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
