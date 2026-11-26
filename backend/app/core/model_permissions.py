"""Which AI capability each model is permitted to perform.

Marking is the one capability this build executes, and it has exactly one model:
``gemini-3.6-flash``.  Transcription and independent review are separate
capabilities that are **not implemented** in this build; the table below records
what each model *may* do once those capabilities exist, so a model that is
prohibited from marking is not thereby prohibited from every other AI task.

Four statuses are used:

``ENABLED``
    Active for production work in that capability.
``OPTIONAL``
    Permitted for the capability, but not the designated model and not active by
    default.
``RESERVED``
    Not active in production.  The model may be named in a role's configuration
    only so it can be enabled for *that* capability after validation changes the
    permission to ``ENABLED``.
``DISABLED``
    Prohibited for the capability, including as a fallback.

A role may execute only when its model's permission is ``ENABLED`` or
``OPTIONAL`` *and* the role has been explicitly enabled.  A reserved model can
never execute, and a disabled one can never even be configured.

The marking column is **derived** from :mod:`app.core.marking_policy` rather than
restated here, so the completed production marking migration keeps a single
source of truth and this table cannot drift away from it.

Enforcement lives at the routing boundary
-----------------------------------------
:func:`capability_for_call` and :func:`permitted_models` are read by
``app.services.provider_calls.ProviderCallService`` *before* a credential is
leased or a request is sent.  Until that wiring existed the table was policy
only, and a role's configured fallback chain could reach a model the table had
disabled — the blind transcription, which the prompt manifest files under the
``review`` role, was the live example.  A chain entry is now filtered by
permission, and a role with no permitted model raises a configuration error
naming the models it refused instead of quietly calling one of them.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from .marking_policy import (
    PRIMARY_MARKING_MODELS,
    PRODUCTION_MARKING_MODEL,
    is_disabled_marking_model,
    is_primary_marking_model,
    normalise_model_id,
)


class AICapability(StrEnum):
    """The AI responsibilities a model can be permitted to perform."""

    MARKING = "marking"
    TRANSCRIPTION = "transcription"
    INDEPENDENT_REVIEW = "independent_review"


class PermissionStatus(StrEnum):
    ENABLED = "ENABLED"
    OPTIONAL = "OPTIONAL"
    RESERVED = "RESERVED"
    DISABLED = "DISABLED"


#: The statuses under which a call may be made today.
EXECUTABLE_STATUSES = frozenset(
    {PermissionStatus.ENABLED, PermissionStatus.OPTIONAL}
)

#: The specialist-role table.  Marking is intentionally absent: it is derived
#: from the production marking policy, which allows one model only.
#:
#: ``gemini-3.6-flash`` holds no specialist grant.  It is the marking model, and
#: being permitted to mark is not a grant to read a script blindly or to act as
#: the second examiner: either would make the "independent" reading the same
#: model as the marking pass, which is exactly the defect the transcription
#: comparison exists to detect.  It may be named for those roles (that is what
#: ``RESERVED`` records) but it cannot execute them until the permission itself
#: changes after validation.
#:
#: Both Lite models are reserved for transcription only.  Neither is permitted
#: for marking, and neither may stand in for the reviewer.
_SPECIALIST_PERMISSIONS: dict[str, dict[AICapability, PermissionStatus]] = {
    # Retired by Google on 2026-10-20; the documented replacement is
    # gemini-3.8-flash or gemini-3.5-flash-lite.  It keeps that record and no
    # grant: a retired model must not be the answer to "which model reviews?"
    "gemini-2.5-flash": {
        AICapability.TRANSCRIPTION: PermissionStatus.DISABLED,
        AICapability.INDEPENDENT_REVIEW: PermissionStatus.DISABLED,
    },
    # The three primary marking models.  None of them holds a specialist grant:
    # a reading taken by the marking model is not an independent one, so they may
    # only be named (RESERVED) for those roles, never executed there.
    "gemini-4-hydrogen": {
        AICapability.TRANSCRIPTION: PermissionStatus.RESERVED,
        AICapability.INDEPENDENT_REVIEW: PermissionStatus.RESERVED,
    },
    "gemini-3.8-flash": {
        AICapability.TRANSCRIPTION: PermissionStatus.RESERVED,
        AICapability.INDEPENDENT_REVIEW: PermissionStatus.RESERVED,
    },
    "gemini-3.6-flash": {
        AICapability.TRANSCRIPTION: PermissionStatus.RESERVED,
        AICapability.INDEPENDENT_REVIEW: PermissionStatus.RESERVED,
    },
    # The evidence checker: it independently inspects the approved criteria and
    # the student's evidence for the questions it is given, and never marks.
    # It is not the blind reader as well — one model must not supply both
    # independent readings, or neither is independent of the other.
    "gemini-3.5-flash-lite": {
        AICapability.TRANSCRIPTION: PermissionStatus.RESERVED,
        AICapability.INDEPENDENT_REVIEW: PermissionStatus.ENABLED,
    },
    # The blind transcription checker: it reads the page without the criteria and
    # without the primary model's marks, and never reviews or marks.
    "gemini-3.1-flash-lite": {
        AICapability.TRANSCRIPTION: PermissionStatus.ENABLED,
        AICapability.INDEPENDENT_REVIEW: PermissionStatus.DISABLED,
    },
    # Recorded by the production migration as unavailable: it is listed by no
    # current credential.  Its review configuration stays disabled until both a
    # valid model and a credential configuration exist.
    "gemini-3.1-pro-preview": {
        AICapability.TRANSCRIPTION: PermissionStatus.DISABLED,
        AICapability.INDEPENDENT_REVIEW: PermissionStatus.DISABLED,
    },
}

#: Every model this policy makes a statement about.  A model absent from here is
#: ``DISABLED`` for every specialist capability: a grant is given by name and is
#: never inherited from a family, a version or a chain position.
KNOWN_MODELS = tuple(_SPECIALIST_PERMISSIONS)

#: The capability each correction role performs.  These are the role names the
#: prompt manifest, the model chains and ``provider_model_selections`` already
#: use, so a chain and a permission cannot disagree about vocabulary.
MODEL_CHAIN_CAPABILITY: dict[str, AICapability] = {
    "primary": AICapability.MARKING,
    "review": AICapability.INDEPENDENT_REVIEW,
    "lightweight": AICapability.TRANSCRIPTION,
}

#: Purposes whose capability is not the one their manifest role implies.
#:
#: The blind transcription prompt is filed under the ``review`` role because it
#: shares that role's chain, but it performs a *transcription*: it reads a script
#: blindly and returns text.  Judging it as independent review would authorise a
#: transcription call on a review grant, and is precisely how the disabled review
#: configuration came to execute.  The purpose is the authority here.
PURPOSE_CAPABILITIES: dict[str, AICapability] = {
    "transcription": AICapability.TRANSCRIPTION,
}


class RoleConfigurationProblem(ValueError):
    """A role configuration that would permit a call the policy forbids."""


def marking_permission(model: str | None) -> PermissionStatus:
    """The marking permission, read from the production marking policy.

    ``gemini-3.6-flash`` is ``ENABLED``; every other id is ``DISABLED``.  The
    marking policy is the authority, so this cannot widen it.
    """

    return (
        PermissionStatus.ENABLED
        if is_primary_marking_model(model)
        else PermissionStatus.DISABLED
    )


def permission_for(
    model: str | None, capability: AICapability | str
) -> PermissionStatus:
    """The status of one model for one capability.

    A model absent from the specialist table is ``DISABLED`` for that
    capability: a permission is granted by name, never inherited.
    """

    role = AICapability(capability)
    if role is AICapability.MARKING:
        return marking_permission(model)
    entry = _SPECIALIST_PERMISSIONS.get(normalise_model_id(model)) or {}
    return entry.get(role, PermissionStatus.DISABLED)


def is_permitted(model: str | None, capability: AICapability | str) -> bool:
    """Whether the model may perform the capability today."""

    return permission_for(model, capability) in EXECUTABLE_STATUSES


def is_reserved(model: str | None, capability: AICapability | str) -> bool:
    """Whether the capability is reserved for the model but not yet active."""

    return permission_for(model, capability) is PermissionStatus.RESERVED


def models_with(
    capability: AICapability | str, *statuses: PermissionStatus
) -> list[str]:
    """The known models holding any of ``statuses`` for the capability."""

    role = AICapability(capability)
    return [
        model
        for model in KNOWN_MODELS
        if permission_for(model, role) in statuses
    ]


def capability_for_role(role: str) -> AICapability:
    """The capability a correction role performs when nothing says otherwise."""

    return MODEL_CHAIN_CAPABILITY.get(str(role or "").strip(), AICapability.MARKING)


def capability_for_call(*, role: str, purpose: str) -> AICapability:
    """The capability one provider call actually performs.

    The purpose wins where it is recorded, because a prompt's manifest role names
    the *chain* it walks, not the work it does.  Blind transcription is the case
    that matters: filed under ``review``, performing ``transcription``.
    """

    override = PURPOSE_CAPABILITIES.get(str(purpose or "").strip())
    if override is not None:
        return override
    return capability_for_role(role)


def permitted_models(
    capability: AICapability | str, models: Iterable[str]
) -> list[str]:
    """The models of ``models`` that may perform ``capability`` today, in order."""

    role = AICapability(capability)
    seen: list[str] = []
    for model in models:
        candidate = normalise_model_id(model)
        if candidate and candidate not in seen and is_permitted(candidate, role):
            seen.append(candidate)
    return seen


def permission_problem(
    model: str | None, capability: AICapability | str
) -> str | None:
    """Why the model may not perform the capability now, or ``None``.

    The sentence names the role, the model and what would have to change, so an
    operator is never told only that something is "not allowed".
    """

    role = AICapability(capability)
    candidate = normalise_model_id(model)
    status = permission_for(candidate, role)
    if status in EXECUTABLE_STATUSES:
        return None
    if not candidate:
        return f"No model is configured for {role.value}."
    if role is AICapability.MARKING:
        verified = ", ".join(PRIMARY_MARKING_MODELS)
        if is_disabled_marking_model(candidate):
            return (
                f"{candidate} cannot mark a paper: it is a disabled lightweight "
                f"or independent checking model. The verified marking models are "
                f"{verified}, and a paper is never moved to another of them "
                "after a failure."
            )
        return (
            f"{candidate} cannot mark a paper. The verified marking models are "
            f"{verified}."
        )
    if status is PermissionStatus.RESERVED:
        return (
            f"{candidate} is reserved for {role.value} but is not active there. "
            f"It becomes usable only after validation and an explicit permission "
            f"change from RESERVED to ENABLED; until then the {role.value} role "
            "cannot run with it."
        )
    return (
        f"{candidate} is not permitted for {role.value}. The capability is "
        "granted per role; being permitted elsewhere does not grant it here."
    )


def role_exhausted_problem(
    role: str,
    capability: AICapability | str,
    tried: Iterable[str],
) -> str:
    """The actionable error for a role whose chain holds no permitted model.

    This is raised at the routing boundary instead of calling an unpermitted
    model, so the operator learns which models were refused and what would make
    the role runnable.
    """

    check = AICapability(capability)
    candidates = [normalise_model_id(model) for model in tried if normalise_model_id(model)]
    described = ", ".join(
        f"{model} ({permission_for(model, check).value})" for model in candidates
    ) or "none configured"
    return (
        f"The {role} role cannot run: no model in its chain is permitted for "
        f"{check.value}. Chain: {described}. Nothing was sent to the provider. "
        f"Change the model's permission to ENABLED after validation, or configure "
        f"a model permitted for {check.value}."
    )


def role_configuration_problem(
    model: str | None,
    capability: AICapability | str,
    *,
    enabled: bool,
) -> str | None:
    """Why this role configuration is invalid, or ``None``.

    Naming a reserved model is allowed: that is what "reserved for this role"
    means.  Enabling the role with one is not, because a reserved permission is
    never executable.  A disabled model cannot be named at all.
    """

    role = AICapability(capability)
    candidate = normalise_model_id(model)
    status = permission_for(candidate, role)

    if status is PermissionStatus.DISABLED:
        if not candidate:
            return None if not enabled else f"No model is configured for {role.value}."
        return permission_problem(candidate, role)

    if enabled and status not in EXECUTABLE_STATUSES:
        return (
            f"The {role.value} role cannot be enabled with {candidate}: the "
            f"permission is {status.value}, which never executes. Validate the "
            "model first, then change its permission to ENABLED."
        )
    return None


def model_permission_report() -> dict[str, Any]:
    """The policy as data, for a report or an admin surface.

    It describes permissions only.  It does not claim that transcription or
    independent review is implemented.
    """

    rows = {
        model: {
            capability.value: permission_for(model, capability).value
            for capability in AICapability
        }
        for model in KNOWN_MODELS
    }
    return {
        "marking_model": PRODUCTION_MARKING_MODEL,
        "marking_models": list(PRIMARY_MARKING_MODELS),
        "models": rows,
        "role_capabilities": {
            role: capability.value for role, capability in MODEL_CHAIN_CAPABILITY.items()
        },
        "purpose_capabilities": {
            purpose: capability.value for purpose, capability in PURPOSE_CAPABILITIES.items()
        },
        #: ``ENABLED`` or ``OPTIONAL``: a call is allowed, whether or not the
        #: capability is implemented in this build.
        "permitted": {
            capability.value: models_with(
                capability, PermissionStatus.ENABLED, PermissionStatus.OPTIONAL
            )
            for capability in AICapability
        },
        "reserved": {
            capability.value: models_with(capability, PermissionStatus.RESERVED)
            for capability in AICapability
        },
        "disabled": {
            capability.value: models_with(capability, PermissionStatus.DISABLED)
            for capability in AICapability
        },
        "specialist_roles_implemented": True,
        "note": (
            "Marking is active with the verified primary models ("
            f"{', '.join(PRIMARY_MARKING_MODELS)}); one model marks a given paper "
            "and no model is substituted for it after a failure. Blind "
            "transcription and independent evidence review are separate roles "
            "held by separate models, so neither reading is the marking model's "
            "own. A role with no permitted model refuses before a request is "
            "sent."
        ),
    }


__all__ = [
    "EXECUTABLE_STATUSES",
    "KNOWN_MODELS",
    "MODEL_CHAIN_CAPABILITY",
    "PURPOSE_CAPABILITIES",
    "AICapability",
    "PermissionStatus",
    "RoleConfigurationProblem",
    "capability_for_call",
    "capability_for_role",
    "is_permitted",
    "is_reserved",
    "marking_permission",
    "model_permission_report",
    "models_with",
    "permission_for",
    "permission_problem",
    "permitted_models",
    "role_configuration_problem",
    "role_exhausted_problem",
]
