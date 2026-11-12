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

import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_ENCRYPTION_KEY = "dev-only-not-for-production-rotate-me-0000000000="


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
    timeout_seconds: int = Field(default=20, ge=5, le=60)
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


class ProviderSettings(BaseModel):
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    model_primary: str = "gemini-3.6-flash"
    model_review: str = "gemini-3.1-pro-preview"
    model_lightweight: str = "gemini-3.1-flash-lite"
    #: How long a project's models.list result is reused before it is fetched
    #: again. Discovery is cached per project and key fingerprint.
    model_catalogue_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    request_timeout_seconds: int = Field(default=300, ge=10, le=900)
    max_attempts: int = Field(default=4, ge=1, le=8)
    thinking_budget: int = Field(default=0, ge=0)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.0, le=30.0)
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
    model_limits: dict[str, ModelQuota] = Field(default_factory=dict)
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


class EngineSettings(BaseModel):
    """Which correction engine marks a paper, and nothing else.

    ``aetrix_legacy`` is the shipped default; ``aetrix_v5_5`` is the reviewed V5
    engine, which adds mark integrity, targeted recovery, the independent double
    check and the result guard; ``mathchecker_v5`` is registered but refuses to
    mark until its slice lands.  Selection is configuration only.
    Flipping the value changes what the next claimed job runs on; it writes
    nothing, migrates nothing and leaves every
    stored result attached to the engine that produced it.  An unknown name is
    refused by the type, and again by the registry, rather than falling back to
    a different engine.
    """

    correction_engine: Literal["aetrix_legacy", "aetrix_v5_5", "mathchecker_v5"] = (
        "aetrix_legacy"
    )


class MarkingSettings(BaseModel):
    review_mode: ReviewMode = ReviewMode.BALANCED
    blueprint_approval_required: bool = True
    max_escalations_per_job: int = Field(default=6, ge=0, le=50)
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    max_marks_per_question: int = Field(default=50, ge=1, le=200)
    #: Independent second marking of low-confidence questions.  It never
    #: overwrites the first award: a disagreement goes to a teacher.
    double_check_enabled: bool = False
    double_check_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    double_check_max_questions: int = Field(default=8, ge=0, le=50)


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
        env_file=(".env", "backend/.env"),
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
    engine: EngineSettings = Field(default_factory=EngineSettings)
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
