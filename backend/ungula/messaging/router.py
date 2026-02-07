"""
Message Router for Channel Messaging.

Routes inbound messages to the agent runner and sends responses
back through the appropriate channel.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ..agents.runner import AgentRunner
from ..api.ws_manager import ConnectionManager
from ..security.external_content import wrap_external_content
from ..storage.base import MessageCreate, StorageBackend
from .base import InboundMessage, OutboundMessage, SendResult
from .registry import ChannelRegistry
from .session import SessionManager

logger = logging.getLogger(__name__)


@dataclass
class MessageRouter:
    """
    Routes messages between channels and the agent runner.

    Handles the full flow:
    1. Receive inbound message
    2. Find/create session
    3. Find/create conversation
    4. Persist inbound to inbox
    5. Run through agent
    6. Send response back to channel
    7. Persist outbound to inbox
    """

    storage: StorageBackend
    agent_runner: AgentRunner
    session_manager: SessionManager
    channel_registry: ChannelRegistry
    ws_manager: ConnectionManager | None = None
    default_user_id: UUID | None = None

    async def dispatch(self, message: InboundMessage) -> SendResult:
        """
        Process an inbound message through the full pipeline.

        Args:
            message: The normalized inbound message.

        Returns:
            SendResult indicating success/failure of the response.
        """
        try:
            # 1. Get or create session
            session = await self.session_manager.get_or_create_session(
                channel=message.channel,
                contact_id=message.sender_id,
                contact_name=message.sender_name,
                chat_type=message.chat_type,
                metadata={
                    "group_id": message.group_id,
                    "group_name": message.group_name,
                },
            )
            logger.info(
                "Processing message from %s via %s (session %s)",
                message.sender_name or message.sender_id,
                message.channel,
                session.id,
            )

            # 2. Ensure session has a conversation
            session, conversation_id = await self.session_manager.ensure_conversation(
                session, user_id=self.default_user_id
            )

            # 3. Persist inbound message to inbox
            await self.session_manager.record_inbound_message(session, message)

            # 4. Also persist to conversation for agent context
            user_msg_data = MessageCreate(
                conversation_id=conversation_id,
                role="user",
                content=message.content,
                metadata={
                    "channel": message.channel,
                    "sender_id": message.sender_id,
                    "sender_name": message.sender_name,
                    "channel_message_id": message.id,
                },
            )
            await self.storage.create_message(user_msg_data)

            # 5. Wrap external content with security boundaries before agent processing
            wrapped_content = wrap_external_content(
                content=message.content,
                channel=message.channel,
                sender=message.sender_name or message.sender_id,
            )

            # 6. Run through agent (uses wrapped content for safety)
            response_content = await self._run_agent(conversation_id, wrapped_content)

            # 7. Persist assistant response to conversation
            assistant_msg_data = MessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                content=response_content,
                metadata={"channel": message.channel},
            )
            await self.storage.create_message(assistant_msg_data)

            # 8. Send response back through channel
            target = self._get_reply_target(message)
            outbound = OutboundMessage(
                channel=message.channel,
                target=target,
                content=response_content,
                reply_to_id=message.id,
                metadata={"session_id": str(session.id)},
            )

            result = await self.channel_registry.send(outbound)

            # 9. Persist outbound to inbox
            await self.session_manager.record_outbound_message(
                session=session,
                content=response_content,
                channel_message_id=result.message_id,
                reply_to_id=message.id,
            )

            # 10. Broadcast inbox event via WebSocket
            if self.ws_manager:
                try:
                    await self.ws_manager.broadcast("inbox.new", {
                        "channel": message.channel,
                        "sender": message.sender_name or message.sender_id,
                        "session_id": str(session.id),
                        "conversation_id": str(conversation_id),
                        "preview": message.content[:100],
                    })
                except Exception as e:
                    logger.debug("WebSocket broadcast failed: %s", e)

            # 11. Record the inbound in registry stats
            self.channel_registry.record_inbound(message.channel)

            return result

        except Exception as e:
            logger.error("Error processing message: %s", e, exc_info=True)
            return SendResult(success=False, error=str(e))

    async def _run_agent(self, conversation_id: UUID, content: str) -> str:
        """
        Run the message through the agent.

        Args:
            conversation_id: The conversation ID for context.
            content: The message content.

        Returns:
            The agent's response content.
        """
        try:
            # Use the agent runner to process
            # Note: AgentRunner.run() handles context assembly and LLM query
            response = await self.agent_runner.run(
                conversation_id=conversation_id,
                user_message=content,
            )
            return response.content
        except Exception as e:
            logger.error("Agent error: %s", e, exc_info=True)
            return f"I apologize, but I encountered an error processing your message: {e}"

    def _get_reply_target(self, message: InboundMessage) -> str:
        """
        Determine the target for replying to a message.

        Args:
            message: The inbound message to reply to.

        Returns:
            Channel-specific target identifier.
        """
        # For group chats, reply to the group
        if message.chat_type == "group" and message.group_id:
            return message.group_id

        # For direct messages, reply to the sender
        return message.sender_id

    async def send_message(
        self,
        session_id: UUID,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        """
        Send a message to a session (for inbox replies).

        Args:
            session_id: The session to send to.
            content: The message content.
            metadata: Optional metadata.

        Returns:
            SendResult indicating success/failure.
        """
        session = await self.session_manager.get_session(session_id)
        if not session:
            return SendResult(success=False, error=f"Session not found: {session_id}")

        outbound = OutboundMessage(
            channel=session.channel,
            target=session.contact_id,
            content=content,
            metadata=metadata or {},
        )

        result = await self.channel_registry.send(outbound)

        if result.success:
            # Record outbound message
            await self.session_manager.record_outbound_message(
                session=session,
                content=content,
                channel_message_id=result.message_id,
            )

        return result


async def create_message_callback(router: MessageRouter):
    """
    Create a message callback function for the channel registry.

    Args:
        router: The message router to use.

    Returns:
        An async callback function for inbound messages.
    """

    async def on_message(message: InboundMessage) -> None:
        """Handle an inbound message."""
        result = await router.dispatch(message)
        if not result.success:
            logger.warning(
                "Failed to process message %s: %s",
                message.id,
                result.error,
            )

    return on_message
