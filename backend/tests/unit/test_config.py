from __future__ import annotations

import pytest
from app.core.config import (
    AuthSettings,
    DatabaseSettings,
    Environment,
    SecuritySettings,
    Settings,
)
from pydantic import SecretStr, ValidationError

POSTGRES_URL = "postgresql+psycopg://user:pass@db.example:5432/postgres"


def _settings(**overrides):
    base = {
        "_env_file": None,
        "env": Environment.PRODUCTION,
        "database": DatabaseSettings(url=SecretStr(POSTGRES_URL)),
        "auth": AuthSettings(jwt_secret=SecretStr("a-production-secret")),
        "security": SecuritySettings(
            encryption_key=SecretStr("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
        ),
        "cors_origins": "https://app.example",
    }
    base.update(overrides)
    return Settings(**base)


def test_valid_production_configuration_is_accepted() -> None:
    settings = _settings()
    assert settings.env is Environment.PRODUCTION
    assert settings.database.dsn() == POSTGRES_URL


def test_production_rejects_sqlite() -> None:
    with pytest.raises(ValidationError, match="SQLite"):
        _settings(database=DatabaseSettings(url=SecretStr("sqlite:///local.db")))


def test_production_rejects_development_auth() -> None:
    with pytest.raises(ValidationError, match="development authentication"):
        _settings(auth=AuthSettings(dev_mode=True))


def test_production_requires_encryption_key() -> None:
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        _settings(security=SecuritySettings())


def test_production_rejects_development_encryption_key() -> None:
    with pytest.raises(ValidationError, match="development encryption key"):
        _settings(
            security=SecuritySettings(
                encryption_key=SecretStr("dev-only-not-for-production-rotate-me-0000000000=")
            )
        )


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="wildcard CORS"):
        _settings(cors_origins="*")


def test_development_auth_requires_principal_ids() -> None:
    with pytest.raises(ValidationError, match="DEV_TENANT_ID"):
        _settings(env=Environment.DEVELOPMENT, auth=AuthSettings(dev_mode=True))


def test_authentication_requires_a_verification_source() -> None:
    with pytest.raises(ValidationError, match="JWKS_URL or JWT_SECRET"):
        _settings(auth=AuthSettings())


def test_heartbeat_must_fit_inside_lease() -> None:
    with pytest.raises(ValidationError, match="heartbeat_seconds"):
        _settings(worker={"lease_seconds": 20, "heartbeat_seconds": 20})
