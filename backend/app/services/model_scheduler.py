"""Assign a paper to one of the verified primary marking models.

The scheduler answers one question: *which* verified primary marks this paper?
It never answers "which model should try next", because a paper that changes
model part-way through would have two authors and one recorded name.  Once an
assignment is written to the job, nothing here will change it.

Selection is deterministic and auditable.  Given the same ledger, the same
configuration and the same job, it returns the same model, and it returns the
reason with it so the choice can be explained after the fact.

What it reads
-------------
* **Eligibility** — the verified registry: a model must be stable and able to
  accept a scanned paper.  The two checking models are never eligible.
* **Health** — a model with no healthy credential in the pools cannot be chosen.
* **Allowance** — per-model Aetrix budgets already recorded in the ledger
  (``provider_usage``), not invented RPM/TPM constants.  Google's own limits are
  a project-level fact the pools track separately and are never added up here.
* **Load** — how many jobs each model already has in flight, so work spreads.
* **Reliability** — recent failure rate and latency, used only to break ties.

What it does not do
-------------------
It does not send anything to the provider, does not lease a credential, and does
not spend quota.  A model that is quarantined, exhausted or absent is skipped,
and if none is usable the caller is told exactly that rather than being given a
substitute.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import model_registry
from ..core.config import Settings
from ..core.marking_policy import (
    PRIMARY_MARKING_MODELS,
    PRODUCTION_MARKING_MODEL,
    is_primary_marking_model,
)
from ..db.models import CorrectionJob, ProviderCredential, ProviderUsage

#: Job states that mean the paper is still being worked on.
IN_FLIGHT_STATES = frozenset(
    {"QUEUED", "LEASED", "EXTRACTING", "MAPPING", "CORRECTING", "VERIFYING", "FINALIZING"}
)


class NoEligibleModelError(RuntimeError):
    """No verified primary model can take a paper right now."""

    def __init__(self, message: str, *, considered: Iterable[dict[str, Any]]) -> None:
        super().__init__(message)
        self.considered = list(considered)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One model's case for being chosen."""

    model_id: str
    priority: int
    healthy_credentials: int
    in_flight: int
    requests_today: int
    daily_budget: int | None
    remaining_budget: int | None
    failures_recent: int
    successes_recent: int
    mean_latency_ms: float | None
    eligible: bool
    reason: str

    def as_report(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True, slots=True)
class Assignment:
    """The chosen model and why it was chosen."""

    model_id: str
    reason: str
    candidates: tuple[Candidate, ...]

    def as_report(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "reason": self.reason,
            "candidates": [candidate.as_report() for candidate in self.candidates],
        }


def _eligible_models(settings: Settings) -> list[str]:
    """The configured primaries that the registry still allows to mark."""

    configured = list(settings.provider.primary_marking_models or [])
    models = configured or [settings.provider.model_primary]
    seen: list[str] = []
    for model in models:
        candidate = str(model or "").strip()
        if candidate and candidate not in seen and is_primary_marking_model(candidate):
            seen.append(candidate)
    return seen


def _healthy_credentials(session: Session) -> Mapping[str, int]:
    """Healthy, unrevoked credential pools per model.

    A credential advertises the models it may be used for in ``model_access``;
    an empty list means "unrestricted", which is how the fleet was registered.
    """

    # ``model_access`` is a JSON column, which Postgres cannot group by (json has
    # no equality operator), so the aggregation happens here rather than in SQL.
    rows = session.execute(
        select(ProviderCredential.model_access)
        .where(ProviderCredential.health == "HEALTHY")
        .where(ProviderCredential.revoked_at.is_(None))
        .where(
            (ProviderCredential.cooldown_until.is_(None))
            | (ProviderCredential.cooldown_until <= func.now())
        )
    ).scalars().all()
    counts: dict[str, int] = {}
    for access in rows:
        if not access:
            for model in _all_primaries():
                counts[model] = counts.get(model, 0) + 1
            continue
        for model in access:
            counts[str(model)] = counts.get(str(model), 0) + 1
    return counts


def _all_primaries() -> tuple[str, ...]:
    return tuple(PRIMARY_MARKING_MODELS)


def _usage_today(session: Session) -> Mapping[str, tuple[int, int, float | None]]:
    """Per-model request count and recent failures for the current UTC day."""

    rows = session.execute(
        select(
            ProviderUsage.model,
            func.count(),
            func.count().filter(ProviderUsage.success.is_(False)),
            func.avg(ProviderUsage.latency_ms),
        )
        .where(
            func.date_trunc("day", ProviderUsage.created_at)
            == func.date_trunc("day", func.now())
        )
        .group_by(ProviderUsage.model)
    ).all()
    return {
        str(model): (int(total), int(failed), float(latency) if latency is not None else None)
        for model, total, failed, latency in rows
    }


def _recent(session: Session, model: str, limit: int = 20) -> tuple[int, int]:
    """Successes and failures among the most recent calls for one model."""

    rows = session.execute(
        select(ProviderUsage.success)
        .where(ProviderUsage.model == model)
        .order_by(ProviderUsage.created_at.desc())
        .limit(limit)
    ).scalars().all()
    successes = sum(1 for ok in rows if ok)
    return successes, len(rows) - successes


def _recent_by_model(session: Session, limit: int = 20) -> dict[str, tuple[int, int]]:
    """Successes and failures among each model's most recent calls.

    One windowed statement for every model: the fleet screen asks this once per
    candidate, and a round trip per model is what made the overview slow.
    """

    ranked = (
        select(
            ProviderUsage.model,
            ProviderUsage.success,
            func.row_number()
            .over(
                partition_by=ProviderUsage.model,
                order_by=ProviderUsage.created_at.desc(),
            )
            .label("position"),
        )
        .subquery()
    )
    rows = session.execute(
        select(ranked.c.model, ranked.c.success).where(ranked.c.position <= limit)
    ).all()
    counts: dict[str, tuple[int, int]] = {}
    for model, success in rows:
        successes, failures = counts.get(str(model), (0, 0))
        counts[str(model)] = (
            (successes + 1, failures) if success else (successes, failures + 1)
        )
    return counts


def _in_flight(session: Session) -> Mapping[str, int]:
    rows = session.execute(
        select(CorrectionJob.primary_model, func.count())
        .where(CorrectionJob.state.in_(IN_FLIGHT_STATES))
        .group_by(CorrectionJob.primary_model)
    ).all()
    return {str(model): int(count) for model, count in rows if model}


def _daily_budget(settings: Settings, model: str) -> int | None:
    """The Aetrix request budget for the model, read from configuration.

    ``None`` means the deployment has not declared a per-model budget, and the
    scheduler will not invent one: it falls back to load and health only.
    """

    # ``model_limits`` lives on the quota settings; it is Aetrix's own request
    # budget, never a Google figure.  The provider settings are checked as a
    # fallback so an older deployment layout still reports its budget.
    limits = getattr(settings.quota, "model_limits", None) or {}
    if not limits:
        limits = getattr(settings.provider, "model_limits", None) or {}
    entry = limits.get(model) if isinstance(limits, Mapping) else None
    if entry is None:
        return None
    if isinstance(entry, Mapping):
        value = entry.get("requests_per_day")
    else:
        value = getattr(entry, "requests_per_day", None)
    return int(value) if value is not None else None


def candidates(session: Session, settings: Settings) -> list[Candidate]:
    """Every eligible model with its current case, eligible ones first."""

    healthy = _healthy_credentials(session)
    usage = _usage_today(session)
    recent = _recent_by_model(session)
    in_flight = _in_flight(session)
    evaluated: list[Candidate] = []

    for position, model_id in enumerate(_eligible_models(settings)):
        entry = model_registry.get_model(model_id)
        priority = entry.priority if entry else position + 1
        requests_today, _failed_today, latency = usage.get(model_id, (0, 0, None))
        successes, failures = recent.get(model_id, (0, 0))
        budget = _daily_budget(settings, model_id)
        remaining = None if budget is None else max(0, budget - requests_today)
        credentials = int(healthy.get(model_id, 0))

        eligible = True
        if credentials <= 0:
            eligible = False
            reason = "no healthy credential advertises this model"
        elif budget is None:
            # The engine refuses to spend against an unknown allowance, so
            # assigning a paper here would only fail at the first request.
            eligible = False
            reason = "no declared Aetrix request budget for this model"
        elif remaining == 0:
            eligible = False
            reason = "today's declared request budget is spent"
        elif failures >= 3 and successes == 0:
            eligible = False
            reason = "the recent calls for this model all failed"
        else:
            reason = "eligible"

        evaluated.append(
            Candidate(
                model_id=model_id,
                priority=priority,
                healthy_credentials=credentials,
                in_flight=int(in_flight.get(model_id, 0)),
                requests_today=requests_today,
                daily_budget=budget,
                remaining_budget=remaining,
                failures_recent=failures,
                successes_recent=successes,
                mean_latency_ms=latency,
                eligible=eligible,
                reason=reason,
            )
        )
    return evaluated


def _score(candidate: Candidate) -> tuple[Any, ...]:
    """The ordering key: lower is better.

    1. Fewest papers already in flight, so work spreads across the pool.
    2. Most remaining budget, so a nearly spent model is not chosen next.
    3. Fewest recent failures, then lowest mean latency.
    4. Registered priority, then the id, so ties are deterministic.
    """

    # A declared budget that is known outranks an undeclared one: the scheduler
    # will not prefer a model merely because nobody has recorded its limit.
    budget_key = (
        (0, -candidate.remaining_budget)
        if candidate.remaining_budget is not None
        else (1, 0)
    )
    return (
        candidate.in_flight,
        budget_key,
        -candidate.successes_recent,
        candidate.failures_recent,
        candidate.mean_latency_ms if candidate.mean_latency_ms is not None else float("inf"),
        candidate.priority,
        candidate.model_id,
    )


def choose(session: Session, settings: Settings) -> Assignment:
    """Pick the model for a new paper, or refuse if none can take it."""

    if not settings.provider.scheduler_enabled:
        model = settings.provider.model_primary
        return Assignment(
            model_id=model,
            reason="scheduler disabled; the configured marking model is used",
            candidates=tuple(candidates(session, settings)),
        )

    evaluated = candidates(session, settings)
    eligible = [candidate for candidate in evaluated if candidate.eligible]
    if not eligible:
        raise NoEligibleModelError(
            "No verified primary marking model can take a paper right now. "
            + "; ".join(
                f"{candidate.model_id}: {candidate.reason}" for candidate in evaluated
            )
            or "No primary marking model is configured.",
            considered=[candidate.as_report() for candidate in evaluated],
        )

    chosen = min(eligible, key=_score)
    return Assignment(
        model_id=chosen.model_id,
        reason=(
            f"{chosen.model_id} chosen with {chosen.in_flight} paper(s) in flight, "
            f"{chosen.healthy_credentials} healthy credential(s) and "
            + (
                f"{chosen.remaining_budget} request(s) left today"
                if chosen.remaining_budget is not None
                else "no declared daily budget"
            )
            + f"; {chosen.failures_recent} recent failure(s)."
        ),
        candidates=tuple(evaluated),
    )


def scheduler_report(session: Session, settings: Settings) -> dict[str, Any]:
    """The scheduler's view as data, for an admin surface."""

    try:
        assignment = choose(session, settings)
        return {
            "enabled": settings.provider.scheduler_enabled,
            "would_choose": assignment.model_id,
            "reason": assignment.reason,
            "candidates": [candidate.as_report() for candidate in assignment.candidates],
        }
    except NoEligibleModelError as error:
        return {
            "enabled": settings.provider.scheduler_enabled,
            "would_choose": None,
            "reason": str(error),
            "candidates": error.considered,
        }


__all__ = [
    "IN_FLIGHT_STATES",
    "PRODUCTION_MARKING_MODEL",
    "Assignment",
    "Candidate",
    "NoEligibleModelError",
    "candidates",
    "choose",
    "scheduler_report",
]
