"""Authentication and credential protection.

The engine does not own passwords.  Supabase Auth issues the JWT; this module
verifies it against the project's JWKS (preferred) or the legacy HS256 secret
and extracts a tenant/user principal.  Development mode exists only for local
work and is rejected by configuration validation in production.

Provider credentials are encrypted at rest with Fernet.  Only a key
fingerprint is stored in plaintext, so an operator can identify a credential
without the database containing the credential.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken
from jwt import PyJWKClient

from .config import Settings
from .errors import AppError, ErrorCode


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    subject: str
    role: str

    @property
    def is_reviewer(self) -> bool:
        return self.role in {"OWNER", "ADMIN", "TEACHER", "REVIEWER"}

    @property
    def can_manage_exams(self) -> bool:
        return self.role in {"OWNER", "ADMIN", "TEACHER"}


class SecretBox:
    """Symmetric encryption for provider credentials at rest."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as error:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "The credential encryption key is not a valid Fernet key.",
            ) from error

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as error:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "The stored credential could not be decrypted with the configured key.",
            ) from error


def fingerprint(value: str) -> str:
    """A stable, non-reversible identifier for a credential."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=300)


def decode_jwt(token: str, settings: Settings) -> dict[str, Any]:
    options = {"require": ["exp", "sub"]}
    try:
        if settings.auth.jwks_url:
            signing_key = _jwks_client(settings.auth.jwks_url).get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=settings.auth.jwt_audience,
                issuer=settings.auth.jwt_issuer,
                options=options,
            )
        if settings.auth.jwt_secret:
            return jwt.decode(
                token,
                settings.auth.jwt_secret.get_secret_value(),
                algorithms=["HS256"],
                audience=settings.auth.jwt_audience,
                issuer=settings.auth.jwt_issuer,
                options=options,
            )
    except jwt.PyJWTError as error:
        raise AppError(
            ErrorCode.UNAUTHORIZED,
            "The bearer token is invalid or has expired.",
        ) from error
    raise AppError(ErrorCode.UNAUTHORIZED, "Authentication is not configured.")


def extract_subject(claims: dict[str, Any]) -> str:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AppError(ErrorCode.UNAUTHORIZED, "The token does not identify a subject.")
    return subject


def _uuid_claim(value: Any) -> UUID | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def extract_tenant_id(claims: dict[str, Any]) -> UUID | None:
    """Read the tenant claim from the supported Supabase locations.

    A custom access-token hook may place it at the top level or under
    ``app_metadata``; the engine accepts either and falls back to a database
    lookup by subject when neither is present.
    """
    for container in (claims, claims.get("app_metadata"), claims.get("user_metadata")):
        if isinstance(container, dict):
            tenant = _uuid_claim(container.get("tenant_id"))
            if tenant:
                return tenant
    return None


def require_tenant(principal: Principal) -> UUID:
    return principal.tenant_id


def ensure_reviewer(principal: Principal) -> None:
    if not principal.is_reviewer:
        raise AppError(ErrorCode.FORBIDDEN, "This action requires a reviewer role.")


def ensure_exam_manager(principal: Principal) -> None:
    if not principal.can_manage_exams:
        raise AppError(ErrorCode.FORBIDDEN, "This action requires a teacher or admin role.")
