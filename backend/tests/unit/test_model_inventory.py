"""The supplied inventory is data, not an availability claim."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import get_settings
from app.main import app
from app.schemas.model_inventory import ModelInventoryRead
from app.services.model_catalogue import effective_selection
from app.services.model_inventory import MODEL_RECORDS, inventory_counts, inventory_report
from app.services.provider_calls import ProviderCallService


def test_complete_inventory_is_registered_without_duplicate_ids() -> None:
    counts = inventory_counts()

    assert counts["total"] == 42
    assert len({model.key for model in MODEL_RECORDS}) == 42
    canonical = [model.api_model_id for model in MODEL_RECORDS if model.api_model_id]
    assert len(canonical) == len(set(canonical))


def test_counts_separate_registration_from_availability() -> None:
    counts = inventory_counts()

    assert counts["by_category"] == {
        "TEXT_OUT": 13,
        "OTHER": 4,
        "EMBEDDING": 2,
        "AGENT": 2,
        "IMAGE_GENERATION": 5,
        "MULTIMODAL": 2,
        "MUSIC_GENERATION": 2,
        "TEXT_TO_SPEECH": 5,
        "TRANSCRIPTION": 1,
        "LIVE_API": 6,
    }
    assert counts["verified_api_ids"] == 40
    assert counts["corrected_api_ids"] == 1
    assert counts["unverified_api_ids"] == 2
    assert counts["by_availability"]["AVAILABLE"] == 0
    assert counts["by_availability"]["UNAVAILABLE"] == 4
    assert counts["by_availability"]["NOT_TESTED"] == 38
    assert counts["math_marking_candidates"] == 13


def test_unverified_records_never_carry_a_guessed_identifier() -> None:
    unverified = [model for model in MODEL_RECORDS if model.id_status == "UNVERIFIED"]

    assert {model.key for model in unverified} == {
        "gemini-omni-1.2-flash",
        "gemini-3-flash-live",
    }
    assert all(model.api_model_id is None for model in unverified)
    assert all(model.catalogue_state == "METADATA_INCOMPLETE" for model in unverified)


def test_embedding_identifier_is_corrected_and_visible() -> None:
    corrected = next(
        model for model in MODEL_RECORDS if model.supplied_api_id == "gemini-embedding-2-preview"
    )

    assert corrected.api_model_id == "gemini-embedding-2"
    assert corrected.id_status == "CORRECTED"


def test_quota_snapshot_preserves_usage_above_the_supplied_limit() -> None:
    counts = inventory_counts()
    flash = next(model for model in MODEL_RECORDS if model.key == "gemini-3.6-flash")
    flash_38 = next(model for model in MODEL_RECORDS if model.key == "gemini-3.8-flash")

    assert counts["quota_records"] == 42
    assert counts["quota_records_with_usage"] == 7
    assert counts["quota_inconsistencies"] == 2
    assert flash.quota.rpm_used == 2
    assert flash.quota.tpm_used == 5_510
    assert flash.quota.rpd_used == 23
    assert flash.quota.rpd_limit == 20
    assert flash.quota.inconsistencies == (
        "RPD used 23 exceeds the supplied limit 20.",
    )
    assert flash_38.quota.inconsistencies
    assert flash.quota.observation_time_supplied is False


def test_inventory_route_is_exposed_and_serialises_the_complete_report() -> None:
    class EmptySelectionSession:
        def scalar(self, _statement: object) -> None:
            return None

    report = ModelInventoryRead(**inventory_report(EmptySelectionSession(), get_settings()))

    assert len(report.models) == 42
    assert report.counts.total == 42
    assert "/api/v1/admin/providers/models/inventory" in app.openapi()["paths"]


def test_saved_selection_is_the_model_the_provider_call_path_uses() -> None:
    class StoredSelectionSession:
        def scalar(self, _statement: object) -> SimpleNamespace:
            return SimpleNamespace(model="gemini-3.8-flash")

    session = StoredSelectionSession()
    settings = get_settings()
    service = object.__new__(ProviderCallService)
    service.session = session  # type: ignore[assignment]
    service.settings = settings

    assert effective_selection(session, settings, "primary") == (
        "gemini-3.8-flash",
        "database",
    )
    assert service._model_for("primary") == "gemini-3.8-flash"
    assert service._model_for("review") == "gemini-3.8-flash"


def test_retired_and_agent_entries_keep_their_lifecycle_and_replacement() -> None:
    retired = next(model for model in MODEL_RECORDS if model.key == "gemini-2.0-flash")
    research = next(
        model for model in MODEL_RECORDS if model.key == "deep-research-pro-preview-12-2025"
    )

    assert retired.lifecycle == "RETIRED"
    assert retired.availability == "UNAVAILABLE"
    assert research.lifecycle == "RETIRED"
    assert research.replacement_model_id == "deep-research-preview-04-2026"
