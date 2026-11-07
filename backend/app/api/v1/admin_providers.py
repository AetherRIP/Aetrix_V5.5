"""Platform administration of the Gemini key fleet.

Every route here is a platform capability, not a workspace one: keys are shared
infrastructure and a teacher must not be able to add, disable or read them.  The
gate is the engine's own role, resolved from the database for the verified
subject — never a header, a query parameter or the browser's opinion.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import SecretStr
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.ids import utcnow
from ...core.security import Principal
from ...db.models import ProviderCredential
from ...db.repositories import (
    AuditRepository,
    ContributorRepository,
    CredentialRepository,
    UsageRepository,
)
from ...db.session import get_db_session
from ...providers.base import LLMProvider
from ...schemas.provider_admin import (
    AlertRead,
    DailyUsageRead,
    EnabledRequest,
    FleetOverviewRead,
    ImportOutcomeRead,
    KeyCreate,
    KeyImportRequest,
    KeyPage,
    KeyRead,
    ModelUsageRead,
    ProjectUsageRead,
    UsageReportRead,
    ValidationRead,
)
from ...services.provider_fleet import (
    add_credential,
    fleet_alerts,
    fleet_overview,
    import_credentials,
    remove_credential,
    set_enabled,
    validate_credential,
)
from ..deps import get_principal, get_provider

router = APIRouter(prefix="/admin/providers", tags=["provider administration"])

#: The engine's ADMIN role is the platform operator.  A workspace OWNER is not
#: one: they own a tenant, not the fleet.
#: Platform ownership includes the fleet. A workspace OWNER does not: their
#: role is a tenant relationship and must never reach another tenant's keys.
FLEET_ADMIN_ROLES = frozenset({"ADMIN", "PLATFORM_OWNER"})


def require_fleet_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role not in FLEET_ADMIN_ROLES:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Provider fleet administration is restricted to platform administrators.",
        )
    return principal


def key_read(
    credential: ProviderCredential,
    stats: dict[str, object] | None,
    contributor_name: str | None = None,
) -> KeyRead:
    stats = stats or {}
    return KeyRead(
        id=credential.id,
        contributor_id=credential.contributor_id,
        contributor_name=contributor_name,
        revoked_at=credential.revoked_at,
        project_id=credential.project_id,
        account_label=credential.account_label,
        key_fingerprint=credential.key_fingerprint,
        auth_type=credential.auth_type,
        tier=credential.tier,
        health=credential.health,
        model_access=list(credential.model_access or []),
        cooldown_until=credential.cooldown_until,
        last_success_at=credential.last_success_at,
        last_failure_at=credential.last_failure_at,
        last_failure_status=credential.last_failure_status,
        last_validated_at=credential.last_validated_at,
        last_error=credential.last_error,
        requests=int(stats.get("requests", 0) or 0),
        input_tokens=int(stats.get("input_tokens", 0) or 0),
        output_tokens=int(stats.get("output_tokens", 0) or 0),
        failures=int(stats.get("failures", 0) or 0),
        quota_failures=int(stats.get("quota_failures", 0) or 0),
    )


def _audit(
    session: Session,
    principal: Principal,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    tenant_id: uuid.UUID | None,
    detail: dict[str, object],
) -> None:
    """Record who changed the fleet. Never includes key material."""

    AuditRepository(session).add(
        tenant_id=tenant_id,
        actor_type="USER",
        actor_id=str(principal.user_id),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
    )
    session.commit()


def _credential_or_404(session: Session, credential_id: uuid.UUID) -> ProviderCredential:
    credential = CredentialRepository(session).get(credential_id)
    if credential is None:
        # Absence and a foreign id are indistinguishable by design.
        raise AppError(ErrorCode.NOT_FOUND, "No such credential.")
    return credential


@router.get("/overview", response_model=FleetOverviewRead)
def overview(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> FleetOverviewRead:
    return FleetOverviewRead(**fleet_overview(session, settings))


@router.get("/keys", response_model=KeyPage)
def list_keys(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    project_id: str | None = None,
    health: str | None = None,
    q: str | None = Query(default=None, max_length=120),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KeyPage:
    credentials = CredentialRepository(session)
    rows, total = credentials.fleet(
        project_id=project_id,
        health=health,
        search=q,
        limit=limit,
        offset=offset,
    )
    stats = UsageRepository(session).key_window_stats(
        utcnow() - timedelta(days=30)
    )
    names = {row.id: row.display_name for row in ContributorRepository(session).list()}
    return KeyPage(
        items=[
            key_read(
                row,
                stats.get(row.id),
                names.get(row.contributor_id) if row.contributor_id else None,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/keys", response_model=KeyRead, status_code=status.HTTP_201_CREATED)
def create_key(
    payload: KeyCreate,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> KeyRead:
    credential = add_credential(
        session,
        settings,
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
        action="provider.key.added",
        entity_type="provider_credential",
        entity_id=str(credential.id),
        tenant_id=credential.tenant_id,
        detail={
            "project_id": credential.project_id,
            "fingerprint": credential.key_fingerprint,
            "tier": credential.tier,
            "auth_type": credential.auth_type,
        },
    )
    return key_read(credential, None)


@router.post("/keys/import", response_model=list[ImportOutcomeRead])
def import_keys(
    payload: KeyImportRequest,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[ImportOutcomeRead]:
    outcomes = import_credentials(
        session,
        settings,
        [entry.model_dump() for entry in payload.keys],
    )
    added = sum(1 for outcome in outcomes if outcome.outcome == "added")
    _audit(
        session,
        principal,
        action="provider.keys.imported",
        entity_type="provider_fleet",
        entity_id="import",
        tenant_id=None,
        detail={
            "submitted": len(outcomes),
            "added": added,
            "duplicate": sum(1 for o in outcomes if o.outcome == "duplicate"),
            "rejected": sum(1 for o in outcomes if o.outcome == "rejected"),
        },
    )
    return [ImportOutcomeRead(**outcome.as_dict()) for outcome in outcomes]


@router.post("/keys/{credential_id}/validate", response_model=ValidationRead)
def validate_key(
    credential_id: uuid.UUID,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_provider),
) -> ValidationRead:
    credential = _credential_or_404(session, credential_id)
    result = validate_credential(session, settings, provider, credential)
    _audit(
        session,
        principal,
        action="provider.key.validated",
        entity_type="provider_credential",
        entity_id=str(credential.id),
        tenant_id=credential.tenant_id,
        detail={"health": result["health"], "valid": result["valid"]},
    )
    return ValidationRead(**result)


@router.post("/keys/{credential_id}/enabled", response_model=KeyRead)
def set_key_enabled(
    credential_id: uuid.UUID,
    payload: EnabledRequest,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
) -> KeyRead:
    credential = _credential_or_404(session, credential_id)
    set_enabled(session, credential, enabled=payload.enabled)
    _audit(
        session,
        principal,
        action="provider.key.enabled" if payload.enabled else "provider.key.disabled",
        entity_type="provider_credential",
        entity_id=str(credential.id),
        tenant_id=credential.tenant_id,
        detail={"enabled": payload.enabled, "health": credential.health},
    )
    return key_read(credential, None)


@router.delete("/keys/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(
    credential_id: uuid.UUID,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    credential = _credential_or_404(session, credential_id)
    detail = {
        "project_id": credential.project_id,
        "fingerprint": credential.key_fingerprint,
        "label": credential.account_label,
    }
    entity_id = str(credential.id)
    tenant_id = credential.tenant_id
    outcome = remove_credential(session, settings, credential)
    _audit(
        session,
        principal,
        action="provider.key.removed",
        entity_type="provider_credential",
        entity_id=entity_id,
        tenant_id=tenant_id,
        detail={**detail, "outcome": outcome},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects", response_model=list[dict[str, object]])
def projects(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, object]]:
    overview_payload = fleet_overview(session, settings)
    return list(overview_payload["projects_detail"])


@router.get("/usage", response_model=UsageReportRead)
def usage(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> UsageReportRead:
    since = utcnow() - timedelta(days=days)
    repository = UsageRepository(session)
    return UsageReportRead(
        since=since,
        daily=[DailyUsageRead(**row) for row in repository.daily(since)],
        by_model=[ModelUsageRead(**row) for row in repository.model_window_stats(since)],
        by_project=[ProjectUsageRead(**row) for row in repository.project_window_stats(since)],
    )


@router.get("/alerts", response_model=list[AlertRead])
def alerts(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[AlertRead]:
    return [AlertRead(**alert) for alert in fleet_alerts(session, settings)]
