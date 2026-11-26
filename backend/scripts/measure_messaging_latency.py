"""Measure messaging delivery latency against a running engine.

The harness is deliberately end-to-end: it speaks HTTP to a real engine process
backed by a real PostgreSQL database, opens the same server-sent event stream the
browser opens, and timestamps the send, the persistence acknowledgement and the
recipient's event. Nothing is mocked and no artificial delay is inserted.

Usage (loopback database only, never production):

    python scripts/measure_messaging_latency.py \
        --dsn postgresql+psycopg://postgres@127.0.0.1:5432/aetrix_test_disposable \
        --base http://127.0.0.1:8011 --runs 30
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

DSN_DEFAULT = "postgresql+psycopg://postgres@127.0.0.1:5432/aetrix_test_disposable"
BASE_DEFAULT = "http://127.0.0.1:8011"
SECRET_DEFAULT = "test-secret-not-used-outside-tests"


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "p50_ms": round(_percentile(values, 0.50), 1),
        "p95_ms": round(_percentile(values, 0.95), 1),
        "p99_ms": round(_percentile(values, 0.99), 1),
        "max_ms": round(max(values), 1) if values else float("nan"),
        "mean_ms": round(statistics.fmean(values), 1) if values else float("nan"),
    }


@dataclass
class Receiver:
    """One open SSE stream, recording client-side arrival times."""

    base: str
    token: str
    events: queue.Queue = field(default_factory=queue.Queue)
    stop: threading.Event = field(default_factory=threading.Event)
    ready: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    error: str | None = None

    def start(self, timeout: float = 10.0) -> bool:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self.ready.wait(timeout)

    def _run(self) -> None:
        import httpx

        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0)
            ) as client, client.stream(
                "GET",
                f"{self.base}/api/v1/messaging/stream",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "text/event-stream",
                },
            ) as response:
                if response.status_code != 200:
                    self.error = f"stream status {response.status_code}"
                    self.ready.set()
                    return
                self.ready.set()
                name = ""
                for line in response.iter_lines():
                    if self.stop.is_set():
                        return
                    if line.startswith("event:"):
                        name = line[6:].strip()
                    elif line.startswith("data:"):
                        try:
                            payload = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        self.events.put(
                            {"event": name, "data": payload, "received": time.perf_counter()}
                        )
        except Exception as exc:  # a closed stream ends the thread
            self.error = f"{type(exc).__name__}: {exc}"
            self.ready.set()

    def wait_for(self, message_id: str, timeout: float) -> dict[str, Any] | None:
        deadline = time.perf_counter() + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None
            try:
                item = self.events.get(timeout=remaining)
            except queue.Empty:
                return None
            if item["event"] == "message" and item["data"].get("message_id") == message_id:
                return item

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2.0)


def _token(secret: str, tenant_id: str, subject: str) -> str:
    import jwt

    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=2),
            "app_metadata": {"tenant_id": tenant_id},
        },
        secret,
        algorithm="HS256",
    )


def _seed(dsn: str, sender_count: int = 50) -> dict[str, Any]:
    from app.db.models import Conversation, ConversationMember, Tenant, User
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(dsn)
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        tenant = Tenant(name=f"Latency {suffix}", slug=f"latency-{suffix}")
        session.add(tenant)
        session.flush()
        a = User(
            tenant_id=tenant.id,
            subject=f"latency-a-{suffix}",
            role="OWNER",
            display_name="Latency A",
        )
        b = User(
            tenant_id=tenant.id,
            subject=f"latency-b-{suffix}",
            role="TEACHER",
            display_name="Latency B",
        )
        c = User(
            tenant_id=tenant.id,
            subject=f"latency-c-{suffix}",
            role="TEACHER",
            display_name="Latency C",
        )
        # The engine rate-limits each sender to 30 messages a minute, so a run
        # of independent measurements uses one fresh sender per message.
        senders = [
            User(
                tenant_id=tenant.id,
                subject=f"latency-s{i}-{suffix}",
                role="TEACHER",
                display_name=f"Latency S{i}",
            )
            for i in range(sender_count)
        ]
        session.add_all([a, b, c, *senders])
        session.flush()

        direct = Conversation(tenant_id=tenant.id, kind="DIRECT", direct_key=f"latency-{suffix}-ab")
        channel = Conversation(
            tenant_id=tenant.id,
            kind="CHANNEL",
            channel_key=f"latency-{suffix}",
            title="Latency channel",
            post_policy="EVERYONE",
            created_by_id=a.id,
        )
        private = Conversation(
            tenant_id=tenant.id, kind="DIRECT", direct_key=f"latency-{suffix}-ac"
        )
        session.add_all([direct, channel, private])
        session.flush()
        for conversation, members in (
            (direct, (a, b, *senders)),
            (channel, (a, b, *senders)),
            (private, (a, c)),
        ):
            for user in members:
                session.add(
                    ConversationMember(
                        tenant_id=tenant.id,
                        conversation_id=conversation.id,
                        user_id=user.id,
                    )
                )
        session.commit()
        return {
            "tenant_id": str(tenant.id),
            "a": {"id": str(a.id), "subject": a.subject},
            "b": {"id": str(b.id), "subject": b.subject},
            "c": {"id": str(c.id), "subject": c.subject},
            "direct": str(direct.id),
            "channel": str(channel.id),
            "private": str(private.id),
            "senders": [{"id": str(u.id), "subject": u.subject} for u in senders],
        }


def _wait_ready(base: str) -> None:
    import httpx

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit(f"engine at {base} never became ready")


def _send(
    client, base: str, token: str, conversation_id: str, body: str
) -> tuple[dict[str, Any], float, float]:
    started = time.perf_counter()
    response = client.post(
        f"{base}/api/v1/messaging/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": body, "client_id": str(uuid.uuid4()), "mentioned_user_ids": []},
    )
    acked = time.perf_counter()
    response.raise_for_status()
    return response.json(), started, acked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=DSN_DEFAULT)
    parser.add_argument("--base", default=BASE_DEFAULT)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--secret", default=SECRET_DEFAULT)
    args = parser.parse_args()

    if "127.0.0.1" not in args.dsn and "localhost" not in args.dsn:
        raise SystemExit("Refusing to measure against a non-loopback database.")

    import httpx

    os.environ.setdefault("AETRIX_DATABASE__URL", args.dsn)
    seeded = _seed(args.dsn)
    _wait_ready(args.base)

    token_a = _token(args.secret, seeded["tenant_id"], seeded["a"]["subject"])
    token_b = _token(args.secret, seeded["tenant_id"], seeded["b"]["subject"])
    sender_tokens = [
        _token(args.secret, seeded["tenant_id"], sender["subject"]) for sender in seeded["senders"]
    ]

    import itertools

    sender_order = itertools.cycle(range(len(sender_tokens)))

    def next_sender() -> str:
        return sender_tokens[next(sender_order)]

    results: dict[str, Any] = {
        "base": args.base,
        "database": "loopback disposable",
        "runs_per_phase": args.runs,
    }

    with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)) as client:
        receiver_b = Receiver(args.base, token_b)
        if not receiver_b.start():
            raise SystemExit(f"recipient stream never opened: {receiver_b.error}")
        time.sleep(0.3)

        # Warm-up, discarded: connection setup and query plans.
        for _ in range(5):
            payload, started, acked = _send(
                client, args.base, next_sender(), seeded["direct"], "warm-up"
            )
            receiver_b.wait_for(payload["id"], 5.0)

        persist: list[float] = []
        delivery: list[float] = []
        e2e: list[float] = []
        missing = 0
        duplicates = 0
        order_ok = True
        last_seen = ""

        for index in range(args.runs):
            payload, started, acked = _send(
                client, args.base, next_sender(), seeded["direct"], f"direct #{index}"
            )
            event = receiver_b.wait_for(payload["id"], 5.0)
            if event is None:
                missing += 1
                continue
            persist.append((acked - started) * 1000)
            delivery.append((event["received"] - acked) * 1000)
            e2e.append((event["received"] - started) * 1000)
            if event["data"]["message_id"] == last_seen:
                duplicates += 1
            if event["data"]["created_at"] < last_seen:
                order_ok = False
            last_seen = event["data"]["created_at"]

        results["direct"] = {
            "persistence": _summary(persist),
            "delivery_after_persistence": _summary(delivery),
            "end_to_end": _summary(e2e),
            "missing": missing,
            "duplicates": duplicates,
            "ordered": order_ok,
        }

        # Recipient replies: the other direction on the same conversation.
        receiver_a = Receiver(args.base, token_a)
        receiver_a.start()
        time.sleep(0.3)
        reply_e2e: list[float] = []
        for index in range(min(10, args.runs)):
            payload, started, acked = _send(
                client, args.base, token_b, seeded["direct"], f"reply #{index}"
            )
            event = receiver_a.wait_for(payload["id"], 5.0)
            if event is not None:
                reply_e2e.append((event["received"] - started) * 1000)
        receiver_a.close()
        results["reply_direction"] = _summary(reply_e2e)

        # Workspace channel, same recipient.
        channel_e2e: list[float] = []
        for index in range(min(10, args.runs)):
            payload, started, acked = _send(
                client, args.base, next_sender(), seeded["channel"], f"channel #{index}"
            )
            event = receiver_b.wait_for(payload["id"], 5.0)
            if event is not None:
                channel_e2e.append((event["received"] - started) * 1000)
        results["channel"] = _summary(channel_e2e)

        # Burst: ten quick sends must all arrive once, in order.
        burst_ids = []
        for index in range(10):
            payload, _, _ = _send(
                client, args.base, next_sender(), seeded["direct"], f"burst #{index}"
            )
            burst_ids.append(payload["id"])
        received: list[str] = []
        for message_id in burst_ids:
            event = receiver_b.wait_for(message_id, 5.0)
            if event is None:
                break
            received.append(event["data"]["message_id"])
        results["burst"] = {
            "sent": len(burst_ids),
            "received": len(received),
            "ordered": received == burst_ids,
            "duplicates": len(received) - len(set(received)),
        }

        # Authorization: a conversation B is not a member of must never reach B.
        before = receiver_b.events.qsize()
        _send(client, args.base, token_a, seeded["private"], "not for B")
        time.sleep(1.0)
        leaked = 0
        while not receiver_b.events.empty():
            item = receiver_b.events.get_nowait()
            if item["data"].get("conversation_id") == seeded["private"]:
                leaked += 1
        results["authorization"] = {"leaked_private_messages": leaked, "queued_before": before}

        # Disconnect and recovery: B's stream is closed, a message is sent, and
        # the recipient recovers it from stored history on reconnect.
        receiver_b.close()
        payload, started, _ = _send(
            client, args.base, token_a, seeded["direct"], "missed while away"
        )
        time.sleep(0.5)
        recovered_at: float | None = None
        page = client.get(
            f"{args.base}/api/v1/messaging/conversations/{seeded['direct']}/messages",
            headers={"Authorization": f"Bearer {token_b}"},
            params={"limit": 50},
        )
        if page.status_code == 200 and any(
            item["id"] == payload["id"] for item in page.json()["items"]
        ):
            recovered_at = time.perf_counter()
        reconnect = Receiver(args.base, token_b)
        reconnect.start()
        results["reconnect_recovery"] = {
            "stream_reopened": reconnect.thread is not None and reconnect.error is None,
            "missed_message_recovered_ms": round((recovered_at - started) * 1000, 1)
            if recovered_at
            else None,
        }
        reconnect.close()

        # Duplicate send with the same client id must not create a second row.
        client_id = str(uuid.uuid4())
        body = {"body": "idempotent", "client_id": client_id, "mentioned_user_ids": []}
        first = client.post(
            f"{args.base}/api/v1/messaging/conversations/{seeded['direct']}/messages",
            headers={"Authorization": f"Bearer {token_a}"},
            json=body,
        ).json()
        second = client.post(
            f"{args.base}/api/v1/messaging/conversations/{seeded['direct']}/messages",
            headers={"Authorization": f"Bearer {token_a}"},
            json=body,
        ).json()
        results["idempotency"] = {"same_message_id": first["id"] == second["id"]}

        # Unread count reflects the delivered message immediately.
        unread = client.get(
            f"{args.base}/api/v1/messaging/conversations",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        rows = unread.json() if unread.status_code == 200 else []
        direct_row = next((row for row in rows if row["id"] == seeded["direct"]), None)
        results["unread"] = {
            "direct_unread_count": direct_row["unread_count"] if direct_row else None
        }

    results["environment"] = {
        "os": os.name,
        "client": "httpx",
        "transport": "loopback HTTP",
        "recipient": "server-sent events over fetch/httpx",
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
