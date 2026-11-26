"""Platform configuration endpoints.

Reads are open to any platform administrator (owner or operator); writes are
open to platform administrators except the audit-access list, which only the
platform owner may change (enforced in the service, so the rule holds for every
caller).  The authorization is the verified platform claim, resolved on the
server; nothing here reads a role from the request body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.security import Principal
from ...db.session import get_db_session
from ...schemas.platform_settings import (
    PlatformSettingsRead,
    PlatformSettingsUpdate,
    RetentionPreviewRead,
    RetentionSweepRead,
    RetentionSweepRequest,
)
from ...services.platform_accounts import ensure_platform_admin
from ...services.platform_settings import PlatformSettingsService
from ...services.retention import RetentionService
from ...storage.base import Storage
from ..deps import get_principal, get_storage

router = APIRouter(prefix="/admin/settings", tags=["platform settings"])


def require_platform_admin(principal: Principal = Depends(get_principal)) -> Principal:
    ensure_platform_admin(principal)
    return principal


@router.get("", response_model=PlatformSettingsRead)
def read_platform_settings(
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
) -> PlatformSettingsRead:
    return PlatformSettingsRead.model_validate(
        PlatformSettingsService(session).read(principal)
    )


@router.put("", response_model=PlatformSettingsRead)
def update_platform_settings(
    payload: PlatformSettingsUpdate,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
) -> PlatformSettingsRead:
    updated = PlatformSettingsService(session).update(
        principal,
        default_workspace_template=payload.default_workspace_template,
        uploaded_script_retention_days=payload.uploaded_script_retention_days,
        audit_view_allowed_account_types=payload.audit_view_allowed_account_types,
        expected_version=payload.expected_version,
    )
    session.commit()
    return PlatformSettingsRead.model_validate(updated)


@router.get("/retention/preview", response_model=RetentionPreviewRead)
def preview_retention(
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
    storage: Storage = Depends(get_storage),
) -> RetentionPreviewRead:
    """What the configured window would purge right now.  Deletes nothing."""

    preview = RetentionService(session, storage).preview()
    return RetentionPreviewRead(
        retention_days=preview.retention_days,
        cutoff=preview.cutoff,
        scanned_at=preview.scanned_at,
        eligible_documents=preview.eligible_documents,
        eligible_pages=preview.eligible_pages,
        eligible_bytes=preview.eligible_bytes,
        already_purged_documents=preview.already_purged_documents,
        protected=[
            {"reason": reason, "documents": count}
            for reason, count in preview.protected.items()
        ],
    )


@router.post("/retention/sweep", response_model=RetentionSweepRead)
def sweep_retention(
    payload: RetentionSweepRequest,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
    storage: Storage = Depends(get_storage),
) -> RetentionSweepRead:
    """Remove stored bytes for eligible scripts and record each removal.

    The caller must echo the retention window it previewed; a changed window is
    a 409.  Metadata, page text, jobs, results and approvals are never deleted.
    """

    outcome = RetentionService(session, storage).sweep(
        principal,
        limit=payload.limit,
        expected_retention_days=payload.expected_retention_days,
    )
    session.commit()
    return RetentionSweepRead(
        purged_documents=outcome.purged_documents,
        purged_pages=outcome.purged_pages,
        purged_bytes=outcome.purged_bytes,
        failed_documents=outcome.failed_documents,
        retention_days=outcome.retention_days,
        cutoff=outcome.cutoff,
        completed_at=outcome.completed_at,
    )
