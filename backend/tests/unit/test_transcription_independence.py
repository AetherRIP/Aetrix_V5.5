"""Whether the second reading was actually a second reader.

A transcription that is answered by the model that marked the paper verifies the
prompt, not the reading.  These tests pin the classification: a different
answering model is ``MODEL``, the marking model itself is ``PROMPT``, and an
unknown identity is ``UNKNOWN`` — never ``MODEL`` by default.

They also pin the configuration that made the review role unusable in Mission 5:
the chain began with a model no credential in this deployment is allowed to call.
The replacement starts with the model an isolated live reading of a real page
completed with, and it is not the marking chain's head.
"""

from __future__ import annotations

import pytest
from app.core.config import (
    MODEL_CHAIN_ROLES,
    ModelChainEntry,
    ProviderSettings,
    get_settings,
)
from app.core.errors import AppError
from app.core.marking_policy import PRODUCTION_MARKING_MODEL
from app.core.model_permissions import AICapability, is_permitted
from app.correction.transcription import (
    INDEPENDENCE_MODEL,
    INDEPENDENCE_PROMPT,
    INDEPENDENCE_UNKNOWN,
    classify_independence,
    marking_model_set,
)
from app.services.provider_calls import ProviderCallService


def test_a_different_answering_model_is_a_model_level_reading() -> None:
    assert (
        classify_independence("gemini-2.5-flash", ["gemini-3.1-flash-lite"])
        == INDEPENDENCE_MODEL
    )


def test_the_marking_model_answering_again_is_only_a_prompt_check() -> None:
    assert (
        classify_independence("gemini-3.1-flash-lite", ["gemini-3.1-flash-lite"])
        == INDEPENDENCE_PROMPT
    )
    assert (
        classify_independence(
            "gemini-2.5-flash", ["gemini-3.1-flash-lite", "gemini-2.5-flash"]
        )
        == INDEPENDENCE_PROMPT
    )


def test_an_unreported_answering_model_is_unknown_not_independent() -> None:
    assert classify_independence("", ["gemini-3.1-flash-lite"]) == INDEPENDENCE_UNKNOWN
    assert classify_independence(None, ["gemini-3.1-flash-lite"]) == INDEPENDENCE_UNKNOWN


def test_a_run_with_no_recorded_marking_model_cannot_claim_independence() -> None:
    assert classify_independence("gemini-2.5-flash", []) == INDEPENDENCE_UNKNOWN
    assert classify_independence("gemini-2.5-flash", [None, "  "]) == INDEPENDENCE_UNKNOWN


def test_whitespace_never_makes_two_identities_differ() -> None:
    assert (
        classify_independence("  gemini-3.1-flash-lite  ", ["gemini-3.1-flash-lite"])
        == INDEPENDENCE_PROMPT
    )


# -- every model that marked this job --------------------------------------


def test_every_source_of_a_marking_identity_is_considered() -> None:
    """This execution, the job row and an earlier execution's ledger."""

    models = marking_model_set(
        ["primary-model"],
        ["earlier-fallback-model"],
        ["primary-model", "double-check-model", ""],
        [None, "  "],
    )

    assert models == ("double-check-model", "earlier-fallback-model", "primary-model")


def test_a_blank_identity_never_counts_as_a_marking_model() -> None:
    assert marking_model_set([], [None, ""]) == ()
    assert classify_independence("reader", marking_model_set([""])) == INDEPENDENCE_UNKNOWN


def test_the_second_opinion_model_is_not_a_third_reader() -> None:
    """A double check re-marked the question, so its model is a marking model."""

    models = marking_model_set(["primary-model"], ["double-check-model"])

    assert classify_independence("double-check-model", models) == INDEPENDENCE_PROMPT
    assert classify_independence("a-third-model", models) == INDEPENDENCE_MODEL


# -- the configured review chain ------------------------------------------


def test_the_default_review_chain_starts_with_a_usable_model() -> None:
    settings = get_settings()
    review = settings.provider.model_chains["review"]

    assert review[0].model == "gemini-2.5-flash"
    assert review[0].enabled
    # The model no credential in this deployment may call is gone, rather than
    # sitting in front of every review request as an unusable first entry.
    assert "gemini-3.1-pro-preview" not in {entry.model for entry in review}


def test_the_review_chain_is_not_the_marking_chain() -> None:
    """Copying the marking chain into the review role would prove nothing."""

    chains = get_settings().provider.model_chains

    assert chains["review"][0].model != chains["primary"][0].model
    assert len({entry.model for entry in chains["review"]}) == len(chains["review"])


def test_the_review_chain_names_no_marking_model_fallback() -> None:
    """Falling back into the marking model would not be an independent reading.

    A blind transcription answered by ``gemini-3.6-flash`` is a second look with
    the same model that produced the marks, which is the defect the comparison
    exists to detect.  The chain names the reviewer only; the permission table
    would refuse the marking model for this role in any case.
    """

    review = {entry.model for entry in get_settings().provider.model_chains["review"]}

    assert PRODUCTION_MARKING_MODEL not in review
    assert not is_permitted(PRODUCTION_MARKING_MODEL, AICapability.INDEPENDENT_REVIEW)


def test_the_review_role_the_transcription_prompt_uses_exists() -> None:
    assert "review" in MODEL_CHAIN_ROLES


def test_a_review_chain_of_unpermitted_models_is_refused() -> None:
    """Configuring a fallback is not authorising it.

    Every model in this chain is either disabled for independent review or only
    reserved for it, so the role has no permitted model and must refuse before a
    credential is leased.  Calling ``gemini-3.6-flash`` here would be the silent
    fallback this test exists to prevent.
    """

    base = get_settings()
    provider = base.provider.model_copy(
        update={
            "model_chains": {
                "primary": [ModelChainEntry(model="gemini-3.6-flash")],
                "review": [
                    ModelChainEntry(model="gemini-2.5-flash"),
                    ModelChainEntry(model="gemini-3.6-flash"),
                ],
                "lightweight": [ModelChainEntry(model="gemini-2.5-flash")],
            }
        }
    )
    settings = base.model_copy(update={"provider": provider})
    service = ProviderCallService(None, settings, None, None)  # type: ignore[arg-type]

    with pytest.raises(AppError) as error:
        service.model_chain("review")

    assert error.value.code.value == "CONFIGURATION_ERROR"
    assert "gemini-2.5-flash" in error.value.message
    assert "gemini-3.6-flash" in error.value.message
    assert "independent_review" in error.value.message


def test_a_review_chain_entry_must_be_a_bare_model_id() -> None:
    """A chain that cannot name a model cannot be walked."""

    import pytest

    with pytest.raises(ValueError):
        ModelChainEntry(model="models/gemini-2.5-flash")


def test_the_environment_still_parses_the_default_chains() -> None:
    settings = ProviderSettings()

    assert set(settings.model_chains) == set(MODEL_CHAIN_ROLES)
