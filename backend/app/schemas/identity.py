"""Identity, membership and invitation contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

WorkspaceRole = Literal["OWNER", "ADMIN", "TEACHER", "REVIEWER", "VIEWER"]

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class MeRead(BaseModel):
    """The authenticated principal as the engine sees it.

    ``role`` is the engine's workspace role and the API's authorization source.
    ``ui_role`` is the presentation vocabulary the shell uses; it is derived
    here so the browser never invents a mapping of its own.
    """

    user_id: UUID
    subject: str
    email: str | None
    display_name: str | None
    tenant_id: UUID
    workspace_name: str
    workspace_slug: str
    role: str
    ui_role: str
    capabilities: list[str]
    is_demo: bool


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    email: str | None
    display_name: str | None
    role: str
    created_at: datetime


class MemberRoleUpdate(BaseModel):
    role: WorkspaceRole
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class InvitationCreate(BaseModel):
    email: str = Field(pattern=_EMAIL_PATTERN, max_length=320)
    role: WorkspaceRole = "TEACHER"
    expires_in_days: int = Field(default=14, ge=1, le=90)
    note: str | None = Field(default=None, max_length=300)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    note: str | None
    created_at: datetime


class InvitationCreated(InvitationRead):
    """``acceptance_code`` is returned exactly once and is never stored."""

    acceptance_code: str


class InvitationAccept(BaseModel):
    code: str = Field(min_length=16, max_length=200)
