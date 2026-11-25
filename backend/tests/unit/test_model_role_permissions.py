"""Role-specific model permissions, including the routing gate.

Marking is one capability with one model.  Transcription and independent review
are separate capabilities, and the agreed policy grants them to nobody today:

===================  =========  =============  ==================
Model                Marking    Transcription  Independent review
===================  =========  =============  ==================
gemini-3.6-flash     ENABLED    RESERVED       RESERVED
gemini-3.5-flash-lite DISABLED  RESERVED       DISABLED
gemini-3.1-flash-lite DISABLED  RESERVED       DISABLED
===================  =========  =============  ==================

"Reserved" is not "enabled": a reserved model may be *named* for a role so it
can be switched on after validation, and it may never execute until the
permission itself changes.  The marking model holds no specialist grant because a
reading taken by the marking model is not an independent one.

These tests pin the table, the configuration gate that keeps a reserved role from
executing, the routing boundary that refuses a chain of unpermitted models, and
the production marking restrictions the migration established.
"""

from __future__ import annotations

import pytest
from app.core.config import ProviderSettings
from app.core.marking_policy import (
    DISABLED_MARKING_MODELS,
    PRODUCTION_MARKING_MODEL,
    is_production_marking_model,
    marking_model_problem,
)
from app.core.model_permissions import (
    AICapability,
    PermissionStatus,
    capability_for_call,
    capability_for_role,
    is_permitted,
    is_reserved,
    model_permission_report,
    permission_for,
    permission_problem,
    permitted_models,
    role_configuration_problem,
    role_exhausted_problem,
)
from pydantic import ValidationError

FLASH = PRODUCTION_MARKING_MODEL
FLASH_LITE_35 = "gemini-3.5-flash-lite"
FLASH_LITE_31 = "gemini-3.1-flash-lite"
PRO_PREVIEW = "gemini-3.1-pro-preview"


# -- the agreed table --------------------------------------------------------


def test_the_permission_matrix_matches_the_agreed_policy() -> None:
    assert permission_for(FLASH, AICapability.MARKING) is PermissionStatus.ENABLED
    # Being the marking model is not a grant to read or review.
    assert permission_for(FLASH, AICapability.TRANSCRIPTION) is PermissionStatus.RESERVED
    assert (
        permission_for(FLASH, AICapability.INDEPENDENT_REVIEW)
        is PermissionStatus.RESERVED
    )

    for lite in (FLASH_LITE_35, FLASH_LITE_31):
        assert permission_for(lite, AICapability.MARKING) is PermissionStatus.DISABLED
        assert (
            permission_for(lite, AICapability.TRANSCRIPTION) is PermissionStatus.RESERVED
        )
        assert (
            permission_for(lite, AICapability.INDEPENDENT_REVIEW)
            is PermissionStatus.DISABLED
        )


def test_no_model_is_permitted_for_independent_review() -> None:
    """The review role has no executable model, and that is the policy."""

    assert not is_permitted(FLASH, AICapability.INDEPENDENT_REVIEW)
    assert not is_permitted(FLASH_LITE_35, AICapability.INDEPENDENT_REVIEW)
    assert not is_permitted(FLASH_LITE_31, AICapability.INDEPENDENT_REVIEW)
    assert permitted_models(
        AICapability.INDEPENDENT_REVIEW, [FLASH, FLASH_LITE_35, FLASH_LITE_31]
    ) == []


def test_no_model_is_permitted_for_transcription_yet() -> None:
    assert permitted_models(
        AICapability.TRANSCRIPTION, [FLASH, FLASH_LITE_35, FLASH_LITE_31]
    ) == []


# -- marking stays exactly as it was ----------------------------------------


def test_gemini_3_5_flash_lite_cannot_perform_marking() -> None:
    assert not is_production_marking_model(FLASH_LITE_35)
    assert marking_model_problem(FLASH_LITE_35) is not None
    assert permission_problem(FLASH_LITE_35, AICapability.MARKING) is not None
    assert not is_permitted(FLASH_LITE_35, AICapability.MARKING)

    with pytest.raises(ValidationError) as error:
        ProviderSettings(model_primary=FLASH_LITE_35)

    assert FLASH_LITE_35 in str(error.value)
    assert FLASH in str(error.value)


def test_gemini_3_1_flash_lite_cannot_perform_marking() -> None:
    assert not is_production_marking_model(FLASH_LITE_31)
    assert marking_model_problem(FLASH_LITE_31) is not None
    assert permission_problem(FLASH_LITE_31, AICapability.MARKING) is not None
    assert not is_permitted(FLASH_LITE_31, AICapability.MARKING)

    with pytest.raises(ValidationError) as error:
        ProviderSettings(model_primary=FLASH_LITE_31)

    assert FLASH_LITE_31 in str(error.value)
    assert FLASH in str(error.value)


def test_production_marking_continues_to_use_gemini_3_6_flash_only() -> None:
    settings = ProviderSettings()
    enabled_primary = [
        entry.model for entry in settings.model_chains["primary"] if entry.enabled
    ]

    assert settings.model_primary == FLASH
    assert enabled_primary == [FLASH]
    assert set(DISABLED_MARKING_MODELS) == {FLASH_LITE_35, FLASH_LITE_31}

    for model in sorted(DISABLED_MARKING_MODELS):
        with pytest.raises(ValidationError):
            ProviderSettings(model_primary=model)
        assert permission_problem(model, AICapability.MARKING) is not None


# -- reserved roles cannot execute -----------------------------------------


def test_a_lite_model_may_be_named_for_transcription_without_marking() -> None:
    for lite in (FLASH_LITE_35, FLASH_LITE_31):
        settings = ProviderSettings(transcription_model=lite)

        assert settings.transcription_model == lite
        assert settings.transcription_role_enabled is False
        assert is_reserved(lite, AICapability.TRANSCRIPTION)
        assert not is_permitted(lite, AICapability.TRANSCRIPTION)

        enabled_primary = [
            entry.model for entry in settings.model_chains["primary"] if entry.enabled
        ]
        assert settings.model_primary == FLASH
        assert enabled_primary == [FLASH]
        assert permission_problem(lite, AICapability.MARKING) is not None


def test_the_marking_model_may_be_named_for_a_specialist_role_but_not_enabled() -> None:
    settings = ProviderSettings(transcription_model=FLASH)

    assert settings.transcription_model == FLASH
    assert settings.transcription_role_enabled is False
    assert is_reserved(FLASH, AICapability.TRANSCRIPTION)

    for capability in (AICapability.TRANSCRIPTION, AICapability.INDEPENDENT_REVIEW):
        problem = role_configuration_problem(FLASH, capability, enabled=True)
        assert problem is not None
        assert "RESERVED" in problem
        assert FLASH in problem
        assert not is_permitted(FLASH, capability)

    with pytest.raises(ValidationError) as error:
        ProviderSettings(transcription_model=FLASH, transcription_role_enabled=True)
    assert "RESERVED" in str(error.value)
    assert FLASH in str(error.value)

    with pytest.raises(ValidationError) as error:
        ProviderSettings(
            independent_review_model=FLASH, independent_review_role_enabled=True
        )
    assert "RESERVED" in str(error.value)
    assert FLASH in str(error.value)


def test_reserved_roles_cannot_execute_until_explicitly_enabled() -> None:
    reserved = (
        (FLASH, AICapability.TRANSCRIPTION),
        (FLASH, AICapability.INDEPENDENT_REVIEW),
        (FLASH_LITE_35, AICapability.TRANSCRIPTION),
        (FLASH_LITE_31, AICapability.TRANSCRIPTION),
    )

    for model, capability in reserved:
        # Naming the model (role off) is the reservation, and is accepted.
        assert role_configuration_problem(model, capability, enabled=False) is None
        # Switching the role on is refused while the permission is reserved.
        problem = role_configuration_problem(model, capability, enabled=True)
        assert problem is not None
        assert "RESERVED" in problem
        assert model in problem
        assert not is_permitted(model, capability)

    with pytest.raises(ValidationError) as error:
        ProviderSettings(
            transcription_model=FLASH_LITE_35,
            transcription_role_enabled=True,
        )
    assert "RESERVED" in str(error.value)
    assert FLASH_LITE_35 in str(error.value)


def test_a_disabled_capability_cannot_even_name_its_model() -> None:
    # 3.1 Flash Lite is disabled for review, so it cannot be named for it.
    with pytest.raises(ValidationError) as error:
        ProviderSettings(independent_review_model=FLASH_LITE_31)
    assert FLASH_LITE_31 in str(error.value)

    # 3.5 Flash Lite is disabled for review too.
    with pytest.raises(ValidationError) as error:
        ProviderSettings(independent_review_model=FLASH_LITE_35)
    assert FLASH_LITE_35 in str(error.value)


def test_an_unknown_model_is_not_permitted_by_default() -> None:
    assert (
        permission_for("gemini-9.9-flash", AICapability.TRANSCRIPTION)
        is PermissionStatus.DISABLED
    )
    with pytest.raises(ValidationError):
        ProviderSettings(transcription_model="gemini-9.9-flash")


def test_the_unavailable_pro_preview_review_configuration_stays_disabled() -> None:
    assert (
        permission_for(PRO_PREVIEW, AICapability.INDEPENDENT_REVIEW)
        is PermissionStatus.DISABLED
    )
    assert not is_permitted(PRO_PREVIEW, AICapability.INDEPENDENT_REVIEW)

    with pytest.raises(ValidationError) as error:
        ProviderSettings(independent_review_model=PRO_PREVIEW)
    assert PRO_PREVIEW in str(error.value)

    with pytest.raises(ValidationError):
        ProviderSettings(
            independent_review_model=PRO_PREVIEW,
            independent_review_role_enabled=True,
        )


# -- the routing boundary ----------------------------------------------------


def test_a_role_maps_to_the_capability_it_performs() -> None:
    assert capability_for_role("primary") is AICapability.MARKING
    assert capability_for_role("review") is AICapability.INDEPENDENT_REVIEW
    assert capability_for_role("lightweight") is AICapability.TRANSCRIPTION
    # An unknown role is a marking request, never a silent specialist grant.
    assert capability_for_role("something-else") is AICapability.MARKING


def test_blind_transcription_is_judged_as_transcription_not_review() -> None:
    """The manifest files it under ``review``; the purpose is the authority.

    Without this, a transcription call was authorised by a review grant — the
    defect that let a disabled review configuration execute.
    """

    assert (
        capability_for_call(role="review", purpose="transcription")
        is AICapability.TRANSCRIPTION
    )
    assert (
        capability_for_call(role="review", purpose="double_check")
        is AICapability.INDEPENDENT_REVIEW
    )
    assert capability_for_call(role="primary", purpose="marking") is AICapability.MARKING


def test_a_chain_of_unpermitted_models_produces_an_actionable_refusal() -> None:
    message = role_exhausted_problem(
        "review",
        AICapability.INDEPENDENT_REVIEW,
        ["gemini-2.5-flash", "gemini-3.6-flash"],
    )

    assert "review" in message
    assert "independent_review" in message
    assert "gemini-2.5-flash (DISABLED)" in message
    assert "gemini-3.6-flash (RESERVED)" in message
    assert "Nothing was sent to the provider" in message


def test_the_policy_report_separates_active_reserved_and_disabled() -> None:
    report = model_permission_report()

    assert report["marking_model"] == FLASH
    assert report["specialist_roles_implemented"] is False
    assert "not implemented" in report["note"]
    assert report["role_capabilities"]["review"] == "independent_review"
    assert report["purpose_capabilities"]["transcription"] == "transcription"

    assert report["permitted"]["marking"] == [FLASH]
    assert report["reserved"]["marking"] == []
    assert report["disabled"]["marking"] == [FLASH_LITE_35, FLASH_LITE_31, PRO_PREVIEW]

    assert report["permitted"]["transcription"] == []
    assert report["permitted"]["independent_review"] == []
    assert report["reserved"]["transcription"] == [
        FLASH,
        FLASH_LITE_35,
        FLASH_LITE_31,
    ]
    assert report["reserved"]["independent_review"] == [FLASH]

    assert report["models"][FLASH]["marking"] == "ENABLED"
    assert report["models"][FLASH]["transcription"] == "RESERVED"
    assert report["models"][FLASH_LITE_35]["transcription"] == "RESERVED"
    assert report["models"][FLASH_LITE_31]["transcription"] == "RESERVED"
    assert report["models"][FLASH_LITE_31]["independent_review"] == "DISABLED"
    assert report["models"][PRO_PREVIEW]["independent_review"] == "DISABLED"
