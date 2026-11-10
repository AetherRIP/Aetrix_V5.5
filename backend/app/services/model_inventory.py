"""Operator-supplied AI Studio inventory, quota snapshot and workload taxonomy.

This module is deliberately a *registry*, not a discovery result.  A model can
be registered here while being unavailable to every project; availability is
only ever learned from a credential's own ``models.list``.  The same rule
applies to API identifiers: a record with ``id_status='UNVERIFIED'`` has no
canonical identifier and must never be sent to a provider.

Quota figures are the operator's point-in-time AI Studio snapshot.  They are
stored with their import date and are not treated as live capacity.  Usage is
separate from the limit, including when a used value exceeds a displayed limit;
that inconsistency is preserved rather than normalised away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from ..core.config import Settings
from .model_catalogue import SELECTION_ROLES, effective_selection

Modality = Literal[
    "text",
    "image",
    "audio",
    "video",
    "pdf",
    "embedding",
    "other",
]
Category = Literal[
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
Lifecycle = Literal[
    "STABLE",
    "PREVIEW",
    "EXPERIMENTAL",
    "LEGACY",
    "DEPRECATED",
    "RETIRED",
    "UNKNOWN",
]
Availability = Literal[
    "AVAILABLE",
    "UNAVAILABLE",
    "ACCESS_RESTRICTED",
    "QUOTA_EXHAUSTED",
    "NOT_TESTED",
    "UNKNOWN",
]
IdStatus = Literal["VERIFIED", "CORRECTED", "UNVERIFIED"]
Workload = Literal[
    "mathematics_marking",
    "document_extraction",
    "image_generation",
    "audio_processing",
    "transcription",
    "embeddings",
    "agent_workflows",
    "other",
]

MODELS_URL = "https://ai.google.dev/gemini-api/docs/models"
CAPABILITIES_SOURCE = (
    "Operator-supplied category and official Gemini model pages, read 2026-11-10. "
    "Unset capability fields were not verified."
)
#: The operator did not include a time of day with the snapshot.  Preserve the
#: import date and say so instead of inventing an observation instant.
IMPORTED_AT = datetime(2026, 11, 10, tzinfo=UTC)
QUOTA_SOURCE = "Google AI Studio operator snapshot"

CAPABILITY_FIELDS = (
    "function_calling",
    "structured_output",
    "json_mode",
    "image_input",
    "pdf_input",
    "video_input",
    "audio_input",
    "audio_output",
    "image_generation",
    "thinking",
    "search_grounding",
    "maps_grounding",
    "code_execution",
    "caching",
    "batch_api",
    "live_api",
)

CATEGORY_ORDER: tuple[Category, ...] = (
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
)

WORKLOAD_ORDER: tuple[Workload, ...] = (
    "mathematics_marking",
    "document_extraction",
    "image_generation",
    "audio_processing",
    "transcription",
    "embeddings",
    "agent_workflows",
    "other",
)


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    rpm_limit: int | None
    rpm_used: int
    tpm_limit: int | None
    tpm_used: int
    rpd_limit: int | None
    rpd_used: int
    rpm_unlimited: bool = False
    tpm_unlimited: bool = False
    rpd_unlimited: bool = False
    limits_provided: bool = True
    source: str = QUOTA_SOURCE
    imported_at: datetime = IMPORTED_AT
    observation_time_supplied: bool = False

    @property
    def inconsistencies(self) -> tuple[str, ...]:
        messages: list[str] = []
        for label, used, limit, unlimited in (
            ("RPM", self.rpm_used, self.rpm_limit, self.rpm_unlimited),
            ("TPM", self.tpm_used, self.tpm_limit, self.tpm_unlimited),
            ("RPD", self.rpd_used, self.rpd_limit, self.rpd_unlimited),
        ):
            if limit is not None and not unlimited and used > limit:
                messages.append(f"{label} used {used:,} exceeds the supplied limit {limit:,}.")
        return tuple(messages)

    @property
    def has_usage(self) -> bool:
        return any((self.rpm_used, self.tpm_used, self.rpd_used))


@dataclass(frozen=True, slots=True)
class ModelRecord:
    key: str
    display_name: str
    api_model_id: str | None
    supplied_api_id: str | None
    id_status: IdStatus
    provider: str
    family: str
    version: str | None
    category: Category
    lifecycle: Lifecycle
    catalogue_state: str
    description: str | None
    input_modalities: tuple[Modality, ...] | None
    output_modalities: tuple[Modality, ...] | None
    context_window: int | None
    max_output_tokens: int | None
    supported_generation_methods: tuple[str, ...]
    supports_generate: bool
    capabilities: dict[str, bool | None]
    capability_source: str
    limitations: tuple[str, ...]
    workloads: tuple[Workload, ...]
    availability: Availability
    source_url: str | None
    quota: QuotaSnapshot
    replacement_model_id: str | None = None


def _q(
    rpm: int | None = None,
    tpm: int | None = None,
    rpd: int | None = None,
    *,
    rpm_used: int = 0,
    tpm_used: int = 0,
    rpd_used: int = 0,
    unlimited: tuple[str, ...] = (),
) -> QuotaSnapshot:
    unlimited_set = set(unlimited)
    limits_provided = any(value is not None for value in (rpm, tpm, rpd)) or bool(
        unlimited_set
    )
    return QuotaSnapshot(
        rpm_limit=None if "rpm" in unlimited_set else rpm,
        rpm_used=rpm_used,
        tpm_limit=None if "tpm" in unlimited_set else tpm,
        tpm_used=tpm_used,
        rpd_limit=None if "rpd" in unlimited_set else rpd,
        rpd_used=rpd_used,
        rpm_unlimited="rpm" in unlimited_set,
        tpm_unlimited="tpm" in unlimited_set,
        rpd_unlimited="rpd" in unlimited_set,
        limits_provided=limits_provided,
    )


def _caps(**values: bool | None) -> dict[str, bool | None]:
    capabilities = {field: None for field in CAPABILITY_FIELDS}
    capabilities.update(values)
    return capabilities


def _record(
    display_name: str,
    api_model_id: str | None,
    category: Category,
    *,
    key: str | None = None,
    family: str,
    version: str | None = None,
    lifecycle: Lifecycle = "UNKNOWN",
    id_status: IdStatus = "VERIFIED",
    supplied_api_id: str | None = None,
    input_modalities: tuple[Modality, ...] | None = None,
    output_modalities: tuple[Modality, ...] | None = None,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
    methods: tuple[str, ...] = (),
    supports_generate: bool = False,
    capabilities: dict[str, bool | None] | None = None,
    limitations: tuple[str, ...] = (),
    workloads: tuple[Workload, ...] = ("other",),
    availability: Availability = "NOT_TESTED",
    source_url: str | None = MODELS_URL,
    quota: QuotaSnapshot | None = None,
    replacement_model_id: str | None = None,
) -> ModelRecord:
    notes = list(limitations)
    if id_status == "UNVERIFIED":
        notes.append(
            "No official API model ID was verified; do not send a guessed identifier."
        )
    if id_status == "CORRECTED":
        notes.append(
            "The operator-supplied identifier was corrected to the canonical official ID."
        )
    if lifecycle == "RETIRED":
        notes.append("Official documentation lists this model as shut down.")
    if quota is not None and quota.inconsistencies:
        notes.extend(quota.inconsistencies)
    if quota is not None and not quota.limits_provided:
        notes.append("The supplied snapshot contains no rate limits for this model.")
    if lifecycle == "PREVIEW":
        notes.append("Preview model; lifecycle and access can change.")
    return ModelRecord(
        key=key or api_model_id or display_name.lower().replace(" ", "-"),
        display_name=display_name,
        api_model_id=api_model_id,
        supplied_api_id=supplied_api_id,
        id_status=id_status,
        provider="Google",
        family=family,
        version=version,
        category=category,
        lifecycle=lifecycle,
        catalogue_state=(
            "METADATA_INCOMPLETE" if id_status == "UNVERIFIED" else "REGISTERED"
        ),
        description=None,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        supported_generation_methods=methods,
        supports_generate=supports_generate,
        capabilities=capabilities or _caps(),
        capability_source=CAPABILITIES_SOURCE,
        limitations=tuple(notes),
        workloads=workloads,
        availability=availability,
        source_url=source_url,
        quota=quota or _q(),
        replacement_model_id=replacement_model_id,
    )


def _text(
    display_name: str,
    api_model_id: str | None,
    *,
    family: str,
    version: str,
    lifecycle: Lifecycle,
    quota: QuotaSnapshot | None = None,
    id_status: IdStatus = "VERIFIED",
    supplied_api_id: str | None = None,
    availability: Availability = "NOT_TESTED",
    limitations: tuple[str, ...] = (),
    replacement_model_id: str | None = None,
) -> ModelRecord:
    return _record(
        display_name,
        api_model_id,
        "TEXT_OUT",
        family=family,
        version=version,
        lifecycle=lifecycle,
        id_status=id_status,
        supplied_api_id=supplied_api_id,
        output_modalities=("text",),
        methods=("generateContent",),
        supports_generate=True,
        workloads=("mathematics_marking", "document_extraction"),
        availability=availability,
        quota=quota,
        limitations=limitations,
        replacement_model_id=replacement_model_id,
    )


def _image(
    display_name: str,
    api_model_id: str | None,
    *,
    family: str,
    version: str,
    lifecycle: Lifecycle = "STABLE",
    id_status: IdStatus = "VERIFIED",
    supplied_api_id: str | None = None,
    limitations: tuple[str, ...] = (),
) -> ModelRecord:
    return _record(
        display_name,
        api_model_id,
        "IMAGE_GENERATION",
        family=family,
        version=version,
        lifecycle=lifecycle,
        id_status=id_status,
        supplied_api_id=supplied_api_id,
        input_modalities=("text", "image"),
        output_modalities=("image", "text"),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(image_generation=True, image_input=True),
        workloads=("image_generation",),
        limitations=limitations,
    )


def _tts(
    display_name: str,
    api_model_id: str | None,
    *,
    family: str,
    version: str,
    lifecycle: Lifecycle,
    quota: QuotaSnapshot,
) -> ModelRecord:
    return _record(
        display_name,
        api_model_id,
        "TEXT_TO_SPEECH",
        family=family,
        version=version,
        lifecycle=lifecycle,
        input_modalities=("text",),
        output_modalities=("audio",),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(audio_output=True),
        workloads=("audio_processing",),
        quota=quota,
    )


def _live(
    display_name: str,
    api_model_id: str | None,
    *,
    family: str,
    version: str,
    lifecycle: Lifecycle,
    quota: QuotaSnapshot,
    id_status: IdStatus = "VERIFIED",
    limitations: tuple[str, ...] = (),
) -> ModelRecord:
    return _record(
        display_name,
        api_model_id,
        "LIVE_API",
        family=family,
        version=version,
        lifecycle=lifecycle,
        id_status=id_status,
        input_modalities=("audio", "video", "text"),
        output_modalities=("audio", "text"),
        methods=("live",),
        capabilities=_caps(live_api=True, audio_output=True, audio_input=True),
        workloads=("audio_processing", "transcription"),
        quota=quota,
        limitations=limitations,
    )


def _embedding(
    display_name: str,
    api_model_id: str,
    *,
    family: str,
    version: str,
    lifecycle: Lifecycle = "STABLE",
) -> ModelRecord:
    return _record(
        display_name,
        api_model_id,
        "EMBEDDING",
        family=family,
        version=version,
        lifecycle=lifecycle,
        input_modalities=("text",),
        output_modalities=("embedding",),
        methods=("embedContent",),
        workloads=("embeddings",),
    )


MODEL_RECORDS: tuple[ModelRecord, ...] = (
    # A. Text generation
    _text(
        "Gemini 3.6 Flash",
        "gemini-3.6-flash",
        family="Gemini 3.6",
        version="3.6",
        lifecycle="STABLE",
        quota=_q(5, 250_000, 20, rpm_used=2, tpm_used=5_510, rpd_used=23),
    ),
    _text(
        "Gemini 3.8 Flash",
        "gemini-3.8-flash",
        family="Gemini 3.8",
        version="3.8",
        lifecycle="STABLE",
        quota=_q(5, 250_000, 20, rpm_used=2, tpm_used=5_420, rpd_used=23),
    ),
    _text(
        "Gemini 2.5 Flash",
        "gemini-2.5-flash",
        family="Gemini 2.5",
        version="2.5",
        lifecycle="LEGACY",
        quota=_q(5, 250_000, 20, rpm_used=1, tpm_used=4_860, rpd_used=1),
    ),
    _text(
        "Gemini 3 Flash",
        "gemini-3-flash-preview",
        family="Gemini 3",
        version="3",
        lifecycle="PREVIEW",
        quota=_q(5, 250_000, 20, rpm_used=1, tpm_used=4_570, rpd_used=1),
    ),
    _text(
        "Gemini 3.5 Flash Lite",
        "gemini-3.5-flash-lite",
        family="Gemini 3.5",
        version="3.5",
        lifecycle="STABLE",
        quota=_q(15, 250_000, 500, rpm_used=2, tpm_used=8_490, rpd_used=27),
    ),
    _text(
        "Gemini 3.1 Flash Lite",
        "gemini-3.1-flash-lite",
        family="Gemini 3.1",
        version="3.1",
        lifecycle="STABLE",
        quota=_q(15, 250_000, 500, rpm_used=1, tpm_used=4_100, rpd_used=6),
    ),
    _text(
        "Gemini 3.1 Pro",
        "gemini-3.1-pro-preview",
        family="Gemini 3.1 Pro",
        version="3.1",
        lifecycle="PREVIEW",
        quota=_q(0, 0, 0),
    ),
    _text(
        "Gemini 2 Flash",
        "gemini-2.0-flash",
        family="Gemini 2.0",
        version="2.0",
        lifecycle="RETIRED",
        availability="UNAVAILABLE",
        quota=_q(0, 0, 0),
    ),
    _text(
        "Gemini 2 Flash Lite",
        "gemini-2.0-flash-lite",
        family="Gemini 2.0",
        version="2.0",
        lifecycle="RETIRED",
        availability="UNAVAILABLE",
        quota=_q(0, 0, 0),
    ),
    _text(
        "Gemini 2.5 Flash Lite",
        "gemini-2.5-flash-lite",
        family="Gemini 2.5",
        version="2.5",
        lifecycle="LEGACY",
        quota=_q(10, 250_000, 20),
    ),
    _text(
        "Gemini 2.5 Pro",
        "gemini-2.5-pro",
        family="Gemini 2.5",
        version="2.5",
        lifecycle="LEGACY",
        quota=_q(0, 0, 0),
    ),
    _text(
        "Gemini 4 Argon",
        "gemini-4-argon",
        family="Gemini 4",
        version="4",
        lifecycle="STABLE",
        quota=_q(0, 0, 0),
    ),
    _text(
        "Gemini 4 Carbon",
        "gemini-4-carbon",
        family="Gemini 4",
        version="4",
        lifecycle="STABLE",
        quota=_q(0, 0, 0),
    ),
    # B. Other models
    _record(
        "Gemma 4 31B",
        "gemma-4-31b-it",
        "OTHER",
        family="Gemma 4",
        version="4",
        lifecycle="STABLE",
        input_modalities=("text", "image"),
        output_modalities=("text",),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(function_calling=True),
        workloads=("other", "document_extraction"),
        quota=_q(30, 16_000, 14_400, rpm_used=1, tpm_used=4_140, rpd_used=1),
    ),
    _record(
        "Computer Use Preview",
        "gemini-2.5-computer-use-preview-10-2025",
        "OTHER",
        family="Computer Use",
        version="2.5",
        lifecycle="RETIRED",
        input_modalities=("text", "image"),
        output_modalities=("text",),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(function_calling=True, image_input=True),
        workloads=("agent_workflows", "other"),
        availability="UNAVAILABLE",
        quota=_q(0, 0, 0),
    ),
    _record(
        "Gemini Robotics ER 2 Preview",
        "gemini-robotics-er-2-preview",
        "OTHER",
        family="Gemini Robotics",
        version="ER 2",
        lifecycle="PREVIEW",
        input_modalities=("text", "image", "video"),
        output_modalities=("text",),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(image_input=True, video_input=True),
        workloads=("other",),
        quota=_q(5, 250_000, 20),
    ),
    _record(
        "Gemma 4 26B",
        "gemma-4-26b-a4b-it",
        "OTHER",
        family="Gemma 4",
        version="4",
        lifecycle="STABLE",
        input_modalities=("text", "image"),
        output_modalities=("text",),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(function_calling=True),
        workloads=("other", "document_extraction"),
        quota=_q(30, 16_000, 14_400),
    ),
    _embedding(
        "Gemini Embedding 1",
        "gemini-embedding-001",
        family="Gemini Embedding",
        version="1",
    ),
    _record(
        "Gemini Embedding 2",
        "gemini-embedding-2",
        "EMBEDDING",
        family="Gemini Embedding",
        version="2",
        lifecycle="STABLE",
        id_status="CORRECTED",
        supplied_api_id="gemini-embedding-2-preview",
        input_modalities=("text", "image", "video", "audio", "pdf"),
        output_modalities=("embedding",),
        methods=("embedContent",),
        workloads=("embeddings",),
    ),
    # C. Agent models
    _record(
        "Antigravity",
        "antigravity-preview-09-2026",
        "AGENT",
        family="Antigravity",
        version="09-2026",
        lifecycle="PREVIEW",
        input_modalities=("text", "image", "pdf"),
        output_modalities=("text", "image"),
        methods=("interactions",),
        workloads=("agent_workflows",),
        quota=_q(60, 100_000, 100),
    ),
    _record(
        "Deep Research Pro Preview",
        "deep-research-pro-preview-12-2025",
        "AGENT",
        family="Deep Research",
        version="12-2025",
        lifecycle="RETIRED",
        input_modalities=("text", "image", "pdf", "audio", "video"),
        output_modalities=("text", "image"),
        methods=("interactions",),
        workloads=("agent_workflows", "other"),
        availability="UNAVAILABLE",
        quota=_q(0, 0, 0),
        replacement_model_id="deep-research-preview-04-2026",
    ),
    # D. Image, multimodal and music
    _image(
        "Nano Banana (Gemini 2.5 Flash Preview Image)",
        "gemini-2.5-flash-image",
        family="Nano Banana",
        version="2.5 Flash",
    ),
    _image(
        "Nano Banana Pro (Gemini 3 Pro Image)",
        "gemini-3-pro-image",
        family="Nano Banana",
        version="3 Pro",
    ),
    _image(
        "Nano Banana 2 (Gemini 3.1 Flash Image)",
        "gemini-3.1-flash-image",
        family="Nano Banana",
        version="3.1 Flash",
    ),
    _image(
        "Nano Banana 2 Lite (Gemini 3.1 Flash Lite Image)",
        "gemini-3.1-flash-lite-image",
        family="Nano Banana",
        version="3.1 Flash Lite",
    ),
    _image(
        "Gemini Nano Banana 2.1",
        "gemini-nano-banana-2.1",
        family="Nano Banana",
        version="2.1",
    ),
    _record(
        "Gemini Omni 1.1 Flash",
        "gemini-omni-1.1-flash",
        "MULTIMODAL",
        family="Gemini Omni",
        version="1.1 Flash",
        lifecycle="STABLE",
        input_modalities=("text", "image", "audio", "video"),
        output_modalities=("text", "image", "audio", "video"),
        methods=("generateContent",),
        supports_generate=True,
        workloads=("document_extraction", "other"),
    ),
    _record(
        "Gemini Omni 1.2 Flash",
        None,
        "MULTIMODAL",
        family="Gemini Omni",
        version="1.2 Flash",
        lifecycle="UNKNOWN",
        id_status="UNVERIFIED",
        input_modalities=("text", "image", "audio", "video"),
        output_modalities=("text", "image", "audio", "video"),
        workloads=("document_extraction", "other"),
    ),
    _record(
        "Lyria 3 Clip",
        "lyria-3-clip-preview",
        "MUSIC_GENERATION",
        family="Lyria",
        version="3 Clip",
        lifecycle="PREVIEW",
        input_modalities=("text", "image"),
        output_modalities=("audio", "text"),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(audio_output=True),
        workloads=("audio_processing",),
    ),
    _record(
        "Lyria 3 Pro",
        "lyria-3-pro-preview",
        "MUSIC_GENERATION",
        family="Lyria",
        version="3 Pro",
        lifecycle="PREVIEW",
        input_modalities=("text", "image"),
        output_modalities=("audio", "text"),
        methods=("generateContent",),
        supports_generate=True,
        capabilities=_caps(audio_output=True),
        workloads=("audio_processing",),
    ),
    # E. Audio, speech and Live API
    _tts(
        "Gemini 2.5 Flash TTS",
        "gemini-2.5-flash-preview-tts",
        family="Gemini 2.5",
        version="2.5 Flash",
        lifecycle="PREVIEW",
        quota=_q(3, 10_000, 10),
    ),
    _tts(
        "Gemini 2.5 Pro TTS",
        "gemini-2.5-pro-preview-tts",
        family="Gemini 2.5",
        version="2.5 Pro",
        lifecycle="PREVIEW",
        quota=_q(0, 0, 0),
    ),
    _tts(
        "Gemini 3.1 Flash TTS",
        "gemini-3.1-flash-tts-preview",
        family="Gemini 3.1",
        version="3.1 Flash",
        lifecycle="PREVIEW",
        quota=_q(3, 10_000, 10),
    ),
    _tts(
        "Gemini 3.8 Flash Lite TTS",
        "gemini-3.8-flash-lite-tts",
        family="Gemini 3.8",
        version="3.8 Flash Lite",
        lifecycle="STABLE",
        quota=_q(3, 10_000, 10),
    ),
    _tts(
        "Gemini 3.8 Flash TTS",
        "gemini-3.8-flash-tts",
        family="Gemini 3.8",
        version="3.8 Flash",
        lifecycle="STABLE",
        quota=_q(3, 10_000, 10),
    ),
    _record(
        "Gemini 3.5 Transcribe",
        "gemini-3.5-transcribe",
        "TRANSCRIPTION",
        family="Gemini 3.5",
        version="3.5",
        lifecycle="STABLE",
        input_modalities=("audio",),
        output_modalities=("text",),
        methods=("generateContent",),
        supports_generate=True,
        workloads=("transcription", "audio_processing"),
        quota=_q(3, 10_000, 25),
    ),
    _live(
        "Gemini 2.5 Flash Native Audio Dialog",
        "gemini-2.5-flash-native-audio-preview-12-2025",
        family="Gemini 2.5",
        version="2.5 Flash",
        lifecycle="PREVIEW",
        quota=_q(None, 1_000_000, None, unlimited=("rpm", "rpd")),
    ),
    _live(
        "Gemini 3 Flash Live",
        None,
        family="Gemini 3",
        version="3 Flash",
        lifecycle="UNKNOWN",
        id_status="UNVERIFIED",
        quota=_q(None, 65_000, None, unlimited=("rpm", "rpd")),
        limitations=(
            "The official Gemini 3 Flash model page says Live API is not supported; "
            "no separate Live model ID was verified for this inventory entry.",
        ),
    ),
    _live(
        "Gemini 3.5 Live Translate",
        "gemini-3.5-live-translate-preview",
        family="Gemini 3.5",
        version="3.5",
        lifecycle="PREVIEW",
        quota=_q(None, 20_000, None, unlimited=("rpm", "rpd")),
    ),
    _live(
        "Gemini 3.5 Transcribe Live",
        "gemini-3.5-transcribe-live",
        family="Gemini 3.5",
        version="3.5",
        lifecycle="STABLE",
        quota=_q(None, 20_000, None, unlimited=("rpm", "rpd")),
    ),
    _live(
        "Gemini 3.8 Live",
        "gemini-3.8-live",
        family="Gemini 3.8",
        version="3.8",
        lifecycle="STABLE",
        quota=_q(None, 65_000, None, unlimited=("rpm", "rpd")),
    ),
    _live(
        "Gemini 3.8 Live Extended Thinking",
        "gemini-3.8-live-extended-thinking",
        family="Gemini 3.8",
        version="3.8",
        lifecycle="STABLE",
        quota=_q(None, 65_000, None, unlimited=("rpm", "rpd")),
    ),
)


def _rate(settings: Settings, model_id: str | None) -> dict[str, float | None]:
    if model_id is None:
        return {"input_usd_per_million": None, "output_usd_per_million": None}
    rates = settings.provider.model_rates.get(model_id) or {}

    def one(key: str) -> float | None:
        value = rates.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    return {
        "input_usd_per_million": one("input"),
        "output_usd_per_million": one("output"),
    }


def _quota_read(quota: QuotaSnapshot) -> dict[str, Any]:
    return {
        "rpm_limit": quota.rpm_limit,
        "rpm_used": quota.rpm_used,
        "rpm_unlimited": quota.rpm_unlimited,
        "tpm_limit": quota.tpm_limit,
        "tpm_used": quota.tpm_used,
        "tpm_unlimited": quota.tpm_unlimited,
        "rpd_limit": quota.rpd_limit,
        "rpd_used": quota.rpd_used,
        "rpd_unlimited": quota.rpd_unlimited,
        "limits_provided": quota.limits_provided,
        "source": quota.source,
        "imported_at": quota.imported_at,
        "observation_time_supplied": quota.observation_time_supplied,
        "inconsistencies": list(quota.inconsistencies),
    }


def model_read(record: ModelRecord, settings: Settings) -> dict[str, Any]:
    return {
        "key": record.key,
        "display_name": record.display_name,
        "api_model_id": record.api_model_id,
        "supplied_api_id": record.supplied_api_id,
        "id_status": record.id_status,
        "provider": record.provider,
        "family": record.family,
        "version": record.version,
        "category": record.category,
        "lifecycle": record.lifecycle,
        "catalogue_state": record.catalogue_state,
        "description": record.description,
        "input_modalities": list(record.input_modalities or []),
        "output_modalities": list(record.output_modalities or []),
        "context_window": record.context_window,
        "max_output_tokens": record.max_output_tokens,
        "supported_generation_methods": list(record.supported_generation_methods),
        "supports_generate": record.supports_generate,
        "capabilities": dict(record.capabilities),
        "capability_source": record.capability_source,
        "limitations": list(record.limitations),
        "workloads": list(record.workloads),
        "availability": record.availability,
        "source_url": record.source_url,
        "replacement_model_id": record.replacement_model_id,
        "pricing": _rate(settings, record.api_model_id),
        "quota": _quota_read(record.quota),
    }


def inventory_counts(models: tuple[ModelRecord, ...] = MODEL_RECORDS) -> dict[str, Any]:
    by_category = {
        category: sum(1 for model in models if model.category == category)
        for category in CATEGORY_ORDER
    }
    by_lifecycle = {
        lifecycle: sum(1 for model in models if model.lifecycle == lifecycle)
        for lifecycle in (
            "STABLE",
            "PREVIEW",
            "EXPERIMENTAL",
            "LEGACY",
            "DEPRECATED",
            "RETIRED",
            "UNKNOWN",
        )
    }
    by_workload = {
        workload: sum(1 for model in models if workload in model.workloads)
        for workload in WORKLOAD_ORDER
    }
    by_availability = {
        state: sum(1 for model in models if model.availability == state)
        for state in (
            "AVAILABLE",
            "UNAVAILABLE",
            "ACCESS_RESTRICTED",
            "QUOTA_EXHAUSTED",
            "NOT_TESTED",
            "UNKNOWN",
        )
    }
    return {
        "total": len(models),
        "by_category": by_category,
        "by_lifecycle": by_lifecycle,
        "by_workload": by_workload,
        "by_availability": by_availability,
        "verified_api_ids": sum(
            1
            for model in models
            if model.api_model_id is not None
            and model.id_status in {"VERIFIED", "CORRECTED"}
        ),
        "corrected_api_ids": sum(
            1 for model in models if model.id_status == "CORRECTED"
        ),
        "unverified_api_ids": sum(
            1 for model in models if model.id_status == "UNVERIFIED"
        ),
        "math_marking_candidates": sum(
            1 for model in models if "mathematics_marking" in model.workloads
        ),
        "quota_records": sum(1 for model in models if model.quota is not None),
        "quota_records_with_usage": sum(
            1 for model in models if model.quota is not None and model.quota.has_usage
        ),
        "quota_inconsistencies": sum(
            1
            for model in models
            if model.quota is not None and bool(model.quota.inconsistencies)
        ),
    }


def inventory_report(session: Session, settings: Settings) -> dict[str, Any]:
    models = [model_read(record, settings) for record in MODEL_RECORDS]
    selections: dict[str, str] = {}
    sources: dict[str, str] = {}
    for role in SELECTION_ROLES:
        model, source = effective_selection(session, settings, role)
        selections[role] = model
        sources[role] = source
    return {
        "imported_at": IMPORTED_AT,
        "models": models,
        "counts": inventory_counts(),
        "selections": selections,
        "selection_sources": sources,
        "note": (
            "The inventory is configuration-backed and registered independently of "
            "project availability. Quota and usage are the operator's AI Studio "
            "snapshot imported 2026-11-10; the snapshot did not include a time of "
            "day. A model is not available merely because it is registered."
        ),
    }
