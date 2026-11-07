"""Quota estimation for the Gemini fleet.

Gemini's free tier is metered per Google Cloud project, per model.  There is no
public endpoint that returns "remaining free-tier quota", so this module never
claims to know it: it computes consumption from Aetrix's own reservation and
usage ledgers, compares it with a limit the operator or Google supplied, and
labels the result with how much is actually known.

Three confidence states, and nothing in between:

* ``CONFIRMED``  — the limit came from an authoritative Google surface (a
  ``source='google'`` entry in configuration).  Also requires Aetrix's own
  ledger, so "confirmed" always means "confirmed limit, observed usage".
* ``ESTIMATED``  — a limit is configured as operator policy, or is the platform
  default.  Useful for scheduling; never presented as Google's number.
* ``UNKNOWN``    — no limit is known for this dimension.  No percentage is
  invented to fill the gap.

Counters are read per project: ten keys in one project share one pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from ..core.config import ModelQuota, Settings
from ..core.ids import utcnow
from ..db.repositories import QuotaReservationRepository, UsageRepository

Confidence = Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]


def _midnight(now: datetime, zone: str) -> datetime:
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        # A misconfigured zone must not crash a dashboard; it degrades to UTC
        # and the reset time it reports is the UTC midnight it actually used.
        tz = UTC
    local = now.astimezone(tz)
    tomorrow = (local.date() + timedelta(days=1))
    return datetime.combine(tomorrow, time(0, 0), tzinfo=tz).astimezone(UTC)


def next_reset(now: datetime, zone: str) -> datetime:
    """The next daily reset instant for the configured quota zone."""

    return _midnight(now, zone)


def day_start(now: datetime, zone: str) -> datetime:
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC
    local = now.astimezone(tz)
    return datetime.combine(local.date(), time(0, 0), tzinfo=tz).astimezone(UTC)


def _confidence(limit: int | None, source: str) -> Confidence:
    if limit is None:
        return "UNKNOWN"
    return "CONFIRMED" if source == "google" else "ESTIMATED"


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    """One dimension (RPM, TPM, RPD) of a project's allowance."""

    limit: int | None
    used: int
    confidence: Confidence

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(self.limit - self.used, 0)

    @property
    def used_share(self) -> float | None:
        if not self.limit:
            return None
        return min(self.used / self.limit, 1.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "used": self.used,
            "remaining": self.remaining,
            "used_share": self.used_share,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class QuotaEstimate:
    project_id: str
    model: str
    requests_per_minute: QuotaWindow
    tokens_per_minute: QuotaWindow
    requests_per_day: QuotaWindow
    reset_at: datetime
    observed_at: datetime
    cooldown_until: datetime | None
    notes: tuple[str, ...]

    @property
    def confidence(self) -> Confidence:
        states = {
            self.requests_per_minute.confidence,
            self.tokens_per_minute.confidence,
            self.requests_per_day.confidence,
        }
        if states == {"CONFIRMED"}:
            return "CONFIRMED"
        if "ESTIMATED" in states or "CONFIRMED" in states:
            return "ESTIMATED"
        return "UNKNOWN"

    @property
    def exhausted(self) -> bool:
        """True only when a *known* window has nothing left."""

        return any(
            window.limit is not None and (window.remaining or 0) <= 0
            for window in (
                self.requests_per_minute,
                self.tokens_per_minute,
                self.requests_per_day,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "model": self.model,
            "confidence": self.confidence,
            "requests_per_minute": self.requests_per_minute.as_dict(),
            "tokens_per_minute": self.tokens_per_minute.as_dict(),
            "requests_per_day": self.requests_per_day.as_dict(),
            "reset_at": self.reset_at,
            "observed_at": self.observed_at,
            "cooldown_until": self.cooldown_until,
            "exhausted": self.exhausted,
            "notes": list(self.notes),
        }


class QuotaEstimator:
    """Reads the ledger; it never writes and never calls Google."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.reservations = QuotaReservationRepository(session)
        self.usage = UsageRepository(session)

    def limits_for(self, model: str) -> ModelQuota:
        quota = self.settings.quota
        configured = quota.model_limits.get(model)
        if configured is not None:
            return configured
        return ModelQuota(
            requests_per_minute=quota.requests_per_minute,
            tokens_per_minute=quota.tokens_per_minute,
            requests_per_day=quota.requests_per_day,
            source="operator",
        )

    def estimate(
        self,
        *,
        project_id: str,
        model: str,
        now: datetime | None = None,
    ) -> QuotaEstimate:
        moment = now or utcnow()
        limits = self.limits_for(model)
        minute_used = self.reservations.count_since_project(
            project_id, moment - timedelta(minutes=1), moment
        )
        day_used = self.reservations.count_since_project(
            project_id,
            day_start(moment, self.settings.quota.daily_reset_timezone),
            moment,
        )
        # Reservations carry no token count, so TPM is measured from the usage
        # ledger — the only place Aetrix records what Gemini reported.
        token_rows = self.usage.window_stats(moment - timedelta(minutes=1), project_id=project_id)
        tokens_used = token_rows["input_tokens"] + token_rows["output_tokens"]

        cooldown = self.reservations.project_cooldown(project_id)
        active_cooldown = (
            cooldown.cooldown_until if cooldown and cooldown.cooldown_until > moment else None
        )

        notes: list[str] = [
            "Usage is recorded by Aetrix; Google's console remains the authoritative source.",
        ]
        if any(
            _confidence(limit, limits.source) == "ESTIMATED"
            for limit in (
                limits.requests_per_minute,
                limits.requests_per_day,
                limits.tokens_per_minute,
            )
        ):
            notes.append(
                "At least one limit is Aetrix policy, not a Google-confirmed value."
            )
        if limits.tokens_per_minute is None:
            notes.append("No tokens-per-minute limit is known for this model.")

        return QuotaEstimate(
            project_id=project_id,
            model=model,
            requests_per_minute=QuotaWindow(
                limit=limits.requests_per_minute,
                used=minute_used,
                confidence=_confidence(limits.requests_per_minute, limits.source),
            ),
            tokens_per_minute=QuotaWindow(
                limit=limits.tokens_per_minute,
                used=tokens_used,
                confidence=_confidence(limits.tokens_per_minute, limits.source),
            ),
            requests_per_day=QuotaWindow(
                limit=limits.requests_per_day,
                used=day_used,
                confidence=_confidence(limits.requests_per_day, limits.source),
            ),
            reset_at=_midnight(moment, self.settings.quota.daily_reset_timezone),
            observed_at=moment,
            cooldown_until=active_cooldown,
            notes=tuple(notes),
        )

    def project_estimates(
        self, project_id: str, models: list[str], now: datetime | None = None
    ) -> list[QuotaEstimate]:
        return [self.estimate(project_id=project_id, model=model, now=now) for model in models]


__all__ = [
    "Confidence",
    "QuotaEstimate",
    "QuotaEstimator",
    "QuotaWindow",
    "day_start",
    "next_reset",
]
