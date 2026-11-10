"""Structured subsystem and component status.

Each field is an observation, an explicit ``unknown`` or an explicit
``not_implemented``.  One subsystem is never inferred from another: a reachable
API says nothing about the database, the worker or a provider, and the contract
is shaped so a caller cannot read "API answered" as "everything works".

``components`` goes further than ``worker``/``provider``: it separates *deployment*
(a process or credential exists) from *operation* (it is working right now) from
*readiness* (it can do its job).  A worker can be deployed and unavailable, and a
provider can be configured while its last live call failed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

#: ``unknown`` is deliberate: it is the honest answer when this build has no
#: observation, and it is distinct from ``unavailable`` (observed as down).
SubsystemState = Literal["ok", "degraded", "unavailable", "unknown", "not_implemented"]

#: Whether the component exists and has run: separate from whether it works.
ComponentDeployment = Literal["deployed", "not_deployed", "not_configured", "unknown"]

#: What the component is doing now.  ``unverified`` is not ``available``: no
#: successful observation has been recorded.
ComponentOperational = Literal[
    "available", "starting", "degraded", "unavailable", "unverified", "unknown"
]

#: Whether the component can perform its own job, which is narrower than being up.
ComponentReadiness = Literal[
    "ready", "not_ready", "not_applicable", "unavailable", "unknown"
]


class SubsystemStatus(BaseModel):
    state: SubsystemState
    summary: str
    detail: str | None = None


class ComponentHealthRead(BaseModel):
    """One component's deployment, operation, readiness and evidence."""

    name: str
    deployment: ComponentDeployment
    operational: ComponentOperational
    readiness: ComponentReadiness
    #: When this component's row was composed (the status read itself).
    checked_at: datetime
    #: The last successful health observation, not a claim about now.
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure: str | None = None
    diagnostic: str


class FeatureStatus(BaseModel):
    name: str
    state: Literal["available", "not_implemented"]
    reason: str


class SystemStatusRead(BaseModel):
    checked_at: datetime
    service: str
    version: str
    environment: str
    #: The API answered this request.  It is the only subsystem this response
    #: proves by existing.
    api: SubsystemStatus
    #: The correction-engine process responded.
    engine: SubsystemStatus
    #: The engine is initialised and can accept a correction job.  Job progress
    #: beyond validation is still unimplemented; the detail says so.
    readiness: SubsystemStatus
    database: SubsystemStatus
    worker: SubsystemStatus
    provider: SubsystemStatus
    #: The same observations, shaped for a component table.  Every entry carries
    #: its own evidence so a screen cannot upgrade one state into another.
    components: list[ComponentHealthRead] = Field(default_factory=list)
    features: list[FeatureStatus] = Field(default_factory=list)
