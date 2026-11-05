"""Provider list-price accounting.

Rates are configured per model.  An unknown model produces ``None``, not a
made-up zero: the ledger can distinguish "cost not known" from "cost was zero".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..core.config import Settings
from .base import TokenUsage


@dataclass(frozen=True, slots=True)
class ModelRate:
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None


def rate_for(settings: Settings, model: str) -> ModelRate | None:
    raw = settings.provider.model_rates.get(model)
    if not raw:
        return None
    try:
        return ModelRate(
            input_per_million=Decimal(str(raw["input"])),
            output_per_million=Decimal(str(raw["output"])),
            cached_input_per_million=(
                Decimal(str(raw["cached"])) if raw.get("cached") is not None else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def estimate_cost(rate: ModelRate | None, usage: TokenUsage) -> Decimal | None:
    if rate is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    cached = max(0, usage.cached_tokens or 0)
    billable_input = max(0, usage.input_tokens - cached)
    cost = Decimal(billable_input) / Decimal(1_000_000) * rate.input_per_million
    if cached:
        cached_rate = rate.cached_input_per_million or rate.input_per_million
        cost += Decimal(cached) / Decimal(1_000_000) * cached_rate
    cost += Decimal(usage.output_tokens) / Decimal(1_000_000) * rate.output_per_million
    return cost.quantize(Decimal("0.000001"))
