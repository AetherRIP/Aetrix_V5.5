"""Gemini API key fleet: registration, validation and platform overview.

Secrets never leave this module: a key is encrypted with the configured Fernet
key on the way in, and every read path returns the fingerprint (a truncated
SHA-256) instead of the secret.  There is no endpoint that returns a stored key.

Quota is never counted here — `app.services.quota` does that per project — but
this module deliberately refuses to let a key be registered without a project,
because an unattributed key would silently create a second quota pool.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import SecretBox, fingerprint
from ..db.models import ProviderCredential, ProviderUsage
from ..db.repositories import (
    CredentialRepository,
    QuotaReservationRepository,
    UsageRepository,
)
from ..providers.base import LLMProvider, LLMRequest, ProviderNotConfigured
from ..providers.errors import ProviderAuthenticationError, ProviderError
from .quota import QuotaEstimator, day_start, next_reset

MAX_PROJECT_ID_LENGTH = 100
MAX_LABEL_LENGTH = 120


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    index: int
    label: str
    project_id: str
    outcome: str  # added | duplicate | rejected
    detail: str | None = None
    credential_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "project_id": self.project_id,
            "outcome": self.outcome,
            "detail": self.detail,
            "credential_id": self.credential_id,
        }


def _box(settings: Settings) -> SecretBox:
    if settings.security.encryption_key is None:
        raise AppError(
            ErrorCode.CONFIGURATION_ERROR,
            "Credential encryption is not configured; keys cannot be stored.",
        )
    return SecretBox(settings.security.encryption_key.get_secret_value())


def _clean_project(project_id: str) -> str:
    value = project_id.strip()
    if not value:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Every key must name its Google Cloud project; an unattributed key "
            "would be counted as a separate quota pool.",
        )
    if len(value) > MAX_PROJECT_ID_LENGTH:
        raise AppError(ErrorCode.VALIDATION_ERROR, "The project id is too long.")
    return value


def _clean_label(label: str | None, project_id: str, position: int) -> str:
    value = (label or "").strip() or f"{project_id} key {position}"
    return value[:MAX_LABEL_LENGTH]


def add_credential(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    api_key: SecretStr,
    label: str | None = None,
    model_access: Iterable[str] | None = None,
    tier: str = "UNKNOWN",
    auth_type: str = "api_key",
    tenant_id: uuid.UUID | None = None,
) -> ProviderCredential:
    raw = api_key.get_secret_value().strip()
    if not raw:
        raise AppError(ErrorCode.VALIDATION_ERROR, "The key is empty.")
    if tier not in {"FREE", "PAID", "UNKNOWN"}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown tier.")
    if auth_type not in {"api_key", "oauth"}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown authentication type.")

    project = _clean_project(project_id)
    credentials = CredentialRepository(session)
    key_fingerprint = fingerprint(raw)
    existing = credentials.get_by_fingerprint(key_fingerprint)
    if existing is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            "This credential is already registered.",
            details={"credential_id": str(existing.id)},
        )

    credential = credentials.create(
        tenant_id=tenant_id,
        project_id=project,
        account_label=_clean_label(label, project, 1),
        key_fingerprint=key_fingerprint,
        encrypted_secret=_box(settings).encrypt(raw),
        model_access=list(model_access or []),
        auth_type=auth_type,
        tier=tier,
        # Unknown until a validation call actually succeeds.
        health="UNKNOWN",
    )
    session.commit()
    return credential


def import_credentials(
    session: Session,
    settings: Settings,
    entries: Iterable[dict[str, Any]],
) -> list[ImportOutcome]:
    """Register many keys, reporting each outcome instead of failing the batch.

    A duplicate is not an error the operator needs to fix by hand, and a bad row
    must not discard the good rows around it.
    """

    outcomes: list[ImportOutcome] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        raw = str(entry.get("api_key") or "").strip()
        project_id = str(entry.get("project_id") or "").strip()
        label = str(entry.get("label") or "").strip() or None
        try:
            if not raw:
                raise AppError(ErrorCode.VALIDATION_ERROR, "The key is empty.")
            key_fingerprint = fingerprint(raw)
            if key_fingerprint in seen:
                outcomes.append(
                    ImportOutcome(
                        index=index,
                        label=label or "",
                        project_id=project_id,
                        outcome="duplicate",
                        detail="Repeated within this import.",
                    )
                )
                continue
            seen.add(key_fingerprint)
            credential = add_credential(
                session,
                settings,
                project_id=project_id,
                api_key=SecretStr(raw),
                label=_clean_label(label, project_id or "import", index + 1),
                model_access=entry.get("model_access") or None,
                tier=str(entry.get("tier") or "UNKNOWN"),
                auth_type=str(entry.get("auth_type") or "api_key"),
                tenant_id=entry.get("tenant_id"),
            )
        except AppError as error:
            outcomes.append(
                ImportOutcome(
                    index=index,
                    label=label or "",
                    project_id=project_id,
                    outcome="duplicate" if error.code is ErrorCode.CONFLICT else "rejected",
                    detail=error.message,
                )
            )
            session.rollback()
            continue
        outcomes.append(
            ImportOutcome(
                index=index,
                label=credential.account_label,
                project_id=credential.project_id,
                outcome="added",
                credential_id=credential.id,
            )
        )
    return outcomes


def validate_credential(
    session: Session,
    settings: Settings,
    provider: LLMProvider,
    credential: ProviderCredential,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """One small real request proves the credential, not a format check.

    The call is recorded in the usage ledger with ``purpose='validate'`` so the
    one request it spends is visible rather than hidden.
    """

    box = _box(settings)
    target_model = model or settings.provider.model_primary
    usage = UsageRepository(session)
    request = LLMRequest(
        model=target_model,
        prompt="Reply with the single word: ok",
        max_output_tokens=8,
    )
    now = utcnow()
    try:
        response = provider.generate(request, SecretStr(box.decrypt(credential.encrypted_secret)))
    except ProviderNotConfigured:
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The live provider is disabled in this build; the key was not validated.",
        ) from None
    except ProviderError as error:
        credential.health = (
            "INVALID"
            if isinstance(error, ProviderAuthenticationError)
            else "COOLDOWN"
            if getattr(error, "status_code", None) == 429
            else "UNKNOWN"
        )
        credential.last_error = f"{type(error).__name__}: {error}"[:400]
        credential.last_failure_at = now
        credential.last_failure_status = getattr(error, "status_code", None)
        credential.last_validated_at = now
        usage.record(
            tenant_id=credential.tenant_id,
            credential_id=credential.id,
            job_id=None,
            project_id=credential.project_id,
            provider=provider.name,
            model=target_model,
            purpose="validate",
            prompt_version_id=None,
            input_tokens=None,
            output_tokens=None,
            cached_tokens=None,
            cost_usd=None,
            reported=False,
            success=False,
            request_id=None,
            latency_ms=None,
            http_status=getattr(error, "status_code", None),
            error_class=type(error).__name__,
        )
        session.commit()
        return {
            "credential_id": credential.id,
            "health": credential.health,
            "valid": False,
            "detail": credential.last_error,
        }

    credential.health = "HEALTHY"
    credential.last_error = None
    credential.last_success_at = now
    credential.last_validated_at = now
    credential.cooldown_until = None
    usage.record(
        tenant_id=credential.tenant_id,
        credential_id=credential.id,
        job_id=None,
        project_id=credential.project_id,
        provider=provider.name,
        model=target_model,
        purpose="validate",
        prompt_version_id=None,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cached_tokens=response.usage.cached_tokens,
        cost_usd=None,
        reported=response.usage.reported,
        success=True,
        request_id=response.provider_request_id,
        latency_ms=response.latency_ms,
        http_status=200,
        error_class=None,
    )
    session.commit()
    return {
        "credential_id": credential.id,
        "health": credential.health,
        "valid": True,
        "detail": None,
    }


def set_enabled(
    session: Session, credential: ProviderCredential, *, enabled: bool
) -> ProviderCredential:
    """Disabling is a health state, not a delete: history and the key survive."""

    if enabled:
        if credential.health == "DISABLED":
            credential.health = "UNKNOWN"
            credential.cooldown_until = None
    else:
        credential.health = "DISABLED"
    session.commit()
    return credential


def remove_credential(
    session: Session, settings: Settings, credential: ProviderCredential
) -> str:
    """Retire a key, deleting the row only when it has never been used.

    `provider_usage` is append-only at the database layer (ADR-022), so deleting
    a credential whose usage rows exist would make the FK's ``SET NULL`` issue an
    UPDATE the guard rejects.  A used key is therefore disabled and its
    ciphertext replaced with an encrypted empty string: no reusable secret
    remains, and the ledger keeps its provenance.  Returns ``retired`` or
    ``deleted`` for the audit record.
    """

    used = int(
        session.scalar(
            select(func.count(ProviderUsage.id)).where(
                ProviderUsage.credential_id == credential.id
            )
        )
        or 0
    )
    if used:
        credential.health = "DISABLED"
        credential.encrypted_secret = _box(settings).encrypt("")
        credential.last_error = (
            "Removed by a platform administrator; usage history is retained."
        )
        credential.cooldown_until = None
        session.commit()
        return "retired"
    CredentialRepository(session).delete(credential)
    session.commit()
    return "deleted"


def _models(settings: Settings) -> list[str]:
    seen: dict[str, None] = {}
    for model in (
        settings.provider.model_primary,
        settings.provider.model_review,
        *settings.quota.model_limits.keys(),
    ):
        seen.setdefault(model, None)
    return list(seen)


def fleet_overview(session: Session, settings: Settings) -> dict[str, Any]:
    credentials = CredentialRepository(session).all_credentials()
    usage = UsageRepository(session)
    quota = QuotaEstimator(session, settings)
    now = utcnow()
    start = day_start(now, settings.quota.daily_reset_timezone)
    today = usage.window_stats(start)

    by_health: dict[str, int] = {}
    projects: dict[str, list[ProviderCredential]] = {}
    for credential in credentials:
        by_health[credential.health] = by_health.get(credential.health, 0) + 1
        projects.setdefault(credential.project_id, []).append(credential)

    project_rows: list[dict[str, Any]] = []
    for project_id, keys in sorted(projects.items()):
        estimates = quota.project_estimates(project_id, _models(settings), now)
        project_rows.append(
            {
                "project_id": project_id,
                "keys": len(keys),
                "healthy": sum(1 for key in keys if key.health == "HEALTHY"),
                "disabled": sum(1 for key in keys if key.health == "DISABLED"),
                "invalid": sum(1 for key in keys if key.health == "INVALID"),
                "cooldown_until": max(
                    (key.cooldown_until for key in keys if key.cooldown_until), default=None
                ),
                "estimates": [estimate.as_dict() for estimate in estimates],
            }
        )

    error_rate = today["failures"] / today["requests"] if today["requests"] else None
    return {
        "keys_total": len(credentials),
        "keys_by_health": by_health,
        "projects": len(projects),
        "requests_today": today["requests"],
        "input_tokens_today": today["input_tokens"],
        "output_tokens_today": today["output_tokens"],
        "failures_today": today["failures"],
        "error_rate_today": error_rate,
        "observed_at": now,
        "day_started_at": start,
        "reset_at": next_reset(now, settings.quota.daily_reset_timezone),
        "projects_detail": project_rows,
    }


def fleet_alerts(session: Session, settings: Settings) -> list[dict[str, Any]]:
    """Alerts are derived from recorded state; none is speculative."""

    credentials = CredentialRepository(session).all_credentials()
    usage = UsageRepository(session)
    reservations = QuotaReservationRepository(session)
    quota = QuotaEstimator(session, settings)
    now = utcnow()
    start = day_start(now, settings.quota.daily_reset_timezone)
    alerts: list[dict[str, Any]] = []

    projects: dict[str, list[ProviderCredential]] = {}
    for credential in credentials:
        projects.setdefault(credential.project_id, []).append(credential)

    for project_id, keys in sorted(projects.items()):
        cooldown = reservations.project_cooldown(project_id)
        if cooldown is not None and cooldown.cooldown_until > now:
            alerts.append(
                {
                    "severity": "critical",
                    "kind": "project_cooldown",
                    "project_id": project_id,
                    "message": (
                        f"Project {project_id} is paused until "
                        f"{cooldown.cooldown_until.isoformat()} — {cooldown.reason}"
                    ),
                }
            )
        invalid = [key for key in keys if key.health == "INVALID"]
        if invalid:
            alerts.append(
                {
                    "severity": "critical",
                    "kind": "invalid_credentials",
                    "project_id": project_id,
                    "message": (
                        f"{len(invalid)} key(s) in {project_id} were rejected by Google "
                        "and need rotation or removal."
                    ),
                }
            )
        disabled = [key for key in keys if key.health == "DISABLED"]
        if disabled and len(disabled) == len(keys):
            alerts.append(
                {
                    "severity": "warning",
                    "kind": "project_unusable",
                    "project_id": project_id,
                    "message": f"Every key in {project_id} is disabled.",
                }
            )

        for estimate in quota.project_estimates(project_id, _models(settings), now):
            for label, window in (
                ("requests/minute", estimate.requests_per_minute),
                ("tokens/minute", estimate.tokens_per_minute),
                ("requests/day", estimate.requests_per_day),
            ):
                share = window.used_share
                if share is None:
                    continue
                if share >= 1.0:
                    alerts.append(
                        {
                            "severity": "critical",
                            "kind": "quota_exhausted",
                            "project_id": project_id,
                            "message": (
                                f"{project_id} has no {label} left for "
                                f"{estimate.model} ({window.confidence.lower()} limit)."
                            ),
                        }
                    )
                elif share >= settings.quota.alert_threshold:
                    alerts.append(
                        {
                            "severity": "warning",
                            "kind": "quota_approaching",
                            "project_id": project_id,
                            "message": (
                                f"{project_id} has used {share:.0%} of its {label} for "
                                f"{estimate.model} ({window.confidence.lower()} limit)."
                            ),
                        }
                    )

    window = usage.window_stats(start)
    if window["requests"] >= 20 and window["failures"] / window["requests"] > 0.2:
        alerts.append(
            {
                "severity": "warning",
                "kind": "error_rate",
                "project_id": None,
                "message": (
                    f"{window['failures']} of {window['requests']} provider calls failed "
                    "today; check the provider status before the queue backs up."
                ),
            }
        )
    recent = usage.recent_failures(limit=50)
    if recent:
        newest = recent[0].created_at
        if newest > now - timedelta(minutes=15):
            alerts.append(
                {
                    "severity": "info",
                    "kind": "recent_failure",
                    "project_id": recent[0].project_id,
                    "message": (
                        f"The most recent provider failure was "
                        f"{recent[0].error_class or 'an error'} at {newest.isoformat()}."
                    ),
                }
            )
    return alerts
