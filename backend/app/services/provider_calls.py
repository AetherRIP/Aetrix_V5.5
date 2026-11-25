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

The service walks an ordered **model chain** for the prompt's role.  A model
fails, its attempt and credential budgets are spent, and the next entry is
tried.  Credential rotation (same model, another key) and model fallback
(different model) are separate decisions with separate ledger rows; see
``app/providers/routing.py`` for the policy and why a 429 inside one Google
Cloud project must not be answered by swapping keys.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import MODEL_CHAIN_ROLES, ModelChainEntry, Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.marking_policy import (
    PRODUCTION_MARKING_MODEL,
    is_disabled_marking_model,
    marking_model_problem,
)
from ..core.model_permissions import (
    AICapability,
    capability_for_call,
    capability_for_role,
    is_permitted,
    permission_problem,
    role_exhausted_problem,
)
from ..core.security import SecretBox
from ..db.models import (
    GoogleCloudProject,
    ProviderCredential,
    ProviderQuotaReservation,
)
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
from ..providers.circuit_breaker import CircuitBreaker
from ..providers.errors import (
    ProviderError,
)
from ..providers.pricing import estimate_cost, rate_for
from ..providers.retry import RetryPolicy, retry_delay
from ..providers.routing import (
    TRANSIENT_FAILURES,
    FailureKind,
    RoutingAction,
    classify_failure,
    decide,
)
from .quota import day_start

#: Shared breakers, one per configured (threshold, open_seconds) pair.
#:
#: A breaker that lives on one service instance would be re-armed for every call
#: and every parallel worker thread, which is the opposite of its purpose.  Keyed
#: by its own configuration so a test that changes the settings does not inherit
#: an unrelated open breaker.
_SHARED_BREAKERS: dict[tuple[int, float], CircuitBreaker] = {}
_SHARED_BREAKERS_LOCK = threading.Lock()


def shared_breaker(settings: Settings) -> CircuitBreaker:
    """The process-wide breaker for this deployment's configured policy."""

    key = (
        int(settings.provider.circuit_breaker_threshold),
        float(settings.provider.circuit_breaker_seconds),
    )
    with _SHARED_BREAKERS_LOCK:
        breaker = _SHARED_BREAKERS.get(key)
        if breaker is None:
            breaker = CircuitBreaker(threshold=key[0], open_seconds=key[1])
            _SHARED_BREAKERS[key] = breaker
        return breaker


#: The failures whose consumption nobody can state.  A 5xx or a lost connection
#: may or may not have been metered.  Deliberately *not* the whole transient set:
#: a truncated or unparseable 2xx was generated and billed, so releasing it (or
#: calling it unconfirmed) would understate the day's real spend.
_UNCONFIRMED_FAILURES = frozenset(
    {FailureKind.PROVIDER_SERVER, FailureKind.NETWORK}
)


def reservation_status_for(kind: FailureKind, error: ProviderError) -> str:
    """The honest state of one reservation after a failed attempt.

    Three outcomes, because two cannot describe a 5xx:

    ``CONSUMED``
        Google served or counted the request (a 2xx, or a 4xx it processed).
    ``RELEASED``
        The attempt provably spent no inference: a local configuration failure,
        an internal defect, a refused connection, or an adapter that recorded
        ``reached_provider=False``.
    ``UNCONFIRMED``
        The request may or may not have been metered and nobody can say: a 5xx or
        a transport failure.  Counted per minute, excluded from the daily total.

    ``RELEASED`` says nothing was *metered*; it is not a claim that the request
    never arrived.  A rejected credential reaches Google and is refused before
    any inference runs, so it consumes no tokens — but it did leave the process,
    and describing it as proof of non-delivery would be false.
    """

    if kind is FailureKind.AUTHENTICATION:
        # The 401 came back from Google: the request arrived and was refused
        # before inference.  Nothing was metered, so the allowance is untouched,
        # yet this is the one RELEASED case where ``reached_provider`` is not the
        # reason — the credential, not the transport, is what made it free.
        return "RELEASED"
    if error.reached_provider is False:
        # An adapter that can prove the request never left the process (a refused
        # connection, a local configuration failure) has not spent anything.
        return "RELEASED"
    if kind in _UNCONFIRMED_FAILURES:
        # ``None`` for ``reached_provider`` means "the request was sent and the
        # answer never arrived", which is exactly the case a timeout produces.
        return "UNCONFIRMED"
    return "CONSUMED"


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
    #: Zero-based position in the role's chain of the model that answered.
    model_chain_position: int = 0
    #: The models this call attempted, in order, whether or not they answered.
    models_attempted: tuple[str, ...] = ()
    #: Milliseconds spent waiting for the credential lease and reservation.
    queue_wait_ms: int | None = None


class CredentialPool:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.credentials = CredentialRepository(session)
        self.reservations = QuotaReservationRepository(session)
        self.usage = UsageRepository(session)
        if settings.security.encryption_key is None:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "Credential encryption is not configured; provider calls cannot be made.",
            )
        self._box = SecretBox(settings.security.encryption_key.get_secret_value())

    def allowance_problem(self, model: str) -> str | None:
        """Why no request may be spent against this model's allowance, or ``None``.

        A model with no configured daily limit has an **unknown** allowance, and
        an unknown allowance is not spent: falling back to the platform default
        would invent a limit nobody set and then refuse calls against it.  The
        message names the setting to change, so the refusal is actionable.
        """

        limits = self.settings.quota.model_limits.get(model)
        if limits is None or limits.requests_per_day is None:
            return (
                f"No daily request allowance is configured for {model}. "
                "Aetrix refuses to spend a request against an unknown allowance. "
                "Add the model to AETRIX_QUOTA__MODEL_LIMITS with a limit you can "
                "verify, then retry. No request was sent."
            )
        return None

    def verified_independent_project(
        self,
        *,
        tenant_id: uuid.UUID,
        model: str,
        excluded: set[uuid.UUID],
        projects_tried: set[str],
    ) -> bool:
        """Whether a spare credential bills a project Google has *verified*.

        A quota fallback across projects is a different Google Cloud project or it
        is nothing.  An operator-typed id that is a typo, a duplicate of the
        exhausted project or a deleted project would look like fresh capacity and
        spend an attempt to be told the same 429, so the switch is only taken when
        Resource Manager has confirmed the project exists.
        """

        if self.session is None:
            return False
        candidates = self.credentials.claim_candidates(tenant_id, model, excluded)
        spare = {
            credential.project_id
            for credential in candidates
            if credential.project_id not in projects_tried
        }
        if not spare:
            return False
        rows = self.session.scalars(
            select(GoogleCloudProject).where(
                GoogleCloudProject.project_id.in_(sorted(spare))
            )
        ).all()
        return any(row.verification_status == "VERIFIED" for row in rows)

    def _within_quota(self, project_id: str, model: str) -> bool:
        """Count against the project, never against the key alone.

        Ten keys in one Google Cloud project share one free-tier allowance.  If
        this counted per credential, rotation would multiply the real limit and
        the fleet would answer 429s all day while believing it had capacity.

        Two windows count differently on purpose.  A request whose consumption
        Google never confirmed still hits the per-minute gate, because retrying an
        overloaded model is what turns one outage into a storm; it is excluded
        from the daily gate, because twenty 503s served no paper and must not
        exhaust a day's allowance.
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
            project_id,
            minute_since,
            now,
            model=model,
            include_unconfirmed=True,
        ) + self.usage.validation_count(project_id, model, minute_since)
        # The daily allowance resets at local midnight in the configured quota
        # zone (Pacific by default), not at a rolling UTC 24-hour boundary.
        day = self.reservations.count_since_project(
            project_id,
            day_since,
            now,
            model=model,
        ) + self.usage.validation_count(project_id, model, day_since)
        if minute >= per_minute or day >= per_day:
            return False
        tokens_per_minute = (
            limits.tokens_per_minute
            if limits and limits.tokens_per_minute is not None
            else self.settings.quota.tokens_per_minute
        )
        if tokens_per_minute is None:
            return True
        spent = self.usage.tokens_since_project(project_id, model, minute_since)
        return spent < tokens_per_minute

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
        skip_projects: set[str] | None = None,
    ) -> CredentialLease:
        excluded = excluded or set()
        #: Projects a 429 has already proved exhausted for this model.  The
        #: answer is scoped to this call and this model: Gemini meters each
        #: model separately, so a flash-lite 429 says nothing about 2.5-flash.
        skipped = skip_projects or set()
        # ``claim_candidates`` already excludes keys whose contributor is not
        # ACTIVE or whose contributor revoked them, so a withdrawal takes effect
        # before the next lease rather than at the next health sweep.
        candidates = self.credentials.claim_candidates(tenant_id, model, excluded)
        cooling_projects: set[str] = set()
        for credential in candidates:
            project_id = credential.project_id
            if project_id in skipped:
                # Another key in an exhausted project would spend an attempt
                # to be told exactly what the 429 already said.
                continue
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

    def alternatives(
        self,
        *,
        tenant_id: uuid.UUID,
        model: str,
        excluded: set[uuid.UUID],
        projects_tried: set[str],
    ) -> tuple[bool, bool]:
        """Whether another key exists, and whether one bills a *different* project.

        The second answer is the only one that can recover a project-scoped 429.
        Treating every key as its own quota pool is exactly the mistake that
        turns 15 keys into one exhausted project retried 15 times.
        """

        candidates = self.credentials.claim_candidates(tenant_id, model, excluded)
        if not candidates:
            return False, False
        independent = any(
            credential.project_id not in projects_tried for credential in candidates
        )
        return True, independent

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
        reservation_status: str | None = None,
    ) -> None:
        """Close a reservation with an explicit, recorded outcome.

        ``reservation_status`` is the honest third state; ``count_toward_quota``
        remains for the two-state callers and is only consulted when no explicit
        status is given.
        """

        self._finish(
            lease,
            status=(
                reservation_status
                if reservation_status is not None
                else ("CONSUMED" if count_toward_quota else "RELEASED")
            ),
            health=health,
            error=error,
            status_code=status_code,
            cooldown_seconds=cooldown_seconds,
        )


class ProviderCallService:
    def __init__(
        self,
        session: Session | None,
        settings: Settings,
        provider: LLMProvider,
        registry: PromptRegistry,
        *,
        pool: CredentialPool | None = None,
        usage: UsageRepository | None = None,
        prompt_versions: PromptVersionRepository | None = None,
        acquire_lock: threading.Lock | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        # ``pool``/``usage``/``prompt_versions`` are injectable so the routing
        # path can be tested without a database.  Production passes none of
        # them and gets the SQL-backed implementations.
        self.session = session
        self.settings = settings
        self.provider = provider
        self.registry = registry
        self.pool = pool if pool is not None else CredentialPool(session, settings)
        self.usage = usage if usage is not None else UsageRepository(session)
        self.prompt_versions = (
            prompt_versions
            if prompt_versions is not None
            else PromptVersionRepository(session)
        )
        # Parallel correction creates one service per worker thread.  Quota is
        # counted in the database, but two threads can read the same count before
        # either reservation is committed; a process-wide lock around the lease
        # makes the read-and-reserve atomic without serialising the provider
        # call that follows.  It is opt-in: a sequential caller has nothing to
        # synchronise and pays nothing for it.
        self._acquire_lock = acquire_lock
        # A provider outage is a property of the model, not of one key, so the
        # breaker is shared by every call in this process unless a test injects
        # its own.
        self.breaker = breaker if breaker is not None else shared_breaker(settings)

    def _retry_policy(self) -> RetryPolicy:
        provider = self.settings.provider
        return RetryPolicy(
            backoff_seconds=provider.retry_backoff_seconds,
            max_backoff_seconds=provider.retry_max_backoff_seconds,
            jitter=provider.retry_jitter,
            transient_attempts=1 + provider.transient_retries,
        )

    def _commit(self) -> None:
        if self.session is not None:
            self.session.commit()

    def _settings_model(self, role: str) -> str:
        if role == "review":
            return self.settings.provider.model_review
        if role == "lightweight":
            return self.settings.provider.model_lightweight
        return self.settings.provider.model_primary

    def _model_for(self, role: str) -> str:
        """The single model a role resolves to, before the chain is walked.

        Kept as the stable answer to "which model will this paper be marked
        with": the operator's saved selection when there is one, otherwise the
        environment's role model.  ``model_chain`` starts from this model and
        continues into the configured fallbacks.
        """

        selection_role = "review" if role == "review" else "primary"
        if self.session is None:
            return self._settings_model(selection_role)
        from .model_catalogue import selected_model

        return selected_model(self.session, self.settings, selection_role)

    def _selected_model(self, role: str) -> str | None:
        """The operator's saved selection, when there is a database to read.

        For the marking role the saved value is checked against the production
        policy here, before any request is sent.  A legacy row that still names
        a Lite model fails loudly instead of quietly marking with it.
        """

        if self.session is None:
            return None
        from .model_catalogue import selected_model

        selected = selected_model(self.session, self.settings, role)
        if role == "primary":
            problem = marking_model_problem(selected)
            if problem is not None:
                raise AppError(
                    ErrorCode.CONFIGURATION_ERROR,
                    f"The primary model cannot mark a paper. {problem} Nothing "
                    "was marked and no fallback model was tried.",
                    details={
                        "role": role,
                        "model": selected,
                        "production_marking_model": PRODUCTION_MARKING_MODEL,
                    },
                )
        return selected

    def model_chain(
        self, role: str, *, capability: AICapability | None = None
    ) -> list[ModelChainEntry]:
        """The ordered models this role is permitted to call, selection first.

        The saved selection stays authoritative, so an operator who chose a model
        keeps it; the configured chain follows it and is what the call walks
        when that model fails.  A model appears once, and a disabled entry is
        skipped rather than deleted so it can be re-enabled without reordering.

        Every entry is then checked against the permission table for the
        capability the call performs.  A chain that names a reserved or disabled
        model is filtered, never trusted: configuring a fallback is not authorising
        it.  A role left with no permitted model raises an actionable error here,
        before a credential is leased, rather than running on whatever the chain
        happened to name.
        """

        resolved = role if role in MODEL_CHAIN_ROLES else "primary"
        check = capability if capability is not None else capability_for_role(resolved)
        chain: list[ModelChainEntry] = []
        candidates: list[ModelChainEntry] = []
        selected = self._selected_model(resolved)
        if selected and not is_disabled_marking_model(selected):
            candidates.append(ModelChainEntry(model=selected))
        for entry in self.settings.provider.model_chains.get(resolved) or []:
            if not entry.enabled:
                continue
            # A disabled Lite model is not merely deprioritised: it has no
            # automatic fallback route.  The filter is defence in depth behind
            # the configuration validator and the saved-selection check.
            if is_disabled_marking_model(entry.model):
                continue
            if any(existing.model == entry.model for existing in candidates):
                continue
            candidates.append(entry)
        if not candidates:
            # A deployment whose chain is disabled entirely still has the
            # environment's role model, which is then permission-checked below.
            candidates.append(ModelChainEntry(model=self._settings_model(resolved)))

        for entry in candidates:
            if is_permitted(entry.model, check):
                chain.append(entry)
        if not chain:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                role_exhausted_problem(
                    resolved, check, [entry.model for entry in candidates]
                ),
                details={
                    "role": resolved,
                    "capability": check.value,
                    "chain": [entry.model for entry in candidates],
                    "refusals": {
                        entry.model: permission_problem(entry.model, check)
                        for entry in candidates
                    },
                },
            )
        return chain

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
        model_role: str | None = None,
        chain_position: int | None = None,
        attempt_index: int | None = None,
        routing_decision: str | None = None,
        queue_wait_ms: int | None = None,
    ) -> tuple[uuid.UUID, Decimal | None]:
        # Cost is computed whenever the rate is known and tokens were reported,
        # including a failed attempt: Google bills tokens it generated before a
        # failure, and dropping that would understate the spend.  An unknown
        # rate stays None and is labelled, never written as zero.
        cost = (
            estimate_cost(rate_for(self.settings, model), usage)
            if usage.reported or success
            else None
        )
        cost_status = "KNOWN" if cost is not None else "COST_UNKNOWN"
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
            model_role=model_role,
            model_chain_position=chain_position,
            attempt_index=attempt_index,
            routing_decision=routing_decision,
            cost_status=cost_status,
            queue_wait_ms=queue_wait_ms,
        )
        return row.id, cost

    def _exhausted(
        self,
        *,
        chain: list[ModelChainEntry],
        attempted: list[str],
        last: str | None,
        marking: bool = False,
    ) -> AppError:
        if marking:
            message = (
                f"The production marking model {PRODUCTION_MARKING_MODEL} did not "
                "return a usable response. Nothing was marked, and this build "
                "does not fall back to another model."
            )
        else:
            message = (
                "Every model in this role's chain failed before returning a "
                "usable response. Nothing was marked."
            )
        return AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            message,
            details={
                "chain": [entry.model for entry in chain],
                "attempted": attempted,
                "last_failure": last,
                "production_marking_model": PRODUCTION_MARKING_MODEL,
            },
        )

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
        model: str | None = None,
    ) -> ProviderCallResult:
        asset = self.registry.load(prompt_id, prompt_version)
        prompt_row = self.prompt_versions.get_or_create(
            prompt_id=asset.prompt_id,
            version=asset.version,
            content_hash=asset.content_hash,
            path=asset.path,
            model_role=asset.model_role,
        )
        role = asset.model_role if asset.model_role in MODEL_CHAIN_ROLES else "primary"
        # The capability the call performs, which is not always the capability
        # its manifest role names.  Blind transcription is filed under the review
        # role because it shares that chain, but it is a transcription task; the
        # purpose decides the permission and the chain supplies the models.
        capability = capability_for_call(role=role, purpose=purpose)
        if model is not None:
            # The marking pipeline names its model explicitly.  One entry means
            # one model: there is no fallback that could change the marking
            # model while the job still records the configured one.
            problem = marking_model_problem(model)
            if problem is not None:
                raise AppError(ErrorCode.CONFIGURATION_ERROR, problem)
            chain = [ModelChainEntry(model=model)]
            role = "primary"
            capability = AICapability.MARKING
        else:
            chain = self.model_chain(role, capability=capability)
        # An allowance nobody recorded is not an allowance.  Refusing here means
        # no credential is leased and no request is spent against a limit that
        # cannot be shown to exist.
        for entry in chain:
            allowance = self.pool.allowance_problem(entry.model)
            if allowance is not None:
                raise AppError(
                    ErrorCode.CONFIGURATION_ERROR,
                    allowance,
                    details={
                        "model": entry.model,
                        "role": role,
                        "capability": capability.value,
                        "chain": [item.model for item in chain],
                    },
                )
        # The one number a chain cannot multiply: real requests per operation.
        budget = max(1, int(self.settings.provider.max_requests_per_operation))
        requests_sent = 0
        attempted: list[str] = []
        blocked: list[str] = []
        last_failure: str | None = None
        uncredentialed: list[str] = []

        for position, entry in enumerate(chain):
            model = entry.model
            attempts_allowed = entry.max_attempts or self.settings.provider.max_attempts
            next_model_available = position + 1 < len(chain)
            excluded: set[uuid.UUID] = set()
            projects_tried: set[str] = set()
            breaker_state = self.breaker.status(self.provider.name, model)
            if breaker_state.open:
                # The provider is overloaded for this model.  Walking the fleet
                # would spend one request per key to learn the same thing, so the
                # model is skipped: no lease, no request, no ledger row.
                blocked.append(model)
                last_failure = f"circuit_open:{model}"
                continue
            attempted.append(model)

            for attempt in range(attempts_allowed):
                if requests_sent >= budget:
                    # The operation budget is spent.  Another attempt would be a
                    # request this operation was never allowed to make.
                    break
                queue_started = time.perf_counter()
                queue_wait_ms: int | None = None
                try:
                    if self._acquire_lock is None:
                        lease = self.pool.acquire(
                            tenant_id=tenant_id,
                            model=model,
                            purpose=purpose,
                            excluded=excluded,
                            skip_projects=projects_tried,
                        )
                    else:
                        with self._acquire_lock:
                            lease = self.pool.acquire(
                                tenant_id=tenant_id,
                                model=model,
                                purpose=purpose,
                                excluded=excluded,
                                skip_projects=projects_tried,
                            )
                except AppError:
                    # No key is available or within quota for this model.  No
                    # request was sent, so there is no attempt to ledger; this is
                    # a routing event, and the next model may have capacity.
                    uncredentialed.append(model)
                    last_failure = "no_credential"
                    break

                queue_wait_ms = round((time.perf_counter() - queue_started) * 1000)
                request = LLMRequest(
                    model=model,
                    prompt=asset.content,
                    inputs=tuple(inputs),
                    response_schema=response_schema,
                    max_output_tokens=entry.max_output_tokens or max_output_tokens,
                    timeout_seconds=entry.timeout_seconds,
                    omit_thinking_config=entry.thinking_config_unsupported,
                )
                requests_sent += 1
                try:
                    response = self.provider.generate(request, lease.api_key)
                except ProviderNotConfigured as error:
                    self.pool.failure(
                        lease,
                        error=str(error),
                        count_toward_quota=False,
                        reservation_status="RELEASED",
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
                        model_role=role,
                        chain_position=position,
                        attempt_index=attempt,
                        routing_decision=RoutingAction.STOP.value,
                    )
                    self._commit()
                    raise AppError(
                        ErrorCode.PROVIDER_UNAVAILABLE,
                        str(error),
                    ) from error
                except ProviderError as error:
                    last_failure = f"{type(error).__name__}: {error}"
                    kind = classify_failure(error)
                    is_key_failure = kind in (
                        FailureKind.AUTHENTICATION,
                        FailureKind.PERMISSION,
                        FailureKind.QUOTA,
                    )
                    if is_key_failure:
                        excluded.add(lease.credential_id)
                    if kind is FailureKind.QUOTA:
                        # One project's allowance is shared by every key in
                        # it, so the project is what is recorded as tried.
                        projects_tried.add(lease.project_id)
                    cooldown_seconds = (
                        int(error.retry_after_seconds)
                        if kind is FailureKind.QUOTA and error.retry_after_seconds
                        else self.settings.quota.cooldown_seconds
                        if kind is FailureKind.QUOTA
                        else None
                    )
                    # Only a 401 proves the credential invalid.  Permission,
                    # quota, network and provider failures say nothing about
                    # validity.
                    self.pool.failure(
                        lease,
                        health=(
                            "INVALID"
                            if kind is FailureKind.AUTHENTICATION
                            else None
                        ),
                        error=f"{type(error).__name__}: {error}",
                        status_code=error.status_code,
                        count_toward_quota=kind is not FailureKind.AUTHENTICATION,
                        cooldown_seconds=cooldown_seconds,
                        reservation_status=reservation_status_for(kind, error),
                    )
                    if kind.value in TRANSIENT_FAILURES:
                        # A 5xx is the model being overloaded, not this key
                        # misbehaving.  Repeated overload opens the breaker.
                        self.breaker.record_failure(self.provider.name, model)
                    other_credential, independent_credential = self.pool.alternatives(
                        tenant_id=tenant_id,
                        model=model,
                        excluded=excluded,
                        projects_tried=projects_tried,
                    )
                    # Cross-project quota recovery needs a *verified* project,
                    # not merely a key that names a different id.  Pools without
                    # the check (test doubles) cannot satisfy it, which is the
                    # safe default.
                    verified_independent = False
                    verifier = getattr(
                        self.pool, "verified_independent_project", None
                    )
                    if independent_credential and callable(verifier):
                        verified_independent = bool(
                            verifier(
                                tenant_id=tenant_id,
                                model=model,
                                excluded=excluded,
                                projects_tried=projects_tried,
                            )
                        )
                    action = decide(
                        kind,
                        attempt_index=attempt,
                        attempts_allowed=attempts_allowed,
                        next_model_available=next_model_available,
                        other_credential_available=other_credential,
                        independent_credential_available=independent_credential,
                        independent_project_verified=verified_independent,
                    )
                    self._record(
                        tenant_id=tenant_id,
                        lease=lease,
                        job_id=job_id,
                        model=model,
                        purpose=purpose,
                        prompt_version_id=prompt_row.id,
                        usage=error.usage or TokenUsage(),
                        success=False,
                        request_id=error.provider_request_id,
                        latency_ms=error.latency_ms,
                        http_status=error.status_code,
                        error_class=type(error).__name__,
                        error_category=kind.value,
                        provider_code=error.provider_code,
                        provider_message=error.provider_message,
                        reached_provider=error.reached_provider,
                        finish_reason=None,
                        retry_count=attempt,
                        model_role=role,
                        chain_position=position,
                        attempt_index=attempt,
                        routing_decision=action.value,
                        queue_wait_ms=queue_wait_ms,
                    )
                    self._commit()

                    if action is RoutingAction.RETRY_SAME_MODEL:
                        if requests_sent >= budget:
                            break
                        # Exponential backoff with jitter, honouring a
                        # ``Retry-After`` the provider sent.  Returning is
                        # decided once, here: there is no second retry loop.
                        time.sleep(
                            retry_delay(
                                attempt,
                                policy=self._retry_policy(),
                                retry_after_seconds=error.retry_after_seconds,
                            )
                        )
                        continue
                    if action is RoutingAction.NEXT_MODEL:
                        break
                    if action is RoutingAction.ROTATE_CREDENTIAL:
                        # Same model, another key: the policy has already
                        # established that one exists and can help.
                        continue
                    # STOP.  A 401/403 with no other key, a safety refusal or an
                    # unrecoverable request is not a model problem, so walking
                    # the chain would only spend money to learn the same thing.
                    if kind in (
                        FailureKind.PROVIDER_SERVER,
                        FailureKind.NETWORK,
                        FailureKind.TRUNCATED,
                        FailureKind.RESPONSE_INVALID,
                    ):
                        # The retryable failures reached STOP only because no
                        # model or attempt remains: that is an exhausted chain,
                        # and it is reported as one.
                        raise self._exhausted(
                            chain=chain,
                            attempted=attempted,
                            last=last_failure,
                            marking=model is not None,
                        ) from error
                    refused = kind in (
                        FailureKind.AUTHENTICATION,
                        FailureKind.PERMISSION,
                    )
                    raise AppError(
                        ErrorCode.PROVIDER_UNAVAILABLE,
                        "The provider call cannot be completed: "
                        + (
                            "the credential was refused"
                            if refused
                            else "this project's quota for the model is "
                            "exhausted"
                            if kind is FailureKind.QUOTA
                            else "the request or response was rejected"
                        )
                        + " and no further attempt can help.",
                        details={
                            "status_code": error.status_code,
                            "failure": kind.value,
                            "model": model,
                        },
                    ) from error
                except Exception as error:
                    # An Aetrix-side defect is a failed attempt too.  It must not
                    # leave a reservation RESERVED or vanish from the ledger.
                    self.pool.failure(
                        lease,
                        error=f"Internal: {type(error).__name__}: {error}",
                        count_toward_quota=False,
                        reservation_status="RELEASED",
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
                        model_role=role,
                        chain_position=position,
                        attempt_index=attempt,
                        routing_decision=RoutingAction.STOP.value,
                    )
                    self._commit()
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
                        model_role=role,
                        chain_position=position,
                        attempt_index=attempt,
                        routing_decision="SUCCESS",
                        queue_wait_ms=queue_wait_ms,
                    )
                    self.pool.success(lease)
                    # One answered request is proof the model is reachable again.
                    self.breaker.record_success(self.provider.name, model)
                    return ProviderCallResult(
                        response=response,
                        usage_id=usage_id,
                        prompt=asset,
                        prompt_version_id=prompt_row.id,
                        cost_usd=cost,
                        provider_name=self.provider.name,
                        model_chain_position=position,
                        models_attempted=tuple(attempted),
                        queue_wait_ms=queue_wait_ms,
                    )

        if chain and not attempted and blocked and len(blocked) == len(chain):
            # Every model in the chain is circuit-broken.  Say so, with how long
            # to wait, instead of blaming the credentials or the quota.
            retry_in = max(
                (
                    self.breaker.status(self.provider.name, item.model).retry_in_seconds
                    or 0.0
                )
                for item in chain
            )
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "The provider is overloaded for every model in this role's chain. "
                "No request was sent; the circuit breaker is open, so retry after "
                f"{round(retry_in)}s.",
                details={
                    "chain": [item.model for item in chain],
                    "breaker_open": list(blocked),
                    "breaker_open_for_seconds": round(retry_in, 1),
                    "production_marking_model": PRODUCTION_MARKING_MODEL,
                },
            )
        if chain and len(uncredentialed) == len(chain):
            # No request was sent for any model, so nothing failed at Google.
            # Reporting this as "every model failed" would blame the provider for
            # Aetrix's own exhausted allowance and hide which project to top up.
            message = (
                "No provider credential is available within its project's quota "
                "for any model in this role's chain. Nothing was marked."
            )
            if model is not None:
                message = (
                    "No provider credential is available within its project's "
                    f"quota for {PRODUCTION_MARKING_MODEL}, the production "
                    "marking model. Nothing was marked and no other model was "
                    "tried."
                )
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                message,
                details={
                    "chain": [entry.model for entry in chain],
                    "models_without_credential": uncredentialed,
                    "production_marking_model": PRODUCTION_MARKING_MODEL,
                },
            )
        raise self._exhausted(
            chain=chain,
            attempted=[*uncredentialed, *(m for m in attempted if m not in uncredentialed)],
            last=last_failure,
            marking=model is not None,
        )
