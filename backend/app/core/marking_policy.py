"""The production marking-model policy.

Math Checker V5 ships one trusted marking model and refuses a lightweight model
for marking.  This module carries that policy into Aetrix unchanged: the engine
is the correction pipeline, and ``gemini-3.6-flash`` is the model that pipeline
calls.  There is no fallback, because a fallback that changes the marking model
would make the recorded model a guess.

Two rules follow from the policy and are enforced elsewhere:

* ``selected_model`` (``app.services.model_catalogue``) refuses to resolve a
  primary role that is not the production marking model;
* ``ProviderCallService.call`` accepts an explicit model for a marking request,
  which turns the configured chain into a single entry and removes the
  automatic fallback route entirely.

Disabling a model here never removes its price, quota entry or historical
records.  It only stops the model from being chosen for a new marking request.
"""

from __future__ import annotations

#: The only model a production correction job may mark with.
PRODUCTION_MARKING_MODEL = "gemini-3.6-flash"

#: The two lightweight models the earlier experiments used as marking
#: alternatives.  They remain priced and historically readable; neither can be
#: selected for marking or reached as a fallback.
DISABLED_MARKING_MODELS = frozenset(
    {
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    }
)

#: V5's own trust rule, kept: a lightweight model is never a marking model,
#: including a Lite variant this module has not met by name.
UNTRUSTED_MARKING_SUFFIX = "-lite"


def normalise_model_id(model: str | None) -> str:
    """The bare model id, without surrounding whitespace."""

    return str(model or "").strip()


def is_lightweight_model(model: str | None) -> bool:
    """Whether the id names a lightweight model (``*-lite``)."""

    return normalise_model_id(model).lower().endswith(UNTRUSTED_MARKING_SUFFIX)


def is_disabled_marking_model(model: str | None) -> bool:
    """Whether this id is refused for marking and as a marking fallback."""

    candidate = normalise_model_id(model)
    return candidate in DISABLED_MARKING_MODELS or is_lightweight_model(candidate)


def is_production_marking_model(model: str | None) -> bool:
    """Whether this id is the one model a production paper may be marked with."""

    return normalise_model_id(model) == PRODUCTION_MARKING_MODEL


def marking_model_problem(model: str | None) -> str | None:
    """Why this id cannot be the production marking model, or ``None``.

    The sentence is written for an operator: it names the model that was asked
    for, the model production uses, and what to change.
    """

    candidate = normalise_model_id(model)
    if not candidate:
        return (
            "No production marking model is configured. "
            f"{PRODUCTION_MARKING_MODEL} is the only marking model this build "
            "allows."
        )
    if candidate in DISABLED_MARKING_MODELS:
        return (
            f"{candidate} is a disabled lightweight marking model. "
            f"{PRODUCTION_MARKING_MODEL} is the only marking model production "
            "uses; remove the disabled model from the marking configuration."
        )
    if is_lightweight_model(candidate):
        return (
            f"{candidate} is a lightweight model, and lightweight models are not "
            f"marking models. {PRODUCTION_MARKING_MODEL} is the only marking "
            "model production uses."
        )
    if candidate != PRODUCTION_MARKING_MODEL:
        return (
            f"{candidate} is not the production marking model. "
            f"{PRODUCTION_MARKING_MODEL} is the only model a production "
            "correction job may use; select it or remove the override."
        )
    return None
