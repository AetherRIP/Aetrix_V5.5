"""In-process wake-up bus for messaging streams.

A committed message must reach an open stream immediately. PostgreSQL
``LISTEN/NOTIFY`` would be the cross-process mechanism, but a listener
connection per open panel is a real connection cost for a small deployment and
proved unreliable on the Windows development stack. The engine runs a single API
process, so a process-local bus is the wake-up path; each stream also runs a
slow history query that covers a missed wake-up and a restart.

The bus carries no message data: a wake-up is only a hint to re-read committed
rows, so a lost wake-up can delay an event but can never corrupt or duplicate
one.
"""

from __future__ import annotations

import threading
import uuid

_TIMEOUT = 1.0


class MessagingBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[uuid.UUID, set[threading.Event]] = {}

    def subscribe(self, tenant_id: uuid.UUID) -> threading.Event:
        signal = threading.Event()
        with self._lock:
            self._subscribers.setdefault(tenant_id, set()).add(signal)
        return signal

    def unsubscribe(self, tenant_id: uuid.UUID, signal: threading.Event) -> None:
        with self._lock:
            signals = self._subscribers.get(tenant_id)
            if signals is None:
                return
            signals.discard(signal)
            if not signals:
                self._subscribers.pop(tenant_id, None)

    def publish(self, tenant_id: uuid.UUID) -> None:
        """Wake every stream in this workspace; never raises."""

        with self._lock:
            signals = list(self._subscribers.get(tenant_id, ()))
        for signal in signals:
            signal.set()

    def wait(self, signal: threading.Event, timeout: float = _TIMEOUT) -> bool:
        """Wait for a wake-up, then re-arm.

        Returns True when something may have changed, False on timeout (the
        caller then runs its safety-net history query anyway).
        """

        woken = signal.wait(timeout)
        signal.clear()
        return woken


messaging_bus = MessagingBus()
