"""The provider call path: prompt, credential, quota, usage, retry.

No route calls a provider directly.  This service makes the provider boundary
auditable:

* the prompt asset and its version are resolved before the call;
* a credential is leased from the database with a quota reservation;
* every attempt is written to the append-only usage ledger with token and cost
  accounting;
* authentication failures invalidate only that credential, quota failures put it
  into cooldown, and transient failures may move to another credential;
* keys are decrypted at the point of use and never included in a result, log or
  audit record.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from pydantic import SecretStr
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import SecretBox
from ..db.models import ProviderCredential, ProviderQuotaReservation
from ..db.repositories import (
    CredentialRepository,
    PromptVersionRepository,
    QuotaReservationRepository,
    UsageRepository,
)
from ..prompts.registry import PromptAsset, PromptRegistry
from ..providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderNotConfigured,
    TokenUsage,
)
from ..providers.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaError,
    ProviderTransientError,
    failure_category,
)
from ..providers.pricing import estimate_cost, rate_for
from .quota import day_start


@dataclass(frozen=True, slots=True)
class CredentialLease:
    credential_id: uuid.UUID
    reservation_id: uuid.UUID
    api_key: SecretStr
    health: str
    #: The Google Cloud project the key bills against: the unit of quota.
    project_id: str
    #: Null for a platform-owned key; set when the key was contributed.
    contributor_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ProviderCallResult:
    response: LLMResponse
    usage_id: uuid.UUID
    prompt: PromptAsset
    prompt_version_id: uuid.UUID
    cost_usd: Decimal | None
    provider_name: str


class CredentialPool:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.credentials = CredentialRepository(session)
        self.reservations = QuotaReservationRepository(session)
        if settings.security.encryption_key is None:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "Credential encryption is not configured; provider calls cannot be made.",
            )
        self._box = SecretBox(settings.security.encryption_key.get_secret_value())

    def _within_quota(self, project_id: str, model: str) -> bool:
        """Count against the project, never against the key alone.

        Ten keys in one Google Cloud project share one free-tier allowance.  If
        this counted per credential, rotation would multiply the real limit and
        the fleet would answer 429s all day while believing it had capacity.
        """

        now = utcnow()
        limits = self.settings.quota.model_limits.get(model)
        per_minute = (
            limits.requests_per_minute
            if limits and limits.requests_per_minute is not None
            else self.settings.quota.requests_per_minute
        )
        per_day = (
            limits.requests_per_day
            if limits and limits.requests_per_day is not None
            else self.settings.quota.requests_per_day
        )
        minute_since = now - timedelta(minutes=1)
        day_since = day_start(now, self.settings.quota.daily_reset_timezone)
        minute = self.reservations.count_since_project(
            project_id, minute_since, now, model=model
        ) + self.usage.validation_count(project_id, model, minute_since)
        # The daily allowance resets at local midnight in the configured quota
        # zone (Pacific by default), not at a rolling UTC 24-hour boundary.
        day = self.reservations.count_since_project(
            project_id,
            day_since,
            now,
            model=model,
        ) + self.usage.validation_count(project_id, model, day_since)
        return minute < per_minute and day < per_day

    def _project_in_cooldown(self, project_id: str) -> bool:
        cooldown = self.reservations.project_cooldown(project_id)
        return cooldown is not None and cooldown.cooldown_until > utcnow()

    def acquire(
        self,
        *,
        tenant_id: uuid.UUID,
        model: str,
        purpose: str,
        excluded: set[uuid.UUID] | None = None,
    ) -> CredentialLease:
        excluded = excluded or set()
        # ``claim_candidates`` already excludes keys whose contributor is not
        # ACTIVE or whose contributor revoked them, so a withdrawal takes effect
        # before the next lease rather than at the next health sweep.
        candidates = self.credentials.claim_candidates(tenant_id, model, excluded)
        cooling_projects: set[str] = set()
        for credential in candidates:
            project_id = credential.project_id
            if project_id in cooling_projects:
                continue
            if self._project_in_cooldown(project_id):
                cooling_projects.add(project_id)
                continue
            if not self._within_quota(project_id, model):
                cooling_projects.add(project_id)
                continue
            api_key = SecretStr(self._box.decrypt(credential.encrypted_secret))
            reservation = self.reservations.reserve(
                tenant_id=tenant_id,
                credential_id=credential.id,
                model=model,
                purpose=purpose,
                ttl_seconds=self.settings.quota.reservation_ttl_seconds,
            )
            # Release the row lock before the external call.  The reservation is
            # the durable count; holding a transaction for 30-300 seconds would
            # block every other caller.
            self.session.commit()
            return CredentialLease(
                credential_id=credential.id,
                reservation_id=reservation.id,
                api_key=api_key,
                health=credential.health,
                project_id=project_id,
                contributor_id=credential.contributor_id,
            )
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "No provider credential is available within its project's quota.",
            details={"model": model},
        )

    def _finish(
        self,
        lease: CredentialLease,
        *,
        status: str,
        health: str | None,
        error: str | None = None,
        status_code: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        credential = self.session.get(ProviderCredential, lease.credential_id)
        reservation = self.session.get(ProviderQuotaReservation, lease.reservation_id)
        now = utcnow()
        if reservation is not None:
            reservation.status = status
        if credential is not None:
            # ``health`` is None for operational failures.  A timeout, 403 or
            # 5xx does not erase the last authentication verdict.
            if health is not None:
                credential.health = health
            if health == "HEALTHY":
                credential.last_success_at = now
                credential.cooldown_until = None
            else:
                credential.last_failure_at = now
                credential.last_failure_status = status_code
                # Keep the last failure even after a later success: the key may
                # be healthy now, and the operator still needs to know what
                # broke and when.
                credential.last_error = error[:400] if error else None
                if health is not None and health != "HEALTHY":
                    credential.last_failure_at = now
                if cooldown_seconds:
                    credential.cooldown_until = now + timedelta(seconds=cooldown_seconds)
        self.session.commit()

    def success(self, lease: CredentialLease) -> None:
        # A successful call proves the project is usable again, so a stale
        # project-wide pause is lifted rather than left to expire.
        self.reservations.clear_project_cooldown(lease.project_id)
        self._finish(lease, status="CONSUMED", health="HEALTHY")

    def project_cooldown(self, lease: CredentialLease, seconds: int, reason: str) -> None:
        """Pause every key in the project: the 429 is shared, not personal."""

        self.reservations.set_project_cooldown(
            project_id=lease.project_id,
            reason=reason,
            cooldown_until=utcnow() + timedelta(seconds=seconds),
        )
        self.session.commit()

    def failure(
        self,
        lease: CredentialLease,
        *,
        health: str | None = None,
        error: str,
        status_code: int | None = None,
        count_toward_quota: bool = True,
        cooldown_seconds: int | None = None,
    ) -> None:
        self._finish(
            lease,
            status="CONSUMED" if count_toward_quota else "RELEASED",
            health=health,
            error=error,
            status_code=status_code,
            cooldown_seconds=cooldown_seconds,
        )


class ProviderCallService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        provider: LLMProvider,
        registry: PromptRegistry,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.registry = registry
        self.pool = CredentialPool(session, settings)
        self.usage = UsageRepository(session)
        self.prompt_versions = PromptVersionRepository(session)

    def _model_for(self, role: str) -> str:
        # The saved selection is authoritative; the environment is only the
        # fallback before an operator has chosen a model.
        from .model_catalogue import selected_model

        return selected_model(
            self.session,
            self.settings,
            "review" if role == "review" else "primary",
        )

    def _record(
        self,
        *,
        tenant_id: uuid.UUID,
        lease: CredentialLease | None,
        job_id: uuid.UUID | None,
        model: str,
        purpose: str,
        prompt_version_id: uuid.UUID,
        usage: TokenUsage,
        success: bool,
        request_id: str | None,
        latency_ms: int | None,
        http_status: int | None,
        error_class: str | None,
        error_category: str | None = None,
        provider_code: str | None = None,
        provider_message: str | None = None,
        reached_provider: bool | None = None,
        finish_reason: str | None = None,
        retry_count: int = 0,
    ) -> tuple[uuid.UUID, Decimal | None]:
        cost = estimate_cost(rate_for(self.settings, model), usage) if success else None
        row = self.usage.record(
            tenant_id=tenant_id,
            credential_id=lease.credential_id if lease else None,
            contributor_id=lease.contributor_id if lease else None,
            job_id=job_id,
            project_id=lease.project_id if lease else "unattributed",
            retry_count=retry_count,
            provider=self.provider.name,
            model=model,
            purpose=purpose,
            prompt_version_id=prompt_version_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            cost_usd=cost,
            reported=usage.reported,
            success=success,
            request_id=request_id,
            latency_ms=latency_ms,
            http_status=http_status,
            error_class=error_class,
            error_category=error_category,
            provider_code=provider_code,
            provider_message=provider_message,
            reached_provider=reached_provider,
            finish_reason=finish_reason,
        )
        return row.id, cost

    def call(
        self,
        *,
        tenant_id: uuid.UUID,
        purpose: str,
        prompt_id: str,
        inputs: tuple[Any, ...] = (),
        job_id: uuid.UUID | None = None,
        prompt_version: int | None = None,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int = 16384,
    ) -> ProviderCallResult:
        asset = self.registry.load(prompt_id, prompt_version)
        prompt_row = self.prompt_versions.get_or_create(
            prompt_id=asset.prompt_id,
            version=asset.version,
            content_hash=asset.content_hash,
            path=asset.path,
            model_role=asset.model_role,
        )
        model = self._model_for(asset.model_role)
        request = LLMRequest(
            model=model,
            prompt=asset.content,
            inputs=tuple(inputs),
            response_schema=response_schema,
            max_output_tokens=max_output_tokens,
        )
        excluded: set[uuid.UUID] = set()
        last_error: ProviderError | None = None

        for attempt in range(self.settings.provider.max_attempts):
            lease = self.pool.acquire(
                tenant_id=tenant_id,
                model=model,
                purpose=purpose,
                excluded=excluded,
            )
            try:
                response = self.provider.generate(request, lease.api_key)
            except ProviderNotConfigured as error:
                self.pool.failure(
                    lease,
                    error=str(error),
                    count_toward_quota=False,
                )
                self._record(
                    tenant_id=tenant_id,
                    lease=lease,
                    job_id=job_id,
                    model=model,
                    purpose=purpose,
                    prompt_version_id=prompt_row.id,
                    usage=TokenUsage(),
                    success=False,
                    request_id=None,
                    latency_ms=None,
                    http_status=None,
                    error_class="ProviderNotConfigured",
                    error_category="configuration",
                    provider_message=str(error)[:300],
                    reached_provider=False,
                    retry_count=attempt,
                )
                self.session.commit()
                raise AppError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    str(error),
                ) from error
            except ProviderError as error:
                last_error = error
                is_auth = isinstance(error, ProviderAuthenticationError)
                is_quota = isinstance(error, ProviderQuotaError)
                is_transient = isinstance(error, ProviderTransientError)
                if is_auth or is_quota:
                    excluded.add(lease.credential_id)
                cooldown_seconds = (
                    int(error.retry_after_seconds)
                    if is_quota and error.retry_after_seconds
                    else None
                )
                # Only a 401 proves the credential invalid.  Permission, quota,
                # network and provider failures say nothing about validity.
                self.pool.failure(
                    lease,
                    health="INVALID" if is_auth else None,
                    error=f"{type(error).__name__}: {error}",
                    status_code=error.status_code,
                    count_toward_quota=not is_auth,
                    cooldown_seconds=cooldown_seconds,
                )
                if is_quota:
                    # Free-tier quota is shared by the project, so one 429 pauses
                    # every key under it; rotating to a sibling key would only
                    # produce another 429.
                    self.pool.project_cooldown(
                        lease,
                        seconds=cooldown_seconds or self.settings.quota.cooldown_seconds,
                        reason=f"Project quota exhausted: {error}",
                    )
                error_usage = error.usage or TokenUsage()
                self._record(
                    tenant_id=tenant_id,
                    lease=lease,
                    job_id=job_id,
                    model=model,
                    purpose=purpose,
                    prompt_version_id=prompt_row.id,
                    usage=error_usage,
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
                    retry_count=attempt,
                )
                self.session.commit()
                if is_auth or is_quota or is_transient:
                    if is_transient and attempt + 1 < self.settings.provider.max_attempts:
                        time.sleep(
                            min(
                                self.settings.provider.retry_backoff_seconds * (2**attempt),
                                10.0,
                            )
                        )
                    continue
                raise AppError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    "The provider rejected the request; retrying it unchanged cannot help.",
                    details={"status_code": error.status_code},
                ) from error
            except Exception as error:
                # An Aetrix-side defect is a failed attempt too.  It must not
                # leave a reservation RESERVED or vanish from the ledger.
                self.pool.failure(
                    lease,
                    error=f"Internal: {type(error).__name__}: {error}",
                    count_toward_quota=False,
                )
                self._record(
                    tenant_id=tenant_id,
                    lease=lease,
                    job_id=job_id,
                    model=model,
                    purpose=purpose,
                    prompt_version_id=prompt_row.id,
                    usage=TokenUsage(),
                    success=False,
                    request_id=None,
                    latency_ms=None,
                    http_status=None,
                    error_class=type(error).__name__,
                    error_category="internal",
                    provider_message=str(error)[:300],
                    reached_provider=False,
                    retry_count=attempt,
                )
                self.session.commit()
                raise
            else:
                usage_id, cost = self._record(
                    tenant_id=tenant_id,
                    lease=lease,
                    job_id=job_id,
                    model=model,
                    purpose=purpose,
                    prompt_version_id=prompt_row.id,
                    usage=response.usage,
                    success=True,
                    request_id=response.provider_request_id,
                    latency_ms=response.latency_ms,
                    http_status=200,
                    error_class=None,
                    reached_provider=True,
                    finish_reason=response.finish_reason,
                    retry_count=attempt,
                )
                self.pool.success(lease)
                return ProviderCallResult(
                    response=response,
                    usage_id=usage_id,
                    prompt=asset,
                    prompt_version_id=prompt_row.id,
                    cost_usd=cost,
                    provider_name=self.provider.name,
                )

        if last_error is not None:
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "The provider call exhausted its attempt budget. "
                f"Last failure: {type(last_error).__name__}.",
                details={"status_code": last_error.status_code},
            ) from last_error
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The provider call exhausted its attempt budget.",
        )
