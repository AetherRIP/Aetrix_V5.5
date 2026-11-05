"""FastAPI application factory.

The API process does not start workers.  Marking is a separate process with its
own crash domain; an API restart must not interrupt a correction, and a worker
restart must not drop HTTP traffic.
"""

from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import ENGINE_NAME, __version__
from .api import health
from .api.v1.router import router as v1_router
from .core.config import Environment, Settings, get_settings
from .core.errors import install_exception_handlers
from .core.logging import configure_logging, get_logger, request_id_var
from .db.session import reset_engine
from .prompts.registry import PromptRegistry
from .providers.factory import build_provider
from .storage import build_storage

log = get_logger("aetrix.api")
_REQUEST_ID_ALLOWED = re.compile(r"[^A-Za-z0-9._-]")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging("DEBUG" if resolved.debug else "INFO", json_output=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        reset_engine()

    app = FastAPI(
        title="Aetrix V5.5 Correction Engine",
        version=__version__,
        description=(
            "Provider-independent correction engine. Phase 1 exposes the job "
            "lifecycle, canonical blueprints and tenancy; marking itself is "
            "implemented in later phases and jobs park honestly until then."
        ),
        openapi_url=f"{resolved.api_prefix}/openapi.json",
        docs_url="/docs" if resolved.env is not Environment.PRODUCTION else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.storage = build_storage(resolved)
    app.state.prompt_registry = PromptRegistry(resolved.provider.prompt_root)
    app.state.provider = build_provider(resolved)

    origins = resolved.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(v1_router, prefix=resolved.api_prefix)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = _REQUEST_ID_ALLOWED.sub("", supplied)[:80] or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    log.info(
        "api configured",
        extra={"extra_fields": {"environment": resolved.env.value, "version": __version__}},
    )
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


__all__ = ["ENGINE_NAME", "app", "create_app", "run"]
