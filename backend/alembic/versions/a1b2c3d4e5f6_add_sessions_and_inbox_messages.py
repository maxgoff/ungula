"""Add sessions and inbox_messages tables

Revision ID: a1b2c3d4e5f6
Revises: 42ee8ba3faa2
Create Date: 2026-02-03 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "42ee8ba3faa2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create sessions table
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("contact_id", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("chat_type", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_activity", sa.DateTime(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_channel", "sessions", ["channel"], unique=False)
    op.create_index(
        "ix_sessions_channel_contact",
        "sessions",
        ["channel", "contact_id"],
        unique=True,
    )

    # Create inbox_messages table
    op.create_table(
        "inbox_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("sender_id", sa.String(length=255), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("channel_message_id", sa.String(length=255), nullable=True),
        sa.Column("reply_to_id", sa.String(length=255), nullable=True),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inbox_messages_session_id", "inbox_messages", ["session_id"], unique=False)
    op.create_index("ix_inbox_messages_channel", "inbox_messages", ["channel"], unique=False)
    op.create_index("ix_inbox_messages_unread", "inbox_messages", ["unread"], unique=False)
    op.create_index("ix_inbox_messages_created_at", "inbox_messages", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_inbox_messages_created_at", table_name="inbox_messages")
    op.drop_index("ix_inbox_messages_unread", table_name="inbox_messages")
    op.drop_index("ix_inbox_messages_channel", table_name="inbox_messages")
    op.drop_index("ix_inbox_messages_session_id", table_name="inbox_messages")
    op.drop_table("inbox_messages")
    op.drop_index("ix_sessions_channel_contact", table_name="sessions")
    op.drop_index("ix_sessions_channel", table_name="sessions")
    op.drop_table("sessions")
