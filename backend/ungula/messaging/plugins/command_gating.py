"""
Per-channel command permission gating.

Controls which commands/directives are allowed per channel,
preventing unauthorized access to admin commands from public channels.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default command permissions by channel type
DEFAULT_PERMISSIONS: dict[str, set[str]] = {
    "direct": {"*"},  # All commands allowed in DMs
    "group": {"help", "status", "model"},  # Limited in groups
}


class CommandGate:
    """
    Gates command execution based on channel and chat type.

    Checks if a command/directive is allowed for the given channel
    and chat context before execution.
    """

    def __init__(
        self,
        permissions: dict[str, set[str]] | None = None,
        admin_users: set[str] | None = None,
    ):
        """
        Args:
            permissions: Map of chat_type -> set of allowed commands.
                         Use "*" to allow all commands.
            admin_users: Set of user IDs that bypass all gates.
        """
        self.permissions = permissions or DEFAULT_PERMISSIONS
        self.admin_users = admin_users or set()

    def is_allowed(
        self,
        command: str,
        chat_type: str = "direct",
        sender_id: str | None = None,
        channel: str | None = None,
    ) -> bool:
        """
        Check if a command is allowed in this context.

        Args:
            command: The command name (e.g., "model", "reset", "admin").
            chat_type: "direct" or "group".
            sender_id: The sender's ID for admin check.
            channel: The channel name (for channel-specific overrides).

        Returns:
            True if the command is allowed.
        """
        # Admin users bypass all gates
        if sender_id and sender_id in self.admin_users:
            return True

        # Check channel-specific permissions first
        channel_key = f"{channel}:{chat_type}" if channel else None
        if channel_key and channel_key in self.permissions:
            allowed = self.permissions[channel_key]
            return "*" in allowed or command.lower() in allowed

        # Fall back to chat type permissions
        allowed = self.permissions.get(chat_type, set())
        return "*" in allowed or command.lower() in allowed

    def add_permission(
        self,
        chat_type: str,
        command: str,
        channel: str | None = None,
    ) -> None:
        """Add a command permission."""
        key = f"{channel}:{chat_type}" if channel else chat_type
        if key not in self.permissions:
            self.permissions[key] = set()
        self.permissions[key].add(command.lower())

    def remove_permission(
        self,
        chat_type: str,
        command: str,
        channel: str | None = None,
    ) -> None:
        """Remove a command permission."""
        key = f"{channel}:{chat_type}" if channel else chat_type
        if key in self.permissions:
            self.permissions[key].discard(command.lower())
