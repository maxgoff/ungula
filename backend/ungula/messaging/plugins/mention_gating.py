"""
Mention requirement gating for group channels.

In group chats, requires the bot to be @mentioned before responding,
preventing the bot from responding to every message in a busy channel.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class MentionGate:
    """
    Gates message processing based on @mention requirements.

    In group contexts, only processes messages that mention the bot.
    Direct messages always pass through.
    """

    def __init__(
        self,
        bot_ids: set[str] | None = None,
        bot_names: set[str] | None = None,
        require_in_groups: bool = True,
    ):
        """
        Args:
            bot_ids: Set of bot user IDs to detect mentions.
            bot_names: Set of bot names to detect in text.
            require_in_groups: Whether to require mentions in group chats.
        """
        self.bot_ids = bot_ids or set()
        self.bot_names = bot_names or set()
        self.require_in_groups = require_in_groups

    def should_process(
        self,
        content: str,
        chat_type: str = "direct",
        mentioned_ids: list[str] | None = None,
    ) -> bool:
        """
        Check if a message should be processed.

        Args:
            content: The message text.
            chat_type: "direct" or "group".
            mentioned_ids: List of user IDs mentioned in the message.

        Returns:
            True if the message should be processed.
        """
        # DMs always pass
        if chat_type == "direct":
            return True

        # Groups don't require mention if disabled
        if not self.require_in_groups:
            return True

        # Check explicit mention IDs
        if mentioned_ids:
            for mid in mentioned_ids:
                if mid in self.bot_ids:
                    return True

        # Check text for bot name mentions
        content_lower = content.lower()
        for name in self.bot_names:
            if name.lower() in content_lower:
                return True

        # Check for @mention patterns in text
        for bot_id in self.bot_ids:
            if f"<@{bot_id}>" in content or f"@{bot_id}" in content:
                return True

        return False

    def strip_mention(self, content: str) -> str:
        """
        Remove bot @mentions from message content.

        Cleans up the message after the mention check so the
        agent doesn't see the @mention as part of the query.
        """
        result = content

        # Remove <@bot_id> patterns (Discord/Slack style)
        for bot_id in self.bot_ids:
            result = result.replace(f"<@{bot_id}>", "")
            result = result.replace(f"<@!{bot_id}>", "")

        # Remove @name patterns
        for name in self.bot_names:
            result = re.sub(rf"@{re.escape(name)}\b", "", result, flags=re.IGNORECASE)

        return result.strip()
