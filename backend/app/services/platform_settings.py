"""Platform configuration: one row, validated, audited.

The row is created on first use with explicit defaults rather than left absent,
so a read never has to guess what the platform is configured to do.  Creation is
race-safe (``ON CONFLICT DO NOTHING``), every update takes a row lock and an
optional expected version, and every changed setting writes its own append-only
audit event with the previous and new value.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.security import Principal, platform_authority
from ..core.workspace_templates import (
    DEFAULT_WORKSPACE_TEMPLATE,
    get_workspace_template,
    template_options,
)
from ..db.models import PlatformSettings

SINGLETON_ID = 1

#: Explicit, documented defaults.  The audit default preserves the behaviour the
#: engine had before configuration existed (platform owner only), so creating the
#: row cannot widen access.
DEFAULT_RETENTION_DAYS = 365
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
DEFAULT_AUDIT_ACCOUNT_TYPES: tuple[str, ...] = ("owner",)

#: The account types that carry platform authority, derived from the same
#: vocabulary the identity service presents (``PLATFORM_OWNER`` is ``owner``,
#: ``ADMIN`` is ``platform_operator``).  Workspace roles are deliberately absent:
#: this setting governs the cross-tenant audit view, and a workspace member's
#: access to their own ledger is membership-scoped and unaffected.
@dataclass(frozen=True, slots=True)
class AuditAccountType:
    key: str
    platform_role: str
    label: str
    description: str


AUDIT_ACCOUNT_TYPES: dict[str, AuditAccountType] = {
    "owner": AuditAccountType(
        key="owner",
        platform_role="PLATFORM_OWNER",
        label="Platform owner",
        description=(
            "Platform ownership. The only account type that may change platform "
            "settings, including this list."
        ),
    ),
    "platform_operator": AuditAccountType(
        key="platform_operator",
        platform_role="ADMIN",
        label="Platform operator",
        description=(
            "Platform administration without ownership. Granting this lets an "
            "operator read the cross-tenant ledger; it grants no workspace role."
        ),
    ),
}

AUDIT_ACCOUNT_TYPE_BY_PLATFORM_ROLE: dict[str, str] = {
    account_type.platform_role: account_type.key
    for account_type in AUDIT_ACCOUNT_TYPES.values()
}


def audit_account_type_options() -> list[dict[str, str]]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "description": item.description,
            "platform_role": item.platform_role,
        }
        for item in AUDIT_ACCOUNT_TYPES.values()
    ]


def account_type_for(principal: Principal) -> str:
    """The platform account type of a verified principal, or ''."""

    return AUDIT_ACCOUNT_TYPE_BY_PLATFORM_ROLE.get(platform_authority(principal), "")


def _snapshot(row: PlatformSettings) -> dict[str, Any]:
    return {
        "default_workspace_template": row.default_workspace_template,
        "uploaded_script_retention_days": row.uploaded_script_retention_days,
        "audit_view_allowed_account_types": list(row.audit_view_allowed_account_types),
    }


def _actor_label(principal: Principal | None) -> tuple[uuid.UUID | None, str | None, str | None]:
    if principal is None:
        return None, None, None
    return principal.user_id, principal.subject, principal.subject


class PlatformSettingsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditService(session)

    # -- initialization -------------------------------------------------
    def ensure(self) -> PlatformSettings:
        """Return the single row, creating it with the documented defaults.

        Creation is not itself a settings change (the migration inserts the same
        row in a deployed environment), so it writes no audit event and does not
        add noise to the platform ledger.  The row's ``created_at`` is the record
        of when the defaults came into force.
        """

        statement = (
            pg_insert(PlatformSettings)
            .values(
                id=SINGLETON_ID,
                default_workspace_template=DEFAULT_WORKSPACE_TEMPLATE,
                uploaded_script_retention_days=DEFAULT_RETENTION_DAYS,
                audit_view_allowed_account_types=list(DEFAULT_AUDIT_ACCOUNT_TYPES),
                version=1,
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(PlatformSettings.id)
        )
        created = self.session.execute(statement).scalar() is not None
        row = self.session.scalar(
            select(PlatformSettings)
            .where(PlatformSettings.id == SINGLETON_ID)
            .execution_options(populate_existing=True)
        )
        if row is None:  # pragma: no cover - the insert either won or the row exists
            raise AppError(
                ErrorCode.INTERNAL_ERROR, "The platform configuration row is missing."
            )
        del created
        return row

    # -- read -----------------------------------------------------------
    def read(self, principal: Principal) -> dict[str, Any]:
        row = self.ensure()
        return {
            **_snapshot(row),
            "version": row.version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "updated_by_label": row.updated_by_label,
            "updated_by_subject": row.updated_by_subject,
            "updated_by_user_id": row.updated_by_user_id,
            "available_templates": template_options(),
            "audit_account_types": audit_account_type_options(),
            "retention_min_days": MIN_RETENTION_DAYS,
            "retention_max_days": MAX_RETENTION_DAYS,
        }

    # -- update ---------------------------------------------------------
    def update(
        self,
        principal: Principal,
        *,
        default_workspace_template: str,
        uploaded_script_retention_days: int,
        audit_view_allowed_account_types: list[str],
        expected_version: int | None,
    ) -> dict[str, Any]:
        row = self.ensure()
        # A second administrator's save must not be silently overwritten, and a
        # version the browser did not send is not trusted to be current.
        if expected_version is not None and row.version != expected_version:
            raise AppError(
                ErrorCode.CONFLICT,
                "The platform settings changed after this page was loaded. "
                "Reload them and make the change again.",
            )
        self.session.refresh(row, with_for_update=True)

        template = get_workspace_template(default_workspace_template)
        if template is None:
            registered = ", ".join(item["key"] for item in template_options())
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"'{default_workspace_template}' is not a registered workspace "
                f"template. Registered templates: {registered}.",
            )
        if not MIN_RETENTION_DAYS <= uploaded_script_retention_days <= MAX_RETENTION_DAYS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The retention window must be between "
                f"{MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS} days.",
            )
        allowed = list(dict.fromkeys(audit_view_allowed_account_types))
        unknown = [key for key in allowed if key not in AUDIT_ACCOUNT_TYPES]
        if unknown:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Unknown account type(s) for audit access: "
                + ", ".join(unknown)
                + ". Recognised account types: "
                + ", ".join(AUDIT_ACCOUNT_TYPES)
                + ".",
            )
        if not allowed:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "At least one account type must be allowed to open the audit view.",
            )
        allowed = [key for key in AUDIT_ACCOUNT_TYPES if key in allowed]

        previous = _snapshot(row)
        changes = {
            "default_workspace_template": (
                previous["default_workspace_template"],
                template.key,
            ),
            "uploaded_script_retention_days": (
                previous["uploaded_script_retention_days"],
                uploaded_script_retention_days,
            ),
            "audit_view_allowed_account_types": (
                previous["audit_view_allowed_account_types"],
                allowed,
            ),
        }
        # Granting the cross-tenant ledger is an ownership decision, even though
        # ordinary platform administration may change the other two settings.
        # Without this an operator could grant itself audit access.
        if (
            changes["audit_view_allowed_account_types"][0] != allowed
            and platform_authority(principal) != "PLATFORM_OWNER"
        ):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only the platform owner may change who can open the audit view.",
            )
        changed = {key: pair for key, pair in changes.items() if pair[0] != pair[1]}
        if not changed:
            return self.read(principal)

        row.default_workspace_template = template.key
        row.uploaded_script_retention_days = uploaded_script_retention_days
        row.audit_view_allowed_account_types = allowed
        row.version = row.version + 1
        row.updated_by_user_id, row.updated_by_label, row.updated_by_subject = (
            _actor_label(principal)
        )
        row.updated_at = datetime.now(UTC)

        for setting, (before_value, after_value) in changed.items():
            self.audit.record(
                tenant_id=None,
                action=f"platform.settings.{setting}.changed",
                entity_type="platform_settings",
                entity_id=str(SINGLETON_ID),
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "setting": setting,
                    "previous": before_value,
                    "new": after_value,
                    "actor_subject": principal.subject,
                    "actor_label": principal.subject,
                },
                before={setting: before_value},
                after={setting: after_value},
            )
        self.session.flush()
        return self.read(principal)



def ensure_platform_audit_access(session: Session, principal: Principal) -> None:
    """Enforce the configured audit-view permission on every read.

    The caller has already established *some* platform authority; this decides
    whether that particular account type is currently allowed to read the
    cross-tenant ledger.  It never grants access: an account with no platform
    authority is refused before the setting is consulted.
    """

    authority = platform_authority(principal)
    if not authority:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Platform audit is restricted to platform accounts.",
        )
    account_type = AUDIT_ACCOUNT_TYPE_BY_PLATFORM_ROLE.get(authority, "")
    row = PlatformSettingsService(session).ensure()
    if account_type not in row.audit_view_allowed_account_types:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "The platform owner has not allowed this account type to open the "
            "audit view.",
        )
