"""Request dependencies: identity, tenant resolution and services."""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.errors import AppError, ErrorCode
from ..core.logging import tenant_id_var
from ..core.security import Principal, decode_jwt, extract_subject, extract_tenant_id
from ..db.repositories import UserRepository
from ..db.session import get_db_session
from ..prompts.registry import PromptRegistry
from ..providers.base import LLMProvider
from ..services.provider_calls import ProviderCallService
from ..storage.base import Storage


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(ErrorCode.UNAUTHORIZED, "Expected a Bearer token.")
    return token.strip()


def get_principal(
    request: Request,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Principal:
    token = _bearer(request)
    users = UserRepository(session)

    if token is None:
        if not settings.auth.dev_mode:
            raise AppError(ErrorCode.UNAUTHORIZED, "Authentication is required.")
        assert settings.auth.dev_tenant_id is not None
        assert settings.auth.dev_user_id is not None
        user = users.get(settings.auth.dev_tenant_id, settings.auth.dev_user_id)
        if user is None:
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "The development principal is not seeded in this database.",
            )
        principal = Principal(
            user_id=user.id,
            tenant_id=user.tenant_id,
            subject=user.subject,
            role=user.role,
        )
        tenant_id_var.set(str(principal.tenant_id))
        return principal

    claims = decode_jwt(token, settings)
    subject = extract_subject(claims)
    tenant_claim = extract_tenant_id(claims)

    if tenant_claim is not None:
        user = users.get_by_subject(tenant_claim, subject)
        if user is None:
            raise AppError(
                ErrorCode.FORBIDDEN, "This account does not belong to the requested workspace."
            )
    else:
        matches = users.find_by_subject_any_tenant(subject)
        if len(matches) != 1:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "The token does not identify a workspace and the account is ambiguous.",
            )
        user = matches[0]

    principal = Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        subject=user.subject,
        role=user.role,
    )
    tenant_id_var.set(str(principal.tenant_id))
    return principal


def tenant_id(principal: Principal = Depends(get_principal)) -> uuid.UUID:
    return principal.tenant_id


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_prompt_registry(request: Request) -> PromptRegistry:
    return request.app.state.prompt_registry


def get_provider_calls(
    request: Request,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ProviderCallService:
    return ProviderCallService(
        session,
        settings,
        request.app.state.provider,
        request.app.state.prompt_registry,
    )
