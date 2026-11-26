"""Role-specific model permissions, including the routing gate.

Marking is one capability with one model.  Transcription and independent review
are separate capabilities, granted to the designated review model:

===================  =========  =============  ==================
Model                Marking    Transcription  Independent review
===================  =========  =============  ==================
gemini-2.5-flash     DISABLED   ENABLED        ENABLED
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
#: The designated review model: the second examiner and the blind reader.
FLASH_REVIEW = "gemini-2.5-flash"
FLASH_LITE_35 = "gemini-3.5-flash-lite"
FLASH_LITE_31 = "gemini-3.1-flash-lite"
PRO_PREVIEW = "gemini-3.1-pro-preview"
HYDROGEN = "gemini-4-hydrogen"
FLASH_38 = "gemini-3.8-flash"
#: The three verified primary marking models, in declared priority order.
PRIMARIES = (HYDROGEN, FLASH_38, FLASH)


# -- the agreed table --------------------------------------------------------


def test_the_permission_matrix_matches_the_agreed_policy() -> None:
    # All three verified primaries may mark; none may review or transcribe.
    for model in PRIMARIES:
        assert permission_for(model, AICapability.MARKING) is PermissionStatus.ENABLED
        assert (
            permission_for(model, AICapability.TRANSCRIPTION)
            is PermissionStatus.RESERVED
        )
        assert (
            permission_for(model, AICapability.INDEPENDENT_REVIEW)
            is PermissionStatus.RESERVED
        )

    # The two checkers each hold exactly one specialist role, and neither marks.
    assert permission_for(FLASH_LITE_31, AICapability.MARKING) is PermissionStatus.DISABLED
    assert (
        permission_for(FLASH_LITE_31, AICapability.TRANSCRIPTION)
        is PermissionStatus.ENABLED
    )
    assert (
        permission_for(FLASH_LITE_31, AICapability.INDEPENDENT_REVIEW)
        is PermissionStatus.DISABLED
    )

    assert permission_for(FLASH_LITE_35, AICapability.MARKING) is PermissionStatus.DISABLED
    assert (
        permission_for(FLASH_LITE_35, AICapability.INDEPENDENT_REVIEW)
        is PermissionStatus.ENABLED
    )
    assert (
        permission_for(FLASH_LITE_35, AICapability.TRANSCRIPTION)
        is PermissionStatus.RESERVED
    )

    # The retired review model holds no grant at all.
    for capability in AICapability:
        assert (
            permission_for(FLASH_REVIEW, capability) is PermissionStatus.DISABLED
        ), capability


def test_exactly_one_model_is_permitted_for_independent_review() -> None:
    """The evidence checker, and never a marking model."""

    assert permitted_models(
        AICapability.INDEPENDENT_REVIEW, [*PRIMARIES, FLASH_LITE_35, FLASH_LITE_31]
    ) == [FLASH_LITE_35]
    for model in PRIMARIES:
        assert not is_permitted(model, AICapability.INDEPENDENT_REVIEW)


def test_exactly_one_model_is_permitted_for_blind_transcription() -> None:
    """The transcription checker, and never the model that marked the paper."""

    assert permitted_models(
        AICapability.TRANSCRIPTION, [*PRIMARIES, FLASH_LITE_35, FLASH_LITE_31]
    ) == [FLASH_LITE_31]
    for model in PRIMARIES:
        assert not is_permitted(model, AICapability.TRANSCRIPTION)


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


def test_a_checker_is_named_for_its_own_role_and_never_for_marking() -> None:
    # The evidence checker is reserved for transcription, and permitted for the
    # role it actually performs.
    settings = ProviderSettings(transcription_model=FLASH_LITE_35)
    assert settings.transcription_model == FLASH_LITE_35
    assert is_reserved(FLASH_LITE_35, AICapability.TRANSCRIPTION)
    assert not is_permitted(FLASH_LITE_35, AICapability.TRANSCRIPTION)
    assert is_permitted(FLASH_LITE_35, AICapability.INDEPENDENT_REVIEW)

    # A checker never marks, however permissive its other role is.
    for lite in (FLASH_LITE_35, FLASH_LITE_31):
        assert permission_problem(lite, AICapability.MARKING) is not None
        with pytest.raises(ValidationError):
            ProviderSettings(model_primary=lite)

    enabled_primary = [
        entry.model for entry in ProviderSettings().model_chains["primary"] if entry.enabled
    ]
    assert enabled_primary == [FLASH]


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
    reserved = tuple(
        (model, capability)
        for model in PRIMARIES
        for capability in (AICapability.TRANSCRIPTION, AICapability.INDEPENDENT_REVIEW)
    )
    reserved += ((FLASH_LITE_35, AICapability.TRANSCRIPTION),)

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
    # 3.1 Flash Lite holds the transcription role only; review is disabled for
    # it, so it cannot even be named for review.
    with pytest.raises(ValidationError) as error:
        ProviderSettings(independent_review_model=FLASH_LITE_31)
    assert FLASH_LITE_31 in str(error.value)

    # The retired review model may not be named for either role.
    with pytest.raises(ValidationError):
        ProviderSettings(independent_review_model=FLASH_REVIEW)


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
        [FLASH_LITE_31, FLASH],
    )

    assert "review" in message
    assert "independent_review" in message
    assert f"{FLASH_LITE_31} (DISABLED)" in message
    assert f"{FLASH} (RESERVED)" in message
    assert "Nothing was sent to the provider" in message


def test_the_policy_report_separates_active_reserved_and_disabled() -> None:
    report = model_permission_report()

    assert report["marking_model"] == FLASH
    assert report["marking_models"] == list(PRIMARIES)
    assert report["specialist_roles_implemented"] is True
    assert "primary models" in report["note"]
    assert report["role_capabilities"]["review"] == "independent_review"
    assert report["purpose_capabilities"]["transcription"] == "transcription"

    # Three models may mark; nothing else may, and the pool is not a fallback.
    assert report["permitted"]["marking"] == list(PRIMARIES)
    assert report["reserved"]["marking"] == []
    assert report["disabled"]["marking"] == [
        FLASH_REVIEW,
        FLASH_LITE_35,
        FLASH_LITE_31,
        PRO_PREVIEW,
    ]

    # Each independent role belongs to exactly one model, and it is not a
    # marking model; the primaries may only be named for those roles.
    assert report["permitted"]["transcription"] == [FLASH_LITE_31]
    assert report["permitted"]["independent_review"] == [FLASH_LITE_35]
    assert report["reserved"]["transcription"] == [
        HYDROGEN,
        FLASH_38,
        FLASH,
        FLASH_LITE_35,
    ]
    assert report["reserved"]["independent_review"] == [HYDROGEN, FLASH_38, FLASH]

    for model in PRIMARIES:
        assert report["models"][model]["marking"] == "ENABLED"
        assert report["models"][model]["transcription"] == "RESERVED"
        assert report["models"][model]["independent_review"] == "RESERVED"
    assert report["models"][FLASH_REVIEW]["marking"] == "DISABLED"
    assert report["models"][FLASH_REVIEW]["transcription"] == "DISABLED"
    assert report["models"][FLASH_REVIEW]["independent_review"] == "DISABLED"
    assert report["models"][FLASH_LITE_35]["transcription"] == "RESERVED"
    assert report["models"][FLASH_LITE_31]["transcription"] == "ENABLED"
    assert report["models"][FLASH_LITE_31]["independent_review"] == "DISABLED"
    assert report["models"][PRO_PREVIEW]["independent_review"] == "DISABLED"
