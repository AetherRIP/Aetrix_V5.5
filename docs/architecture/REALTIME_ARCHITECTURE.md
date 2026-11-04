# Realtime Architecture

**Status:** RECOMMENDED — deliberately narrow. Realtime is the most over-requested feature in this brief and
the easiest to over-build. Only two things justify it at MVP.

## 1. What earns realtime, and what does not

| Feature | Realtime? | Why |
|---|---|---|
| Correction job progress | **Yes** | The core wait; a 3-minute job with no feedback feels broken |
| Notifications / inbox badge | **Yes** | Cheap, high value, same transport |
| Review-request handoff | **Yes** | "Someone asked you to check this" should arrive |
| Presence ("who is online") | **No** | Near-zero value for 5–10 assistants in one room |
| Live cursors / collaborative editing | **No** | Conflicts are solved by versioning, not by CRDTs |
| Comment streams | **Poll on focus** | Comments are append-only; 30 s staleness is fine |
| Dashboard counters | **No** | Poll on mount + on window focus |
| Grade matrix updates | **No** | Refetch on action completion |

Rationale: presence and co-editing add operational surface (reconnect storms, auth on sockets, fan-out cost)
for a product whose collaboration pattern is *asynchronous handoff*, not simultaneous typing.

## 2. Transport decision

| Option | Verdict |
|---|---|
| **SSE from a Worker** | Simple, one-way, no hibernation needed — but a long-lived request per client, no fan-out primitive, and it does not scale to "notify the whole workspace" without a hub anyway |
| **Durable Object per workspace + WebSocket (hibernating)** | **Chosen.** One hub fans out to all members; hibernation keeps idle sockets off the duration bill; DO storage holds the last N events for replay |
| Polling only | **Kept as the fallback and the recovery path** — and as the MVP default if the DO work slips |

```
Browser ──(ticket)──▶ GET /w/{slug}/events   [auth + membership + role]
       ◀── { url, expiresIn }                (single-use, 30 s)
Browser ──WSS──▶ WorkspaceHub (DO, name = workspaceId)
       ◀── hello { cursor }  →  replay since cursor
       ◀── job.progress / job.state / notification / membership.changed
```

**Tickets, not cookies, on the socket.** The Worker mints a single-use, 30-second HMAC ticket bound to
`{userId, workspaceId, role, exp}`. The DO validates it on upgrade — never trusting a query-string
`workspaceId`. This closes the classic WebSocket auth hole where the handshake skips normal middleware.

## 3. Durable Object design

- **One object per workspace**: `env.HUB.idFromName(workspaceId)`. Tenancy is structural, not a filter.
- Uses the **WebSocket Hibernation API** (`state.acceptWebSocket`), so idle sockets do not accrue duration.
- Holds, in DO SQLite storage: `last_event_id`, a ring buffer of the last 200 events (≤ 7 days), and the set
  of connected `userId`s (for optional presence later).
- **Never** holds authoritative state. If the object is evicted, clients reconnect, send their `cursor`, and
  the Worker resyncs from D1 (`jobs` + `notifications`).
- Emits **coalesced** progress: at most 4 events/second per job and 20/second per workspace. A progress event
  carries `{jobId, state, step, percent, at}`, not token-level detail.

## 4. Event envelope

```json
{ "id": "evt_01J...", "type": "job.progress", "workspaceId": "ws_...",
  "at": "2026-11-03T10:12:31Z", "data": { "jobId": "job_...", "state": "running",
  "step": "verify", "percent": 62 } }
```

Types: `job.queued`, `job.progress`, `job.state`, `job.failed`, `submission.assigned`,
`notification.created`, `membership.changed`, `integration.health`.

`membership.changed` is mandatory: a role change or removal causes the DO to re-authorise affected sockets
and **close** them within 30 s if the member lost access. Permissions are re-checked on every privileged
message, not just at connect time.

## 5. Client behaviour

1. Open socket on app shell mount, once per workspace, after auth.
2. On `open`, send `cursor` (last seen event id). Server replays missed events, then live.
3. On `close`/error: exponential backoff (1s → 30s, jitter), cap 5 attempts, then **switch to polling**
   every 10 s and show a discreet "live updates paused" indicator.
4. On `visibilitychange` → visible: refetch the current route's data regardless of socket state.
5. Never derive state from events alone: events are hints; the authoritative read is always the REST GET.

## 6. Limits and cost (VERIFIED)

- DO soft limit ~1,000 req/s per individual object → coalescing is not optional.
- WebSockets bill 1 request on upgrade; messages are cheap but **incoming** messages are billed at a 20:1
  ratio, so client→server chatter (typing indicators, heartbeats) is deliberately avoided.
- Hibernation: idle sockets wake only on message; this is what keeps a workspace with 10 open tabs cheap.
- Incoming WebSocket frame ≤ 32 MiB (irrelevant here — our frames are < 1 KB).

## 7. Failure modes

| Failure | Behaviour |
|---|---|
| DO unavailable | Upgrade fails → client falls back to polling; job continues unaffected (D1 is authority) |
| Client offline during job | On reconnect, replay from cursor; if cursor expired, full resync |
| Duplicate event | Client dedupes by `id` (monotonic) |
| Stale role in ticket | Ticket TTL 30 s + per-message permission recheck bounds the window |
| Event storm (bulk 200 jobs) | Server aggregates: per-job events only for jobs the user can see; bulk summary events otherwise |

## 8. If we are wrong about presence

Adding presence later is additive: the DO already tracks connected users. The decision to expose it is a UI
one (a small avatar row), not an architectural one — which is exactly why it can wait.
