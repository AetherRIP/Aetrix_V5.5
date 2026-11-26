"""Workspace messaging, direct threads and message notifications.

Revision ID: 0040_messaging
Revises: 0039_credential_pools
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_messaging"
down_revision = "0039_credential_pools"
branch_labels = None
depends_on = None

_TABLES = (
    "conversations",
    "conversation_members",
    "messages",
    "message_notifications",
)


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("direct_key", sa.String(80)),
        sa.Column("channel_key", sa.String(80)),
        sa.Column("title", sa.String(120)),
        sa.Column("topic", sa.String(500)),
        sa.Column("post_policy", sa.String(16), nullable=False, server_default="EVERYONE"),
        sa.Column(
            "created_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("kind IN ('DIRECT','CHANNEL')", name="ck_conversations_kind"),
        sa.CheckConstraint(
            "(kind = 'DIRECT' AND direct_key IS NOT NULL AND channel_key IS NULL) "
            "OR (kind = 'CHANNEL' AND channel_key IS NOT NULL AND direct_key IS NULL)",
            name="ck_conversations_identity",
        ),
        sa.CheckConstraint(
            "post_policy IN ('EVERYONE','MANAGERS')", name="ck_conversations_post_policy"
        ),
        sa.UniqueConstraint("tenant_id", "direct_key", name="uq_conversation_direct"),
        sa.UniqueConstraint("tenant_id", "channel_key", name="uq_conversation_channel"),
    )
    op.create_index(
        "ix_conversation_tenant_last",
        "conversations",
        ["tenant_id", "last_message_at"],
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])

    op.create_table(
        "conversation_members",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_read_at", sa.DateTime(timezone=True)),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_member"
        ),
    )
    op.create_index(
        "ix_conversation_member_user",
        "conversation_members",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_conversation_members_tenant_id", "conversation_members", ["tenant_id"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("client_id", sa.String(64)),
        sa.Column(
            "reply_to_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("pinned_at", sa.DateTime(timezone=True)),
        sa.Column(
            "pinned_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("char_length(body) <= 4000", name="ck_messages_body_length"),
        sa.UniqueConstraint(
            "sender_id", "client_id", name="uq_message_sender_client"
        ),
    )
    op.create_index(
        "ix_message_conversation_time",
        "messages",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index("ix_message_tenant_time", "messages", ["tenant_id", "created_at"])
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])

    op.create_table(
        "message_notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('DIRECT','MENTION','REPLY','ANNOUNCEMENT')",
            name="ck_message_notifications_kind",
        ),
        sa.UniqueConstraint(
            "user_id", "message_id", name="uq_message_notification"
        ),
    )
    op.create_index(
        "ix_message_notification_user",
        "message_notifications",
        ["tenant_id", "user_id", "read_at"],
    )
    op.create_index(
        "ix_message_notifications_tenant_id", "message_notifications", ["tenant_id"]
    )

    # The browser has no Data API path to these tables.  Supabase stores the
    # rows; the VM API is the only authorized reader/writer.
    for table in _TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated')
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
