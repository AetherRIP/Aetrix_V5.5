"""Authenticated messaging routes.

Authorization lives here and in ``MessagingService``; the browser never receives
a database credential or a direct Supabase table endpoint.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.errors import AppError, ErrorCode
from ...core.security import Principal
from ...db.session import get_db_session, session_scope
from ...schemas.messaging import (
    ChannelCreate,
    ChannelUpdate,
    ConversationRead,
    DirectConversationCreate,
    DirectoryUserRead,
    MembershipUpdate,
    MessageCreate,
    MessageEdit,
    MessageNotificationRead,
    MessagePage,
    MessageRead,
    PinUpdate,
    ReadReceipt,
    SearchHit,
    UnreadCountRead,
)
from ...services.messaging import MessagingService
from ...services.messaging_bus import messaging_bus
from ..deps import get_principal

router = APIRouter(prefix="/messaging", tags=["messaging"])


def _service(session: Session) -> MessagingService:
    return MessagingService(session)


@router.get("/directory", response_model=list[DirectoryUserRead])
def directory(
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[DirectoryUserRead]:
    return _service(session).directory(principal, q=q)


@router.get("/conversations", response_model=list[ConversationRead])
def conversations(
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[ConversationRead]:
    return _service(session).conversations(principal, q=q)


@router.post(
    "/conversations/direct",
    response_model=ConversationRead,
    status_code=201,
)
def create_direct(
    payload: DirectConversationCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ConversationRead:
    return _service(session).create_direct(principal, payload)


@router.post("/channels", response_model=ConversationRead, status_code=201)
def create_channel(
    payload: ChannelCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ConversationRead:
    return _service(session).create_channel(principal, payload)


@router.patch("/channels/{conversation_id}", response_model=ConversationRead)
def update_channel(
    conversation_id: uuid.UUID,
    payload: ChannelUpdate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ConversationRead:
    return _service(session).update_channel(principal, conversation_id, payload)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagePage,
)
def messages(
    conversation_id: uuid.UUID,
    before: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MessagePage:
    return _service(session).messages(principal, conversation_id, before=before, limit=limit)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=201,
)
def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MessageRead:
    return _service(session).send(principal, conversation_id, payload)


@router.post("/conversations/{conversation_id}/read", response_model=ReadReceipt)
def mark_read(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ReadReceipt:
    at = _service(session).mark_read(principal, conversation_id)
    return ReadReceipt(conversation_id=conversation_id, last_read_at=at)


@router.patch(
    "/conversations/{conversation_id}/membership",
    response_model=ConversationRead,
)
def update_membership(
    conversation_id: uuid.UUID,
    payload: MembershipUpdate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> ConversationRead:
    return _service(session).set_muted(principal, conversation_id, payload.muted)


@router.patch("/messages/{message_id}", response_model=MessageRead)
def edit_message(
    message_id: uuid.UUID,
    payload: MessageEdit,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MessageRead:
    return _service(session).edit(principal, message_id, payload)


@router.delete("/messages/{message_id}", response_model=MessageRead)
def delete_message(
    message_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MessageRead:
    return _service(session).delete(principal, message_id)


@router.patch("/messages/{message_id}/pin", response_model=MessageRead)
def pin_message(
    message_id: uuid.UUID,
    payload: PinUpdate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MessageRead:
    return _service(session).pin(principal, message_id, payload.pinned)


@router.get("/search", response_model=list[SearchHit])
def search(
    q: str = Query(min_length=2, max_length=120),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[SearchHit]:
    return _service(session).search(principal, q)


@router.get("/notifications", response_model=list[MessageNotificationRead])
def notifications(
    unread_only: bool = Query(default=False),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[MessageNotificationRead]:
    return _service(session).notifications(principal, unread_only=unread_only)


@router.get("/notifications/unread-count", response_model=UnreadCountRead)
def unread_count(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> UnreadCountRead:
    return UnreadCountRead(unread=_service(session).unread_notifications(principal))


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MessageNotificationRead,
)
def read_notification(
    notification_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> MessageNotificationRead:
    item = _service(session).read_notification(principal, notification_id)
    if item is None:
        raise AppError(ErrorCode.NOT_FOUND, "Notification not found.")
    return item


@router.post("/notifications/read-all", response_model=UnreadCountRead)
def read_all_notifications(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> UnreadCountRead:
    read = _service(session).read_all_notifications(principal)
    return UnreadCountRead(unread=_service(session).unread_notifications(principal), read=read)


def _event_stream(principal: Principal) -> Iterator[str]:
    """Persisted-event stream.

    A message committed in this process wakes every open stream immediately, so
    delivery does not wait for a poll. The one-second history query is only a
    safety net for a missed wake-up, a process restart or a row written by
    another process; a reconnect resumes from stored history as well.
    """

    last = datetime.now(UTC)
    yield "retry: 3000\n\n"
    signal = messaging_bus.subscribe(principal.tenant_id)
    try:
        while True:
            try:
                with session_scope() as session:
                    events = MessagingService(session).events_since(principal, last)
                for event in events:
                    last = datetime.fromisoformat(event["created_at"]) + timedelta(microseconds=1)
                    yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
            except GeneratorExit:
                return
            except Exception:
                # A transient database failure must not turn into an infinite
                # error loop; the client reconnects and reconciles from history.
                yield "event: reconnect\ndata: {}\n\n"
                time.sleep(3)
                continue

            if not messaging_bus.wait(signal):
                yield ": keep-alive\n\n"
    finally:
        messaging_bus.unsubscribe(principal.tenant_id, signal)


@router.get("/stream")
def stream(principal: Principal = Depends(get_principal)) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(principal),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache, no-store, must-revalidate",
            "x-accel-buffering": "no",
            "connection": "keep-alive",
        },
    )
