"""Tenant-scoped messaging, membership, notifications and delivery state.

The browser talks only to this service through the authenticated engine API.
There is no direct Supabase Data API path: PostgreSQL stores the rows, the VM
authorises every read and write, and the database roles remain closed. Realtime
delivery is an authenticated server-sent event stream over persisted rows.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.security import Principal
from ..db.models import (
    Conversation,
    ConversationMember,
    Message,
    MessageNotification,
    User,
)
from ..db.repositories import UserRepository
from ..schemas.messaging import (
    ChannelCreate,
    ChannelUpdate,
    ConversationRead,
    DirectConversationCreate,
    DirectoryUserRead,
    MessageCreate,
    MessageEdit,
    MessageNotificationRead,
    MessagePage,
    MessageRead,
    MessageReplyRead,
    SearchHit,
)
from .messaging_bus import messaging_bus

_MANAGER_ROLES = {"OWNER", "ADMIN", "PLATFORM_OWNER"}
_RATE_WINDOW = timedelta(seconds=60)
_RATE_LIMIT = 30

_DEFAULT_CHANNELS = (
    (
        "general",
        "General",
        "Workspace-wide conversation for everyone in this workspace.",
        "EVERYONE",
    ),
    (
        "announcements",
        "Announcements",
        "Important workspace notices. Only workspace managers can post.",
        "MANAGERS",
    ),
    (
        "teaching",
        "Teaching",
        "Planning, classes and teaching practice.",
        "EVERYONE",
    ),
    (
        "review",
        "Correction review",
        "Discussion about correction jobs, review questions and evidence.",
        "EVERYONE",
    ),
)

_PREVIEW_LIMIT = 180


def _now() -> datetime:
    return datetime.now(UTC)


def _name(user: User | None) -> str:
    if user is None:
        return "Unknown member"
    if user.display_name and user.display_name.strip():
        return user.display_name.strip()
    if user.email:
        return user.email.split("@", 1)[0]
    return "Workspace member"


def _slug(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return (value or "channel")[:60]


def _preview(body: str, *, deleted: bool = False) -> str:
    if deleted:
        return "Message removed"
    text = " ".join(body.split())
    return text if len(text) <= _PREVIEW_LIMIT else f"{text[: _PREVIEW_LIMIT - 1]}…"


class MessagingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    # -- access helpers --------------------------------------------------
    @staticmethod
    def _manager(principal: Principal) -> bool:
        return principal.role in _MANAGER_ROLES

    def _channels(self, principal: Principal) -> list[Conversation]:
        statement = select(Conversation).where(
            Conversation.tenant_id == principal.tenant_id,
            Conversation.kind == "CHANNEL",
        )
        # Archived channels keep their history for managers, who can restore
        # them; everyone else no longer sees or reaches them.
        if not self._manager(principal):
            statement = statement.where(Conversation.archived_at.is_(None))
        return list(
            self.session.scalars(
                statement.order_by(Conversation.created_at.asc(), Conversation.id.asc())
            )
        )

    def _membership(
        self, principal: Principal, conversation_id: uuid.UUID
    ) -> ConversationMember | None:
        return self.session.scalar(
            select(ConversationMember).where(
                ConversationMember.tenant_id == principal.tenant_id,
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == principal.user_id,
            )
        )

    def _conversation(self, principal: Principal, conversation_id: uuid.UUID) -> Conversation:
        conversation = self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == principal.tenant_id,
            )
        )
        if conversation is None:
            raise AppError(ErrorCode.NOT_FOUND, "Conversation not found.")
        if conversation.kind == "DIRECT" and self._membership(principal, conversation.id) is None:
            raise AppError(ErrorCode.NOT_FOUND, "Conversation not found.")
        if (
            conversation.kind == "CHANNEL"
            and conversation.archived_at is not None
            and not self._manager(principal)
        ):
            raise AppError(ErrorCode.NOT_FOUND, "Conversation not found.")
        return conversation

    def _participant(
        self, principal: Principal, conversation: Conversation, user_id: uuid.UUID
    ) -> bool:
        if user_id == principal.user_id:
            return True
        if conversation.kind == "CHANNEL":
            return self.users.get(principal.tenant_id, user_id) is not None
        return (
            self.session.scalar(
                select(ConversationMember.id).where(
                    ConversationMember.tenant_id == principal.tenant_id,
                    ConversationMember.conversation_id == conversation.id,
                    ConversationMember.user_id == user_id,
                )
            )
            is not None
        )

    def _dm_peer(self, principal: Principal, conversation: Conversation) -> User | None:
        peer_id = self.session.scalar(
            select(ConversationMember.user_id).where(
                ConversationMember.tenant_id == principal.tenant_id,
                ConversationMember.conversation_id == conversation.id,
                ConversationMember.user_id != principal.user_id,
            )
        )
        return self.users.get(principal.tenant_id, peer_id) if peer_id else None

    def _title(self, principal: Principal, conversation: Conversation) -> str:
        if conversation.kind == "CHANNEL":
            return conversation.title or "Workspace channel"
        return _name(self._dm_peer(principal, conversation))

    def _directory_user(self, user: User) -> DirectoryUserRead:
        return DirectoryUserRead(
            id=user.id,
            display_name=_name(user),
            email=user.email,
            role=user.role,
        )

    # -- defaults --------------------------------------------------------
    def ensure_default_channels(self, principal: Principal) -> None:
        """Create the four workspace channels once per tenant.

        ``ON CONFLICT DO NOTHING`` makes this safe when two first visitors race.
        The migration does not seed tenants because a tenant created after the
        migration must get the same channels on its first visit.
        """

        values = [
            {
                "tenant_id": principal.tenant_id,
                "kind": "CHANNEL",
                "channel_key": key,
                "title": title,
                "topic": topic,
                "post_policy": policy,
                "created_by_id": None,
            }
            for key, title, topic, policy in _DEFAULT_CHANNELS
        ]
        result = self.session.execute(
            pg_insert(Conversation)
            .values(values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "channel_key"])
            .returning(Conversation.id)
        )
        if result.first() is not None:
            self.session.commit()

    # -- reads -----------------------------------------------------------
    def directory(self, principal: Principal, *, q: str | None = None) -> list[DirectoryUserRead]:
        statement = select(User).where(
            User.tenant_id == principal.tenant_id,
            User.id != principal.user_id,
        )
        if q and q.strip():
            needle = f"%{q.strip()}%"
            statement = statement.where(
                or_(User.display_name.ilike(needle), User.email.ilike(needle))
            )
        rows = self.session.scalars(
            statement.order_by(User.display_name.asc(), User.created_at.asc()).limit(100)
        )
        return [self._directory_user(row) for row in rows]

    def conversations(
        self, principal: Principal, *, q: str | None = None
    ) -> list[ConversationRead]:
        self.ensure_default_channels(principal)
        channels = self._channels(principal)
        direct_ids = list(
            self.session.scalars(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.tenant_id == principal.tenant_id,
                    ConversationMember.user_id == principal.user_id,
                )
            )
        )
        directs = (
            list(
                self.session.scalars(
                    select(Conversation).where(
                        Conversation.tenant_id == principal.tenant_id,
                        Conversation.kind == "DIRECT",
                        Conversation.id.in_(direct_ids),
                    )
                )
            )
            if direct_ids
            else []
        )
        rows = channels + directs
        if q and q.strip():
            needle = q.strip().casefold()
            rows = [row for row in rows if needle in self._title(principal, row).casefold()]
        ordered = sorted(
            rows,
            key=lambda row: row.last_message_at or row.created_at,
            reverse=True,
        )
        return [self._conversation_read(principal, row) for row in ordered]

    def _conversation_read(
        self, principal: Principal, conversation: Conversation
    ) -> ConversationRead:
        member = self._membership(principal, conversation.id)
        last_read = member.last_read_at if member else None
        message_filters = [
            Message.tenant_id == principal.tenant_id,
            Message.conversation_id == conversation.id,
            Message.sender_id != principal.user_id,
            Message.deleted_at.is_(None),
        ]
        if last_read is not None:
            message_filters.append(Message.created_at > last_read)
        unread = int(
            self.session.scalar(select(func.count()).select_from(Message).where(*message_filters))
            or 0
        )
        last = self.session.scalar(
            select(Message)
            .where(
                Message.tenant_id == principal.tenant_id,
                Message.conversation_id == conversation.id,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        if conversation.kind == "CHANNEL":
            member_count = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.tenant_id == principal.tenant_id)
                )
                or 0
            )
            peer = None
        else:
            member_count = 2
            peer_user = self._dm_peer(principal, conversation)
            peer = self._directory_user(peer_user) if peer_user else None
        archived = conversation.archived_at is not None
        can_post = conversation.kind == "DIRECT" or (
            not archived and (conversation.post_policy == "EVERYONE" or self._manager(principal))
        )
        return ConversationRead(
            id=conversation.id,
            kind=conversation.kind,
            title=self._title(principal, conversation),
            topic=conversation.topic,
            post_policy=conversation.post_policy,
            channel_key=conversation.channel_key,
            peer=peer,
            last_message=_preview(last.body, deleted=last.deleted_at is not None) if last else None,
            last_message_at=conversation.last_message_at,
            unread_count=unread,
            member_count=member_count,
            muted=bool(member.muted) if member else False,
            can_post=can_post,
            can_manage=conversation.kind == "CHANNEL" and self._manager(principal),
            archived=archived,
        )

    def create_direct(
        self, principal: Principal, payload: DirectConversationCreate
    ) -> ConversationRead:
        if payload.user_id == principal.user_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "A direct conversation needs another person."
            )
        target = self.users.get(principal.tenant_id, payload.user_id)
        if target is None:
            raise AppError(ErrorCode.NOT_FOUND, "That person is not in this workspace.")
        key = ":".join(sorted((str(principal.user_id), str(target.id))))
        existing = self.session.scalar(
            select(Conversation).where(
                Conversation.tenant_id == principal.tenant_id,
                Conversation.direct_key == key,
            )
        )
        if existing is not None:
            self._ensure_dm_members(principal, existing, (principal.user_id, target.id))
            return self._conversation_read(principal, existing)
        conversation = Conversation(
            tenant_id=principal.tenant_id,
            kind="DIRECT",
            direct_key=key,
            created_by_id=principal.user_id,
            post_policy="EVERYONE",
        )
        self.session.add(conversation)
        self.session.flush()
        self._ensure_dm_members(principal, conversation, (principal.user_id, target.id))
        self.session.commit()
        return self._conversation_read(principal, conversation)

    def _ensure_dm_members(
        self,
        principal: Principal,
        conversation: Conversation,
        user_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        for user_id in user_ids:
            existing = self.session.scalar(
                select(ConversationMember).where(
                    ConversationMember.tenant_id == principal.tenant_id,
                    ConversationMember.conversation_id == conversation.id,
                    ConversationMember.user_id == user_id,
                )
            )
            if existing is None:
                self.session.add(
                    ConversationMember(
                        tenant_id=principal.tenant_id,
                        conversation_id=conversation.id,
                        user_id=user_id,
                    )
                )
        self.session.flush()

    def create_channel(self, principal: Principal, payload: ChannelCreate) -> ConversationRead:
        if not self._manager(principal):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only a workspace owner or administrator can create a channel.",
            )
        base = _slug(payload.title)
        key = base
        suffix = 2
        while self.session.scalar(
            select(Conversation.id).where(
                Conversation.tenant_id == principal.tenant_id,
                Conversation.channel_key == key,
            )
        ):
            key = f"{base[:55]}-{suffix}"
            suffix += 1
        conversation = Conversation(
            tenant_id=principal.tenant_id,
            kind="CHANNEL",
            channel_key=key,
            title=payload.title,
            topic=payload.topic,
            post_policy=payload.post_policy,
            created_by_id=principal.user_id,
        )
        self.session.add(conversation)
        self.session.flush()
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="messaging.channel.created",
            entity_type="conversation",
            entity_id=conversation.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"channel_key": key, "post_policy": payload.post_policy},
        )
        self.session.commit()
        return self._conversation_read(principal, conversation)

    def update_channel(
        self, principal: Principal, conversation_id: uuid.UUID, payload: ChannelUpdate
    ) -> ConversationRead:
        conversation = self._conversation(principal, conversation_id)
        if conversation.kind != "CHANNEL":
            raise AppError(ErrorCode.VALIDATION_ERROR, "Only a workspace channel can be changed.")
        if not self._manager(principal):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only a workspace owner or administrator can manage a channel.",
            )

        changed: dict[str, object] = {}
        if payload.title is not None:
            conversation.title = payload.title
            changed["title"] = payload.title
        if "topic" in payload.model_fields_set:
            conversation.topic = payload.topic
            changed["topic"] = payload.topic
        if payload.post_policy is not None:
            conversation.post_policy = payload.post_policy
            changed["post_policy"] = payload.post_policy
        if payload.archived is not None:
            was_archived = conversation.archived_at is not None
            if payload.archived and not was_archived:
                conversation.archived_at = _now()
            elif not payload.archived:
                conversation.archived_at = None
            if payload.archived != was_archived:
                changed["archived"] = payload.archived

        action = "messaging.channel.updated"
        if changed.get("archived") is True:
            action = "messaging.channel.archived"
        elif changed.get("archived") is False:
            action = "messaging.channel.restored"
        self.audit.record(
            tenant_id=principal.tenant_id,
            action=action,
            entity_type="conversation",
            entity_id=conversation.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"conversation_id": str(conversation.id), **changed},
        )
        self.session.commit()
        return self._conversation_read(principal, conversation)

    def messages(
        self,
        principal: Principal,
        conversation_id: uuid.UUID,
        *,
        before: uuid.UUID | None = None,
        limit: int = 50,
    ) -> MessagePage:
        conversation = self._conversation(principal, conversation_id)
        statement = select(Message).where(
            Message.tenant_id == principal.tenant_id,
            Message.conversation_id == conversation.id,
        )
        if before is not None:
            cursor = self.session.scalar(
                select(Message).where(
                    Message.id == before,
                    Message.tenant_id == principal.tenant_id,
                    Message.conversation_id == conversation.id,
                )
            )
            if cursor is None:
                raise AppError(ErrorCode.VALIDATION_ERROR, "The page cursor is not valid.")
            statement = statement.where(
                or_(
                    Message.created_at < cursor.created_at,
                    and_(Message.created_at == cursor.created_at, Message.id < cursor.id),
                )
            )
        rows = list(
            self.session.scalars(
                statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        return MessagePage(
            items=[self._message_read(principal, row, conversation) for row in rows],
            has_more=has_more,
            next_before=rows[0].id if has_more and rows else None,
        )

    def _message_read(
        self, principal: Principal, message: Message, conversation: Conversation
    ) -> MessageRead:
        sender = self.users.get(principal.tenant_id, message.sender_id)
        reply = None
        if message.reply_to_id is not None:
            parent = self.session.scalar(
                select(Message).where(
                    Message.id == message.reply_to_id,
                    Message.tenant_id == principal.tenant_id,
                )
            )
            if parent is not None:
                reply = MessageReplyRead(
                    id=parent.id,
                    sender_name=_name(self.users.get(principal.tenant_id, parent.sender_id)),
                    body=""
                    if parent.deleted_at is not None
                    else _preview(parent.body, deleted=False),
                    deleted=parent.deleted_at is not None,
                )
        deleted = message.deleted_at is not None
        can_delete = not deleted and (
            message.sender_id == principal.user_id
            or (conversation.kind == "CHANNEL" and self._manager(principal))
        )
        return MessageRead(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_id=message.sender_id,
            sender_name=_name(sender),
            sender_role=sender.role if sender else "UNKNOWN",
            body="" if deleted else message.body,
            created_at=message.created_at,
            edited_at=message.edited_at,
            deleted=deleted,
            pinned=message.pinned_at is not None,
            can_edit=not deleted and message.sender_id == principal.user_id,
            can_delete=can_delete,
            reply_to=reply,
        )

    # -- writes ----------------------------------------------------------
    def send(
        self,
        principal: Principal,
        conversation_id: uuid.UUID,
        payload: MessageCreate,
    ) -> MessageRead:
        conversation = self._conversation(principal, conversation_id)
        if conversation.archived_at is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "This channel is archived and cannot accept new messages.",
            )
        if (
            conversation.kind == "CHANNEL"
            and conversation.post_policy == "MANAGERS"
            and not self._manager(principal)
        ):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only a workspace owner or administrator can post in this channel.",
            )
        existing = None
        if payload.client_id:
            existing = self.session.scalar(
                select(Message).where(
                    Message.tenant_id == principal.tenant_id,
                    Message.sender_id == principal.user_id,
                    Message.client_id == payload.client_id,
                )
            )
        if existing is not None:
            return self._message_read(principal, existing, conversation)

        recent = int(
            self.session.scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.tenant_id == principal.tenant_id,
                    Message.sender_id == principal.user_id,
                    Message.created_at > _now() - _RATE_WINDOW,
                )
            )
            or 0
        )
        if recent >= _RATE_LIMIT:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "You are sending messages too quickly. Wait a moment and try again.",
            )

        parent = None
        if payload.reply_to_id is not None:
            parent = self.session.scalar(
                select(Message).where(
                    Message.id == payload.reply_to_id,
                    Message.tenant_id == principal.tenant_id,
                    Message.conversation_id == conversation.id,
                    Message.deleted_at.is_(None),
                )
            )
            if parent is None:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "The message being replied to is not in this conversation.",
                )
        mentioned: list[uuid.UUID] = []
        for user_id in dict.fromkeys(payload.mentioned_user_ids):
            if not self._participant(principal, conversation, user_id):
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "A mentioned account is not a participant in this conversation.",
                )
            if user_id != principal.user_id:
                mentioned.append(user_id)

        now = _now()
        message = Message(
            tenant_id=principal.tenant_id,
            conversation_id=conversation.id,
            sender_id=principal.user_id,
            body=payload.body,
            client_id=payload.client_id,
            reply_to_id=parent.id if parent else None,
            created_at=now,
        )
        self.session.add(message)
        conversation.last_message_at = now
        self.session.flush()

        if conversation.kind == "DIRECT":
            recipients = [user_id for user_id in (payload.mentioned_user_ids or [])]
            peer_id = self.session.scalar(
                select(ConversationMember.user_id).where(
                    ConversationMember.tenant_id == principal.tenant_id,
                    ConversationMember.conversation_id == conversation.id,
                    ConversationMember.user_id != principal.user_id,
                )
            )
            if peer_id is not None:
                recipients.append(peer_id)
            kinds = {recipient: "DIRECT" for recipient in recipients}
        else:
            recipients = list(mentioned)
            kinds = {recipient: "MENTION" for recipient in mentioned}
            if parent is not None and parent.sender_id != principal.user_id:
                recipients.append(parent.sender_id)
                kinds[parent.sender_id] = "REPLY"
            is_announcement = conversation.channel_key == "announcements"
            if is_announcement:
                for user_id in self.session.scalars(
                    select(User.id).where(User.tenant_id == principal.tenant_id)
                ):
                    if user_id != principal.user_id:
                        recipients.append(user_id)
                        kinds.setdefault(user_id, "ANNOUNCEMENT")
        for user_id in dict.fromkeys(recipients):
            if user_id == principal.user_id:
                continue
            recipient_member = self.session.scalar(
                select(ConversationMember).where(
                    ConversationMember.tenant_id == principal.tenant_id,
                    ConversationMember.conversation_id == conversation.id,
                    ConversationMember.user_id == user_id,
                )
            )
            if recipient_member is not None and recipient_member.muted:
                continue
            self.session.execute(
                pg_insert(MessageNotification)
                .values(
                    tenant_id=principal.tenant_id,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    kind=kinds.get(user_id, "DIRECT"),
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "message_id"])
            )
        self._publish(principal.tenant_id)
        self.session.commit()
        return self._message_read(principal, message, conversation)

    def _publish(self, tenant_id: uuid.UUID) -> None:
        """Wake open streams in this workspace so they re-read committed rows.

        The wake-up carries no message data, so a spurious or missed wake-up can
        only cause a redundant read, never a wrong or duplicated one.
        """

        messaging_bus.publish(tenant_id)

    def edit(
        self, principal: Principal, message_id: uuid.UUID, payload: MessageEdit
    ) -> MessageRead:
        message = self._message(principal, message_id)
        if message.sender_id != principal.user_id:
            raise AppError(ErrorCode.FORBIDDEN, "Only the sender can edit this message.")
        if message.deleted_at is not None:
            raise AppError(ErrorCode.CONFLICT, "A removed message cannot be edited.")
        conversation = self._conversation(principal, message.conversation_id)
        before_length = len(message.body)
        message.body = payload.body
        message.edited_at = _now()
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="messaging.message.edited",
            entity_type="message",
            entity_id=message.id,
            actor_type="USER",
            actor_id=principal.user_id,
            # Keep the audit trail useful without copying private message text.
            detail={
                "conversation_id": str(conversation.id),
                "before_length": before_length,
                "after_length": len(message.body),
            },
        )
        self._publish(principal.tenant_id)
        self.session.commit()
        return self._message_read(principal, message, conversation)

    def delete(self, principal: Principal, message_id: uuid.UUID) -> MessageRead:
        message = self._message(principal, message_id)
        conversation = self._conversation(principal, message.conversation_id)
        allowed = message.sender_id == principal.user_id or (
            conversation.kind == "CHANNEL" and self._manager(principal)
        )
        if not allowed:
            raise AppError(ErrorCode.FORBIDDEN, "You cannot remove this message.")
        if message.deleted_at is None:
            message.deleted_at = _now()
            message.body = ""
            message.pinned_at = None
            message.pinned_by_id = None
            self.audit.record(
                tenant_id=principal.tenant_id,
                action="messaging.message.removed",
                entity_type="message",
                entity_id=message.id,
                actor_type="USER",
                actor_id=principal.user_id,
                detail={
                    "conversation_id": str(conversation.id),
                    "sender_id": str(message.sender_id),
                },
            )
            self.session.commit()
        return self._message_read(principal, message, conversation)

    def pin(self, principal: Principal, message_id: uuid.UUID, pinned: bool) -> MessageRead:
        message = self._message(principal, message_id)
        conversation = self._conversation(principal, message.conversation_id)
        if conversation.kind != "CHANNEL" or not self._manager(principal):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only a workspace owner or administrator can pin channel messages.",
            )
        if message.deleted_at is not None:
            raise AppError(ErrorCode.CONFLICT, "A removed message cannot be pinned.")
        message.pinned_at = _now() if pinned else None
        message.pinned_by_id = principal.user_id if pinned else None
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="messaging.message.pinned" if pinned else "messaging.message.unpinned",
            entity_type="message",
            entity_id=message.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"conversation_id": str(conversation.id)},
        )
        self.session.commit()
        return self._message_read(principal, message, conversation)

    def mark_read(self, principal: Principal, conversation_id: uuid.UUID) -> datetime:
        conversation = self._conversation(principal, conversation_id)
        now = _now()
        member = self._membership(principal, conversation.id)
        if member is None:
            member = ConversationMember(
                tenant_id=principal.tenant_id,
                conversation_id=conversation.id,
                user_id=principal.user_id,
            )
            self.session.add(member)
        member.last_read_at = now
        self.session.execute(
            MessageNotification.__table__.update()
            .where(
                MessageNotification.tenant_id == principal.tenant_id,
                MessageNotification.user_id == principal.user_id,
                MessageNotification.conversation_id == conversation.id,
                MessageNotification.read_at.is_(None),
            )
            .values(read_at=now)
        )
        self.session.commit()
        return now

    def set_muted(
        self, principal: Principal, conversation_id: uuid.UUID, muted: bool
    ) -> ConversationRead:
        conversation = self._conversation(principal, conversation_id)
        member = self._membership(principal, conversation.id)
        if member is None:
            member = ConversationMember(
                tenant_id=principal.tenant_id,
                conversation_id=conversation.id,
                user_id=principal.user_id,
            )
            self.session.add(member)
        member.muted = muted
        self.session.commit()
        return self._conversation_read(principal, conversation)

    def _message(self, principal: Principal, message_id: uuid.UUID) -> Message:
        message = self.session.scalar(
            select(Message).where(
                Message.id == message_id,
                Message.tenant_id == principal.tenant_id,
            )
        )
        if message is None:
            raise AppError(ErrorCode.NOT_FOUND, "Message not found.")
        self._conversation(principal, message.conversation_id)
        return message

    # -- search / notifications -----------------------------------------
    def _accessible_conversation_ids(self, principal: Principal) -> list[uuid.UUID]:
        channel_filters = [
            Conversation.tenant_id == principal.tenant_id,
            Conversation.kind == "CHANNEL",
        ]
        if not self._manager(principal):
            channel_filters.append(Conversation.archived_at.is_(None))
        channels = list(self.session.scalars(select(Conversation.id).where(*channel_filters)))
        directs = list(
            self.session.scalars(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.tenant_id == principal.tenant_id,
                    ConversationMember.user_id == principal.user_id,
                )
            )
        )
        return channels + [row for row in directs if row not in channels]

    def search(self, principal: Principal, query: str) -> list[SearchHit]:
        needle = query.strip()
        if len(needle) < 2:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Search for at least two characters.")
        ids = self._accessible_conversation_ids(principal)
        if not ids:
            return []
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = list(
            self.session.scalars(
                select(Message)
                .where(
                    Message.tenant_id == principal.tenant_id,
                    Message.conversation_id.in_(ids),
                    Message.deleted_at.is_(None),
                    Message.body.ilike(f"%{escaped}%", escape="\\"),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(50)
            )
        )
        result: list[SearchHit] = []
        for row in rows:
            conversation = self.session.get(Conversation, row.conversation_id)
            if conversation is None:
                continue
            result.append(
                SearchHit(
                    message_id=row.id,
                    conversation_id=row.conversation_id,
                    conversation_title=self._title(principal, conversation),
                    sender_name=_name(self.users.get(principal.tenant_id, row.sender_id)),
                    body=_preview(row.body),
                    created_at=row.created_at,
                )
            )
        return result

    def notifications(
        self, principal: Principal, *, unread_only: bool = False
    ) -> list[MessageNotificationRead]:
        statement = select(MessageNotification).where(
            MessageNotification.tenant_id == principal.tenant_id,
            MessageNotification.user_id == principal.user_id,
        )
        if unread_only:
            statement = statement.where(MessageNotification.read_at.is_(None))
        rows = list(
            self.session.scalars(
                statement.order_by(MessageNotification.created_at.desc()).limit(50)
            )
        )
        result: list[MessageNotificationRead] = []
        for row in rows:
            message = self.session.get(Message, row.message_id)
            conversation = self.session.get(Conversation, row.conversation_id)
            if message is None or conversation is None:
                continue
            sender = self.users.get(principal.tenant_id, message.sender_id)
            result.append(
                MessageNotificationRead(
                    id=row.id,
                    kind=row.kind,
                    conversation_id=row.conversation_id,
                    conversation_title=self._title(principal, conversation),
                    message_id=row.message_id,
                    actor_name=_name(sender),
                    preview=_preview(message.body, deleted=message.deleted_at is not None),
                    created_at=row.created_at,
                    read_at=row.read_at,
                )
            )
        return result

    def unread_notifications(self, principal: Principal) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(MessageNotification)
                .where(
                    MessageNotification.tenant_id == principal.tenant_id,
                    MessageNotification.user_id == principal.user_id,
                    MessageNotification.read_at.is_(None),
                )
            )
            or 0
        )

    def read_notification(
        self, principal: Principal, notification_id: uuid.UUID
    ) -> MessageNotificationRead | None:
        row = self.session.scalar(
            select(MessageNotification).where(
                MessageNotification.id == notification_id,
                MessageNotification.tenant_id == principal.tenant_id,
                MessageNotification.user_id == principal.user_id,
            )
        )
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Notification not found.")
        if row.read_at is None:
            row.read_at = _now()
            self.session.commit()
        return next(
            (item for item in self.notifications(principal) if item.id == row.id),
            None,
        )

    def read_all_notifications(self, principal: Principal) -> int:
        now = _now()
        result = self.session.execute(
            MessageNotification.__table__.update()
            .where(
                MessageNotification.tenant_id == principal.tenant_id,
                MessageNotification.user_id == principal.user_id,
                MessageNotification.read_at.is_(None),
            )
            .values(read_at=now)
        )
        self.session.commit()
        return int(result.rowcount or 0)

    # -- realtime --------------------------------------------------------
    def events_since(self, principal: Principal, since: datetime) -> list[dict[str, Any]]:
        ids = self._accessible_conversation_ids(principal)
        events: list[dict[str, Any]] = []
        if ids:
            rows = list(
                self.session.execute(
                    select(Message, User)
                    .join(User, User.id == Message.sender_id)
                    .where(
                        Message.tenant_id == principal.tenant_id,
                        Message.conversation_id.in_(ids),
                        or_(
                            Message.created_at > since,
                            Message.edited_at > since,
                            Message.deleted_at > since,
                        ),
                    )
                    .order_by(Message.created_at.asc(), Message.id.asc())
                    .limit(100)
                ).all()
            )
            for row, sender in rows:
                # Edits and tombstones are updates to an existing row, so use
                # the newest mutation time for the stream cursor.  A reconnect
                # after either change reconciles the thread instead of showing
                # stale text.
                changed_at = max(
                    stamp
                    for stamp in (row.created_at, row.edited_at, row.deleted_at)
                    if stamp is not None
                )
                if changed_at <= since:
                    continue
                events.append(
                    {
                        "type": "message",
                        "message_id": str(row.id),
                        "conversation_id": str(row.conversation_id),
                        "created_at": changed_at.isoformat(),
                        # The body and sender are carried so a recipient can
                        # render the stored message without a follow-up
                        # request; persistence already happened in this
                        # committed row.
                        "sender_id": str(row.sender_id),
                        "sender_name": _name(sender),
                        "body": "" if row.deleted_at else row.body,
                        "edited": row.edited_at is not None,
                        "deleted": row.deleted_at is not None,
                    }
                )
        notes = list(
            self.session.execute(
                select(MessageNotification, Message, User)
                .join(Message, Message.id == MessageNotification.message_id)
                .join(User, User.id == Message.sender_id)
                .where(
                    MessageNotification.tenant_id == principal.tenant_id,
                    MessageNotification.user_id == principal.user_id,
                    MessageNotification.created_at > since,
                )
                .order_by(MessageNotification.created_at.asc())
                .limit(100)
            ).all()
        )
        for row, message, sender in notes:
            events.append(
                {
                    "type": "notification",
                    "notification_id": str(row.id),
                    "conversation_id": str(row.conversation_id),
                    "created_at": row.created_at.isoformat(),
                    "kind": row.kind,
                    "message_id": str(row.message_id),
                    "actor_name": _name(sender),
                    "preview": (message.body or "")[:160],
                }
            )
        events.sort(key=lambda event: event["created_at"])
        return events
