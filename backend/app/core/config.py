"""Typed configuration.

Every value is read from ``AETRIX_*`` environment variables (or ``backend/.env``
for development).  Production validation is deliberately strict: the engine
refuses to start with development authentication, a non-PostgreSQL database or
an unset credential-encryption key.  A misconfigured deployment must fail at
boot, not silently mark papers with weaker settings.

No secret is ever stored in this module, printed by ``repr`` or written to a log:
``SecretStr`` fields hide their value and the application only reads them at the
point of use.
"""

from __future__ import annotations

import os
import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..correction.transcription import TRANSCRIPTION_REQUEST_MAX_PAGES
from .marking_policy import (
    DISABLED_MARKING_MODELS,
    PRODUCTION_MARKING_MODEL,
    is_disabled_marking_model,
    marking_model_problem,
)
from .model_permissions import AICapability, role_configuration_problem

DEV_ENCRYPTION_KEY = "dev-only-not-for-production-rotate-me-0000000000="

#: The one correction engine this build contains.  Historical rows may name
#: engines that no longer exist; those values are read as stored, never rewritten.
CORRECTION_ENGINE_NAME = "aetrix_v5_5"
CORRECTION_ENGINE_VERSION = "5.5.0"

#: The engine-selection variable earlier builds read.  Selection is gone, so a
#: deployment that still asks for another engine must fail at startup rather
#: than silently run this one instead.
OBSOLETE_CORRECTION_ENGINE_ENV = "AETRIX_ENGINE__CORRECTION_ENGINE"

#: Files the settings layer reads, relative to the working directory.
ENV_FILES = (".env", "backend/.env")


def _obsolete_engine_setting() -> str | None:
    """The obsolete engine-selection value, from the environment or an env file.

    ``backend/.env`` is read by the settings layer itself, so a value written
    there is as real as an exported variable and is refused the same way.  The
    value is returned, never logged.
    """

    for key, value in os.environ.items():
        if key.upper() == OBSOLETE_CORRECTION_ENGINE_ENV:
            return value
    for name in ENV_FILES:
        path = Path(name)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#") or "=" not in entry:
                continue
            key, _, value = entry.partition("=")
            if key.strip().upper() == OBSOLETE_CORRECTION_ENGINE_ENV:
                return value.strip().strip("\"'")
    return None


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ReviewMode(StrEnum):
    ECONOMY = "ECONOMY"
    BALANCED = "BALANCED"
    ACCURACY = "ACCURACY"


class DatabaseSettings(BaseModel):
    """PostgreSQL only.  SQLite is not a supported production dialect."""

    url: SecretStr
    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_pre_ping: bool = True
    pool_recycle_seconds: int = Field(default=1800, ge=60)
    statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=300_000)

    def dsn(self) -> str:
        return self.url.get_secret_value()


class AuthSettings(BaseModel):
    supabase_url: str | None = None
    jwks_url: str | None = None
    jwt_secret: SecretStr | None = None
    jwt_audience: str = "authenticated"
    jwt_issuer: str | None = None
    dev_mode: bool = False
    dev_tenant_id: UUID | None = None
    dev_user_id: UUID | None = None

    #: Open access admits any verified identity into one shared workspace instead
    #: of refusing every account that has no invitation.  It is a deliberate
    #: posture for a private pilot deployment, not a default: it never widens
    #: tenancy (every read stays scoped to that one workspace), the workspace is
    #: resolved from this setting rather than from a token or a request body, and
    #: every admission is written to the audit log as ``method: open_access``.
    open_access: bool = False
    open_access_tenant_slug: str = "pilot"
    open_access_tenant_name: str = "Pilot workspace"
    open_access_role: Literal["OWNER", "ADMIN", "TEACHER", "REVIEWER", "VIEWER"] = "TEACHER"

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _empty_secret_is_none(cls, value: Any) -> Any:
        if value == "" or value is None:
            return None
        return value

    @field_validator("dev_tenant_id", "dev_user_id", mode="before")
    @classmethod
    def _empty_uuid_is_none(cls, value: Any) -> Any:
        if value == "" or value is None:
            return None
        return value

    @field_validator("open_access_tenant_slug", "open_access_tenant_name")
    @classmethod
    def _open_access_field_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("open-access workspace fields must not be blank")
        return value.strip()

    @field_validator("jwks_url", "supabase_url", "jwt_issuer", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value


class PlatformAdminSettings(BaseModel):
    """Supabase Auth administration for platform account management.

    Absent configuration is a normal, reported state: the account routes answer
    ``ADMIN_NOT_CONFIGURED`` rather than pretending to list accounts.  The key is
    a ``SecretStr`` and is only read at the point of use; it is never logged,
    returned in a response or compiled into the browser bundle.
    """

    supabase_url: str | None = None
    service_role_key: SecretStr | None = None
    timeout_seconds: int = Field(default=15, ge=5, le=60)
    #: A hard ceiling on accounts read per request.  The response says when the
    #: ceiling was reached instead of silently showing a partial list.
    max_accounts: int = Field(default=5000, ge=1, le=50_000)
    page_size: int = Field(default=200, ge=1, le=1000)
    #: How long the platform overview reuses its Supabase role census.  Reading
    #: every account pages the admin API, so a dashboard refresh must not do it
    #: each time; a manual refresh bypasses this cache.
    census_ttl_seconds: int = Field(default=60, ge=0, le=3600)

    @field_validator("supabase_url", "service_role_key", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: Any) -> Any:
        if value == "" or value is None:
            return None
        return value

    def configured(self) -> bool:
        return bool(self.supabase_url and self.service_role_key)


class ClassroomSettings(BaseModel):
    """Google Classroom OAuth client and discovery bounds.

    Absent configuration is a reported state: the Classroom screens say OAuth
    is not configured and never fabricate a connected account.  The client
    secret is a ``SecretStr``; tokens are encrypted separately with the
    credential-encryption key before they touch the database.
    """

    client_id: str | None = None
    client_secret: SecretStr | None = None
    #: The frontend route Google redirects to.  It must be registered byte for
    #: byte on the Google OAuth client; it is never derived from a request Host.
    redirect_uri: str | None = None
    auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url: str = "https://oauth2.googleapis.com/token"
    revoke_url: str = "https://oauth2.googleapis.com/revoke"
    api_base_url: str = "https://classroom.googleapis.com/v1"
    drive_base_url: str = "https://www.googleapis.com/drive/v3"
    userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    timeout_seconds: int = Field(default=20, ge=5, le=60)
    #: One request is retried at most this many times for a 429 or 5xx.
    request_attempts: int = Field(default=3, ge=1, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=10.0)
    #: Per-course ceilings.  Reaching one truncates the sync and says so.
    max_roster_students: int = Field(default=5000, ge=1, le=50_000)
    max_submissions: int = Field(default=5000, ge=1, le=50_000)
    #: Largest attachment fetched from Drive.  A larger file is refused
    #: with an explicit reason; it is never silently dropped.
    max_attachment_bytes: int = Field(
        default=25_000_000, ge=1_000_000, le=100_000_000
    )
    #: A short window for the signed OAuth state.  The code exchange also
    #: verifies that the state belongs to the authenticated workspace account.
    state_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    max_courses: int = Field(default=2000, ge=1, le=10_000)

    @field_validator("client_id", "client_secret", "redirect_uri", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: Any) -> Any:
        if value == "" or value is None:
            return None
        return value

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


class SecuritySettings(BaseModel):
    encryption_key: SecretStr | None = None
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    allowed_mime_types: tuple[str, ...] = ("application/pdf", "image/png", "image/jpeg")
    signed_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    @field_validator("encryption_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, value: Any) -> Any:
        if value == "" or value is None:
            return None
        return value


class ModelChainEntry(BaseModel):
    """One model in an ordered fallback chain for one correction role.

    The chain is ordered: the first enabled entry that answers is the one whose
    reply is used.  Everything a model needs in order to be *reachable by this
    deployment* lives here rather than in the correction engine, so adding a
    model is a configuration change, not an engine change:

    * ``max_attempts`` — the attempt budget for this model, over the platform
      default.  A model that times out once should not consume the whole job's
      budget.
    * ``timeout_seconds`` — a per-model wall clock, because a slow reasoning
      model and a fast lite model do not deserve the same timeout.
    * ``max_output_tokens`` — a per-model ceiling, capped again by the caller.
    * ``thinking_budget`` — request compatibility.  Some Gemini models refuse a
      zero thinking budget with an unnamed 400; recording the value here makes
      that a configuration fact instead of a request that is rediscovered.

    ``None`` means "inherit the platform default", never "zero".
    """

    model: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    max_attempts: int | None = Field(default=None, ge=1, le=8)
    timeout_seconds: float | None = Field(default=None, ge=5, le=900)
    max_output_tokens: int | None = Field(default=None, ge=256, le=65536)
    thinking_budget: int | None = Field(default=None, ge=0, le=65536)
    #: True for a model that answers 400 to ``thinkingConfig``.  Measured, not
    #: guessed: ``gemini-3.5-flash-lite`` does, and the request omits the block
    #: for it instead of spending a call to rediscover the same 400.
    thinking_config_unsupported: bool = False

    @field_validator("model")
    @classmethod
    def _model_shape(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate or "/" in candidate or " " in candidate:
            raise ValueError("a chain entry must be a bare model id")
        return candidate


#: The correction roles a chain may be configured for.  These are the same role
#: names the prompt manifest and ``provider_model_selections`` already use, so a
#: chain and an operator's saved selection cannot disagree about vocabulary.
MODEL_CHAIN_ROLES = ("primary", "review", "lightweight")


def _default_model_chains() -> dict[str, list[ModelChainEntry]]:
    """The production chains.

    ``primary`` is the marking chain and it has exactly one entry: the model
    Math Checker V5 marks with.  A second entry would be an automatic fallback
    to another marking model, which this build refuses.  When the model cannot
    be used the job is parked with a provider error and no mark is invented.

    ``review`` is the independent second examiner, used only by the optional
    double check and the blind transcription.  It must not be the marking model
    for a disagreement to mean anything, so it names ``gemini-2.5-flash`` and
    **no marking-model fallback**: falling back into ``gemini-3.6-flash`` would
    make the "independent" reading the model that produced the marks, which is
    the defect the transcription comparison exists to detect.  A role with no
    permitted model refuses at the routing boundary instead of borrowing the
    marking model.

    ``lightweight`` is extraction/classification work.  It never marks a paper;
    the two Lite models that earlier experiments used for marking are disabled
    here and cannot be selected as a fallback.
    """

    return {
        "primary": [
            ModelChainEntry(model=PRODUCTION_MARKING_MODEL),
        ],
        "review": [
            ModelChainEntry(model="gemini-2.5-flash", timeout_seconds=180.0),
        ],
        "lightweight": [
            ModelChainEntry(model="gemini-2.5-flash", timeout_seconds=120.0),
        ],
    }


class ProviderSettings(BaseModel):
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    #: The one production marking model.  Configuration validation refuses any
    #: other value, so this is not a preference an environment can override.
    model_primary: str = PRODUCTION_MARKING_MODEL
    #: The review role is the second examiner and the blind reader.  It is not a
    #: marking model; the double check records disagreement instead of replacing
    #: an award.
    model_review: str = "gemini-2.5-flash"
    model_lightweight: str = "gemini-2.5-flash"
    #: The model each specialist role *would* use, and whether that role may run.
    #: Neither role is implemented or active in this build: no code path reads
    #: these values to make a call, so they cannot activate a pipeline.  They
    #: exist so a validated model can be named per role without editing engine
    #: code, under the per-role permissions in ``app.core.model_permissions``.
    #: A reserved model may be named here; enabling its role is refused until
    #: its permission is ENABLED.
    transcription_model: str | None = None
    transcription_role_enabled: bool = False
    independent_review_model: str | None = None
    independent_review_role_enabled: bool = False
    #: Ordered fallback chains, per correction role.  A role's chain is the
    #: models an operator's saved selection is prepended to; the chain itself is
    #: what the provider service walks when a model fails.
    model_chains: dict[str, list[ModelChainEntry]] = Field(
        default_factory=_default_model_chains
    )
    #: How long a project's models.list result is reused before it is fetched
    #: again. Discovery is cached per project and key fingerprint.
    model_catalogue_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    request_timeout_seconds: int = Field(default=300, ge=10, le=900)
    max_attempts: int = Field(default=4, ge=1, le=8)
    thinking_budget: int = Field(default=0, ge=0)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.0, le=30.0)
    #: Retries allowed for a transient (5xx/network) failure on one model.  One,
    #: and it cannot be raised past one: a second retry of an overloaded model
    #: is the same request against the same project allowance.
    transient_retries: int = Field(default=1, ge=0, le=1)
    #: Ceiling for one backoff wait, including an honoured ``Retry-After``.
    retry_max_backoff_seconds: float = Field(default=8.0, ge=0.0, le=60.0)
    #: Fractional jitter on a computed backoff, so a fleet does not retry in step.
    retry_jitter: float = Field(default=0.5, ge=0.0, le=1.0)
    #: The hard ceiling on real HTTP requests one logical operation may send,
    #: across every model in its chain.  Attempt budgets multiply inside a chain;
    #: this is the number that does not.
    max_requests_per_operation: int = Field(default=3, ge=1, le=8)
    #: Consecutive transient failures for one (provider, model) that open the
    #: breaker.  A 5xx is a property of the model, not of one key.
    circuit_breaker_threshold: int = Field(default=3, ge=1, le=20)
    #: How long the breaker stays open.  While it is open no credential is leased
    #: and no request is sent, so an outage costs no quota.
    circuit_breaker_seconds: float = Field(default=300.0, ge=0.0, le=3600.0)
    prompt_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "prompts"
    )
    #: Per-million-token list prices.  ``None`` means the price is unknown and
    #: the ledger records no cost rather than inventing one.
    model_rates: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "gemini-3.6-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
            "gemini-3.8-flash": {"input": 0.75, "output": 3.75, "cached": 0.075},
            "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50, "cached": 0.03},
            "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50, "cached": 0.025},
            "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00, "cached": 0.20},
        }
    )

    @model_validator(mode="after")
    def _production_marking_policy(self) -> ProviderSettings:
        """Refuse a configuration that could mark with another model.

        Three facts are checked at boot rather than discovered during a paid
        run: the primary role names the one production marking model, the
        marking chain has no fallback, and no chain names a disabled Lite model.
        """

        problem = marking_model_problem(self.model_primary)
        if problem is not None:
            raise ValueError(
                f"AETRIX_PROVIDER__MODEL_PRIMARY is not usable for marking. {problem}"
            )

        primary = self.model_chains.get("primary") or []
        enabled = [entry for entry in primary if entry.enabled]
        if len(enabled) != 1 or enabled[0].model != PRODUCTION_MARKING_MODEL:
            names = [entry.model for entry in enabled]
            raise ValueError(
                "The primary (marking) model chain must contain exactly one "
                f"enabled entry, {PRODUCTION_MARKING_MODEL!r}, and no fallback. "
                f"This deployment configures {names!r}. A fallback that changes "
                "the marking model would make the recorded model a guess; remove "
                "the extra entries."
            )

        for role, entries in self.model_chains.items():
            for entry in entries:
                if is_disabled_marking_model(entry.model):
                    raise ValueError(
                        f"Model chain {role!r} names {entry.model!r}, which is a "
                        "disabled lightweight model. Enabled marking models are "
                        f"{PRODUCTION_MARKING_MODEL!r}; disabled: "
                        f"{sorted(DISABLED_MARKING_MODELS)!r}."
                    )

        # The per-role environment fallbacks are read when no database selection
        # exists, so they are policy-checked too.  A Lite value here could
        # otherwise become the review role's first attempt through the back door.
        for field_name in ("model_review", "model_lightweight"):
            value = getattr(self, field_name)
            if is_disabled_marking_model(value):
                raise ValueError(
                    f"{field_name} is {value!r}, a disabled lightweight model. "
                    f"Enabled marking models are {PRODUCTION_MARKING_MODEL!r}; "
                    f"disabled: {sorted(DISABLED_MARKING_MODELS)!r}."
                )
        return self

    @field_validator("transcription_model", "independent_review_model", mode="before")
    @classmethod
    def _blank_role_model_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _specialist_role_permissions(self) -> ProviderSettings:
        """Refuse a specialist role that names a model its permission forbids.

        A reserved model may be named — that is what the reservation records —
        but its role cannot be enabled, because a reserved permission never
        executes.  Only a validated change of the model's permission to ENABLED
        can switch the role on.  A disabled model cannot be named at all.
        """

        role_fields = (
            (
                "transcription_model",
                "transcription_role_enabled",
                AICapability.TRANSCRIPTION,
            ),
            (
                "independent_review_model",
                "independent_review_role_enabled",
                AICapability.INDEPENDENT_REVIEW,
            ),
        )
        for model_field, enabled_field, capability in role_fields:
            problem = role_configuration_problem(
                getattr(self, model_field),
                capability,
                enabled=getattr(self, enabled_field),
            )
            if problem is not None:
                raise ValueError(
                    f"AETRIX_PROVIDER__{model_field.upper()}: {problem}"
                )
        return self

    @field_validator("model_chains")
    @classmethod
    def _chain_roles(
        cls, value: dict[str, list[ModelChainEntry]]
    ) -> dict[str, list[ModelChainEntry]]:
        """Reject a chain that names a role nothing reads, or has no enabled entry."""

        unknown = sorted(set(value) - set(MODEL_CHAIN_ROLES))
        if unknown:
            raise ValueError(
                f"unknown model-chain role(s) {unknown}; expected {list(MODEL_CHAIN_ROLES)}"
            )
        for role, entries in value.items():
            if not entries:
                raise ValueError(f"model chain {role!r} is empty")
            if not any(entry.enabled for entry in entries):
                raise ValueError(
                    f"model chain {role!r} has no enabled entry, so it could never "
                    "make a call"
                )
            models = [entry.model for entry in entries]
            if len(models) != len(set(models)):
                raise ValueError(f"model chain {role!r} repeats a model")
        return value


class ModelQuota(BaseModel):
    """The limits an operator attributes to one model on one project.

    ``source`` is what makes an estimate honest: ``"google"`` means the numbers
    were read from an authoritative Google surface and may be reported as
    CONFIRMED; anything else is an operator-entered policy and can only ever be
    ESTIMATED.  No default here is presented as a Google-confirmed limit.
    """

    requests_per_minute: int | None = Field(default=None, ge=1)
    tokens_per_minute: int | None = Field(default=None, ge=1)
    requests_per_day: int | None = Field(default=None, ge=1)
    source: str = Field(default="operator", pattern="^(operator|google)$")


#: The operator's Google AI Studio snapshot for this deployment.
#:
#: These are *project* limits: every key in one Google Cloud project shares
#: them, which is why they are attached to the project/model pair and never
#: multiplied by the number of credentials.  ``source="operator"`` keeps the
#: quota report honest: only a value read from a Google surface may be
#: reported as CONFIRMED.  Gemma is deliberately absent, because its 16K TPM
#: cannot carry a whole-paper request and it has not passed a compatibility
#: test, so it must not be given an allowance that invites a failed run.
def _default_model_limits() -> dict[str, ModelQuota]:
    def limit(requests_per_minute: int, requests_per_day: int) -> ModelQuota:
        return ModelQuota(
            requests_per_minute=requests_per_minute,
            tokens_per_minute=250_000,
            requests_per_day=requests_per_day,
            source="operator",
        )

    return {
        "gemini-3.1-flash-lite": limit(15, 500),
        "gemini-3.5-flash-lite": limit(15, 500),
        "gemini-2.5-flash": limit(5, 20),
        "gemini-3-flash-preview": limit(5, 20),
        "gemini-3.6-flash": limit(5, 20),
        "gemini-3.8-flash": limit(5, 20),
        "gemini-4-hydrogen": limit(5, 20),
    }


class QuotaSettings(BaseModel):
    #: Platform defaults applied to a model with no explicit entry in
    #: ``model_limits``.  They are Aetrix policy, never a Google figure.
    requests_per_minute: int = Field(default=10, ge=1)
    requests_per_day: int = Field(default=200, ge=1)
    review_budget_share: float = Field(default=0.25, ge=0.0, le=1.0)
    cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    reservation_ttl_seconds: int = Field(default=300, ge=30, le=1800)
    #: Tokens-per-minute policy, per project and model.  ``None`` means unknown:
    #: the estimate reports UNKNOWN rather than dividing by a made-up number.
    tokens_per_minute: int | None = Field(default=None, ge=1)
    model_limits: dict[str, ModelQuota] = Field(
        default_factory=_default_model_limits
    )
    #: Gemini's daily free-tier window resets at midnight Pacific time.
    daily_reset_timezone: str = "America/Los_Angeles"
    #: Usage above this share of a limit raises an "approaching quota" alert.
    alert_threshold: float = Field(default=0.8, ge=0.1, le=1.0)
    #: How often the background monitor samples project health.  It never
    #: validates the whole fleet inline with a correction request.
    monitoring_interval_seconds: int = Field(default=300, ge=30, le=3600)


class GoogleCloudSettings(BaseModel):
    """Read-only Google Cloud quota/usage synchronisation.

    Credentials are deliberately *not* Gemini API keys.  A service-account JSON
    file outside the repository is the supported production mechanism; inline
    JSON exists for secret managers and the metadata server for GCE/Cloud Run.
    The OAuth scope is broad because Cloud Quotas only accepts ``cloud-platform``;
    least privilege is enforced by the IAM roles granted to the account, not by
    the scope string.
    """

    enabled: bool = True
    service_account_file: Path | None = None
    #: Inline service-account JSON.  Prefer a mounted file; this exists so a
    #: secret manager can inject the document without writing it to disk.
    service_account_json: SecretStr | None = None
    use_metadata: bool = False
    service: str = "generativelanguage.googleapis.com"
    sync_interval_seconds: int = Field(default=900, ge=60, le=86400)
    stale_after_seconds: int = Field(default=3600, ge=60, le=604800)
    request_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    max_attempts: int = Field(default=3, ge=1, le=6)
    backoff_seconds: float = Field(default=1.0, ge=0.0, le=30.0)
    max_quota_infos: int = Field(default=2000, ge=1, le=10000)
    usage_window_minutes: int = Field(default=15, ge=1, le=1440)

    @field_validator("service_account_file", mode="before")
    @classmethod
    def _blank_file_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("service_account_json", mode="before")
    @classmethod
    def _blank_json_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("service")
    @classmethod
    def _service_shape(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate.endswith(".googleapis.com") or "/" in candidate:
            raise ValueError("service must be a Google API service name")
        return candidate

    @property
    def configured(self) -> bool:
        return self.use_metadata or bool(
            self.service_account_file or self.service_account_json
        )


class MarkingSettings(BaseModel):
    review_mode: ReviewMode = ReviewMode.BALANCED
    blueprint_approval_required: bool = True
    #: How one paper is marked.  ``WHOLE_PAPER`` is the product: one request for
    #: the complete script against the complete scheme, so the model reads the
    #: paper as a whole, and the per-question engine answers only the leaves that
    #: reply did not decide.  ``PER_QUESTION`` remains selectable for a controlled
    #: comparison, but it is not the default and must not be presented as
    #: evidence that whole-paper marking works.  ``PARALLEL`` sends the same
    #: per-question request as ``PER_QUESTION`` but corrects independent questions
    #: concurrently, bounded by ``parallel_max_concurrency``.
    marking_mode: Literal["PER_QUESTION", "WHOLE_PAPER", "PARALLEL"] = "WHOLE_PAPER"
    #: How many question requests one parallel pass may have in flight.  Every
    #: request still goes through the same credential pool, project cooldown and
    #: append-only usage ledger, so raising this cannot buy quota the provider
    #: does not have; it only shortens the wall clock while capacity remains.  The
    #: ceiling is deliberately small: a paper is a few dozen questions and the
    #: pool's per-minute allowance, not the CPU, is the real limit.
    parallel_max_concurrency: int = Field(default=3, ge=1, le=8)
    #: How many rendered pages one paper request may carry.  A script with more
    #: pages is marked per question, which can still send a question only the
    #: pages mapped to it; dropping pages from a paper request would turn a
    #: present answer into an apparent blank.
    whole_paper_max_pages: int = Field(default=12, ge=1, le=40)
    #: The output budget for the paper reply.  32,768 covers 39 leaves at the
    #: bounded supporting-text sizes with headroom; the model's own ceiling is
    #: 65,536 and is enforced here rather than assumed.
    whole_paper_max_output_tokens: int = Field(default=32768, ge=4096, le=65536)
    max_escalations_per_job: int = Field(default=6, ge=0, le=50)
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    max_marks_per_question: int = Field(default=50, ge=1, le=200)
    #: Pin the marking prompt to one manifest version for a controlled experiment.
    #: ``None`` uses the newest version, which is the production default.  This
    #: exists so a validation run can compare prompt v1 and v2 on the same papers
    #: without editing a file between runs.
    marking_prompt_version: int | None = Field(default=None, ge=1)
    #: Independent second marking of low-confidence questions.  It never
    #: overwrites the first award: a disagreement goes to a teacher.
    double_check_enabled: bool = False
    double_check_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    double_check_max_questions: int = Field(default=8, ge=0, le=50)
    #: A blind second reading of a question's answer, compared with the answer the
    #: marking pass extracted.  Off by default because it costs a request per
    #: selected question; a difference goes to a person and never rewrites anything.
    #: A blind second reading of selected answers.  On by default: a zero that
    #: rests on an unverified reading is not a confirmed zero, and the mission
    #: that added material transcription comparison exists because a confident
    #: zero stood without one.  An operator can still turn it off, and the mode
    #: budget bounds what it can spend.
    transcription_enabled: bool = True
    transcription_max_questions: int = Field(default=4, ge=0, le=20)
    #: How many page images one transcription request may carry.  A question that
    #: needs more pages than this is reported as unavailable rather than sent a
    #: silently thinned script: a missing page reads as a missing answer.  The
    #: upper bound is the request builder's own ceiling, not a separate promise:
    #: a larger value could only be honoured by dropping pages.
    transcription_max_pages: int = Field(
        default=3, ge=1, le=TRANSCRIPTION_REQUEST_MAX_PAGES
    )
    #: The image budget of one transcription request, in bytes before base64
    #: encoding.  The provider's inline request ceiling is around 20 MB encoded,
    #: so the raw ceiling is deliberately well below it.
    transcription_max_image_bytes: int = Field(default=8_388_608, ge=1_048_576)
    #: Whether a mark that no evidence check has examined sends its question to a
    #: person.  On by default, and the reason is a real paper: a full-marks award
    #: for an answer that was never written was presented as a finished result
    #: because the evidence check had simply not been bought for that question.
    #: The comparison is bought for a few questions per paper, so this makes an
    #: unverified award a review item rather than a decided mark — raise
    #: ``transcription_max_questions`` to verify more of a paper automatically.
    #: An operator who turns this off is choosing to present unverified awards;
    #: the paper's verification state still records that they were unverified.
    require_evidence_for_award: bool = True


class WorkerSettings(BaseModel):
    concurrency: int = Field(default=2, ge=1, le=32)
    poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    lease_seconds: int = Field(default=60, ge=10, le=3600)
    heartbeat_seconds: int = Field(default=20, ge=5, le=1800)
    max_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def _heartbeat_fits_inside_lease(self) -> WorkerSettings:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("heartbeat_seconds must be smaller than lease_seconds")
        return self


class StorageSettings(BaseModel):
    backend: str = "local"
    root: Path = Path("./data/documents")
    bucket: str = ""


class IngestionSettings(BaseModel):
    render_dpi: int = Field(default=144, ge=72, le=300)
    max_pages: int = Field(default=80, ge=1, le=500)
    max_image_pixels: int = Field(default=40_000_000, ge=1_000_000)
    min_page_width_px: int = Field(default=800, ge=200)
    unreadable_width_px: int = Field(default=300, ge=50)
    blank_ink_ratio: float = Field(default=0.001, ge=0.0, le=1.0)
    low_ink_ratio: float = Field(default=0.012, ge=0.0, le=1.0)
    low_contrast_std: float = Field(default=18.0, ge=0.0)
    low_edge_energy: float = Field(default=1.5, ge=0.0)
    duplicate_hash_distance: int = Field(default=2, ge=0, le=64)


class FeatureFlags(BaseModel):
    live_provider: bool = False
    #: Selective review is not implemented; the flag must not imply otherwise.
    selective_review: bool = False
    cohort_intelligence: bool = False
    automatic_second_pass: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AETRIX_",
        env_file=ENV_FILES,
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: str = ""
    database: DatabaseSettings
    auth: AuthSettings = Field(default_factory=AuthSettings)
    platform_admin: PlatformAdminSettings = Field(default_factory=PlatformAdminSettings)
    classroom: ClassroomSettings = Field(default_factory=ClassroomSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    quota: QuotaSettings = Field(default_factory=QuotaSettings)
    google_cloud: GoogleCloudSettings = Field(default_factory=GoogleCloudSettings)
    marking: MarkingSettings = Field(default_factory=MarkingSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    @field_validator("api_prefix")
    @classmethod
    def _prefix_shape(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("api_prefix must start with '/' and not end with '/'")
        return value

    @model_validator(mode="after")
    def _refuse_obsolete_engine_selection(self) -> Settings:
        """Fail at boot when a deployment still selects a correction engine.

        ``aetrix_v5_5`` is the only engine and there is no fallback.  The old
        variable is no longer a field, so accepting another value would mark
        papers with an engine the operator did not choose.
        """

        configured = _obsolete_engine_setting()
        if configured is None or configured.strip() == CORRECTION_ENGINE_NAME:
            return self
        raise ValueError(
            f"{OBSOLETE_CORRECTION_ENGINE_ENV}={configured!r} is not supported. "
            f"{CORRECTION_ENGINE_NAME!r} is the only correction engine in this "
            "build, and this build never falls back to another. Remove the "
            f"variable or set it to {CORRECTION_ENGINE_NAME!r}."
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _validate_environment(self) -> Settings:
        if not self.database.dsn().startswith("postgresql"):
            raise ValueError(
                "AETRIX_DATABASE__URL must be a PostgreSQL URL; SQLite is not supported"
            )

        if self.env is Environment.PRODUCTION:
            if self.debug:
                raise ValueError("debug must be false in production")
            if self.auth.dev_mode:
                raise ValueError("development authentication must be disabled in production")
            if not (self.auth.jwks_url or self.auth.jwt_secret):
                raise ValueError("production requires AETRIX_AUTH__JWKS_URL or JWT_SECRET")
            if not self.security.encryption_key:
                raise ValueError(
                    "production requires AETRIX_SECURITY__ENCRYPTION_KEY to encrypt credentials"
                )
            if self.security.encryption_key.get_secret_value() == DEV_ENCRYPTION_KEY:
                raise ValueError("the development encryption key is refused in production")
            if "*" in self.cors_origin_list:
                raise ValueError("wildcard CORS is refused in production")
        elif self.auth.dev_mode:
            if not self.auth.dev_tenant_id or not self.auth.dev_user_id:
                raise ValueError(
                    "development authentication requires AETRIX_AUTH__DEV_TENANT_ID "
                    "and AETRIX_AUTH__DEV_USER_ID"
                )
        elif not (self.auth.jwks_url or self.auth.jwt_secret):
            raise ValueError("authentication requires AETRIX_AUTH__JWKS_URL or JWT_SECRET")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test helper: force the next ``get_settings`` call to re-read the environment."""
    get_settings.cache_clear()


def generate_encryption_key() -> str:
    """Generate a Fernet key without importing the application at module import time."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def generate_dev_jwt_secret() -> str:
    return secrets.token_urlsafe(32)
