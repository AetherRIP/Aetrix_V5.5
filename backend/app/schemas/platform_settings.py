"""Platform configuration contracts.

Every field the settings screen renders comes from here, including the options
it may choose from: the browser never invents a template key or an account type.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TemplateOption(BaseModel):
    key: str
    label: str
    description: str


class AuditAccountTypeOption(BaseModel):
    """One account type that may be granted the platform-wide audit view."""

    key: str
    label: str
    description: str
    #: The platform role this account type resolves to from the verified claim.
    platform_role: str


class PlatformSettingsRead(BaseModel):
    default_workspace_template: str
    uploaded_script_retention_days: int
    audit_view_allowed_account_types: list[str]
    version: int
    created_at: datetime
    updated_at: datetime
    updated_by_label: str | None = None
    updated_by_subject: str | None = None
    updated_by_user_id: UUID | None = None
    #: The registry and vocabulary the controls are built from.
    available_templates: list[TemplateOption] = Field(default_factory=list)
    audit_account_types: list[AuditAccountTypeOption] = Field(default_factory=list)
    retention_min_days: int
    retention_max_days: int


class PlatformSettingsUpdate(BaseModel):
    default_workspace_template: str
    uploaded_script_retention_days: int = Field(ge=1, le=3650)
    audit_view_allowed_account_types: list[str] = Field(min_length=1)
    #: The version the browser read.  A mismatch is a 409, never a silent
    #: last-writer-wins overwrite of another administrator's save.
    expected_version: int | None = None


class RetentionProtectedCount(BaseModel):
    reason: str
    documents: int


class RetentionPreviewRead(BaseModel):
    """What the configured window would purge right now.  Read-only."""

    retention_days: int
    cutoff: datetime
    scanned_at: datetime
    eligible_documents: int
    eligible_pages: int
    eligible_bytes: int
    already_purged_documents: int
    protected: list[RetentionProtectedCount] = Field(default_factory=list)


class RetentionSweepRequest(BaseModel):
    #: Applying is destructive, so the caller must echo the policy it previewed
    #: against.  A changed window refuses instead of deleting under a stale view.
    expected_retention_days: int = Field(ge=1, le=3650)
    limit: int = Field(default=100, ge=1, le=500)


class RetentionSweepRead(BaseModel):
    purged_documents: int
    purged_pages: int
    purged_bytes: int
    failed_documents: int
    retention_days: int
    cutoff: datetime
    completed_at: datetime
