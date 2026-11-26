"""The production marking-model policy.

Aetrix marks a paper with exactly one model, and that model must be one of the
verified primary marking models.  Three models are certified for that job:

``gemini-4-hydrogen``
    Priority 1.  Stable, 1M context, PDF and image input, structured output.
``gemini-3.8-flash``
    Priority 2.  Stable, the current Flash generation.
``gemini-3.6-flash``
    Priority 3.  The previous-generation Flash this engine has actually marked
    papers with, and the default when no scheduler choice is configured.

What changed, and what did not
------------------------------
This used to name a single marking model and refuse every other id.  That rule
protected the thing that matters — a recorded model is never a guess, and a
paper is never re-marked by a different model part-way through — but it also
meant one model's daily allowance capped the platform's throughput.

The protection is kept and the scope is widened: a paper is still assigned to
one model, that assignment is recorded before the first paid request, and no
model is ever substituted after a failure.  Three models are eligible to *be*
that assignment.  Which one is chosen is the scheduler's decision
(``app.services.model_scheduler``), not a fallback.

A lightweight model is still never a marking model, and the two independent
checking models are excluded by name: a checker that marks is not independent.
"""

from __future__ import annotations

from .model_registry import (
    MARKING_EXCLUDED,
    PRIMARY_ORDER,
    can_mark,
    get_model,
    is_registered,
)
from .model_registry import (
    marking_model_problem as registry_marking_problem,
)

#: The declared primary marking models, highest priority first.
PRIMARY_MARKING_MODELS: tuple[str, ...] = PRIMARY_ORDER

#: The model used when no scheduler choice has been recorded.  It is a member of
#: :data:`PRIMARY_MARKING_MODELS`, not a privileged alternative to them.
PRODUCTION_MARKING_MODEL = "gemini-3.6-flash"

if PRODUCTION_MARKING_MODEL not in PRIMARY_MARKING_MODELS:  # pragma: no cover
    raise AssertionError("the default marking model must be a primary model")

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
    """Whether this id is refused for marking and as a marking fallback.

    Any lightweight model is refused by suffix, and the two independent checking
    models are refused by name even if they were ever renamed.
    """

    candidate = normalise_model_id(model)
    return (
        candidate in DISABLED_MARKING_MODELS
        or candidate in MARKING_EXCLUDED
        or is_lightweight_model(candidate)
    )


def is_primary_marking_model(model: str | None) -> bool:
    """Whether a production paper may be marked by this model.

    Requires all three: a registered primary, stable, and able to accept the
    scanned evidence and return structured output.
    """

    return can_mark(normalise_model_id(model))


def is_production_marking_model(model: str | None) -> bool:
    """Whether this is the default marking model.

    Kept for the callers that need the *default*, not the whole tier; use
    :func:`is_primary_marking_model` to ask whether a model may mark at all.
    """

    return normalise_model_id(model) == PRODUCTION_MARKING_MODEL


def marking_model_problem(model: str | None) -> str | None:
    """Why this id cannot mark a production paper, or ``None``.

    The sentence names the model that was asked for, the models that may mark,
    and what to change.
    """

    candidate = normalise_model_id(model)
    if not candidate:
        return (
            "No marking model is configured. The verified marking models are "
            f"{', '.join(PRIMARY_MARKING_MODELS)}."
        )
    if candidate in MARKING_EXCLUDED:
        return (
            f"{candidate} is an independent checking model: a checker that marks "
            "a paper is not independent, so it may never mark one. The verified "
            f"marking models are {', '.join(PRIMARY_MARKING_MODELS)}."
        )
    if candidate in DISABLED_MARKING_MODELS:
        return (
            f"{candidate} is a disabled lightweight marking model. The verified "
            f"marking models are {', '.join(PRIMARY_MARKING_MODELS)}; remove the "
            "disabled model from the marking configuration."
        )
    if is_lightweight_model(candidate) and not is_registered(candidate):
        return (
            f"{candidate} is a lightweight model, and lightweight models are not "
            f"marking models. The verified marking models are "
            f"{', '.join(PRIMARY_MARKING_MODELS)}."
        )
    problem = registry_marking_problem(candidate)
    if problem is not None:
        return problem
    return None


def marking_assignment_problem(model: str | None) -> str | None:
    """Why a *recorded* assignment is unusable now, or ``None``.

    A job records the model it was assigned before its first paid request.  This
    separates "this model may never mark" from "this model is retiring", so a
    paper already in flight is not silently moved or re-marked.
    """

    problem = marking_model_problem(model)
    if problem is not None:
        return problem
    entry = get_model(model)
    if entry is None:  # pragma: no cover - marking_model_problem covers this
        return f"{model} is not a verified marking model."
    if entry.retiring:
        return (
            f"{entry.model_id} is retiring"
            + (f" on {entry.retirement_date.isoformat()}" if entry.retirement_date else "")
            + "; the paper can still be marked by it, but a replacement should be "
            "scheduled."
        )
    return None


__all__ = [
    "DISABLED_MARKING_MODELS",
    "PRIMARY_MARKING_MODELS",
    "PRODUCTION_MARKING_MODEL",
    "UNTRUSTED_MARKING_SUFFIX",
    "is_disabled_marking_model",
    "is_lightweight_model",
    "is_primary_marking_model",
    "is_production_marking_model",
    "marking_assignment_problem",
    "marking_model_problem",
    "normalise_model_id",
]
