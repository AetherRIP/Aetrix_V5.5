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
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.ids import utcnow
from ...core.security import Principal, platform_authority
from ...db.models import ProviderCredential, ProviderUsage
from ...db.repositories import (
    AuditRepository,
    ContributorRepository,
    CredentialRepository,
    UsageRepository,
)
from ...db.session import get_db_session
from ...providers.base import LLMProvider
from ...schemas.google_quota import (
    GoogleQuotaReportRead,
    GoogleQuotaSyncRequest,
)
from ...schemas.model_catalogue import (
    ModelCatalogueRead,
    ModelSelectionRead,
    ModelSelectionWrite,
    ModelTestRequest,
)
from ...schemas.model_inventory import ModelInventoryRead
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
    RecentProviderCallRead,
    UsageReportRead,
    ValidationRead,
)
from ...services.google_quota import (
    QuotaSyncUnavailable,
    declared_project_ids,
    quota_report,
    sync_projects,
)
from ...services.model_catalogue import (
    MODEL_ID_PATTERN,
    discover_catalogue,
    set_selection,
)
from ...services.model_inventory import inventory_report
from ...services.provider_fleet import (
    PROJECT_VERIFICATION,
    add_credential,
    fleet_alerts,
    fleet_overview,
    import_credentials,
    operational_status,
    remove_credential,
    set_enabled,
    usage_category,
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
    if platform_authority(principal) not in FLEET_ADMIN_ROLES:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Provider fleet administration is restricted to platform administrators.",
        )
    return principal


def key_read(
    credential: ProviderCredential,
    stats: dict[str, object] | None,
    contributor_name: str | None = None,
    latest: ProviderUsage | None = None,
    last_failure: ProviderUsage | None = None,
) -> KeyRead:
    stats = stats or {}
    from ...core.ids import utcnow

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
        operational_status=operational_status(
            health=credential.health,
            revoked=credential.revoked_at is not None,
            cooldown_until=credential.cooldown_until,
            latest=latest,
            now=utcnow(),
        ),
        project_verification=PROJECT_VERIFICATION,
        model_access=list(credential.model_access or []),
        cooldown_until=credential.cooldown_until,
        last_success_at=credential.last_success_at,
        last_failure_at=credential.last_failure_at,
        last_failure_status=credential.last_failure_status,
        last_failure_category=usage_category(last_failure),
        last_failure_provider_code=(
            last_failure.provider_code if last_failure else None
        ),
        last_failure_message=(
            last_failure.provider_message if last_failure else None
        ),
        last_failure_reached_provider=(
            last_failure.reached_provider if last_failure else None
        ),
        last_usage_at=latest.created_at if latest else None,
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
    repository = UsageRepository(session)
    stats = repository.key_window_stats(utcnow() - timedelta(days=30))
    ids = [row.id for row in rows]
    latest = repository.latest_by_credential(ids)
    latest_failures = repository.latest_failures_by_credential(ids)
    names = {row.id: row.display_name for row in ContributorRepository(session).list()}
    return KeyPage(
        items=[
            key_read(
                row,
                stats.get(row.id),
                names.get(row.contributor_id) if row.contributor_id else None,
                latest.get(row.id),
                latest_failures.get(row.id),
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
    settings: Settings = Depends(get_settings),
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> UsageReportRead:
    since = utcnow() - timedelta(days=days)
    repository = UsageRepository(session)
    labels = {
        row.id: row.account_label
        for row in CredentialRepository(session).all_credentials()
    }
    recent = repository.recent_calls(25)
    return UsageReportRead(
        since=since,
        timezone=settings.quota.daily_reset_timezone,
        daily=[
            DailyUsageRead(**row)
            for row in repository.daily(
                since, settings.quota.daily_reset_timezone
            )
        ],
        by_model=[ModelUsageRead(**row) for row in repository.model_window_stats(since)],
        by_project=[ProjectUsageRead(**row) for row in repository.project_window_stats(since)],
        recent_calls=[
            RecentProviderCallRead(
                id=row.id,
                created_at=row.created_at,
                credential_id=row.credential_id,
                credential_label=(
                    labels.get(row.credential_id) if row.credential_id else None
                ),
                project_id=row.project_id,
                model=row.model,
                purpose=row.purpose,
                success=row.success,
                http_status=row.http_status,
                error_class=row.error_class,
                error_category=usage_category(row),
                provider_code=row.provider_code,
                provider_message=row.provider_message,
                reached_provider=row.reached_provider,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                request_id=row.request_id,
                latency_ms=row.latency_ms,
            )
            for row in recent
        ],
    )


@router.get("/alerts", response_model=list[AlertRead])
def alerts(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list[AlertRead]:
    return [AlertRead(**alert) for alert in fleet_alerts(session, settings)]


def _model_test_credential(
    session: Session, payload: ModelTestRequest
) -> ProviderCredential:
    """The key that will actually be used to test a model, named or chosen."""

    if payload.credential_id is not None:
        return _credential_or_404(session, payload.credential_id)
    query = select(ProviderCredential).where(
        ProviderCredential.revoked_at.is_(None),
        ProviderCredential.health.in_(("HEALTHY", "UNKNOWN")),
    )
    if payload.project_id:
        query = query.where(ProviderCredential.project_id == payload.project_id)
    credential = session.scalar(
        query.order_by(ProviderCredential.last_success_at.desc().nullslast())
    )
    if credential is None:
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "No usable credential is registered for that project, so no model "
            "was tested.",
        )
    return credential


@router.get("/models/inventory", response_model=ModelInventoryRead)
def model_inventory(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ModelInventoryRead:
    """The complete operator inventory, independent of live project access."""

    return ModelInventoryRead(**inventory_report(session, settings))


@router.get("/models", response_model=ModelCatalogueRead)
def models(
    refresh: bool = False,
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ModelCatalogueRead:
    """What the registered credentials can actually reach, read live."""

    return ModelCatalogueRead(**discover_catalogue(session, settings, refresh=refresh))


@router.put("/models/selection/{role}", response_model=ModelSelectionRead)
def select_model(
    role: str,
    payload: ModelSelectionWrite,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ModelSelectionRead:
    row = set_selection(
        session, settings, role, payload.model, actor=str(principal.user_id)
    )
    _audit(
        session,
        principal,
        action="provider.model.selected",
        entity_type="provider_model_selection",
        entity_id=role,
        tenant_id=None,
        detail={"role": role, "model": row.model},
    )
    return ModelSelectionRead(
        role=row.role,
        model=row.model,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@router.post("/models/{model_id}/test", response_model=ValidationRead)
def test_model(
    model_id: str,
    payload: ModelTestRequest,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_provider),
) -> ValidationRead:
    """One real probe of one model with a named credential. Never a swap."""

    if not MODEL_ID_PATTERN.match(model_id):
        raise AppError(ErrorCode.NOT_FOUND, "That is not a valid Gemini model id.")
    credential = _model_test_credential(session, payload)
    result = validate_credential(
        session, settings, provider, credential, model=model_id
    )
    _audit(
        session,
        principal,
        action="provider.model.tested",
        entity_type="provider_credential",
        entity_id=str(credential.id),
        tenant_id=credential.tenant_id,
        detail={
            "model": model_id,
            "health": result["health"],
            "valid": result["valid"],
        },
    )
    return ValidationRead(**result)


@router.get("/google-quota", response_model=GoogleQuotaReportRead)
def google_quota(
    _: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> GoogleQuotaReportRead:
    """Cached Google-reported quotas, with per-project freshness and errors."""

    return GoogleQuotaReportRead(**quota_report(session, settings))


@router.post("/google-quota/sync", response_model=GoogleQuotaReportRead)
def google_quota_sync(
    payload: GoogleQuotaSyncRequest,
    principal: Principal = Depends(require_fleet_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> GoogleQuotaReportRead:
    """Read Google Cloud now. This never mutates quotas, billing or IAM."""

    if payload.project_id and payload.project_id not in declared_project_ids(session):
        raise AppError(
            ErrorCode.NOT_FOUND,
            "No registered key declares that Google Cloud project.",
        )
    try:
        report = sync_projects(
            session,
            settings,
            project_ids=[payload.project_id] if payload.project_id else None,
            trigger="MANUAL",
        )
    except QuotaSyncUnavailable as exc:
        raise AppError(
            ErrorCode.CONFIGURATION_ERROR, str(exc), status_code=503
        ) from exc
    _audit(
        session,
        principal,
        action="provider.google_quota.synced",
        entity_type="google_cloud_project",
        entity_id=payload.project_id or "fleet",
        tenant_id=None,
        detail={
            "projects": len(report["projects"]),
            "results": len(report["sync_results"]),
            "configured": report["fleet"]["configured"],
            "credential_source": report["fleet"]["credential_source"],
        },
    )
    return GoogleQuotaReportRead(**report)
