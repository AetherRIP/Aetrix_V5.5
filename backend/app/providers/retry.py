"""The bounded retry policy for one logical provider operation.

"Retry" is the most expensive word in a provider client, because every retry is a
real request against an allowance that is shared by every key in a Google Cloud
project.  Four rules keep it honest:

* **one retry** for a transient provider failure.  A second retry has never been
  the difference between an outage and a paper, and it doubles the spend;
* **exponential backoff with jitter**, so a fleet waking up at the same moment
  does not arrive in one burst;
* **``Retry-After`` wins** where Google sends it, clamped to the policy ceiling so
  a provider cannot park a worker for an hour;
* **no nested multiplication**: the delay function never decides *whether* to
  retry.  That is :func:`app.providers.routing.decide`, and the caller enforces a
  single request budget across the whole chain.  A retry loop in two places is
  how four attempts became twenty requests.

Nothing here contacts a provider or reads a clock: the delay is a pure function
of the attempt number, so a test can pin it exactly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How long to wait before one retry, and how many retries are allowed."""

    #: Base delay in seconds for the first retry.
    backoff_seconds: float = 1.0
    #: Ceiling for one wait, including an honoured ``Retry-After``.
    max_backoff_seconds: float = 8.0
    #: Fractional jitter applied to the computed delay, e.g. 0.5 = +/-50%.
    jitter: float = 0.5
    #: Attempts allowed for a transient failure, including the first.  Two means
    #: exactly one retry.
    transient_attempts: int = 2


#: The policy this build uses.  Read from settings at the call boundary so a
#: deployment can tighten it, never loosen it past one retry.
DEFAULT_RETRY_POLICY = RetryPolicy()


def transient_attempts_allowed(configured: int, retries: int = 1) -> int:
    """The attempt budget for a transient failure: at most ``1 + retries``.

    ``configured`` is the model's own attempt budget.  A larger configured budget
    is deliberately *not* honoured for a 5xx: the platform retry policy is the
    ceiling, not the floor, and a per-model setting must not be able to turn one
    outage into a burst.
    """

    return max(1, min(int(configured or 1), 1 + max(0, int(retries))))


def retry_delay(
    attempt_index: int,
    *,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    retry_after_seconds: float | None = None,
    rng: random.Random | None = None,
) -> float:
    """Seconds to wait before retrying after failure ``attempt_index`` (zero-based).

    ``retry_after_seconds`` is used when the provider sent it: the provider knows
    when its own window reopens.  It is clamped to ``max_backoff_seconds`` so one
    header cannot stall a worker, and it is still jittered upwards only — waiting
    *less* than Google asked would repeat the same rejection.
    """

    ceiling = max(0.0, float(policy.max_backoff_seconds))
    if retry_after_seconds is not None and retry_after_seconds >= 0:
        honoured = min(float(retry_after_seconds), ceiling)
        # Jitter upward only when honouring a provider instruction.
        spread = honoured * max(0.0, float(policy.jitter))
        if spread <= 0:
            return honoured
        return honoured + random_float(rng) * spread * 0.25

    index = max(0, int(attempt_index))
    base = max(0.0, float(policy.backoff_seconds))
    exponential = min(base * (2**index), ceiling)
    if exponential <= 0:
        return 0.0
    spread = exponential * max(0.0, float(policy.jitter))
    # Symmetric jitter around the exponential delay, never below zero.
    return max(0.0, exponential + (random_float(rng) * 2.0 - 1.0) * spread)


def random_float(rng: random.Random | None) -> float:
    """A uniform float in [0, 1) from the injected generator, or the module one."""

    generator = rng or random
    return generator.random()


__all__ = [
    "DEFAULT_RETRY_POLICY",
    "RetryPolicy",
    "random_float",
    "retry_delay",
    "transient_attempts_allowed",
]
