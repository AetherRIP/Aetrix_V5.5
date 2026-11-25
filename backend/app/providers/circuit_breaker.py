"""A small circuit breaker for repeated provider overload.

A 503 from Gemini is not a property of one key.  When the model is overloaded,
every credential in every project receives it, so the honest response is to stop
asking for a while rather than to walk the fleet and record a failure per key.
That is what this breaker does: after a threshold of consecutive transient
failures for one ``(provider, model)`` it opens for a bounded period, and a call
that finds it open spends **no** credential, **no** request and **no** quota.

Two limits are deliberate and are stated rather than implied:

* it is **process-local**.  The worker and the API are separate processes and
  this breaker does not coordinate them; a second process simply learns the same
  lesson itself, spending one attempt.  Making it shared would need a table and a
  lease, and a breaker that is wrong is worse than one that is late;
* it never claims the credential is bad.  Opening on a 5xx says the *provider*
  is overloaded; no key's health is changed by it.

The clock and the storage are injectable, so the behaviour is tested without
sleeping.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

#: One breaker key: a provider name and a model id.
BreakerKey = tuple[str, str]


@dataclass(slots=True)
class _State:
    consecutive_failures: int = 0
    opened_until: float | None = None
    last_failure_at: float | None = None


@dataclass(frozen=True, slots=True)
class BreakerStatus:
    """What the breaker says about one key right now."""

    open: bool
    retry_in_seconds: float | None
    consecutive_failures: int


@dataclass(slots=True)
class CircuitBreaker:
    """Consecutive-failure breaker, one entry per ``(provider, model)``.

    ``threshold`` counts consecutive transient failures.  A success at any point
    closes the breaker for that key, because one answered request is proof the
    model is reachable again.
    """

    threshold: int = 3
    open_seconds: float = 300.0
    clock: Callable[[], float] = time.monotonic
    _states: dict[BreakerKey, _State] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.threshold = max(1, int(self.threshold))
        self.open_seconds = max(0.0, float(self.open_seconds))

    @staticmethod
    def key(provider: str, model: str) -> BreakerKey:
        return (str(provider or "provider"), str(model or "").strip())

    def status(self, provider: str, model: str) -> BreakerStatus:
        key = self.key(provider, model)
        now = self.clock()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return BreakerStatus(False, None, 0)
            if state.opened_until is not None and state.opened_until > now:
                return BreakerStatus(
                    True,
                    state.opened_until - now,
                    state.consecutive_failures,
                )
            if state.opened_until is not None:
                # The open period elapsed: the next attempt is a probe, and it
                # starts from a clean count so one failure does not immediately
                # re-open the breaker for a full period.
                state.opened_until = None
                state.consecutive_failures = 0
            return BreakerStatus(False, None, state.consecutive_failures)

    def is_open(self, provider: str, model: str) -> bool:
        return self.status(provider, model).open

    def record_failure(self, provider: str, model: str) -> BreakerStatus:
        """Record one transient failure; open the breaker at the threshold."""

        key = self.key(provider, model)
        now = self.clock()
        with self._lock:
            state = self._states.setdefault(key, _State())
            state.consecutive_failures += 1
            state.last_failure_at = now
            if (
                state.consecutive_failures >= self.threshold
                and self.open_seconds > 0
            ):
                state.opened_until = now + self.open_seconds
            opened = state.opened_until
            failures = state.consecutive_failures
        return BreakerStatus(
            opened is not None and opened > now,
            (opened - now) if opened is not None and opened > now else None,
            failures,
        )

    def record_success(self, provider: str, model: str) -> None:
        """One answered request closes the breaker for this key."""

        key = self.key(provider, model)
        with self._lock:
            self._states.pop(key, None)

    def reset(self) -> None:
        """Clear every entry.  Used by tests and by a process restart."""

        with self._lock:
            self._states.clear()

    def snapshot(self) -> dict[BreakerKey, BreakerStatus]:
        """Every currently open key, for a diagnostic or a test."""

        now = self.clock()
        with self._lock:
            return {
                key: BreakerStatus(
                    state.opened_until is not None and state.opened_until > now,
                    (state.opened_until - now)
                    if state.opened_until is not None and state.opened_until > now
                    else None,
                    state.consecutive_failures,
                )
                for key, state in self._states.items()
            }


#: The breaker the provider call path uses unless one is injected.
DEFAULT_BREAKER = CircuitBreaker()


__all__ = [
    "DEFAULT_BREAKER",
    "BreakerKey",
    "BreakerStatus",
    "CircuitBreaker",
]
