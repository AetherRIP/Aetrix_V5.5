"""Failure classification and the model-chain routing decision.

The correction engine does not decide how to recover from a provider failure.
That decision is made here, as a pure function of the failure and the state of
the chain, so it can be tested without a database, a network or a real key.

Three mechanisms are deliberately kept apart, because conflating them is how a
call path lies about what it did:

* **credential rotation** — same model, different key.  Only useful when the
  failure is about the key, or when the replacement key bills against a
  genuinely different Google Cloud project.  Keys inside one project share one
  quota pool, so swapping them buys nothing.
* **model fallback** — a different model.  This is the only mechanism that
  recovers from a project-wide quota ceiling or a model that is unavailable.
* **per-question recovery** — a different *request shape* inside one job.  It
  lives in the pipeline and is not decided here.

The failures are classified into the categories an operator can act on.  A
mathematically invalid answer is *not* one of them: that is a finding about the
marking, not a provider failure, and it is handled by validation, never by
silently asking another model for a different number.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTruncatedResponse,
)


class FailureKind(StrEnum):
    """Why one provider attempt failed, in the terms the policy reasons about."""

    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    QUOTA = "quota"
    PROVIDER_SERVER = "provider_server"
    NETWORK = "network"
    UNSUPPORTED_MODEL = "unsupported_model"
    INVALID_REQUEST = "invalid_request"
    TRUNCATED = "truncated"
    RESPONSE_INVALID = "response_invalid"
    SAFETY_REFUSAL = "safety_refusal"
    CONFIGURATION = "configuration"
    INTERNAL = "internal"


class RoutingAction(StrEnum):
    """What the call path does after one failed attempt."""

    #: Try the same model again, after a backoff.
    RETRY_SAME_MODEL = "RETRY_SAME_MODEL"
    #: Try the same model with another credential.
    ROTATE_CREDENTIAL = "ROTATE_CREDENTIAL"
    #: Give up on this model and move to the next entry in the chain.
    NEXT_MODEL = "NEXT_MODEL"
    #: Stop the chain; no further attempt can help.
    STOP = "STOP"


#: Finish reasons that are a deliberate refusal, not a transient outage.
_SAFETY_FINISH_REASONS = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)

#: How many times a transient failure may be retried on the same model.  One.
#: This is the ceiling, not a default: a per-model attempt budget or a chain of
#: four models cannot raise it, because the only thing a second retry of a 503
#: reliably buys is another 503 charged to the same project allowance.
MAX_TRANSIENT_RETRIES = 1

#: The failures a retry can plausibly recover from.
TRANSIENT_FAILURES = frozenset(
    {
        "provider_server",
        "network",
        "truncated",
        "response_invalid",
    }
)


def classify_failure(error: ProviderError) -> FailureKind:
    """Classify one provider failure.

    Order matters: the more specific subclass wins, because a 404 arrives as a
    ``ProviderRequestError`` and must not be reported as an incompatible
    request body.
    """

    code = (error.provider_code or "").upper()
    if isinstance(error, ProviderAuthenticationError):
        return FailureKind.AUTHENTICATION
    if isinstance(error, ProviderPermissionError):
        return FailureKind.PERMISSION
    if isinstance(error, ProviderQuotaError):
        return FailureKind.QUOTA
    if isinstance(error, ProviderNetworkError):
        return FailureKind.NETWORK
    if isinstance(error, ProviderServerError):
        return FailureKind.PROVIDER_SERVER
    if isinstance(error, ProviderTruncatedResponse):
        return FailureKind.TRUNCATED
    if isinstance(error, ProviderResponseError):
        if code in _SAFETY_FINISH_REASONS:
            return FailureKind.SAFETY_REFUSAL
        return FailureKind.RESPONSE_INVALID
    if isinstance(error, ProviderRequestError):
        if error.status_code == 404:
            return FailureKind.UNSUPPORTED_MODEL
        # A 401/403 can also reach here if an adapter maps it to a plain request
        # error; the HTTP status is the authority.
        if error.status_code == 401:
            return FailureKind.AUTHENTICATION
        if error.status_code == 403:
            return FailureKind.PERMISSION
        return FailureKind.INVALID_REQUEST
    return FailureKind.INTERNAL


def decide(
    kind: FailureKind,
    *,
    attempt_index: int,
    attempts_allowed: int,
    next_model_available: bool,
    other_credential_available: bool,
    independent_credential_available: bool,
    independent_project_verified: bool = False,
) -> RoutingAction:
    """The routing decision for one failed attempt.

    ``attempt_index`` is zero-based within the current model, so
    ``attempt_index + 1 < attempts_allowed`` means another attempt remains.

    ``independent_credential_available`` means a different credential that bills
    against a *different Google Cloud project*; only that can recover a
    project-scoped quota failure.  ``other_credential_available`` is any other
    eligible key at all, which is enough for a key-specific failure.

    ``independent_project_verified`` says Google's Resource Manager has confirmed
    that the other project is a distinct, live project.  A quota fallback across
    projects is refused without it: an operator-typed project id that is a typo,
    a duplicate or a deleted project would otherwise look like fresh capacity and
    the call would spend an attempt to be told the same 429.
    """

    exhausted = attempt_index + 1 >= attempts_allowed

    if kind in (FailureKind.AUTHENTICATION, FailureKind.PERMISSION):
        # The key (or its permission) failed, not the model.  Never record the
        # model as unavailable because of it.  A rotation needs an attempt to
        # spend: when the budget for this model is gone, the honest decision is
        # the one the loop will actually take, not one it cannot afford.
        if other_credential_available and not exhausted:
            return RoutingAction.ROTATE_CREDENTIAL
        if other_credential_available and next_model_available:
            return RoutingAction.NEXT_MODEL
        return RoutingAction.STOP

    if kind is FailureKind.QUOTA:
        # A 429 is shared by every key in the project, so rotating inside one
        # project is a paid no-op that also hides the real ceiling.  Rotating to
        # an independent project costs an attempt, so it is only decided when
        # that attempt exists *and* the other project's identity is verified.
        if (
            independent_credential_available
            and independent_project_verified
            and not exhausted
        ):
            return RoutingAction.ROTATE_CREDENTIAL
        return RoutingAction.NEXT_MODEL if next_model_available else RoutingAction.STOP

    if kind in (
        FailureKind.PROVIDER_SERVER,
        FailureKind.NETWORK,
        FailureKind.TRUNCATED,
        FailureKind.RESPONSE_INVALID,
    ):
        # One retry, whatever the model's own attempt budget says.
        transient_budget = min(attempts_allowed, 1 + MAX_TRANSIENT_RETRIES)
        if attempt_index + 1 < transient_budget:
            return RoutingAction.RETRY_SAME_MODEL
        return RoutingAction.NEXT_MODEL if next_model_available else RoutingAction.STOP

    if kind in (FailureKind.UNSUPPORTED_MODEL, FailureKind.INVALID_REQUEST):
        # Retrying an identical request cannot succeed; a different model may
        # well accept it.
        return RoutingAction.NEXT_MODEL if next_model_available else RoutingAction.STOP

    # A safety refusal is about the input, not the model.  Walking the chain to
    # find a model that will answer anyway would be an attempt to bypass it.
    return RoutingAction.STOP


def is_stop(action: RoutingAction) -> bool:
    return action is RoutingAction.STOP


__all__ = [
    "MAX_TRANSIENT_RETRIES",
    "TRANSIENT_FAILURES",
    "FailureKind",
    "RoutingAction",
    "classify_failure",
    "decide",
    "is_stop",
]
