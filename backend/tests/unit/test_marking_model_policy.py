"""One production marking model, and no route to a disabled one.

The policy is a property of the build, not a preference: configuration that
names another marking model fails at boot, a legacy saved selection fails before
a request is sent, and an explicit marking call never walks a fallback chain.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import ModelChainEntry, ProviderSettings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.marking_policy import (
    DISABLED_MARKING_MODELS,
    PRODUCTION_MARKING_MODEL,
    is_disabled_marking_model,
    is_production_marking_model,
    marking_model_problem,
)
from app.services.model_catalogue import (
    marking_policy_report,
    selected_model,
    set_selection,
)
from pydantic import ValidationError


def test_the_default_marking_chain_is_one_model() -> None:
    settings = ProviderSettings()

    enabled = [entry.model for entry in settings.model_chains["primary"] if entry.enabled]
    assert enabled == [PRODUCTION_MARKING_MODEL]
    assert settings.model_primary == PRODUCTION_MARKING_MODEL


def test_both_lite_models_are_disabled() -> None:
    assert set(DISABLED_MARKING_MODELS) == {
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    }
    for model in DISABLED_MARKING_MODELS:
        assert is_disabled_marking_model(model)
        assert not is_production_marking_model(model)
        assert marking_model_problem(model) is not None


def test_a_lightweight_model_is_never_a_marking_model() -> None:
    # V5's own rule, kept: ``-lite`` is refused even when the id is new.
    assert is_disabled_marking_model("gemini-9.9-flash-lite")
    # Surrounding whitespace is not a different model.
    assert is_production_marking_model("  gemini-3.6-flash  ")
    assert not is_production_marking_model("gemini-3.6-flash-preview")


def test_configuration_refuses_a_lite_marking_chain() -> None:
    with pytest.raises(ValidationError) as error:
        ProviderSettings(
            model_chains={
                "primary": [ModelChainEntry(model="gemini-3.1-flash-lite")],
                "review": [ModelChainEntry(model="gemini-2.5-flash")],
                "lightweight": [ModelChainEntry(model="gemini-2.5-flash")],
            }
        )

    message = str(error.value)
    assert "gemini-3.1-flash-lite" in message
    assert PRODUCTION_MARKING_MODEL in message


def test_configuration_refuses_a_marking_fallback() -> None:
    with pytest.raises(ValidationError) as error:
        ProviderSettings(
            model_chains={
                "primary": [
                    ModelChainEntry(model=PRODUCTION_MARKING_MODEL),
                    ModelChainEntry(model="gemini-2.5-flash"),
                ],
                "review": [ModelChainEntry(model="gemini-2.5-flash")],
                "lightweight": [ModelChainEntry(model="gemini-2.5-flash")],
            }
        )

    assert "exactly one enabled entry" in str(error.value)
    assert "no fallback" in str(error.value)


def test_configuration_refuses_a_lite_environment_model() -> None:
    with pytest.raises(ValidationError) as error:
        ProviderSettings(model_primary="gemini-3.5-flash-lite")

    assert "gemini-3.5-flash-lite" in str(error.value)


def test_a_legacy_saved_lite_selection_is_refused_before_marking() -> None:
    class LegacySelection:
        def scalar(self, _statement: object) -> SimpleNamespace:
            return SimpleNamespace(model="gemini-3.1-flash-lite")

    with pytest.raises(AppError) as error:
        selected_model(LegacySelection(), get_settings(), "primary")

    assert error.value.code is ErrorCode.CONFIGURATION_ERROR
    assert "gemini-3.1-flash-lite" in error.value.message
    assert PRODUCTION_MARKING_MODEL in error.value.message
    assert error.value.details["disabled_models"] == sorted(DISABLED_MARKING_MODELS)


def test_the_selection_api_refuses_a_lite_marking_model() -> None:
    """The refusal happens before any project discovery or database write."""

    for model in sorted(DISABLED_MARKING_MODELS):
        with pytest.raises(AppError) as error:
            set_selection(None, get_settings(), "primary", model, actor="test")  # type: ignore[arg-type]

        assert error.value.code is ErrorCode.CONFLICT
        assert model in error.value.message
        assert PRODUCTION_MARKING_MODEL in error.value.message


def test_the_selection_api_refuses_a_lite_review_model() -> None:
    with pytest.raises(AppError) as error:
        set_selection(
            None, get_settings(), "review", "gemini-3.5-flash-lite", actor="test"  # type: ignore[arg-type]
        )

    assert error.value.code is ErrorCode.CONFLICT
    assert "disabled lightweight model" in error.value.message


def test_the_admin_policy_report_names_the_one_model_and_the_disabled_set() -> None:
    report = marking_policy_report(get_settings())

    assert report["marking_model"] == PRODUCTION_MARKING_MODEL
    assert report["disabled_models"] == sorted(DISABLED_MARKING_MODELS)
    assert report["primary_chain"] == [PRODUCTION_MARKING_MODEL]
    assert report["enforced"] is True
