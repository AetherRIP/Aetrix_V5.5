from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.core.errors import AppError
from app.schemas.messaging import ChannelCreate, ChannelUpdate, MessageCreate
from app.services.messaging import MessagingService, _preview, _slug
from pydantic import ValidationError


def test_message_body_is_trimmed_and_newlines_preserved() -> None:
    payload = MessageCreate(body="  first line\nsecond line  ", client_id="client-123")
    assert payload.body == "first line\nsecond line"


def test_blank_message_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MessageCreate(body="   ", client_id="client-123")


def test_channel_title_and_topic_are_normalised() -> None:
    payload = ChannelCreate(title="  Year   11  ", topic="  revision   notes ")
    assert payload.title == "Year 11"
    assert payload.topic == "revision notes"


def test_channel_update_normalises_a_new_title_and_can_clear_the_topic() -> None:
    payload = ChannelUpdate(title="  Year   11  ", topic=None, archived=True)
    assert payload.title == "Year 11"
    assert payload.topic is None
    assert payload.archived is True
    # An omitted topic is left alone; an explicit null clears it.
    assert "topic" in payload.model_fields_set


@pytest.mark.parametrize("title", [" ", "a", "x" * 121])
def test_channel_update_rejects_an_invalid_title(title: str) -> None:
    with pytest.raises(ValidationError):
        ChannelUpdate(title=title)


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _channel_service(
    *, manager: bool
) -> tuple[MessagingService, SimpleNamespace, _FakeSession, _FakeAudit]:
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        kind="CHANNEL",
        title="General",
        topic="Old topic",
        post_policy="EVERYONE",
        archived_at=None,
    )
    service = object.__new__(MessagingService)
    service.session = _FakeSession()
    audit = _FakeAudit()
    service.audit = audit
    service._conversation = lambda principal, conversation_id: conversation
    service._manager = lambda principal: manager
    service._conversation_read = lambda principal, row: {
        "archived": row.archived_at is not None,
        "title": row.title,
        "topic": row.topic,
    }
    return service, conversation, service.session, audit


def test_a_manager_can_archive_a_channel_and_the_change_is_audited() -> None:
    service, conversation, session, audit = _channel_service(manager=True)

    result = service.update_channel(
        SimpleNamespace(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role="OWNER"),
        conversation.id,
        ChannelUpdate(archived=True),
    )

    assert result["archived"] is True
    assert conversation.archived_at is not None
    assert session.committed is True
    assert audit.calls[-1]["action"] == "messaging.channel.archived"


def test_a_non_manager_cannot_archive_a_channel() -> None:
    service, conversation, session, _ = _channel_service(manager=False)

    with pytest.raises(AppError):
        service.update_channel(
            SimpleNamespace(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role="REVIEWER"),
            conversation.id,
            ChannelUpdate(archived=True),
        )

    assert conversation.archived_at is None
    assert session.committed is False


def test_preview_marks_removed_messages_and_shortens_long_text() -> None:
    assert _preview("hello", deleted=True) == "Message removed"
    assert len(_preview("x" * 500)) <= 180


def test_channel_key_is_stable_and_safe() -> None:
    assert _slug("Year 11 / Revision!") == "year-11-revision"
    assert _slug("***") == "channel"
