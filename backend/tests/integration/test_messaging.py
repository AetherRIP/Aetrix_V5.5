"""Messaging authorization, persistence and notification behaviour.

These tests run only against the disposable loopback PostgreSQL database the
integration fixture owns; they never touch the deployed Supabase project.
"""

from __future__ import annotations

import uuid


def _channel(client, headers, key: str) -> dict:
    conversations = client.get("/api/v1/messaging/conversations", headers=headers)
    assert conversations.status_code == 200
    return next(item for item in conversations.json() if item["channel_key"] == key)


def test_default_channels_and_direct_thread(client, auth_headers, identity) -> None:
    owner = auth_headers(identity.user_a)
    reviewer = auth_headers(identity.reviewer)

    general = _channel(client, owner, "general")
    assert general["kind"] == "CHANNEL"
    assert general["can_post"] is True

    direct = client.post(
        "/api/v1/messaging/conversations/direct",
        headers=owner,
        json={"user_id": str(identity.reviewer.id)},
    )
    assert direct.status_code == 201
    conversation = direct.json()
    assert conversation["kind"] == "DIRECT"
    assert conversation["peer"]["id"] == str(identity.reviewer.id)

    sent = client.post(
        f"/api/v1/messaging/conversations/{conversation['id']}/messages",
        headers=owner,
        json={"body": "Hello reviewer", "client_id": "direct-1"},
    )
    assert sent.status_code == 201
    message = sent.json()
    assert message["body"] == "Hello reviewer"

    inbox = client.get("/api/v1/messaging/conversations", headers=reviewer)
    assert inbox.status_code == 200
    row = next(item for item in inbox.json() if item["id"] == conversation["id"])
    assert row["unread_count"] == 1

    read = client.post(
        f"/api/v1/messaging/conversations/{conversation['id']}/read", headers=reviewer
    )
    assert read.status_code == 200
    after = client.get("/api/v1/messaging/conversations", headers=reviewer)
    row = next(item for item in after.json() if item["id"] == conversation["id"])
    assert row["unread_count"] == 0

    notifications = client.get("/api/v1/messaging/notifications", headers=reviewer)
    assert notifications.status_code == 200
    assert [item["kind"] for item in notifications.json()] == ["DIRECT"]


def test_cross_workspace_direct_and_reads_look_nonexistent(
    client, auth_headers, identity
) -> None:
    owner = auth_headers(identity.user_a)
    outsider = auth_headers(identity.user_b)
    direct = client.post(
        "/api/v1/messaging/conversations/direct",
        headers=owner,
        json={"user_id": str(identity.reviewer.id)},
    ).json()

    assert (
        client.post(
            "/api/v1/messaging/conversations/direct",
            headers=owner,
            json={"user_id": str(identity.user_b.id)},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/messaging/conversations/{direct['id']}/messages",
            headers=outsider,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/messaging/conversations/{direct['id']}/messages",
            headers=outsider,
            json={"body": "not mine", "client_id": "cross-workspace-1"},
        ).status_code
        == 404
    )


def test_announcement_posting_is_manager_only_and_viewers_can_use_general(
    client, auth_headers, identity
) -> None:
    owner = auth_headers(identity.user_a)
    viewer = auth_headers(identity.viewer)
    announcements = _channel(client, owner, "announcements")
    general = _channel(client, owner, "general")

    assert (
        client.post(
            f"/api/v1/messaging/conversations/{announcements['id']}/messages",
            headers=viewer,
            json={"body": "not allowed", "client_id": "ann-viewer"},
        ).status_code
        == 403
    )
    allowed = client.post(
        f"/api/v1/messaging/conversations/{general['id']}/messages",
        headers=viewer,
        json={"body": "hello general", "client_id": "general-viewer"},
    )
    assert allowed.status_code == 201


def test_mentions_replies_and_notification_deduplication(client, auth_headers, identity) -> None:
    owner = auth_headers(identity.user_a)
    reviewer = auth_headers(identity.reviewer)
    general = _channel(client, owner, "general")
    first = client.post(
        f"/api/v1/messaging/conversations/{general['id']}/messages",
        headers=owner,
        json={"body": "Question for review", "client_id": "mention-parent"},
    ).json()
    second = client.post(
        f"/api/v1/messaging/conversations/{general['id']}/messages",
        headers=reviewer,
        json={
            "body": "I can look",
            "client_id": "mention-reply",
            "reply_to_id": first["id"],
            "mentioned_user_ids": [str(identity.user_a.id)],
        },
    )
    assert second.status_code == 201

    # Both a mention and a reply target the same owner; the per-message unique
    # constraint keeps one notification rather than two.
    notifications = client.get("/api/v1/messaging/notifications", headers=owner)
    matching = [item for item in notifications.json() if item["message_id"] == second.json()["id"]]
    assert len(matching) == 1
    assert matching[0]["kind"] in {"MENTION", "REPLY"}


def test_idempotent_send_edit_pin_and_remove(client, auth_headers, identity) -> None:
    owner = auth_headers(identity.user_a)
    general = _channel(client, owner, "general")
    first = client.post(
        f"/api/v1/messaging/conversations/{general['id']}/messages",
        headers=owner,
        json={"body": "first", "client_id": "idem-key-1"},
    )
    assert first.status_code == 201
    again = client.post(
        f"/api/v1/messaging/conversations/{general['id']}/messages",
        headers=owner,
        json={"body": "first", "client_id": "idem-key-1"},
    )
    assert again.status_code == 201
    assert again.json()["id"] == first.json()["id"]

    message_id = first.json()["id"]
    edited = client.patch(
        f"/api/v1/messaging/messages/{message_id}",
        headers=owner,
        json={"body": "first, corrected"},
    )
    assert edited.status_code == 200
    assert edited.json()["edited_at"] is not None

    pinned = client.patch(
        f"/api/v1/messaging/messages/{message_id}/pin",
        headers=owner,
        json={"pinned": True},
    )
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True

    removed = client.delete(f"/api/v1/messaging/messages/{message_id}", headers=owner)
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert removed.json()["body"] == ""


def test_unknown_conversation_is_not_found(client, auth_headers, identity) -> None:
    owner = auth_headers(identity.user_a)
    assert (
        client.get(
            f"/api/v1/messaging/conversations/{uuid.uuid4()}/messages", headers=owner
        ).status_code
        == 404
    )


def test_directory_lists_only_same_workspace_accounts(client, auth_headers, identity) -> None:
    owner = auth_headers(identity.user_a)
    directory = client.get("/api/v1/messaging/directory", headers=owner)
    assert directory.status_code == 200
    ids = {item["id"] for item in directory.json()}
    assert str(identity.reviewer.id) in ids
    assert str(identity.viewer.id) in ids
    assert str(identity.user_a.id) not in ids
    assert str(identity.user_b.id) not in ids
