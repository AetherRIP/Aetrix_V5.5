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
    #: Platform authority from the verified ``app_metadata.aetrix_role`` claim.
    #: Empty for a workspace account.  Kept apart from ``role``, which is the
    #: workspace membership role: a workspace OWNER is not a platform operator.
    platform_role: str = ""

    @property
    def is_platform_admin(self) -> bool:
        return self.platform_role in {"PLATFORM_OWNER", "ADMIN"}

    @property
    def is_platform_owner(self) -> bool:
        return self.platform_role == "PLATFORM_OWNER"

    @property
    def is_reviewer(self) -> bool:
        # PLATFORM_OWNER keeps the workspace capabilities it had before the
        # platform role existed; owning the platform must not remove them.
        return self.role in {"OWNER", "ADMIN", "TEACHER", "REVIEWER", "PLATFORM_OWNER"}

    @property
    def can_manage_exams(self) -> bool:
        return self.role in {"OWNER", "ADMIN", "TEACHER", "PLATFORM_OWNER"}


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


#: Only these two values of ``app_metadata.aetrix_role`` carry platform
#: authority.  Everything else is a workspace role, and the engine's own role
#: spellings are accepted because an operator CLI may have written them.
PLATFORM_ROLE_BY_CLAIM: dict[str, str] = {
    "owner": "PLATFORM_OWNER",
    "platform_operator": "ADMIN",
    "PLATFORM_OWNER": "PLATFORM_OWNER",
    "ADMIN": "ADMIN",
}


def extract_platform_role(claims: dict[str, Any]) -> str:
    """Platform authority from the verified token, or '' for a workspace user.

    The claim is read from ``app_metadata`` only.  ``user_metadata`` is
    writable by the account itself, so reading it here would let any user
    promote themselves to platform administrator.
    """

    containers: list[Any] = [claims.get("app_metadata")]
    app_metadata = claims.get("app_metadata")
    if isinstance(app_metadata, dict):
        containers.append(app_metadata.get("aetrix"))
    for container in containers:
        if not isinstance(container, dict):
            continue
        value = container.get("aetrix_role")
        if isinstance(value, str) and value in PLATFORM_ROLE_BY_CLAIM:
            return PLATFORM_ROLE_BY_CLAIM[value]
    return ""


def platform_authority(principal: Principal) -> str:
    """The platform role for authorization, with the engine role as fallback.

    The claim is authoritative.  The fallback keeps an account whose engine row
    already says ADMIN or PLATFORM_OWNER working before its identity-provider
    claim is provisioned, and keeps existing tests meaningful.
    """

    if principal.platform_role:
        return principal.platform_role
    if principal.role in {"PLATFORM_OWNER", "ADMIN"}:
        return principal.role
    return ""


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def extract_verified_email(claims: dict[str, Any]) -> tuple[str | None, bool]:
    """Return the token's email and whether it counts as verified.

    Supabase access tokens do not always carry ``email_verified``.  A Google
    identity is verified by Google at consent, so its address may be trusted
    for invitation matching when no explicit claim is present; an email/password
    identity must carry an explicit verification claim, otherwise an
    unconfirmed address could redeem someone
    else's invitation.  The tenant is never taken from these claims: only the
    invitation decides which workspace a new principal joins.
    """

    app_metadata = claims.get("app_metadata")
    user_metadata = claims.get("user_metadata")
    containers = [claims]
    for container in (app_metadata, user_metadata):
        if isinstance(container, dict):
            containers.append(container)

    email: str | None = None
    for container in containers:
        value = container.get("email")
        if isinstance(value, str) and value.strip():
            email = value.strip().lower()
            break

    claim_present = any("email_verified" in container for container in containers)
    explicit = any(_truthy(container.get("email_verified")) for container in containers)
    provider = None
    if isinstance(app_metadata, dict):
        raw = app_metadata.get("provider")
        if isinstance(raw, str):
            provider = raw.lower()
    google = provider == "google" and email is not None
    if claim_present:
        # An explicit claim is authoritative even when it is false.  A token
        # that says the address is unverified must never be upgraded to
        # verified by a provider name alone.
        return email, explicit
    return email, google


def extract_display_name(claims: dict[str, Any]) -> str | None:
    user_metadata = claims.get("user_metadata")
    containers = [user_metadata, claims.get("app_metadata")]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("full_name", "name", "display_name"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
    return None


def require_tenant(principal: Principal) -> UUID:
    return principal.tenant_id


def ensure_reviewer(principal: Principal) -> None:
    if not principal.is_reviewer:
        raise AppError(ErrorCode.FORBIDDEN, "This action requires a reviewer role.")


def ensure_exam_manager(principal: Principal) -> None:
    if not principal.can_manage_exams:
        raise AppError(ErrorCode.FORBIDDEN, "This action requires a teacher or admin role.")
