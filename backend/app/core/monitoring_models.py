"""The single allowlist every monitoring surface is filtered by.

Monitoring is a **reporting** view.  It answers "how are the three models we
watch behaving", and it never grants, removes or changes permission to execute
anything: a model that disappears from this list is still callable if the
permission table in :mod:`app.core.model_permissions` permits it, and a model
that appears here is not thereby authorised to mark a paper.

Three rules follow, and they are the reason this module exists rather than the
filter living in each query:

* one list, so a table, a chart, a dropdown and a health card cannot disagree;
* historical provider rows are never deleted or rewritten, so a retired or
  deprecated model keeps its audit trail — it is *excluded* from the three-model
  view, not erased from the ledger;
* an excluded model is reported as an excluded count, never as a zero-usage row.
  A zero would claim the model was quiet; an exclusion says it was not watched.
"""

from __future__ import annotations

from collections.abc import Iterable

#: The only models a monitoring surface may show, in display order.
MONITORED_MODELS: tuple[str, ...] = (
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
)

#: Position lookup, so a caller can order a mixed list without re-declaring it.
MONITORED_ORDER: dict[str, int] = {
    model: index for index, model in enumerate(MONITORED_MODELS)
}

def is_monitored_model(model: str | None) -> bool:
    """Whether a model id belongs to the three-model monitoring view."""

    return str(model or "").strip() in MONITORED_ORDER


def filter_monitored(models: Iterable[str]) -> list[str]:
    """The monitored subset of ``models``, deduplicated and in display order."""

    return [model for model in MONITORED_MODELS if model in set(models)]


def excluded_count(models: Iterable[str]) -> int:
    """How many rows fall outside the allowlist.

    Reported beside a filtered table so its totals can be reconciled against a
    daily total that is not model-filtered.
    """

    return sum(1 for model in models if not is_monitored_model(model))


__all__ = [
    "MONITORED_MODELS",
    "MONITORED_ORDER",
    "excluded_count",
    "filter_monitored",
    "is_monitored_model",
]
