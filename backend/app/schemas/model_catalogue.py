"""Contracts for model discovery and correction-role selection.

Nothing here reports a model as available on the strength of documentation: an
entry exists because a registered credential's ``models.list`` returned it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ModelRole = Literal["primary", "review", "lightweight"]
ModelStatus = Literal["stable", "preview", "deprecated", "unsupported"]


class ModelCapabilitiesRead(BaseModel):
    structured_outputs: bool | None
    thinking: bool | None
    documented_inputs: list[str] | None
    source: str | None


class ModelProjectAccessRead(BaseModel):
    project_id: str
    #: True only when this project's own models.list returned the model.
    available: bool


class CatalogueModelRead(BaseModel):
    id: str
    display_name: str | None
    description: str | None
    status: ModelStatus
    status_detail: str | None
    supports_generate: bool
    input_token_limit: int | None
    output_token_limit: int | None
    capabilities: ModelCapabilitiesRead
    input_usd_per_million: float | None
    output_usd_per_million: float | None
    projects: list[ModelProjectAccessRead]


class CatalogueProjectRead(BaseModel):
    project_id: str
    #: Which key was actually used to list this project's models. A fingerprint,
    #: never the secret.
    credential_fingerprint: str
    ok: bool
    models: int
    error: str | None


class ModelCatalogueRead(BaseModel):
    discovered_at: datetime
    cached: bool
    ttl_seconds: int
    projects: list[CatalogueProjectRead]
    models: list[CatalogueModelRead]
    selections: dict[str, str]
    selection_sources: dict[str, str]
    note: str


class ModelSelectionWrite(BaseModel):
    model: str = Field(min_length=1, max_length=120)


class ModelSelectionRead(BaseModel):
    role: ModelRole
    model: str
    updated_at: datetime
    updated_by: str | None


class ModelTestRequest(BaseModel):
    credential_id: UUID | None = None
    project_id: str | None = Field(default=None, max_length=100)
