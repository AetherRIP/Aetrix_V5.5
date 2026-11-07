"""The contributor-aware Gemini key pool.

Keys no longer come from one operator: independent people lend one or more keys,
sometimes from the same Google Cloud project, sometimes from several.  This
module owns the three things that makes safe:

* **Attribution** — every contributed key carries its contributor, and the
  contributor is the record of consent, suspension and withdrawal.
* **Revocation** — a contributor can take a key back.  The ciphertext is
  destroyed at that moment, the row and its usage history stay, and the
  scheduler's eligibility query excludes the key before the next request.
* **Statistics** — usage is attributed in the ledger, so contribution totals do
  not depend on the key still existing.

Quota is deliberately *not* modelled here.  ``app.services.quota`` counts per
Google Cloud project; contributors and projects are many-to-many, so any
per-contributor counter would reintroduce the "one key equals one pool" defect
this fleet exists to avoid.  ``capacity`` therefore reports per-project
allowances and sums them across projects — never across keys.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from pydantic import SecretStr
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.ids import utcnow
from ..db.models import ProviderContributor, ProviderCredential
from ..db.repositories import (
    ContributorRepository,
    CredentialRepository,
    UsageRepository,
)
from .provider_fleet import _box, add_credential
from .quota import QuotaEstimator, day_start

MAX_DISPLAY_NAME = 200
MAX_EMAIL = 320
MAX_REASON = 300

CONTRIBUTOR_STATUSES = frozenset({"ACTIVE", "SUSPENDED", "WITHDRAWN"})


def _clean_name(display_name: str) -> str:
    value = display_name.strip()
    if not value:
        raise AppError(ErrorCode.VALIDATION_ERROR, "A contributor needs a display name.")
    return value[:MAX_DISPLAY_NAME]


def _clean_email(contact_email: str | None) -> str | None:
    value = (contact_email or "").strip()
    if not value:
        return None
    if "@" not in value or len(value) > MAX_EMAIL:
        raise AppError(ErrorCode.VALIDATION_ERROR, "That contact email is not valid.")
    return value


def _clean_reason(reason: str | None) -> str | None:
    value = (reason or "").strip()
    return value[:MAX_REASON] or None


def get_contributor(session: Session, contributor_id: uuid.UUID) -> ProviderContributor:
    contributor = ContributorRepository(session).get(contributor_id)
    if contributor is None:
        # A foreign id and a missing one are indistinguishable by design.
        raise AppError(ErrorCode.NOT_FOUND, "No such contributor.")
    return contributor


def create_contributor(
    session: Session,
    *,
    display_name: str,
    consent_version: str,
    contact_email: str | None = None,
    user_id: uuid.UUID | None = None,
    consent_reference: str | None = None,
) -> ProviderContributor:
    """Record a contributor and the consent they gave.

    Consent is stored before any key can be registered against the record, and
    it is never inferred from the key itself.
    """

    version = consent_version.strip()
    if not version:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "The contribution agreement version is required; consent must be recorded.",
        )

    repository = ContributorRepository(session)
    if user_id is not None and repository.get_for_user(user_id) is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            "That account already has a contribution record.",
        )

    contributor = repository.create(
        display_name=_clean_name(display_name),
        contact_email=_clean_email(contact_email),
        user_id=user_id,
        consent_version=version[:40],
        consent_reference=(consent_reference or "").strip()[:200] or None,
    )
    session.commit()
    return contributor


def ensure_contributor_for_user(
    session: Session,
    *,
    user_id: uuid.UUID,
    display_name: str,
    consent_version: str,
    contact_email: str | None = None,
    consent_reference: str | None = None,
) -> tuple[ProviderContributor, bool]:
    """Return the signed-in person's contribution record, creating it once.

    Returns ``(contributor, created)``.  An existing withdrawal is final for
    that record — reinstating it would silently revoke a revocation — and a
    suspension is an administrative decision the contributor cannot lift.
    """

    repository = ContributorRepository(session)
    existing = repository.get_for_user(user_id)
    if existing is not None:
        if existing.status == "WITHDRAWN":
            raise AppError(
                ErrorCode.CONFLICT,
                "This contribution was withdrawn; a new contribution needs a new record.",
            )
        if existing.status == "SUSPENDED":
            raise AppError(
                ErrorCode.FORBIDDEN,
                "This contribution is suspended. Contact the platform administrators.",
            )
        return existing, False

    created = create_contributor(
        session,
        display_name=display_name,
        consent_version=consent_version,
        contact_email=contact_email,
        user_id=user_id,
        consent_reference=consent_reference,
    )
    return created, True


def register_key(
    session: Session,
    settings: Settings,
    contributor: ProviderContributor,
    *,
    project_id: str,
    api_key: SecretStr,
    label: str | None = None,
    model_access: list[str] | None = None,
    tier: str = "UNKNOWN",
    auth_type: str = "api_key",
) -> ProviderCredential:
    """Register a key *as a contribution*, not as platform property."""

    if contributor.status != "ACTIVE":
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Only an active contributor can register a key.",
        )
    return add_credential(
        session,
        settings,
        project_id=project_id,
        api_key=api_key,
        label=label,
        model_access=model_access,
        tier=tier,
        auth_type=auth_type,
        contributor_id=contributor.id,
    )


def revoke_credential(
    session: Session,
    settings: Settings,
    credential: ProviderCredential,
    *,
    reason: str | None,
) -> str:
    """Withdraw one key: destroy the ciphertext, keep the provenance.

    ``provider_usage`` is append-only, so the row cannot be deleted once the key
    has been used; neutralising the secret is what "revoked" means here.
    """

    if credential.revoked_at is not None:
        return "already_revoked"

    credential.health = "DISABLED"
    credential.encrypted_secret = _box(settings).encrypt("")
    credential.revoked_at = utcnow()
    credential.revoked_reason = _clean_reason(reason) or "Withdrawn by its contributor."
    credential.cooldown_until = None
    credential.last_error = credential.revoked_reason
    session.commit()
    return "revoked"


def suspend_contributor(
    session: Session, contributor: ProviderContributor, *, reason: str | None
) -> ProviderContributor:
    """Stop all of a contributor's keys while keeping their ciphertext.

    Suspension is reversible, so the secret is kept; eligibility is decided by
    the contributor status in the scheduler's query, and the keys are also
    marked disabled so no dashboard reports them as usable.
    """

    if contributor.status == "WITHDRAWN":
        raise AppError(ErrorCode.CONFLICT, "A withdrawn contribution cannot be suspended.")
    if contributor.status == "SUSPENDED":
        return contributor

    note = _clean_reason(reason)
    contributor.status = "SUSPENDED"
    contributor.status_reason = note
    contributor.suspended_at = utcnow()
    for credential in CredentialRepository(session).for_contributor(contributor.id):
        if credential.revoked_at is None:
            credential.health = "DISABLED"
            credential.cooldown_until = None
            credential.last_error = (
                f"Contributor suspended: {note}" if note else "Contributor suspended."
            )[:400]
    session.commit()
    return contributor


def reinstate_contributor(
    session: Session, contributor: ProviderContributor
) -> ProviderContributor:
    """Lift a suspension; the keys must prove themselves again before use."""

    if contributor.status != "SUSPENDED":
        raise AppError(
            ErrorCode.CONFLICT, "Only a suspended contribution can be reinstated."
        )

    contributor.status = "ACTIVE"
    contributor.status_reason = None
    contributor.suspended_at = None
    for credential in CredentialRepository(session).for_contributor(contributor.id):
        if credential.revoked_at is None and credential.health == "DISABLED":
            # Never assume a key that was paused for a suspension is still good.
            credential.health = "UNKNOWN"
            credential.last_error = None
    session.commit()
    return contributor


def withdraw_contributor(
    session: Session,
    settings: Settings,
    contributor: ProviderContributor,
    *,
    reason: str | None,
) -> int:
    """The contributor takes every key back.  Irreversible, and immediate.

    Returns the number of keys that were revoked by this call so the caller can
    audit the outcome without re-reading rows.
    """

    if contributor.status == "WITHDRAWN":
        return 0

    revoked = 0
    for credential in CredentialRepository(session).for_contributor(contributor.id):
        if credential.revoked_at is None:
            revoke_credential(session, settings, credential, reason=reason)
            revoked += 1

    contributor.status = "WITHDRAWN"
    contributor.withdrawn_at = utcnow()
    contributor.status_reason = _clean_reason(reason)
    session.commit()
    return revoked


def contributor_keys(
    session: Session, contributor: ProviderContributor
) -> list[ProviderCredential]:
    return CredentialRepository(session).for_contributor(contributor.id)


def contributor_usage(
    session: Session,
    settings: Settings,
    contributor_id: uuid.UUID,
    *,
    window_days: int = 14,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(window, today)`` usage for one contributor, from the ledger only."""

    usage = UsageRepository(session)
    now = utcnow()
    window = usage.contributor_window_stats(now - timedelta(days=window_days)).get(
        contributor_id
    ) or _empty_usage()
    today = usage.contributor_window_stats(
        day_start(now, settings.quota.daily_reset_timezone)
    ).get(contributor_id) or _empty_usage()
    return window, today


def _fleet_models(settings: Settings) -> list[str]:
    seen: dict[str, None] = {}
    for model in (
        settings.provider.model_primary,
        settings.provider.model_review,
        *settings.quota.model_limits.keys(),
    ):
        seen.setdefault(model, None)
    return list(seen)


def _is_eligible(credential: ProviderCredential) -> bool:
    return credential.revoked_at is None and credential.health not in {
        "INVALID",
        "DISABLED",
    }


def capacity(session: Session, settings: Settings) -> dict[str, Any]:
    """Available allowance across eligible projects, per model.

    Only projects that still have an eligible key contribute.  Keys are counted
    for attribution, never for capacity: two keys in one project report the same
    remaining allowance, because that is what Google enforces.
    """

    credentials = CredentialRepository(session).all_credentials()
    contributors = {row.id: row for row in ContributorRepository(session).list()}
    estimator = QuotaEstimator(session, settings)
    now = utcnow()

    eligible: dict[str, list[ProviderCredential]] = {}
    for credential in credentials:
        if not _is_eligible(credential):
            continue
        if credential.contributor_id is not None:
            owner = contributors.get(credential.contributor_id)
            if owner is None or owner.status != "ACTIVE":
                continue
        eligible.setdefault(credential.project_id, []).append(credential)

    models: list[dict[str, Any]] = []
    for model in _fleet_models(settings):
        rows: list[dict[str, Any]] = []
        minute_total: int | None = None
        day_total: int | None = None
        known = 0
        unknown = 0
        confirmed = True
        for project_id, keys in sorted(eligible.items()):
            estimate = estimator.estimate(project_id=project_id, model=model, now=now)
            owners = {
                key.contributor_id for key in keys if key.contributor_id is not None
            }
            rows.append(
                {
                    "project_id": project_id,
                    "contributors": len(owners),
                    "keys": len(keys),
                    "requests_per_minute_remaining": estimate.requests_per_minute.remaining,
                    "requests_per_day_remaining": estimate.requests_per_day.remaining,
                    "confidence": estimate.confidence,
                    "cooldown_until": estimate.cooldown_until,
                }
            )
            for window in (estimate.requests_per_minute, estimate.requests_per_day):
                if window.remaining is None:
                    continue
                known += 1
                if window.confidence != "CONFIRMED":
                    confirmed = False
            if estimate.requests_per_minute.remaining is not None:
                minute_total = (minute_total or 0) + estimate.requests_per_minute.remaining
            else:
                unknown += 1
            if estimate.requests_per_day.remaining is not None:
                day_total = (day_total or 0) + estimate.requests_per_day.remaining
            else:
                unknown += 1
        models.append(
            {
                "model": model,
                "projects": rows,
                "totals": {
                    "projects": len(rows),
                    "requests_per_minute_remaining": minute_total,
                    "requests_per_day_remaining": day_total,
                    "windows_measured": known,
                    "windows_unknown": unknown,
                    "confidence": (
                        "UNKNOWN"
                        if known == 0
                        else "CONFIRMED"
                        if confirmed
                        else "ESTIMATED"
                    ),
                },
            }
        )

    return {
        "models": models,
        "note": (
            "Quota is counted per Google Cloud project. Keys are never added up "
            "as capacity, so two contributors sharing a project still share its "
            "allowance."
        ),
    }


def _empty_usage() -> dict[str, Any]:
    return {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "failures": 0,
        "quota_failures": 0,
        "last_success_at": None,
    }


def contribution_summary(
    session: Session, settings: Settings, *, window_days: int = 14
) -> dict[str, Any]:
    """Aggregate and per-contributor statistics, from recorded state only."""

    repository = ContributorRepository(session)
    contributors = repository.list()
    credentials = CredentialRepository(session).all_credentials()
    usage_repository = UsageRepository(session)
    now = utcnow()
    window_start = now - timedelta(days=window_days)
    today_start = day_start(now, settings.quota.daily_reset_timezone)

    window_stats = usage_repository.contributor_window_stats(window_start)
    today_stats = usage_repository.contributor_window_stats(today_start)

    by_contributor: dict[uuid.UUID, list[ProviderCredential]] = {}
    platform_keys = 0
    for credential in credentials:
        if credential.contributor_id is None:
            platform_keys += 1
            continue
        by_contributor.setdefault(credential.contributor_id, []).append(credential)

    rows: list[dict[str, Any]] = []
    for contributor in contributors:
        keys = by_contributor.pop(contributor.id, [])
        stats = window_stats.get(contributor.id) or _empty_usage()
        today = today_stats.get(contributor.id) or _empty_usage()
        rows.append(
            {
                "contributor": contributor,
                "keys_total": len(keys),
                "keys_eligible": sum(
                    1
                    for key in keys
                    if _is_eligible(key) and contributor.status == "ACTIVE"
                ),
                "keys_revoked": sum(1 for key in keys if key.revoked_at is not None),
                "projects": sorted({key.project_id for key in keys}),
                "window": stats,
                "today": today,
            }
        )

    # A key can outlive its contributor row's absence from the list only if the
    # row was deleted out of band; surface it rather than hiding the traffic.
    orphaned = sum(len(keys) for keys in by_contributor.values())

    statuses: dict[str, int] = {status: 0 for status in sorted(CONTRIBUTOR_STATUSES)}
    for contributor in contributors:
        statuses[contributor.status] = statuses.get(contributor.status, 0) + 1

    contributed = [credential for credential in credentials if credential.contributor_id]
    projects: dict[str, set[uuid.UUID]] = {}
    for credential in contributed:
        projects.setdefault(credential.project_id, set()).add(credential.contributor_id)

    window_totals = _sum(w["window"] for w in rows)
    today_totals = _sum(w["today"] for w in rows)

    return {
        "observed_at": now,
        "window_started_at": window_start,
        "day_started_at": today_start,
        "aggregate": {
            "contributors_total": len(contributors),
            "contributors_by_status": statuses,
            "keys_contributed": len(contributed),
            "keys_eligible": sum(row["keys_eligible"] for row in rows),
            "keys_revoked": sum(row["keys_revoked"] for row in rows),
            "platform_keys": platform_keys,
            "orphaned_contributor_keys": orphaned,
            "projects": len(projects),
            "shared_projects": sum(1 for owners in projects.values() if len(owners) > 1),
            "requests_in_window": window_totals["requests"],
            "requests_today": today_totals["requests"],
            "input_tokens_in_window": window_totals["input_tokens"],
            "output_tokens_in_window": window_totals["output_tokens"],
            "failures_in_window": window_totals["failures"],
        },
        "contributors": rows,
        "capacity": capacity(session, settings),
    }


def _sum(stats: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "requests": sum(int(item.get("requests", 0) or 0) for item in stats),
        "input_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in stats),
        "output_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in stats),
        "failures": sum(int(item.get("failures", 0) or 0) for item in stats),
        "quota_failures": sum(int(item.get("quota_failures", 0) or 0) for item in stats),
    }


def contributor_detail(
    session: Session, settings: Settings, contributor_id: uuid.UUID
) -> dict[str, Any]:
    contributor = get_contributor(session, contributor_id)
    summary = contribution_summary(session, settings)
    for row in summary["contributors"]:
        if row["contributor"].id == contributor.id:
            return row
    return {
        "contributor": contributor,
        "keys_total": 0,
        "keys_eligible": 0,
        "keys_revoked": 0,
        "projects": [],
        "window": _empty_usage(),
        "today": _empty_usage(),
    }


__all__ = [
    "CONTRIBUTOR_STATUSES",
    "capacity",
    "contribution_summary",
    "contributor_detail",
    "contributor_keys",
    "contributor_usage",
    "create_contributor",
    "ensure_contributor_for_user",
    "get_contributor",
    "register_key",
    "reinstate_contributor",
    "revoke_credential",
    "suspend_contributor",
    "withdraw_contributor",
]
