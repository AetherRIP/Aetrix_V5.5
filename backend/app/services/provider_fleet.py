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
from ..providers.base import LLMProvider, LLMRequest, ProviderNotConfigured, TokenUsage
from ..providers.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTransientError,
    ProviderTruncatedResponse,
    category_for_legacy_error,
    failure_category,
)
from .google_quota import (
    PROJECT_VERIFICATION_FALLBACK,
    is_stale,
    verification_summary,
)
from .quota import QuotaEstimator, day_start, next_reset, quota_timezone

MAX_PROJECT_ID_LENGTH = 100
MAX_LABEL_LENGTH = 120

#: A validation probe is one tiny completion.  It must leave room for a thinking
#: model's reasoning *and* the answer: with a smaller budget Gemini 3.6 burned
#: four tokens thinking, returned MAX_TOKENS and no content, and every valid key
#: looked broken.
VALIDATION_MAX_OUTPUT_TOKENS = 64
VALIDATION_TIMEOUT_SECONDS = 15
VALIDATION_PROMPT = "Reply with the single word: ok"


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
    contributor_id: uuid.UUID | None = None,
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
        contributor_id=contributor_id,
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


#: A project id is supplied by an operator.  Nothing in this build can prove
#: that a key belongs to that Google Cloud project, so no row is labelled
#: VERIFIED.
PROJECT_VERIFICATION = "OPERATOR_DECLARED"


@dataclass(frozen=True, slots=True)
class ValidationVerdict:
    #: Credential validity only.  None means "this failure does not judge it".
    health: str | None
    category: str
    recommendation: str


def classify_validation_error(error: ProviderError) -> ValidationVerdict:
    """Turn a provider failure into a health state and an operator action.

    The distinction matters: a 401 says the key is bad, a 429 says the project is
    throttled, a timeout says nothing about the key, and a truncated answer says
    nothing about the credential at all.  None of them may be reported as the
    others.
    """

    status = error.status_code
    if isinstance(error, ProviderAuthenticationError):
        return ValidationVerdict(
            "INVALID",
            "authentication",
            "Google rejected this key (401). Confirm the key is not revoked, then rotate it.",
        )
    if isinstance(error, ProviderPermissionError):
        return ValidationVerdict(
            None,
            "permission",
            "Google accepted the request but refused access (403). Check that the "
            "Generative Language API is enabled, the key restriction allows it and the "
            "project can use this model. The key itself was not proven invalid.",
        )
    if isinstance(error, ProviderQuotaError):
        return ValidationVerdict(
            None,
            "quota",
            "The project is rate-limited or out of quota. Wait for the window to reset "
            "or raise the limit; retrying the same key now cannot succeed.",
        )
    if isinstance(error, ProviderNetworkError):
        return ValidationVerdict(
            None,
            "network",
            "Google could not be reached. This does not show the key is bad; retry shortly.",
        )
    if isinstance(error, ProviderServerError):
        return ValidationVerdict(
            None,
            "provider_server",
            "Google returned a server error. The credential was not judged; retry shortly.",
        )
    if isinstance(error, ProviderTransientError):
        return ValidationVerdict(
            None,
            "network" if status is None else "provider_server",
            "The provider was unavailable. This does not show the key is bad; retry shortly.",
        )
    if isinstance(error, ProviderTruncatedResponse):
        return ValidationVerdict(
            None,
            "provider_response",
            "Google answered but produced no text within the output budget. The key was "
            "not rejected; retry, and check the model's thinking configuration.",
        )
    if isinstance(error, ProviderRequestError) and status == 404:
        return ValidationVerdict(
            None,
            "unsupported_model",
            "The configured model is not available to this key or project. Choose a model "
            "the project can access.",
        )
    if isinstance(error, ProviderRequestError):
        return ValidationVerdict(
            None,
            "invalid_request",
            "The request was rejected before the key could be judged. Check the API "
            "version, model id and request shape.",
        )
    if isinstance(error, ProviderResponseError):
        return ValidationVerdict(
            None,
            "provider_response",
            "Google answered but the response was unusable. The key itself was not "
            "rejected.",
        )
    return ValidationVerdict(
        None,
        "internal",
        "The provider failed without a classified reason. Check the engine log.",
    )


def usage_category(row: ProviderUsage | None) -> str | None:
    if row is None:
        return None
    return row.error_category or category_for_legacy_error(
        row.error_class, row.http_status
    )


def operational_status(
    *,
    health: str,
    revoked: bool,
    cooldown_until: Any,
    latest: ProviderUsage | None,
    now: Any,
) -> str:
    """Recent operational state, deliberately separate from credential validity."""

    if revoked or health == "DISABLED":
        return "DISABLED"
    if cooldown_until is not None and cooldown_until > now:
        return "RATE_LIMITED"
    if latest is None:
        return "NOT_TESTED"
    if latest.success:
        return "OPERATIONAL"
    category = usage_category(latest)
    if category == "quota":
        return "RATE_LIMITED"
    if category == "network":
        return "NETWORK_FAILURE"
    if category == "provider_server":
        return "PROVIDER_UNAVAILABLE"
    return "DEGRADED"


def operational_from_error(error: ProviderError) -> str:
    if isinstance(error, ProviderQuotaError):
        return "RATE_LIMITED"
    if isinstance(error, ProviderNetworkError):
        return "NETWORK_FAILURE"
    if isinstance(error, ProviderServerError):
        return "PROVIDER_UNAVAILABLE"
    if isinstance(error, ProviderTransientError):
        return (
            "NETWORK_FAILURE"
            if error.status_code is None
            else "PROVIDER_UNAVAILABLE"
        )
    return "DEGRADED"


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
    one request it spends is visible rather than hidden.  Only the named
    credential is ever tried: silently substituting a sibling would report a
    usable fleet while the selected key stayed broken.
    """

    # Two concurrent clicks must serialise on the row, or the second can
    # overwrite the first's health with a stale copy of the credential object.
    locked = session.get(ProviderCredential, credential.id, with_for_update=True)
    if locked is not None:
        credential = locked

    box = _box(settings)
    # Prefer a model the credential was registered for; fall back to the primary
    # only when the key declares no access at all.
    if model:
        target_model = model
    elif credential.model_access:
        target_model = credential.model_access[0]
    else:
        from .model_catalogue import selected_model

        target_model = selected_model(session, settings, "primary")
    usage = UsageRepository(session)
    request = LLMRequest(
        model=target_model,
        prompt=VALIDATION_PROMPT,
        temperature=0.0,
        max_output_tokens=VALIDATION_MAX_OUTPUT_TOKENS,
        timeout_seconds=VALIDATION_TIMEOUT_SECONDS,
    )
    now = utcnow()
    base: dict[str, Any] = {
        "credential_id": credential.id,
        "model": target_model,
        "checked_at": now,
        "key_fingerprint": credential.key_fingerprint,
        "project_id": credential.project_id,
        "account_label": credential.account_label,
    }
    try:
        response = provider.generate(request, SecretStr(box.decrypt(credential.encrypted_secret)))
    except ProviderNotConfigured:
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The live provider is disabled in this build; the key was not validated.",
        ) from None
    except ProviderError as error:
        verdict = classify_validation_error(error)
        # Only a 401 changes validity.  A timeout, 403, 429, 5xx or parser
        # failure leaves the last authentication verdict intact.
        if verdict.health is not None:
            credential.health = verdict.health
        credential.last_error = f"{type(error).__name__}: {error}"[:400]
        credential.last_failure_at = now
        credential.last_failure_status = error.status_code
        credential.last_validated_at = now
        if verdict.category == "quota":
            QuotaReservationRepository(session).set_project_cooldown(
                project_id=credential.project_id,
                reason=f"Validation probe rate-limited: {error}",
                cooldown_until=now
                + timedelta(seconds=settings.quota.cooldown_seconds),
            )
        error_usage = error.usage or TokenUsage()
        usage.record(
            tenant_id=credential.tenant_id,
            credential_id=credential.id,
            contributor_id=credential.contributor_id,
            job_id=None,
            project_id=credential.project_id,
            provider=provider.name,
            model=target_model,
            purpose="validate",
            prompt_version_id=None,
            input_tokens=error_usage.input_tokens,
            output_tokens=error_usage.output_tokens,
            cached_tokens=error_usage.cached_tokens,
            cost_usd=None,
            reported=error_usage.reported,
            success=False,
            request_id=error.provider_request_id,
            latency_ms=error.latency_ms,
            http_status=error.status_code,
            error_class=type(error).__name__,
            error_category=failure_category(error),
            provider_code=error.provider_code,
            provider_message=error.provider_message,
            reached_provider=error.reached_provider,
            finish_reason=error.provider_code,
        )
        session.commit()
        return {
            **base,
            "health": credential.health,
            "operational_status": operational_from_error(error),
            "valid": False,
            "detail": credential.last_error,
            "category": verdict.category,
            "http_status": error.status_code,
            "provider_code": error.provider_code,
            "provider_message": error.provider_message,
            "reached_provider": error.reached_provider,
            "recommendation": verdict.recommendation,
            "latency_ms": error.latency_ms,
        }

    credential.health = "HEALTHY"
    credential.last_success_at = now
    credential.last_validated_at = now
    credential.cooldown_until = None
    usage.record(
        tenant_id=credential.tenant_id,
        credential_id=credential.id,
        contributor_id=credential.contributor_id,
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
        reached_provider=True,
        finish_reason=response.finish_reason,
    )
    session.commit()
    return {
        **base,
        "health": credential.health,
        "operational_status": "OPERATIONAL",
        "valid": True,
        "detail": None,
        "category": "ok",
        "http_status": 200,
        "provider_code": None,
        "provider_message": None,
        "reached_provider": True,
        "recommendation": None,
        "latency_ms": response.latency_ms,
    }


def set_enabled(
    session: Session, credential: ProviderCredential, *, enabled: bool
) -> ProviderCredential:
    """Disabling is a health state, not a delete: history and the key survive.

    A revoked key is never re-enabled here: revocation destroyed its ciphertext,
    so "enabled" would only produce a credential that cannot authenticate.  A
    contributor who wants back in registers a new key.
    """

    if credential.revoked_at is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            "This key was revoked; a withdrawn credential cannot be re-enabled.",
        )
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
        credential.revoked_at = utcnow()
        credential.revoked_reason = "Removed by a platform administrator."
        credential.cooldown_until = None
        session.commit()
        return "retired"
    CredentialRepository(session).delete(credential)
    session.commit()
    return "deleted"


def _models(
    settings: Settings, credentials: Iterable[ProviderCredential] = ()
) -> list[str]:
    seen: dict[str, None] = {}
    for model in (
        settings.provider.model_primary,
        settings.provider.model_review,
        *settings.quota.model_limits.keys(),
    ):
        seen.setdefault(model, None)
    for credential in credentials:
        for model in credential.model_access or []:
            seen.setdefault(model, None)
    return list(seen)


def _project_operational(
    keys: list[ProviderCredential],
    latest: ProviderUsage | None,
    *,
    now: Any,
    cooldown_until: Any,
) -> str:
    if keys and all(key.health == "DISABLED" or key.revoked_at for key in keys):
        return "DISABLED"
    status = operational_status(
        health="HEALTHY",
        revoked=False,
        cooldown_until=cooldown_until,
        latest=latest,
        now=now,
    )
    if status == "OPERATIONAL" and any(key.health == "INVALID" for key in keys):
        return "DEGRADED"
    return status


def fleet_overview(session: Session, settings: Settings) -> dict[str, Any]:
    credentials = CredentialRepository(session).all_credentials()
    usage = UsageRepository(session)
    quota = QuotaEstimator(session, settings)
    now = utcnow()
    zone = settings.quota.daily_reset_timezone
    _, effective_zone = quota_timezone(zone)
    start = day_start(now, zone)
    today = usage.window_stats(start)
    latest_calls = usage.recent_calls(1)
    latest_success = usage.latest_success()
    latest_failures = usage.latest_failures(1)
    latest_failure = latest_failures[0] if latest_failures else None
    latest_project = usage.latest_by_project(sorted({c.project_id for c in credentials}))

    by_health: dict[str, int] = {}
    projects: dict[str, list[ProviderCredential]] = {}
    for credential in credentials:
        by_health[credential.health] = by_health.get(credential.health, 0) + 1
        projects.setdefault(credential.project_id, []).append(credential)

    project_rows: list[dict[str, Any]] = []
    verifications = verification_summary(session, sorted(projects))
    for project_id, keys in sorted(projects.items()):
        estimates = quota.project_estimates(project_id, _models(settings, keys), now)
        cooldown_until = max(
            (key.cooldown_until for key in keys if key.cooldown_until), default=None
        )
        verification = verifications.get(project_id)
        verification_status = (
            verification.verification_status
            if verification is not None
            else PROJECT_VERIFICATION_FALLBACK
        )
        project_rows.append(
            {
                "project_id": project_id,
                "verification": verification_status,
                "verified": verification_status == "VERIFIED",
                "project_number": (
                    verification.project_number if verification is not None else None
                ),
                "google_last_attempt_at": (
                    verification.last_attempt_at if verification is not None else None
                ),
                "google_quota_last_synced_at": (
                    verification.last_success_at if verification is not None else None
                ),
                "google_quota_stale": is_stale(
                    verification.last_success_at if verification is not None else None,
                    now,
                    settings.google_cloud.stale_after_seconds,
                ),
                "keys": len(keys),
                "contributors": len(
                    {key.contributor_id for key in keys if key.contributor_id is not None}
                ),
                "healthy": sum(1 for key in keys if key.health == "HEALTHY"),
                "unknown": sum(1 for key in keys if key.health == "UNKNOWN"),
                "disabled": sum(1 for key in keys if key.health == "DISABLED"),
                "invalid": sum(1 for key in keys if key.health == "INVALID"),
                "cooldown_until": cooldown_until,
                "operational_status": _project_operational(
                    keys,
                    latest_project.get(project_id),
                    now=now,
                    cooldown_until=cooldown_until,
                ),
                "estimates": [estimate.as_dict() for estimate in estimates],
            }
        )

    latest = latest_calls[0] if latest_calls else None
    operational = operational_status(
        health="HEALTHY",
        revoked=False,
        cooldown_until=None,
        latest=latest,
        now=now,
    )
    if operational == "OPERATIONAL" and by_health.get("INVALID", 0):
        operational = "DEGRADED"
    error_rate = today["failures"] / today["attempted"] if today["attempted"] else None
    return {
        "keys_total": len(credentials),
        "external_keys": sum(1 for key in credentials if key.contributor_id is not None),
        "platform_keys": sum(1 for key in credentials if key.contributor_id is None),
        "keys_by_health": by_health,
        "projects": len(projects),
        "declared_projects": len(projects),
        "verified_projects": sum(1 for row in project_rows if row["verified"]),
        "project_verification": (
            "GOOGLE_CLOUD"
            if any(row["verified"] for row in project_rows)
            else PROJECT_VERIFICATION
        ),
        "attempted_today": today["attempted"],
        "requests_today": today["attempted"],
        "successful_today": today["successes"],
        "input_tokens_today": today["input_tokens"],
        "output_tokens_today": today["output_tokens"],
        "failures_today": today["failures"],
        "reported_requests_today": today["reported_requests"],
        "error_rate_today": error_rate,
        "operational_status": operational,
        "last_success_at": latest_success.created_at if latest_success else None,
        "last_failure_at": latest_failure.created_at if latest_failure else None,
        "last_failure_category": usage_category(latest_failure),
        "last_failure_message": (
            (latest_failure.provider_message or latest_failure.error_class)
            if latest_failure
            else None
        ),
        "observed_at": now,
        "day_started_at": start,
        "reset_at": next_reset(now, zone),
        "reset_timezone": effective_zone,
        "quota_accounting": "AETRIX_RESERVATIONS_PLUS_VALIDATION",
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

        for estimate in quota.project_estimates(project_id, _models(settings, keys), now):
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
                        f"{usage_category(recent[0]) or recent[0].error_class or 'an error'}"
                        f" at {newest.isoformat()}."
                    ),
                }
            )
    return alerts
