"""
Reaction-based acknowledgment gating.

Adds reaction acknowledgments to incoming messages (e.g., thumbs up)
to confirm receipt before processing, and error reactions on failure.
"""

import logging
from typing import Any

from ..base import ChannelProvider

logger = logging.getLogger(__name__)

# Default reactions
ACK_REACTION = "eyes"       # Acknowledge receipt
DONE_REACTION = "white_check_mark"  # Processing complete
ERROR_REACTION = "x"        # Processing failed


class ReactionManager:
    """
    Manages reaction-based acknowledgments for channel messages.

    Adds reactions to indicate message status:
    - eyes: Message received, processing
    - check mark: Response sent successfully
    - x: Error occurred
    """

    def __init__(
        self,
        ack_emoji: str = ACK_REACTION,
        done_emoji: str = DONE_REACTION,
        error_emoji: str = ERROR_REACTION,
    ):
        self.ack_emoji = ack_emoji
        self.done_emoji = done_emoji
        self.error_emoji = error_emoji

    async def acknowledge(
        self,
        provider: ChannelProvider,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Add an acknowledgment reaction to a message."""
        try:
            if hasattr(provider, "react"):
                await provider.react(channel_id, message_id, self.ack_emoji)
        except Exception as e:
            logger.debug("Failed to add ack reaction: %s", e)

    async def mark_done(
        self,
        provider: ChannelProvider,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Add a completion reaction to a message."""
        try:
            if hasattr(provider, "react"):
                await provider.react(channel_id, message_id, self.done_emoji)
        except Exception as e:
            logger.debug("Failed to add done reaction: %s", e)

    async def mark_error(
        self,
        provider: ChannelProvider,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Add an error reaction to a message."""
        try:
            if hasattr(provider, "react"):
                await provider.react(channel_id, message_id, self.error_emoji)
        except Exception as e:
            logger.debug("Failed to add error reaction: %s", e)
