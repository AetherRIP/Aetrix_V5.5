"""Whether a credential's Google Cloud project is actually established.

Gemini's free tier is metered per Google Cloud project and model, and several
API keys can bill the same project.  Aetrix accounts each credential as its own
operational pool (see :mod:`app.services.credential_pools`), but that is our
ledger, not Google's: it cannot tell whether two lent keys share a project.

Three states of project identity, and nothing in between:

``VERIFIED``
    Google Resource Manager confirmed the project exists (the Cloud Quota
    integration stores that verdict in ``google_cloud_projects``).  Evidence from
    Google is the only thing that earns this state.
``DECLARED``
    An administrator explicitly asserted, through the fleet API, that this key
    bills this project, and the id has the shape of a project id.  The assertion
    is recorded with who made it and when; it is not a Google confirmation and
    never displayed as one.
``PROJECT_IDENTITY_UNVERIFIED``
    Nobody has established the project.  The credential is still a usable Aetrix
    pool; what is unknown is the Google allowance behind it, so per-project
    capacity is reported ``UNKNOWN`` and pool budgets are never summed as Google
    capacity.

A successful request, its latency, its key fingerprint or a 200 response says
nothing about which project a key bills, so none of them is used here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import (
    ESTABLISHED_PROJECT_IDENTITIES,
    PROJECT_IDENTITY_DECLARED,
    PROJECT_IDENTITY_UNVERIFIED,
    PROJECT_IDENTITY_VERIFIED,
    GoogleCloudProject,
    ProviderCredential,
)
from .google_cloud import SYNTHETIC_PROJECT_PREFIXES, is_verifiable_project_id

#: Re-exported so callers have one import for the vocabulary.
VERIFIED = PROJECT_IDENTITY_VERIFIED
DECLARED = PROJECT_IDENTITY_DECLARED
PROJECT_IDENTITY_UNVERIFIED = PROJECT_IDENTITY_UNVERIFIED
ESTABLISHED = ESTABLISHED_PROJECT_IDENTITIES

UNVERIFIED_REASON = (
    "No administrator has asserted which Google Cloud project this key bills, "
    "so Google-level capacity is unknown; the key is accounted as its own "
    "Aetrix pool."
)

DECLARED_REASON = (
    "An administrator declared this project; Google Resource Manager has not "
    "confirmed it."
)

VERIFIED_REASON = "Google Resource Manager confirmed this project exists."

#: Ordering for reporting a group's state: the strongest evidence wins.
_RANK = {
    PROJECT_IDENTITY_UNVERIFIED: 0,
    PROJECT_IDENTITY_DECLARED: 1,
    PROJECT_IDENTITY_VERIFIED: 2,
}


def is_established(identity: str) -> bool:
    """Whether the project behind a credential has been established.

    This decides whether a statement about *Google-level* allowance is possible.
    It does not decide whether the credential may be leased: that is the pool's
    own budget, enable switch and quarantine.
    """

    return identity in ESTABLISHED_PROJECT_IDENTITIES


def is_pool_label(project_id: str) -> bool:
    """Whether the id is one of Aetrix's own pooled names, not a project.

    A pool label can satisfy the project-id pattern (``user-downloads-pool``
    does), so shape alone cannot tell them apart.  The fleet's naming convention
    can: ``*-pool`` and the synthetic prefixes are names for "keys with no
    established project".  A declaration that kept one would turn a label into a
    project, so it is refused here.  Google evidence is not subject to this rule:
    a project Resource Manager confirmed exists, by whatever name.
    """

    value = project_id.strip().lower()
    return (
        value.endswith("-pool")
        or value == "unattributed"
        or value.startswith(SYNTHETIC_PROJECT_PREFIXES)
    )


def classify(
    *,
    project_id: str,
    google_verified: bool,
    declared_at: datetime | None,
) -> tuple[str, str]:
    """The identity state and its reason, from evidence only.

    ``declared_at`` is set only by an audited administrator assertion.  A
    declared id that does not look like a project id (a synthetic pool label, an
    empty string) is not an identity, however it was typed, so it stays
    unverified rather than becoming a project nobody can verify.
    """

    if google_verified:
        return PROJECT_IDENTITY_VERIFIED, VERIFIED_REASON
    if is_pool_label(project_id):
        return (
            PROJECT_IDENTITY_UNVERIFIED,
            f"{project_id.strip()!r} is a pooled label, not a Google Cloud "
            "project, so Google-level capacity for this key is unknown.",
        )
    if declared_at is not None and is_verifiable_project_id(project_id):
        return PROJECT_IDENTITY_DECLARED, DECLARED_REASON
    if not is_verifiable_project_id(project_id):
        return (
            PROJECT_IDENTITY_UNVERIFIED,
            f"{project_id.strip()!r} is not a Google Cloud project id, so "
            "Google-level capacity for this key is unknown.",
        )
    return PROJECT_IDENTITY_UNVERIFIED, UNVERIFIED_REASON


def google_project_verified(session: Session | None, project_id: str) -> bool:
    """Whether Resource Manager has already confirmed this project."""

    if session is None:
        return False
    project = session.get(GoogleCloudProject, project_id.strip())
    return bool(project and project.verification_status == "VERIFIED")


def identities_for(session: Session | None, project_ids: list[str]) -> dict[str, str]:
    """The strongest recorded identity for many labels, in one statement."""

    targets = sorted({value.strip() for value in project_ids if value})
    if session is None or not targets:
        return {}
    rows = session.execute(
        select(ProviderCredential.project_id, ProviderCredential.project_identity).where(
            ProviderCredential.project_id.in_(targets)
        )
    ).all()
    best: dict[str, str] = {}
    for project_id, identity in rows:
        current = best.get(project_id, PROJECT_IDENTITY_UNVERIFIED)
        if _RANK.get(identity, -1) > _RANK.get(current, -1):
            best[project_id] = identity
    return best


def identity_for(session: Session | None, project_id: str) -> str:
    """The strongest identity recorded for a declared project label.

    Reads the column rather than re-deriving it, so the dashboard, the gate and
    the routing decision all describe the same stored evidence.  A label with no
    credential is unverified; a group mixing a verified key with unverified ones
    is reported as ``VERIFIED`` for display, and Google-level capacity remains
    stated per credential, never per pool count.
    """

    if session is None:
        return PROJECT_IDENTITY_UNVERIFIED
    rows = session.execute(
        select(ProviderCredential.project_identity).where(
            ProviderCredential.project_id == project_id.strip()
        )
    ).scalars()
    best = PROJECT_IDENTITY_UNVERIFIED
    for identity in rows:
        if _RANK.get(identity, -1) > _RANK.get(best, -1):
            best = identity
    return best


def pool_identity(identities: list[str]) -> str:
    """The strongest identity in a group, for display over a project row."""

    best = PROJECT_IDENTITY_UNVERIFIED
    for identity in identities:
        if _RANK.get(identity, -1) > _RANK.get(best, -1):
            best = identity
    return best


def apply_google_verification(session: Session, project_id: str) -> int:
    """Upgrade every credential of a Google-confirmed project to ``VERIFIED``.

    Only the identity columns change.  ``provider_usage`` rows carry the project
    id they were recorded under and are never rewritten, so the ledger keeps
    describing what actually happened at the time.
    """

    result = session.execute(
        update(ProviderCredential)
        .where(
            ProviderCredential.project_id == project_id.strip(),
            ProviderCredential.project_identity != PROJECT_IDENTITY_VERIFIED,
        )
        .values(
            project_identity=PROJECT_IDENTITY_VERIFIED,
            project_identity_reason=VERIFIED_REASON,
        )
    )
    return int(result.rowcount or 0)


__all__ = [
    "DECLARED",
    "DECLARED_REASON",
    "ESTABLISHED",
    "PROJECT_IDENTITY_UNVERIFIED",
    "UNVERIFIED_REASON",
    "VERIFIED",
    "VERIFIED_REASON",
    "apply_google_verification",
    "classify",
    "google_project_verified",
    "identity_for",
    "is_established",
    "is_pool_label",
    "pool_identity",
]
