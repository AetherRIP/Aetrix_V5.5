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
)
from ..providers.pricing import estimate_cost, rate_for


@dataclass(frozen=True, slots=True)
class CredentialLease:
    credential_id: uuid.UUID
    reservation_id: uuid.UUID
    api_key: SecretStr
    health: str


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

    def _within_quota(self, credential_id: uuid.UUID) -> bool:
        now = utcnow()
        minute = self.reservations.count_since(credential_id, now - timedelta(minutes=1), now)
        day = self.reservations.count_since(credential_id, now - timedelta(days=1), now)
        return (
            minute < self.settings.quota.requests_per_minute
            and day < self.settings.quota.requests_per_day
        )

    def acquire(
        self,
        *,
        tenant_id: uuid.UUID,
        model: str,
        purpose: str,
        excluded: set[uuid.UUID] | None = None,
    ) -> CredentialLease:
        excluded = excluded or set()
        candidates = self.credentials.claim_candidates(tenant_id, model, excluded)
        for credential in candidates:
            if not self._within_quota(credential.id):
                continue
            api_key = SecretStr(self._box.decrypt(credential.encrypted_secret))
            reservation = self.reservations.reserve(
                tenant_id=tenant_id,
                credential_id=credential.id,
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
            )
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "No provider credential is available within its quota.",
            details={"model": model},
        )

    def _finish(
        self,
        lease: CredentialLease,
        *,
        status: str,
        health: str,
        error: str | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        credential = self.session.get(ProviderCredential, lease.credential_id)
        reservation = self.session.get(ProviderQuotaReservation, lease.reservation_id)
        if reservation is not None:
            reservation.status = status
        if credential is not None:
            credential.health = health
            credential.last_error = error[:400] if error else None
            if health == "HEALTHY":
                credential.last_success_at = utcnow()
                credential.cooldown_until = None
            elif health == "COOLDOWN":
                credential.cooldown_until = utcnow() + timedelta(
                    seconds=cooldown_seconds or self.settings.quota.cooldown_seconds
                )
        self.session.commit()

    def success(self, lease: CredentialLease) -> None:
        self._finish(lease, status="CONSUMED", health="HEALTHY")

    def failure(
        self,
        lease: CredentialLease,
        *,
        health: str,
        error: str,
        count_toward_quota: bool = True,
        cooldown_seconds: int | None = None,
    ) -> None:
        self._finish(
            lease,
            status="CONSUMED" if count_toward_quota else "RELEASED",
            health=health,
            error=error,
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
        if role == "review":
            return self.settings.provider.model_review
        return self.settings.provider.model_primary

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
    ) -> tuple[uuid.UUID, Decimal | None]:
        cost = estimate_cost(rate_for(self.settings, model), usage) if success else None
        row = self.usage.record(
            tenant_id=tenant_id,
            credential_id=lease.credential_id if lease else None,
            job_id=job_id,
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
                    health="UNKNOWN",
                    error=str(error),
                    count_toward_quota=False,
                )
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
                self.pool.failure(
                    lease,
                    health="INVALID" if is_auth else ("COOLDOWN" if is_quota else "UNKNOWN"),
                    error=f"{type(error).__name__}: {error}",
                    count_toward_quota=not is_auth,
                    cooldown_seconds=(
                        int(error.retry_after_seconds)
                        if is_quota and error.retry_after_seconds
                        else None
                    ),
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
                    http_status=error.status_code,
                    error_class=type(error).__name__,
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
