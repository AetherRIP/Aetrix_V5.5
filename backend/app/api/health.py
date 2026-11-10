"""Liveness, readiness and version endpoints.

``/health`` answers even when the database is down; ``/ready`` executes a real
query and refuses to claim readiness if it fails.  A load balancer should route
on ``/ready``, not on the process merely existing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import ENGINE_NAME, __version__
from ..core.config import Settings, get_settings
from ..core.errors import ErrorCode
from ..db.session import get_db_session
from ..schemas.api import HealthRead, ReadinessRead
from ..schemas.status import SystemStatusRead
from ..services.status import read_system_status

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthRead)
def health() -> HealthRead:
    return HealthRead(status="ok", service=ENGINE_NAME, version=__version__)


@router.get("/version", response_model=HealthRead)
def version(settings: Settings = Depends(get_settings)) -> HealthRead:
    return HealthRead(status=settings.env.value, service=ENGINE_NAME, version=__version__)


@router.get("/status", response_model=SystemStatusRead)
def status(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SystemStatusRead:
    """Every subsystem, observed separately.

    A 200 here is not a claim that everything works: it says the API answered.
    The body carries the database probe, the worker heartbeat and the feature
    registry, each with its own state.
    """

    return read_system_status(session, settings)


@router.get("/ready", response_model=ReadinessRead)
def ready(session: Session = Depends(get_db_session)) -> ReadinessRead | JSONResponse:
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": str(ErrorCode.SERVICE_NOT_READY),
                    "message": "The database is not reachable.",
                    "details": {},
                }
            },
        )
    return ReadinessRead(status="ready", database="ok")
