"""
Session Manager for Channel Messaging.

Manages sessions (contact conversations) and their mapping to Ungula conversations.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from ..storage.base import (
    ConversationCreate,
    InboxMessage,
    InboxMessageCreate,
    Session,
    SessionCreate,
    StorageBackend,
)
from .base import InboundMessage

logger = logging.getLogger(__name__)


@dataclass
class SessionManager:
    """
    Manages channel sessions and conversation mapping.

    Sessions track contact conversations across channels. Each session
    can be linked to an Ungula conversation for agent processing.
    """

    storage: StorageBackend

    async def get_or_create_session(
        self,
        channel: str,
        contact_id: str,
        contact_name: str | None = None,
        chat_type: str = "direct",
        metadata: dict | None = None,
    ) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            channel: The channel name (discord, imessage, etc.)
            contact_id: Channel-specific contact identifier.
            contact_name: Human-readable contact name.
            chat_type: "direct" for DMs, "group" for group chats.
            metadata: Optional metadata for the session.

        Returns:
            The existing or newly created session.
        """
        # Try to find existing session
        session = await self.storage.get_session_by_contact(channel, contact_id)
        if session:
            # Update contact name if provided and different
            if contact_name and contact_name != session.contact_name:
                session = await self.storage.update_session(
                    session.id, contact_name=contact_name
                )
            return session

        # Create new session
        session_data = SessionCreate(
            channel=channel,
            contact_id=contact_id,
            contact_name=contact_name,
            chat_type=chat_type,
            metadata=metadata or {},
        )
        session = await self.storage.create_session(session_data)
        logger.info(
            "Created new session %s for %s:%s",
            session.id,
            channel,
            contact_id,
        )
        return session

    async def get_session(self, session_id: UUID) -> Session | None:
        """Get a session by ID."""
        return await self.storage.get_session(session_id)

    async def list_sessions(
        self,
        channel: str | None = None,
        active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """List sessions with optional filtering."""
        return await self.storage.list_sessions(
            channel=channel,
            active=active,
            limit=limit,
            offset=offset,
        )

    async def link_conversation(
        self, session_id: UUID, conversation_id: UUID
    ) -> Session | None:
        """
        Link a session to an Ungula conversation.

        Args:
            session_id: The session to link.
            conversation_id: The conversation to link to.

        Returns:
            The updated session.
        """
        session = await self.storage.update_session(
            session_id, conversation_id=conversation_id
        )
        if session:
            logger.info(
                "Linked session %s to conversation %s",
                session_id,
                conversation_id,
            )
        return session

    async def ensure_conversation(
        self, session: Session, user_id: UUID | None = None
    ) -> tuple[Session, UUID]:
        """
        Ensure a session has a linked conversation, creating one if needed.

        Args:
            session: The session to ensure has a conversation.
            user_id: Optional user ID for the conversation.

        Returns:
            Tuple of (updated session, conversation_id).
        """
        if session.conversation_id:
            return session, session.conversation_id

        # Create a new conversation for this session
        conv_title = f"{session.channel}: {session.contact_name or session.contact_id}"
        conv_data = ConversationCreate(
            title=conv_title,
            user_id=user_id,
            metadata={
                "channel": session.channel,
                "contact_id": session.contact_id,
                "session_id": str(session.id),
            },
        )
        conversation = await self.storage.create_conversation(conv_data)

        # Link the session to the conversation
        session = await self.link_conversation(session.id, conversation.id)
        return session, conversation.id

    async def deactivate_session(self, session_id: UUID) -> Session | None:
        """Mark a session as inactive."""
        return await self.storage.update_session(session_id, active=False)

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session and its messages."""
        return await self.storage.delete_session(session_id)

    async def record_inbound_message(
        self,
        session: Session,
        message: InboundMessage,
    ) -> InboxMessage:
        """
        Record an inbound message in the inbox.

        Args:
            session: The session the message belongs to.
            message: The normalized inbound message.

        Returns:
            The created inbox message.
        """
        inbox_data = InboxMessageCreate(
            session_id=session.id,
            channel=message.channel,
            direction="inbound",
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            content=message.content,
            channel_message_id=message.id,
            reply_to_id=message.reply_to_id,
            media_urls=message.media_urls,
            metadata=message.metadata,
        )
        inbox_msg = await self.storage.create_inbox_message(inbox_data)

        # Update session activity
        await self.storage.update_session_activity(session.id, increment_count=True)

        logger.debug(
            "Recorded inbound message %s for session %s",
            inbox_msg.id,
            session.id,
        )
        return inbox_msg

    async def record_outbound_message(
        self,
        session: Session,
        content: str,
        channel_message_id: str | None = None,
        reply_to_id: str | None = None,
        sender_name: str = "Ungula",
        metadata: dict | None = None,
    ) -> InboxMessage:
        """
        Record an outbound message in the inbox.

        Args:
            session: The session the message belongs to.
            content: The message content.
            channel_message_id: The ID from the channel (if sent).
            reply_to_id: ID of message being replied to.
            sender_name: Name to show for outbound messages.
            metadata: Optional metadata.

        Returns:
            The created inbox message.
        """
        inbox_data = InboxMessageCreate(
            session_id=session.id,
            channel=session.channel,
            direction="outbound",
            sender_id="ungula",
            sender_name=sender_name,
            content=content,
            channel_message_id=channel_message_id,
            reply_to_id=reply_to_id,
            metadata=metadata or {},
        )
        inbox_msg = await self.storage.create_inbox_message(inbox_data)

        # Update session activity (don't increment count for outbound)
        await self.storage.update_session_activity(session.id, increment_count=False)

        logger.debug(
            "Recorded outbound message %s for session %s",
            inbox_msg.id,
            session.id,
        )
        return inbox_msg

    async def get_inbox_messages(
        self,
        session_id: UUID | None = None,
        channel: str | None = None,
        unread: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InboxMessage]:
        """List inbox messages with optional filtering."""
        return await self.storage.list_inbox_messages(
            session_id=session_id,
            channel=channel,
            unread=unread,
            limit=limit,
            offset=offset,
        )

    async def mark_messages_read(
        self,
        session_id: UUID | None = None,
        message_ids: list[UUID] | None = None,
    ) -> int:
        """Mark messages as read."""
        return await self.storage.mark_messages_read(
            session_id=session_id,
            message_ids=message_ids,
        )

    async def count_unread(
        self, channel: str | None = None, session_id: UUID | None = None
    ) -> int:
        """Count unread messages."""
        return await self.storage.count_unread_messages(
            channel=channel,
            session_id=session_id,
        )

    async def get_last_message_content(self, session_id: UUID) -> str | None:
        """Get the content of the last message in a session."""
        messages = await self.storage.list_inbox_messages(
            session_id=session_id, limit=1
        )
        if messages:
            return messages[0].content
        return None
