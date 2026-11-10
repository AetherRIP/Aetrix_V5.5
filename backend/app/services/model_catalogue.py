"""Dynamic Gemini model discovery and correction-role selection.

Google's ``models.list`` is the authority for what a credential can reach; the
public catalogue is not.  Discovery is therefore performed per Google Cloud
project with that project's own key, cached for a bounded time, and never
replaced by a hardcoded "available" list.

Two rules shape the result:

* a model is only *available* where that project's ``models.list`` returned it;
* a model with no ``generateContent`` method, or one of Google's specialised
  image/TTS/Live/embedding endpoints, is listed but marked unsupported so it can
  never be selected as a correction model.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..core.security import SecretBox
from ..db.models import ProviderCredential, ProviderModelSelection
from ..providers.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTransientError,
)

SELECTION_ROLES = ("primary", "review", "lightweight")
MODEL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,118}$")

#: Deprecations that ``models.list`` does not report.  Kept small and dated: a
#: model's presence here is the only reason Aetrix calls it deprecated.
_DEPRECATED: dict[str, str] = {
    "gemini-3.1-flash-lite-preview": (
        "Google lists this preview as shut down on 2026-05-25; "
        "use gemini-3.1-flash-lite."
    ),
    "gemini-3-pro-preview": (
        "Google lists this preview as shut down on 2026-03-09; "
        "use gemini-3.1-pro-preview."
    ),
}

#: Endpoints that answer ``generateContent`` but are not general correction
#: models.  Excluding them is a taxonomy decision, not an availability claim.
_SPECIALISED = (
    "embedding",
    "tts",
    "image",
    "live",
    "transcribe",
    "lyria",
    "robotics",
    "computer-use",
    "deep-research",
    "antigravity",
    "aqa",
    "omni",
    "nano-banana",
    "gemma",
)

#: Input modalities read from Google's model pages, not inferred from an id.
_DOCUMENTED_INPUTS: dict[str, list[str]] = {
    "gemini-3.8-flash": ["text", "image", "video", "audio", "pdf"],
    "gemini-3.5-flash-lite": ["text", "image", "video", "audio", "pdf"],
    "gemini-3.1-flash-lite": ["text", "image", "video", "audio", "pdf"],
}
_CAPABILITY_SOURCE = "ai.google.dev Gemini model pages, read 2026-11-10"

_STATUS_RANK = {"stable": 0, "preview": 1, "deprecated": 2, "unsupported": 3}

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()


def _provider_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "provider returned a non-JSON error response"
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str):
        return message[:300]
    return "provider returned an error"


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    status_code = response.status_code
    message = _provider_message(response)
    if status_code in {401, 403}:
        raise ProviderAuthenticationError(
            "The provider rejected the credential.",
            status_code=status_code,
            provider_message=message,
        )
    if status_code == 429:
        raise ProviderQuotaError(
            "The provider quota is exhausted for this key.",
            status_code=status_code,
            provider_message=message,
        )
    if status_code >= 500:
        raise ProviderTransientError(
            "The provider is temporarily unavailable.",
            status_code=status_code,
            provider_message=message,
        )
    raise ProviderRequestError(
        "The provider rejected the model-list request.",
        status_code=status_code,
        provider_message=message,
    )


def fetch_project_models(
    base_url: str,
    api_key: SecretStr,
    *,
    timeout_seconds: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, Any]]:
    """One project's ``models.list``, paginated and never keyed by guesswork."""

    collected: list[dict[str, Any]] = []
    page_token: str | None = None
    with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
        for _ in range(5):
            params: dict[str, Any] = {"pageSize": 200}
            if page_token:
                params["pageToken"] = page_token
            response = client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"x-goog-api-key": api_key.get_secret_value()},
                params=params,
            )
            _raise_for_status(response)
            try:
                body = response.json()
            except ValueError as error:
                raise ProviderResponseError(
                    "The model list was not JSON.",
                    status_code=response.status_code,
                ) from error
            if not isinstance(body, dict):
                raise ProviderResponseError(
                    "The model list was malformed.",
                    status_code=response.status_code,
                )
            models = body.get("models")
            if isinstance(models, list):
                collected.extend(item for item in models if isinstance(item, dict))
            token = body.get("nextPageToken")
            page_token = token if isinstance(token, str) and token else None
            if page_token is None:
                break
    return collected


def _cached_models(
    cache_key: str,
    ttl_seconds: int,
    loader: Any,
    *,
    refresh: bool,
) -> tuple[list[dict[str, Any]], bool]:
    if not refresh:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1], True
    models = loader()
    with _CACHE_LOCK:
        _CACHE[cache_key] = (time.monotonic() + ttl_seconds, models)
    return models, False


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _unsupported_reason(model_id: str, methods: list[str]) -> str | None:
    if "generateContent" not in methods:
        return "This endpoint does not support generateContent."
    if model_id.startswith("gemma"):
        return "Gemma is a separate model family, not a Gemini correction model."
    for marker in _SPECIALISED:
        if marker in model_id:
            return f"Specialised '{marker}' endpoint; not a general correction model."
    return None


def _rate(rates: dict[str, Any], key: str) -> float | None:
    value = rates.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def build_catalogue(
    raw_by_project: dict[str, list[dict[str, Any]]],
    settings: Settings,
    *,
    discovered_at: datetime,
    cached: bool,
) -> dict[str, Any]:
    """Union the projects' lists without ever claiming more than they returned."""

    merged: dict[str, dict[str, Any]] = {}
    for project_id, raw_models in raw_by_project.items():
        for raw in raw_models:
            model_id = str(raw.get("name", "")).removeprefix("models/")
            if not model_id:
                continue
            entry = merged.setdefault(model_id, {"raw": raw, "projects": set()})
            entry["projects"].add(project_id)

    models: list[dict[str, Any]] = []
    for model_id, entry in merged.items():
        raw = entry["raw"]
        methods = [str(item) for item in raw.get("supportedGenerationMethods") or []]
        reason = _unsupported_reason(model_id, methods)
        status = (
            "unsupported"
            if reason
            else "deprecated"
            if model_id in _DEPRECATED
            else "preview"
            if "preview" in model_id
            else "stable"
        )
        rates = settings.provider.model_rates.get(model_id) or {}
        input_limit = raw.get("inputTokenLimit")
        output_limit = raw.get("outputTokenLimit")
        models.append(
            {
                "id": model_id,
                "display_name": raw.get("displayName"),
                "description": raw.get("description"),
                "status": status,
                "status_detail": reason or _DEPRECATED.get(model_id),
                "supports_generate": "generateContent" in methods,
                "input_token_limit": (
                    input_limit if isinstance(input_limit, int) else None
                ),
                "output_token_limit": (
                    output_limit if isinstance(output_limit, int) else None
                ),
                "capabilities": {
                    "structured_outputs": None,
                    "thinking": None,
                    "documented_inputs": _DOCUMENTED_INPUTS.get(model_id),
                    "source": (
                        _CAPABILITY_SOURCE
                        if model_id in _DOCUMENTED_INPUTS
                        else None
                    ),
                },
                "input_usd_per_million": _rate(rates, "input"),
                "output_usd_per_million": _rate(rates, "output"),
                "projects": [
                    {"project_id": project_id, "available": project_id in entry["projects"]}
                    for project_id in sorted(raw_by_project)
                ],
            }
        )

    models.sort(key=lambda model: (_STATUS_RANK[model["status"]], model["id"]))
    return {
        "discovered_at": discovered_at,
        "cached": cached,
        "ttl_seconds": 0,
        "projects": [],
        "models": models,
        "selections": {},
        "selection_sources": {},
        "note": "",
    }


def _usable_by_project(session: Session) -> dict[str, ProviderCredential]:
    rows = session.scalars(
        select(ProviderCredential)
        .where(
            ProviderCredential.revoked_at.is_(None),
            ProviderCredential.health.in_(("HEALTHY", "UNKNOWN")),
        )
        .order_by(ProviderCredential.project_id)
    ).all()
    chosen: dict[str, ProviderCredential] = {}
    for row in rows:
        current = chosen.get(row.project_id)
        if current is None or (current.health != "HEALTHY" and row.health == "HEALTHY"):
            chosen[row.project_id] = row
    return chosen


def _fallback_model(settings: Settings, role: str) -> str:
    if role == "review":
        return settings.provider.model_review
    if role == "lightweight":
        return settings.provider.model_lightweight
    return settings.provider.model_primary


def effective_selection(
    session: Session, settings: Settings, role: str
) -> tuple[str, str]:
    stored = session.scalar(
        select(ProviderModelSelection).where(ProviderModelSelection.role == role)
    )
    if stored is not None:
        return stored.model, "database"
    return _fallback_model(settings, role), "settings"


def selected_model(session: Session, settings: Settings, role: str) -> str:
    return effective_selection(session, settings, role)[0]


def discover_catalogue(
    session: Session, settings: Settings, *, refresh: bool = False
) -> dict[str, Any]:
    discovered_at = utcnow()
    chosen = _usable_by_project(session)
    box = SecretBox(settings.security.encryption_key.get_secret_value())

    raw_by_project: dict[str, list[dict[str, Any]]] = {}
    projects: list[dict[str, Any]] = []
    all_cached = bool(chosen)

    for project_id, credential in sorted(chosen.items()):
        cache_key = (
            f"{settings.provider.gemini_base_url}|{project_id}|"
            f"{credential.key_fingerprint}"
        )

        def load(
            credential: ProviderCredential = credential,
        ) -> list[dict[str, Any]]:
            return fetch_project_models(
                settings.provider.gemini_base_url,
                SecretStr(box.decrypt(credential.encrypted_secret)),
                timeout_seconds=15.0,
            )

        try:
            models, cached = _cached_models(
                cache_key,
                settings.provider.model_catalogue_ttl_seconds,
                load,
                refresh=refresh,
            )
        except (InvalidTag, ValueError):
            projects.append(
                {
                    "project_id": project_id,
                    "ok": False,
                    "models": 0,
                    "error": "The stored key could not be decrypted; re-register it.",
                    "credential_fingerprint": credential.key_fingerprint,
                }
            )
            all_cached = False
            continue
        except ProviderError as error:
            projects.append(
                {
                    "project_id": project_id,
                    "ok": False,
                    "models": 0,
                    "error": f"{type(error).__name__}: {error}",
                    "credential_fingerprint": credential.key_fingerprint,
                }
            )
            all_cached = False
            continue

        raw_by_project[project_id] = models
        projects.append(
            {
                "project_id": project_id,
                "ok": True,
                "models": len(models),
                "error": None,
                "credential_fingerprint": credential.key_fingerprint,
            }
        )
        all_cached = all_cached and cached

    catalogue = build_catalogue(
        raw_by_project,
        settings,
        discovered_at=discovered_at,
        cached=all_cached,
    )
    catalogue["projects"] = projects
    catalogue["ttl_seconds"] = settings.provider.model_catalogue_ttl_seconds

    selections: dict[str, str] = {}
    sources: dict[str, str] = {}
    for role in SELECTION_ROLES:
        model, source = effective_selection(session, settings, role)
        selections[role] = model
        sources[role] = source
    catalogue["selections"] = selections
    catalogue["selection_sources"] = sources
    catalogue["note"] = (
        "Availability is read from models.list with one key per Google Cloud "
        "project; a model absent from a project's list is shown unavailable to "
        "it. Prices are Aetrix-configured list prices, not a Google quote."
    )
    return catalogue


def set_selection(
    session: Session,
    settings: Settings,
    role: str,
    model: str,
    *,
    actor: str | None,
) -> ProviderModelSelection:
    """Persist a role's model after checking it was really listed."""

    if role not in SELECTION_ROLES:
        raise AppError(ErrorCode.NOT_FOUND, f"Unknown model role '{role}'.")
    model = model.strip()
    if not MODEL_ID_PATTERN.match(model):
        raise AppError(ErrorCode.CONFLICT, "That is not a valid Gemini model id.")

    catalogue = discover_catalogue(session, settings)
    if not catalogue["models"]:
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "No registered credential could list models, so the selection was "
            "not saved. Nothing was changed.",
        )
    match = next(
        (entry for entry in catalogue["models"] if entry["id"] == model), None
    )
    if match is None:
        raise AppError(
            ErrorCode.CONFLICT,
            f"'{model}' was not listed for any registered project. Nothing was "
            "saved; refresh discovery before selecting it.",
        )
    if match["status"] == "unsupported":
        raise AppError(
            ErrorCode.CONFLICT,
            f"'{model}' is not a correction model: {match['status_detail']}",
        )

    now = utcnow()
    row = session.scalar(
        select(ProviderModelSelection)
        .where(ProviderModelSelection.role == role)
        .with_for_update()
    )
    if row is None:
        row = ProviderModelSelection(
            role=role, model=model, updated_at=now, updated_by=actor
        )
        session.add(row)
    else:
        row.model = model
        row.updated_at = now
        row.updated_by = actor
    session.commit()
    return row
