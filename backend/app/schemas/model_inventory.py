"""Contracts for the operator-visible model inventory.

The inventory is separate from live discovery: a registered model can be
unavailable, untested or missing an API identifier, and none of those states is
collapsed into "available".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

InventoryIdStatus = Literal["VERIFIED", "CORRECTED", "UNVERIFIED"]
InventoryCategory = Literal[
    "TEXT_OUT",
    "OTHER",
    "EMBEDDING",
    "AGENT",
    "IMAGE_GENERATION",
    "MULTIMODAL",
    "MUSIC_GENERATION",
    "TEXT_TO_SPEECH",
    "TRANSCRIPTION",
    "LIVE_API",
]
InventoryLifecycle = Literal[
    "STABLE",
    "PREVIEW",
    "EXPERIMENTAL",
    "LEGACY",
    "DEPRECATED",
    "RETIRED",
    "UNKNOWN",
]
InventoryAvailability = Literal[
    "AVAILABLE",
    "UNAVAILABLE",
    "ACCESS_RESTRICTED",
    "QUOTA_EXHAUSTED",
    "NOT_TESTED",
    "UNKNOWN",
]
InventoryWorkload = Literal[
    "mathematics_marking",
    "document_extraction",
    "image_generation",
    "audio_processing",
    "transcription",
    "embeddings",
    "agent_workflows",
    "other",
]


class InventoryQuotaRead(BaseModel):
    rpm_limit: int | None
    rpm_used: int
    rpm_unlimited: bool
    tpm_limit: int | None
    tpm_used: int
    tpm_unlimited: bool
    rpd_limit: int | None
    rpd_used: int
    rpd_unlimited: bool
    limits_provided: bool
    source: str
    imported_at: datetime
    observation_time_supplied: bool
    inconsistencies: list[str] = Field(default_factory=list)


class InventoryPricingRead(BaseModel):
    input_usd_per_million: float | None
    output_usd_per_million: float | None


class InventoryModelRead(BaseModel):
    key: str
    display_name: str
    api_model_id: str | None
    supplied_api_id: str | None
    id_status: InventoryIdStatus
    provider: str
    family: str
    version: str | None
    category: InventoryCategory
    lifecycle: InventoryLifecycle
    catalogue_state: str
    description: str | None
    input_modalities: list[str]
    output_modalities: list[str]
    context_window: int | None
    max_output_tokens: int | None
    supported_generation_methods: list[str]
    supports_generate: bool
    capabilities: dict[str, bool | None]
    capability_source: str
    limitations: list[str]
    workloads: list[InventoryWorkload]
    availability: InventoryAvailability
    source_url: str | None
    replacement_model_id: str | None
    pricing: InventoryPricingRead
    quota: InventoryQuotaRead


class InventoryCountsRead(BaseModel):
    total: int
    by_category: dict[str, int]
    by_lifecycle: dict[str, int]
    by_workload: dict[str, int]
    by_availability: dict[str, int]
    verified_api_ids: int
    corrected_api_ids: int
    unverified_api_ids: int
    math_marking_candidates: int
    quota_records: int
    quota_records_with_usage: int
    quota_inconsistencies: int


class ModelInventoryRead(BaseModel):
    imported_at: datetime
    models: list[InventoryModelRead]
    counts: InventoryCountsRead
    selections: dict[str, str]
    selection_sources: dict[str, str]
    note: str
