"""One Aetrix operational pool per Gemini credential.

Keys are lent by independent people, and the fleet has to be able to observe,
budget, quarantine and enable each of them separately.  That is what a *pool*
is here: ``gemini-key-{credential_id}``, with its own reservations, confirmed and
unconfirmed usage, failure counter, quarantine window and last successful call.

A pool is **not** a Google Cloud project.  Google meters the free tier per
project and model, and it may place several API keys under one project.  Nothing
observable from a key — a 200, a latency, a fingerprint, or the fact that it has
its own Aetrix pool — establishes which project bills it.  So the two
accountings are kept apart and named apart:

* Aetrix pool counters answer "how much has *this key* spent in our ledger?".
* Google quota status answers "what can we say about the project behind it?",
  and is ``UNKNOWN`` whenever no project has been established.  A per-pool
  budget is never added up as Google capacity.

A 429 quarantines the credential that received it and is never answered by
leasing a sibling key: if the keys share a project, the sibling will be refused
too, and if they do not, Aetrix still has no evidence to spend the second one
against an allowance it cannot see.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from ..db.models import (
    ESTABLISHED_PROJECT_IDENTITIES,
    GOOGLE_QUOTA_EXHAUSTED,
    GOOGLE_QUOTA_KNOWN,
    GOOGLE_QUOTA_UNKNOWN,
    POOL_ID_PREFIX,
    ProviderCredential,
)

QUOTA = "QUOTA"
AUTH = "AUTH"
NONE = "NONE"

GOOGLE_STATUSES = (GOOGLE_QUOTA_KNOWN, GOOGLE_QUOTA_EXHAUSTED, GOOGLE_QUOTA_UNKNOWN)

#: Stated on every pool view, because the distinction is the whole point.
POOL_NOTE = (
    "Aetrix pools are per credential and are not separate Google Cloud projects: "
    "Google may meter several keys under one project, so pool budgets are never "
    "summed as Google capacity."
)


def pool_id_for(credential_id: uuid.UUID) -> str:
    """The stable pool id for a credential.

    Derived from the primary key, so it cannot be retyped, reused or confused
    with a project id, and it survives re-registration of the same Google key as
    a different row only if that row is genuinely a different credential.
    """

    return f"{POOL_ID_PREFIX}{credential_id}"


def is_pool_id(value: str) -> bool:
    return value.strip().lower().startswith(POOL_ID_PREFIX)


def project_identity_established(credential: ProviderCredential) -> bool:
    return credential.project_identity in ESTABLISHED_PROJECT_IDENTITIES


def pool_enabled(credential: ProviderCredential) -> bool:
    """Whether an administrator's enable/disable switch allows this pool.

    Health is credential validity: a revoked key and an ``INVALID`` (401) key are
    not selectable, and ``DISABLED`` is the administrator's own switch.  A
    quarantine window is separate and is checked by the lease.
    """

    if credential.revoked_at is not None:
        return False
    return credential.health not in {"INVALID", "DISABLED"}


@dataclass(frozen=True, slots=True)
class Quarantine:
    active: bool
    until: datetime | None
    kind: str
    reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "quarantined": self.active,
            "quarantine_until": self.until,
            "quarantine_kind": self.kind,
            "quarantine_reason": self.reason,
        }


def quarantine_for(credential: ProviderCredential, now: datetime) -> Quarantine:
    """The pool's quarantine window, from recorded state only."""

    until = credential.cooldown_until
    active = until is not None and until > now
    kind = (credential.cooldown_kind or NONE) if active else NONE
    reason = None
    if active:
        reason = (
            credential.last_quota_reason
            if kind == QUOTA
            else credential.last_error
        ) or (
            "Google returned a quota refusal (HTTP 429)."
            if kind == QUOTA
            else "The credential was refused; see the last error."
        )
    return Quarantine(active=active, until=until, kind=kind, reason=reason)


def google_quota_status(
    credential: ProviderCredential,
    *,
    now: datetime,
    day_limit_known: bool,
) -> tuple[str, str]:
    """What Aetrix can truthfully say about this pool's *Google* allowance.

    ``EXHAUSTED`` only while a quota quarantine is active and Google's own
    reason is on record.  ``KNOWN`` requires an established project *and* a
    configured day limit; even then it means "the project is identified and no
    refusal is outstanding", never "Google has this many requests left".
    Otherwise ``UNKNOWN``: no project has been established, so per-project
    capacity cannot be stated.
    """

    quarantine = quarantine_for(credential, now)
    if quarantine.active and quarantine.kind == QUOTA:
        return (
            GOOGLE_QUOTA_EXHAUSTED,
            quarantine.reason or "Google returned a quota refusal (HTTP 429).",
        )
    if not project_identity_established(credential):
        return (
            GOOGLE_QUOTA_UNKNOWN,
            f"Project identity is {credential.project_identity}: Aetrix cannot "
            "say which Google Cloud project meters this key, so Google-level "
            "capacity is unknown. Declare the project in the fleet console to "
            "establish it.",
        )
    if not day_limit_known:
        return (
            GOOGLE_QUOTA_UNKNOWN,
            "No daily request limit is configured for this model, so no "
            "Google-level capacity can be stated.",
        )
    return (
        GOOGLE_QUOTA_KNOWN,
        "The project is established and no quota refusal is outstanding. "
        "Aetrix still does not read Google's remaining count.",
    )


__all__ = [
    "AUTH",
    "GOOGLE_STATUSES",
    "NONE",
    "POOL_NOTE",
    "QUOTA",
    "Quarantine",
    "google_quota_status",
    "is_pool_id",
    "pool_enabled",
    "pool_id_for",
    "project_identity_established",
    "quarantine_for",
]
