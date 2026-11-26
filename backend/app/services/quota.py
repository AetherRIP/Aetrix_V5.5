"""Quota estimation: one Aetrix pool per credential, Google kept separate.

Gemini's free tier is metered per Google Cloud project and model.  There is no
public endpoint that returns "remaining free-tier quota", so this module never
claims to know it.  It computes two different things and refuses to blur them:

* **Aetrix pool windows** — reservations and validation probes recorded against
  one credential, compared with the configured limit.  This is the number the
  lease enforces, and it is per credential because the fleet is administered per
  credential.
* **Google quota status** — ``KNOWN`` / ``EXHAUSTED`` / ``UNKNOWN``.  A pool is
  never evidence of a separate Google project: keys may share one, so per-pool
  budgets are never summed into a Google-level capacity figure.  When no project
  is established, Google's allowance is ``UNKNOWN`` and the screen says so.

Confidence of a configured limit is unchanged: ``CONFIRMED`` only when Google
supplied it, ``ESTIMATED`` when it is operator policy or the platform default,
``UNKNOWN`` when no limit is known.  No percentage is invented to fill a gap.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from ..core.config import ModelQuota, Settings
from ..core.ids import utcnow
from ..db.models import (
    GOOGLE_QUOTA_EXHAUSTED,
    GOOGLE_QUOTA_KNOWN,
    GOOGLE_QUOTA_UNKNOWN,
    PROJECT_IDENTITY_UNVERIFIED,
    ProviderCredential,
)
from ..db.repositories import QuotaReservationRepository, UsageRepository
from .credential_pools import (
    POOL_NOTE,
    google_quota_status,
    pool_enabled,
    quarantine_for,
)
from .project_identity import identities_for, is_established

Confidence = Literal["CONFIRMED", "ESTIMATED", "UNKNOWN"]
GoogleQuotaStatus = Literal["KNOWN", "EXHAUSTED", "UNKNOWN"]


def quota_timezone(zone: str) -> tuple[ZoneInfo, str]:
    """The effective quota zone, falling back to UTC explicitly.

    A bad zone name must not crash a dashboard.  Returning the effective name
    keeps the screen from continuing to claim "Pacific" after it has silently
    started aggregating in UTC.
    """

    try:
        return ZoneInfo(zone), zone
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC"), "UTC"


def _midnight(now: datetime, zone: str) -> datetime:
    tz, _ = quota_timezone(zone)
    local = now.astimezone(tz)
    tomorrow = local.date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(0, 0), tzinfo=tz).astimezone(UTC)


def next_reset(now: datetime, zone: str) -> datetime:
    """The next daily reset instant for the configured quota zone."""

    return _midnight(now, zone)


def day_start(now: datetime, zone: str) -> datetime:
    tz, _ = quota_timezone(zone)
    local = now.astimezone(tz)
    return datetime.combine(local.date(), time(0, 0), tzinfo=tz).astimezone(UTC)


def _confidence(limit: int | None, source: str) -> Confidence:
    if limit is None:
        return "UNKNOWN"
    return "CONFIRMED" if source == "google" else "ESTIMATED"


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    """One dimension (RPM, TPM, RPD) of an allowance."""

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
class CredentialPoolEstimate:
    """The complete recorded state of one ``gemini-key-{id}`` pool.

    Everything here is Aetrix accounting plus the Google status *label*.  No
    field is a Google-reported remaining count, and ``requests_per_day.remaining``
    is this pool's configured budget, not a share of the project's allowance.
    """

    credential_id: Any
    pool_id: str
    model: str
    project_id: str
    project_identity: str
    google_quota_status: GoogleQuotaStatus
    google_quota_note: str
    requests_per_minute: QuotaWindow
    tokens_per_minute: QuotaWindow
    requests_per_day: QuotaWindow
    reset_at: datetime
    reset_timezone: str
    observed_at: datetime
    quarantined: bool
    quarantine_until: datetime | None
    quarantine_kind: str
    quarantine_reason: str | None
    last_success_at: datetime | None
    last_quota_exhausted_at: datetime | None
    last_quota_reason: str | None
    consecutive_failures: int
    model_access: tuple[str, ...]
    enabled: bool
    unconfirmed_requests: int
    #: Reservation rows in each window, separated from validation probes so the
    #: dashboard can show Aetrix's reservation accounting without folding the
    #: two into one unexplained number.
    reservations_minute: int
    reservations_today: int
    validations_today: int
    accounting: str
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
            "credential_id": self.credential_id,
            "confidence": self.confidence,
            "pool_id": self.pool_id,
            "model": self.model,
            "project_id": self.project_id,
            "project_identity": self.project_identity,
            "google_quota_status": self.google_quota_status,
            "google_quota_note": self.google_quota_note,
            "requests_per_minute": self.requests_per_minute.as_dict(),
            "tokens_per_minute": self.tokens_per_minute.as_dict(),
            "requests_per_day": self.requests_per_day.as_dict(),
            "remaining_today": self.requests_per_day.remaining,
            "remaining_minute": self.requests_per_minute.remaining,
            "reset_at": self.reset_at,
            "reset_timezone": self.reset_timezone,
            "observed_at": self.observed_at,
            "exhausted": self.exhausted,
            "quarantined": self.quarantined,
            "quarantine_until": self.quarantine_until,
            "quarantine_kind": self.quarantine_kind,
            "quarantine_reason": self.quarantine_reason,
            "last_success_at": self.last_success_at,
            "last_quota_exhausted_at": self.last_quota_exhausted_at,
            "last_quota_reason": self.last_quota_reason,
            "consecutive_failures": self.consecutive_failures,
            "model_access": list(self.model_access),
            "enabled": self.enabled,
            "unconfirmed_requests": self.unconfirmed_requests,
            "reservations_minute": self.reservations_minute,
            "reservations_today": self.reservations_today,
            "validations_today": self.validations_today,
            "accounting": self.accounting,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class QuotaEstimate:
    """A declared project label's aggregate, for reporting only.

    It sums Aetrix's records for every credential carrying that label.  It is
    never presented as Google capacity: the label may group keys billing several
    projects, and it may be a pool name that is not a project at all.
    """

    project_id: str
    model: str
    requests_per_minute: QuotaWindow
    tokens_per_minute: QuotaWindow
    requests_per_day: QuotaWindow
    reset_at: datetime
    reset_timezone: str
    observed_at: datetime
    cooldown_until: datetime | None
    accounting: str
    notes: tuple[str, ...]
    unconfirmed_requests: int = 0
    #: Whether this id is an established Google Cloud project.  It decides
    #: whether Google-level capacity can be stated, not whether keys are leased.
    project_identity: str = "PROJECT_IDENTITY_UNVERIFIED"
    google_quota_status: GoogleQuotaStatus = GOOGLE_QUOTA_UNKNOWN

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
            "reset_timezone": self.reset_timezone,
            "observed_at": self.observed_at,
            "cooldown_until": self.cooldown_until,
            "accounting": self.accounting,
            "exhausted": self.exhausted,
            "unconfirmed_requests": self.unconfirmed_requests,
            "project_identity": self.project_identity,
            "google_quota_status": self.google_quota_status,
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
        """The configured allowance for one model, or an UNKNOWN one.

        A model with no entry in ``quota.model_limits`` has **no** known
        allowance.  Substituting the platform default here would make the screen
        report a limit nobody configured, and the call gate would spend requests
        against it; the honest answer is ``None`` per window, which the estimate
        reports as ``UNKNOWN`` and the gate refuses.
        """

        configured = self.settings.quota.model_limits.get(model)
        if configured is not None:
            return configured
        return ModelQuota(
            requests_per_minute=None,
            tokens_per_minute=None,
            requests_per_day=None,
            source="operator",
        )

    def _window_notes(self, limits: ModelQuota, zone: str) -> list[str]:
        notes: list[str] = []
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
        if limits.requests_per_day is None:
            notes.append(
                "No request allowance is configured for this model, so no "
                "remaining capacity can be reported and the call gate refuses it."
            )
        _, effective_zone = quota_timezone(zone)
        if effective_zone != zone:
            notes.append(
                f"The configured quota zone {zone!r} is invalid; UTC midnight is in use."
            )
        return notes

    def pool_estimate(
        self,
        credential: ProviderCredential,
        model: str,
        *,
        now: datetime | None = None,
    ) -> CredentialPoolEstimate:
        """One credential's Aetrix pool, with its Google status label."""

        return self.pool_estimates([credential], model, now=now)[credential.id]

    def pool_estimates(
        self,
        credentials: Iterable[ProviderCredential],
        model: str,
        *,
        now: datetime | None = None,
    ) -> dict[uuid.UUID, CredentialPoolEstimate]:
        """Many Aetrix pools' windows, read in two statements.

        The windows read the same reservation rows the lease enforces, scoped by
        ``credential_id``.  The Google status is derived from project evidence
        and the latest recorded 429 — never from these counters.  Evaluating
        the counters with FILTER instead of one query per counter is what keeps
        a fifteen-pool fleet off a ninety-round-trip page.
        """

        moment = now or utcnow()
        credentials = list(credentials)
        if not credentials:
            return {}
        limits = self.limits_for(model)
        zone = self.settings.quota.daily_reset_timezone
        _, effective_zone = quota_timezone(zone)
        minute_since = moment - timedelta(minutes=1)
        day_since = day_start(moment, zone)
        ids = [credential.id for credential in credentials]
        reservations = self.reservations.credential_window_counts(
            ids,
            minute_since=minute_since,
            day_since=day_since,
            now=moment,
            model=model,
        )
        probes = self.usage.credential_pool_usage(
            ids, model=model, minute_since=minute_since, day_since=day_since
        )
        return {
            credential.id: self._pool_estimate(
                credential,
                model,
                moment,
                limits=limits,
                zone=zone,
                effective_zone=effective_zone,
                minute_reservations=int(
                    reservations.get(credential.id, {}).get("minute", 0)
                ),
                day_reservations=int(
                    reservations.get(credential.id, {}).get("day", 0)
                ),
                unconfirmed=int(
                    reservations.get(credential.id, {}).get("unconfirmed", 0)
                ),
                validations_minute=int(
                    probes.get(credential.id, {}).get("validations_minute", 0)
                ),
                day_validations=int(
                    probes.get(credential.id, {}).get("validations_day", 0)
                ),
                tokens_used=int(probes.get(credential.id, {}).get("tokens_minute", 0)),
            )
            for credential in credentials
        }

    def _pool_estimate(
        self,
        credential: ProviderCredential,
        model: str,
        moment: datetime,
        *,
        limits: ModelQuota,
        zone: str,
        effective_zone: str,
        minute_reservations: int,
        day_reservations: int,
        unconfirmed: int,
        validations_minute: int,
        day_validations: int,
        tokens_used: int,
    ) -> CredentialPoolEstimate:
        # The per-minute window counts unconfirmed requests too (so a retry storm
        # cannot exceed the burst limit while its first attempts are still
        # unresolved); the daily window reports them separately because they did
        # not reach the provider and must not consume the day's allowance.
        minute_used = minute_reservations + validations_minute + unconfirmed
        day_used = day_reservations + day_validations
        quarantine = quarantine_for(credential, moment)
        status, status_note = google_quota_status(
            credential,
            now=moment,
            day_limit_known=limits.requests_per_day is not None,
        )

        notes: list[str] = [
            "Counters are Aetrix reservations plus recorded validation probes "
            "for this credential; they are not Google-metered usage and Google's "
            "console remains authoritative.",
            POOL_NOTE,
            status_note,
        ]
        notes.extend(self._window_notes(limits, zone))
        if unconfirmed:
            notes.append(
                f"{unconfirmed} request(s) today failed without a provider "
                "confirmation that they were metered; they are counted per "
                "minute but not against the daily allowance."
            )
        if quarantine.active:
            notes.append(
                f"Quarantined until {quarantine.until.isoformat()} "
                f"({quarantine.kind})."
            )

        return CredentialPoolEstimate(
            credential_id=credential.id,
            pool_id=credential.pool_id,
            model=model,
            project_id=credential.project_id,
            project_identity=credential.project_identity,
            google_quota_status=status,
            google_quota_note=status_note,
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
            reset_at=_midnight(moment, zone),
            reset_timezone=effective_zone,
            observed_at=moment,
            quarantined=quarantine.active,
            quarantine_until=quarantine.until,
            quarantine_kind=quarantine.kind,
            quarantine_reason=quarantine.reason,
            last_success_at=credential.last_success_at,
            last_quota_exhausted_at=credential.last_quota_exhausted_at,
            last_quota_reason=credential.last_quota_reason,
            consecutive_failures=credential.consecutive_failures,
            model_access=tuple(credential.model_access or ()),
            enabled=pool_enabled(credential),
            unconfirmed_requests=unconfirmed,
            reservations_minute=minute_reservations,
            reservations_today=day_reservations,
            validations_today=day_validations,
            accounting="AETRIX_POOL_RESERVATIONS_PLUS_VALIDATION",
            notes=tuple(notes),
        )

    def estimate(
        self,
        *,
        project_id: str,
        model: str,
        now: datetime | None = None,
    ) -> QuotaEstimate:
        """A declared project label's aggregate, for reporting only."""

        return self.project_estimates_many([project_id], [model], now=now)[project_id][0]

    def project_estimates_many(
        self,
        project_ids: Iterable[str],
        models: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> dict[str, list[QuotaEstimate]]:
        """Every declared label's estimates for ``models``, in a handful of reads.

        Quota is project *and model* scoped in Google's meter; these counters are
        Aetrix's sum over the label, kept because the label is how the fleet
        groups keys.  They do not establish Google capacity.  Identity and the
        legacy project pause are read once for all labels rather than once per
        label and model.
        """

        moment = now or utcnow()
        targets = sorted({str(item) for item in project_ids if item})
        model_list = [str(item) for item in models if item]
        result: dict[str, list[QuotaEstimate]] = {target: [] for target in targets}
        if not targets or not model_list:
            return result
        zone = self.settings.quota.daily_reset_timezone
        _, effective_zone = quota_timezone(zone)
        minute_since = moment - timedelta(minutes=1)
        day_since = day_start(moment, zone)
        identities = identities_for(self.session, targets)
        cooldowns = self.reservations.active_cooldowns_for(targets, moment)
        for model in model_list:
            limits = self.limits_for(model)
            reservations = self.reservations.project_window_counts(
                targets,
                minute_since=minute_since,
                day_since=day_since,
                now=moment,
                model=model,
            )
            probes = self.usage.project_pool_usage(
                targets, model=model, minute_since=minute_since, day_since=day_since
            )
            for project_id in targets:
                reserved = reservations.get(project_id, {})
                probe = probes.get(project_id, {})
                result[project_id].append(
                    self._project_estimate(
                        project_id=project_id,
                        model=model,
                        moment=moment,
                        limits=limits,
                        identity=identities.get(
                            project_id, PROJECT_IDENTITY_UNVERIFIED
                        ),
                        minute_reservations=int(reserved.get("minute", 0)),
                        day_reservations=int(reserved.get("day", 0)),
                        unconfirmed=int(reserved.get("unconfirmed", 0)),
                        validations_minute=int(
                            probe.get("validations_minute", 0)
                        ),
                        day_validations=int(probe.get("validations_day", 0)),
                        tokens_used=int(probe.get("tokens_minute", 0)),
                        active_cooldown=cooldowns.get(project_id),
                        zone=zone,
                        effective_zone=effective_zone,
                    )
                )
        return result

    def _project_estimate(
        self,
        *,
        project_id: str,
        model: str,
        moment: datetime,
        limits: ModelQuota,
        identity: str,
        minute_reservations: int,
        day_reservations: int,
        unconfirmed: int,
        validations_minute: int,
        day_validations: int,
        tokens_used: int,
        active_cooldown: datetime | None,
        zone: str,
        effective_zone: str,
    ) -> QuotaEstimate:
        established = is_established(identity)
        # Unconfirmed attempts count against the minute window only; the daily
        # allowance is spent by real requests and is reported alongside them.
        minute_used = minute_reservations + validations_minute + unconfirmed
        day_used = day_reservations + day_validations
        if active_cooldown is not None:
            google_status: GoogleQuotaStatus = GOOGLE_QUOTA_EXHAUSTED
        elif established and limits.requests_per_day is not None:
            google_status = GOOGLE_QUOTA_KNOWN
        else:
            google_status = GOOGLE_QUOTA_UNKNOWN

        notes: list[str] = [
            "Request counts are Aetrix generation reservations plus recorded "
            "validation probes for this label, not Google-metered usage; Google's "
            "console remains authoritative.",
            "Keys may share one Google Cloud project, so this label's total is "
            "not a count of Google allowances.",
        ]
        notes.extend(self._window_notes(limits, zone))
        if unconfirmed:
            notes.append(
                f"{unconfirmed} request(s) today failed without a provider "
                "confirmation that they were metered; they are counted per "
                "minute but not against the daily allowance."
            )
        if not established:
            notes.append(
                f"Project identity is {identity}: Google-level capacity is "
                "UNKNOWN. Declare each key's Google Cloud project in the fleet "
                "console to state it."
            )

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
            reset_at=_midnight(moment, zone),
            reset_timezone=effective_zone,
            observed_at=moment,
            cooldown_until=active_cooldown,
            accounting="AETRIX_RESERVATIONS_PLUS_VALIDATION",
            notes=tuple(notes),
            unconfirmed_requests=unconfirmed,
            project_identity=identity,
            google_quota_status=google_status,
        )

    def project_estimates(
        self, project_id: str, models: list[str], now: datetime | None = None
    ) -> list[QuotaEstimate]:
        return self.project_estimates_many([project_id], models, now=now)[project_id]


__all__ = [
    "Confidence",
    "CredentialPoolEstimate",
    "GoogleQuotaStatus",
    "QuotaEstimate",
    "QuotaEstimator",
    "QuotaWindow",
    "day_start",
    "next_reset",
    "quota_timezone",
]
