"""Typed contracts for the internal messaging workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MessageKind = Literal["DIRECT", "CHANNEL"]
PostPolicy = Literal["EVERYONE", "MANAGERS"]


def _text(value: str, *, limit: int) -> str:
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        raise ValueError("must not be blank")
    if len(cleaned) > limit:
        raise ValueError(f"must be at most {limit} characters")
    return cleaned


class DirectoryUserRead(BaseModel):
    id: UUID
    display_name: str
    email: str | None
    role: str


class MessageReplyRead(BaseModel):
    id: UUID
    sender_name: str
    body: str
    deleted: bool


class MessageRead(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_id: UUID
    sender_name: str
    sender_role: str
    body: str
    created_at: datetime
    edited_at: datetime | None
    deleted: bool
    pinned: bool
    can_edit: bool
    can_delete: bool
    reply_to: MessageReplyRead | None = None


class ConversationRead(BaseModel):
    id: UUID
    kind: MessageKind
    title: str
    topic: str | None
    post_policy: PostPolicy
    channel_key: str | None
    peer: DirectoryUserRead | None
    last_message: str | None
    last_message_at: datetime | None
    unread_count: int
    member_count: int
    muted: bool
    can_post: bool
    can_manage: bool
    archived: bool


class MessagePage(BaseModel):
    items: list[MessageRead] = Field(default_factory=list)
    has_more: bool = False
    next_before: UUID | None = None


class SearchHit(BaseModel):
    message_id: UUID
    conversation_id: UUID
    conversation_title: str
    sender_name: str
    body: str
    created_at: datetime


class DirectConversationCreate(BaseModel):
    user_id: UUID


class ChannelCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    topic: str | None = Field(default=None, max_length=500)
    post_policy: PostPolicy = "EVERYONE"

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _text(value, limit=120)

    @field_validator("topic")
    @classmethod
    def _topic(cls, value: str | None) -> str | None:
        return _text(value, limit=500) if value else None


class ChannelUpdate(BaseModel):
    """A manager's changes to a channel; omitted fields are left alone."""

    title: str | None = Field(default=None, min_length=2, max_length=120)
    topic: str | None = Field(default=None, max_length=500)
    post_policy: PostPolicy | None = None
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return _text(value, limit=120) if value is not None else None

    @field_validator("topic")
    @classmethod
    def _topic(cls, value: str | None) -> str | None:
        return _text(value, limit=500) if value else None


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    client_id: str = Field(min_length=8, max_length=64)
    reply_to_id: UUID | None = None
    mentioned_user_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        cleaned = value.replace("\r\n", "\n").strip()
        if not cleaned:
            raise ValueError("must not be blank")
        if len(cleaned) > 4000:
            raise ValueError("must be at most 4000 characters")
        return cleaned


class MessageEdit(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        cleaned = value.replace("\r\n", "\n").strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class PinUpdate(BaseModel):
    pinned: bool


class MembershipUpdate(BaseModel):
    muted: bool


class MessageNotificationRead(BaseModel):
    id: UUID
    kind: str
    conversation_id: UUID
    conversation_title: str
    message_id: UUID
    actor_name: str
    preview: str
    created_at: datetime
    read_at: datetime | None


class UnreadCountRead(BaseModel):
    unread: int
    read: int = 0


class ReadReceipt(BaseModel):
    conversation_id: UUID
    last_read_at: datetime
