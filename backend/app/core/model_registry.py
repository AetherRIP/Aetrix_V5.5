"""The verified Gemini model registry.

Every model Aetrix may send a request to is recorded here with the evidence that
it exists and can do the job: the exact API model code, the capabilities the
pipeline depends on (PDF/image input, structured output, thinking), its token
limits, its lifecycle status and where that was verified.

Three rules follow, and they are the reason this module exists:

* A model id is never guessed.  ``is_registered`` is authoritative, and an id
  that is not here is refused everywhere rather than passed to the provider.
* A capability is never assumed.  A model that cannot accept a PDF cannot mark a
  scanned paper, whatever its marketing page says.
* A model's lifecycle is recorded.  A model with an announced shutdown date is
  still selectable today but is reported as retiring, so a replacement can be
  configured without editing the correction engine.

The registry is the model dimension only.  Which *credential* pays for a request
is a separate decision owned by the credential pools in
``app.services.provider_calls``; a model is not a key, and a key is not a
project.

Verification source and date are recorded per model.  They were read from
Google's own pages on the date given; they are evidence, not a guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

#: A model's role in the correction architecture.
ROLE_PRIMARY = "primary"
ROLE_TRANSCRIPTION_CHECKER = "transcription_checker"
ROLE_EVIDENCE_CHECKER = "evidence_checker"


class ModelRegistryError(ValueError):
    """A model id or capability that the verified registry does not allow."""


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    """One verified model, with the capabilities the engine relies on."""

    model_id: str
    display_name: str
    role: str
    priority: int
    #: ``stable`` or ``preview``.  A preview model may never mark a real paper.
    stability: str
    context_limit: int
    max_output: int
    pdf_input: bool
    image_input: bool
    structured_outputs: bool
    thinking: bool
    #: Whether Google's free tier serves this model at all.
    free_tier: bool
    #: Whether free-tier content may be used to improve Google's products.  This
    #: is a student-data fact, not a cost fact: an unapproved tier may not
    #: receive an identifiable submission.
    free_tier_used_for_product_improvement: bool
    #: ``YYYY-MM-DD`` or ``None`` when Google has announced no shutdown date.
    retirement_date: date | None
    source_url: str
    verified_on: date
    notes: str = ""
    #: Thinking levels the API accepts, as documented.  Empty when thinking is
    #: unsupported, so a caller never sends an unsupported level.
    thinking_levels: tuple[str, ...] = field(default_factory=tuple)

    @property
    def retiring(self) -> bool:
        return self.retirement_date is not None

    @property
    def can_mark(self) -> bool:
        """Whether this model may mark a scanned paper.

        Marking needs a stable model that accepts page images and PDFs and can
        return the structured result the pipeline parses.  A preview model or one
        without structured output is never a marking model.
        """

        return (
            self.role == ROLE_PRIMARY
            and self.stability == "stable"
            and self.pdf_input
            and self.image_input
            and self.structured_outputs
        )

    def as_report(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "role": self.role,
            "priority": self.priority,
            "stability": self.stability,
            "context_limit": self.context_limit,
            "max_output": self.max_output,
            "pdf_input": self.pdf_input,
            "image_input": self.image_input,
            "structured_outputs": self.structured_outputs,
            "thinking": self.thinking,
            "thinking_levels": list(self.thinking_levels),
            "free_tier": self.free_tier,
            "free_tier_used_for_product_improvement": (
                self.free_tier_used_for_product_improvement
            ),
            "retirement_date": (
                self.retirement_date.isoformat() if self.retirement_date else None
            ),
            "source_url": self.source_url,
            "verified_on": self.verified_on.isoformat(),
            "notes": self.notes,
        }


_VERIFIED_ON = date(2026, 11, 25)
_MODELS_URL = "https://ai.google.dev/gemini-api/docs/models"
_DEPRECATIONS_URL = "https://ai.google.dev/gemini-api/docs/deprecations"

#: The three primary marking models, in declared priority order.  All three can
#: correct a complete paper; a paper is still marked by exactly one of them.
PRIMARY_MODELS: tuple[RegisteredModel, ...] = (
    RegisteredModel(
        model_id="gemini-4-hydrogen",
        display_name="Gemini 4 Hydrogen",
        role=ROLE_PRIMARY,
        priority=1,
        stability="stable",
        context_limit=1_048_576,
        max_output=65_536,
        pdf_input=True,
        image_input=True,
        structured_outputs=True,
        thinking=True,
        thinking_levels=("low", "medium", "high"),
        free_tier=True,
        free_tier_used_for_product_improvement=True,
        retirement_date=None,
        source_url="https://ai.google.dev/gemini-api/docs/models/gemini-4-hydrogen",
        verified_on=_VERIFIED_ON,
        notes=(
            "Stable, released November 2026, no shutdown date announced. Unified "
            "1M context; max output 65,536 default. Free tier is served but is "
            "identified as used to improve Google's products."
        ),
    ),
    RegisteredModel(
        model_id="gemini-3.8-flash",
        display_name="Gemini 3.8 Flash",
        role=ROLE_PRIMARY,
        priority=2,
        stability="stable",
        context_limit=1_048_576,
        max_output=65_536,
        pdf_input=True,
        image_input=True,
        structured_outputs=True,
        thinking=True,
        thinking_levels=("low", "medium", "high"),
        free_tier=True,
        free_tier_used_for_product_improvement=True,
        retirement_date=date(2027, 9, 2),
        source_url="https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash",
        verified_on=_VERIFIED_ON,
        notes=(
            "Stable, released 2026-09-02. Thinking rejects the 'minimal' level. "
            "Retirement 2027-09-02 or later."
        ),
    ),
    RegisteredModel(
        model_id="gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        role=ROLE_PRIMARY,
        priority=3,
        stability="stable",
        context_limit=1_048_576,
        max_output=65_536,
        pdf_input=True,
        image_input=True,
        structured_outputs=True,
        thinking=True,
        thinking_levels=("low", "medium", "high"),
        free_tier=True,
        free_tier_used_for_product_improvement=True,
        retirement_date=None,
        source_url="https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash",
        verified_on=_VERIFIED_ON,
        notes=(
            "Previous-generation Flash, still available for production use. The "
            "model this engine has actually marked papers with."
        ),
    ),
)

#: The two independent checking models.
CHECKER_MODELS: tuple[RegisteredModel, ...] = (
    RegisteredModel(
        model_id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash-Lite",
        role=ROLE_TRANSCRIPTION_CHECKER,
        priority=1,
        stability="stable",
        context_limit=1_048_576,
        max_output=65_536,
        pdf_input=True,
        image_input=True,
        structured_outputs=True,
        thinking=True,
        thinking_levels=("low", "medium", "high"),
        free_tier=True,
        free_tier_used_for_product_improvement=True,
        retirement_date=date(2027, 5, 7),
        source_url=_DEPRECATIONS_URL,
        verified_on=_VERIFIED_ON,
        notes=(
            "Blind transcription checker. Stable, released 2026-05-07, with an "
            "announced shutdown on 2027-05-07; the documented replacement is "
            "gemini-3.5-flash-lite. Selected for transcription because a blind "
            "reading needs no marking judgement."
        ),
    ),
    RegisteredModel(
        model_id="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash-Lite",
        role=ROLE_EVIDENCE_CHECKER,
        priority=1,
        stability="stable",
        context_limit=1_048_576,
        max_output=65_536,
        pdf_input=True,
        image_input=True,
        structured_outputs=True,
        thinking=True,
        thinking_levels=("low", "medium", "high"),
        free_tier=True,
        free_tier_used_for_product_improvement=True,
        retirement_date=date(2027, 7, 21),
        source_url="https://ai.google.dev/gemini-api/docs/models",
        verified_on=_VERIFIED_ON,
        notes=(
            "Evidence and criterion checker. Stable, released 2026-07-21; "
            "retirement 2027-07-21 or later."
        ),
    ),
)

REGISTRY: dict[str, RegisteredModel] = {
    model.model_id: model for model in (*PRIMARY_MODELS, *CHECKER_MODELS)
}

#: The primary marking models in declared priority order (highest first).
PRIMARY_ORDER: tuple[str, ...] = tuple(model.model_id for model in PRIMARY_MODELS)

#: Model ids that may never mark.  Recorded explicitly, because these are the
#: intended checkers: a checker that also marks is not independent.
MARKING_EXCLUDED: frozenset[str] = frozenset(
    model.model_id for model in CHECKER_MODELS
)


def normalise(model_id: str | None) -> str:
    return str(model_id or "").strip()


def is_registered(model_id: str | None) -> bool:
    return normalise(model_id) in REGISTRY


def get_model(model_id: str | None) -> RegisteredModel | None:
    return REGISTRY.get(normalise(model_id))


def require_model(model_id: str | None) -> RegisteredModel:
    """The verified entry, or a refusal naming the id that was asked for."""

    candidate = normalise(model_id)
    model = REGISTRY.get(candidate)
    if model is None:
        raise ModelRegistryError(
            f"{candidate or 'no model'} is not in the verified model registry. "
            "Add it with its documented capabilities and verification source "
            "before it can be configured or called."
        )
    return model


def can_mark(model_id: str | None) -> bool:
    """Whether the verified registry allows this model to mark a paper."""

    model = get_model(model_id)
    return bool(model and model.can_mark)


def marking_model_problem(model_id: str | None) -> str | None:
    """Why this model may not mark, in an operator's terms, or ``None``."""

    candidate = normalise(model_id)
    model = get_model(candidate)
    if model is None:
        return (
            f"{candidate or 'No model'} is not a verified marking model. "
            f"Verified marking models: {', '.join(PRIMARY_ORDER)}."
        )
    if model.model_id in MARKING_EXCLUDED:
        return (
            f"{model.model_id} is an independent checking model. A checker that "
            "marks a paper is not independent, so it may never mark one."
        )
    if model.stability != "stable":
        return (
            f"{model.model_id} is {model.stability}; only a stable model may mark "
            "a production paper."
        )
    missing = [
        name
        for name, ok in (
            ("PDF input", model.pdf_input),
            ("image input", model.image_input),
            ("structured output", model.structured_outputs),
        )
        if not ok
    ]
    if missing:
        return (
            f"{model.model_id} cannot mark a paper: it lacks {', '.join(missing)}, "
            "which a scanned script requires."
        )
    return None


def models_for_role(role: str) -> list[RegisteredModel]:
    """Every registered model holding ``role``, in priority order."""

    return sorted(
        (model for model in REGISTRY.values() if model.role == role),
        key=lambda model: (model.priority, model.model_id),
    )


def registry_report() -> dict[str, object]:
    """The registry as data, for an admin surface or an operations report."""

    return {
        "verified_on": _VERIFIED_ON.isoformat(),
        "primary_models": [model.as_report() for model in models_for_role(ROLE_PRIMARY)],
        "checker_models": [
            model.as_report()
            for model in (
                *models_for_role(ROLE_TRANSCRIPTION_CHECKER),
                *models_for_role(ROLE_EVIDENCE_CHECKER),
            )
        ],
        "marking_excluded": sorted(MARKING_EXCLUDED),
        "retiring": sorted(
            model.model_id
            for model in REGISTRY.values()
            if model.retiring
        ),
        "sources": {
            "catalogue": _MODELS_URL,
            "deprecations": _DEPRECATIONS_URL,
        },
    }


__all__ = [
    "CHECKER_MODELS",
    "MARKING_EXCLUDED",
    "PRIMARY_MODELS",
    "PRIMARY_ORDER",
    "REGISTRY",
    "ROLE_EVIDENCE_CHECKER",
    "ROLE_PRIMARY",
    "ROLE_TRANSCRIPTION_CHECKER",
    "ModelRegistryError",
    "RegisteredModel",
    "can_mark",
    "get_model",
    "is_registered",
    "marking_model_problem",
    "models_for_role",
    "normalise",
    "registry_report",
    "require_model",
]
