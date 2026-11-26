"""The verified model registry: ids, capabilities, roles and lifecycle.

These tests exist because the mission's five model ids must never be accepted on
trust.  A model that is not in the registry cannot be configured or called, a
model without PDF or image input cannot mark a scanned paper, and a checking
model can never become a marking model.
"""

from __future__ import annotations

import pytest
from app.core import model_registry
from app.core.marking_policy import (
    PRIMARY_MARKING_MODELS,
    PRODUCTION_MARKING_MODEL,
    is_disabled_marking_model,
    is_primary_marking_model,
    marking_model_problem,
)
from app.core.model_registry import (
    MARKING_EXCLUDED,
    REGISTRY,
    ModelRegistryError,
    can_mark,
    get_model,
    is_registered,
    models_for_role,
    registry_report,
    require_model,
)


def test_the_five_mission_models_are_registered():
    expected = {
        "gemini-4-hydrogen",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    }
    assert expected <= set(REGISTRY)


def test_three_primary_models_in_declared_priority_order():
    assert PRIMARY_MARKING_MODELS == (
        "gemini-4-hydrogen",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
    )
    assert PRODUCTION_MARKING_MODEL in PRIMARY_MARKING_MODELS
    assert [model.model_id for model in models_for_role(model_registry.ROLE_PRIMARY)] == [
        "gemini-4-hydrogen",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
    ]


def test_two_checkers_hold_the_two_independent_roles():
    transcription = models_for_role(model_registry.ROLE_TRANSCRIPTION_CHECKER)
    evidence = models_for_role(model_registry.ROLE_EVIDENCE_CHECKER)
    assert [model.model_id for model in transcription] == ["gemini-3.1-flash-lite"]
    assert [model.model_id for model in evidence] == ["gemini-3.5-flash-lite"]


def test_every_primary_can_mark_and_no_checker_can():
    for model_id in PRIMARY_MARKING_MODELS:
        assert can_mark(model_id), model_id
        assert marking_model_problem(model_id) is None
    for model_id in MARKING_EXCLUDED:
        assert not can_mark(model_id)
        assert "independent checking model" in (marking_model_problem(model_id) or "")
        assert is_disabled_marking_model(model_id)


def test_an_unregistered_model_is_refused_by_name():
    assert not is_registered("gemini-9-imaginary")
    assert get_model("gemini-9-imaginary") is None
    assert not can_mark("gemini-9-imaginary")
    problem = marking_model_problem("gemini-9-imaginary")
    assert "not a verified marking model" in problem
    assert "gemini-4-hydrogen" in problem
    with pytest.raises(ModelRegistryError):
        require_model("gemini-9-imaginary")


def test_a_lightweight_model_is_never_a_marking_model():
    assert is_disabled_marking_model("gemini-3.5-flash-lite")
    assert is_disabled_marking_model("gemini-3.1-flash-lite")
    # A Lite id the registry has never met is still refused.
    assert is_disabled_marking_model("gemini-9-flash-lite")
    assert not is_primary_marking_model("gemini-9-flash-lite")


def test_every_model_is_stable_and_accepts_a_scanned_paper():
    """A marking model must accept both page images and PDFs."""

    for model in REGISTRY.values():
        assert model.stability == "stable", model.model_id
        assert model.pdf_input and model.image_input, model.model_id
        assert model.structured_outputs, model.model_id
        assert model.context_limit >= 100_000
        assert model.source_url.startswith("https://ai.google.dev/")
        assert model.verified_on.isoformat()


def test_retirement_dates_are_recorded_rather_than_assumed():
    retiring = registry_report()["retiring"]
    # 3.1 Flash-Lite has an announced shutdown; Hydrogen has none.
    assert "gemini-3.1-flash-lite" in retiring
    assert get_model("gemini-3.1-flash-lite").retirement_date is not None
    assert "gemini-4-hydrogen" not in retiring
    assert get_model("gemini-4-hydrogen").retirement_date is None


def test_the_free_tier_data_use_flag_is_recorded_for_every_model():
    """Free-tier product-improvement use is a student-data fact, not a price."""

    for model in REGISTRY.values():
        assert model.free_tier is True
        assert model.free_tier_used_for_product_improvement is True


def test_the_report_names_sources_and_dates():
    report = registry_report()
    assert len(report["primary_models"]) == 3
    assert len(report["checker_models"]) == 2
    assert report["sources"]["catalogue"].startswith("https://ai.google.dev/")
    assert report["verified_on"] == "2026-11-25"
