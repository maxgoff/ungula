"""
Discord Channel Provider.

Implements the ChannelProvider interface for Discord integration.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..base import (
    ChannelConfigError,
    ChannelConnectionError,
    ChannelProvider,
    ChannelSendError,
    ChannelStatus,
    InboundMessage,
    MessageCallback,
    OutboundMessage,
    SendResult,
)

logger = logging.getLogger(__name__)

# Discord.py is an optional dependency
try:
    import discord
    from discord import Client, Intents, Message

    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None
    Client = None
    Intents = None
    Message = None


@dataclass
class DiscordConfig:
    """Configuration for Discord provider."""

    token: str
    dm_enabled: bool = True
    dm_policy: str = "pairing"  # open, pairing, allowlist
    dm_allowlist: list[str] = field(default_factory=list)
    guild_policy: str = "allowlist"  # open, allowlist, disabled
    guild_allowlist: dict[str, Any] = field(default_factory=dict)
    mention_required: bool = True
    max_response_length: int = 2000


class DiscordProvider(ChannelProvider):
    """
    Discord channel provider using discord.py.

    Handles:
    - Direct messages
    - Guild/server messages (with mention or allowlisted channels)
    - Message sending with chunking
    """

    name = "discord"
    display_name = "Discord"

    def __init__(self):
        """Initialize Discord provider."""
        if not DISCORD_AVAILABLE:
            raise ImportError(
                "discord.py is not installed. Install with: pip install discord.py"
            )

        self._client: Client | None = None
        self._config: DiscordConfig | None = None
        self._on_message: MessageCallback | None = None
        self._status = ChannelStatus(channel="discord")
        self._ready_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(
        self,
        config: Any,
        on_message: MessageCallback,
    ) -> None:
        """
        Start the Discord bot.

        Args:
            config: Discord configuration (dict or DiscordConfig).
            on_message: Callback for inbound messages.
        """
        if isinstance(config, dict):
            self._config = DiscordConfig(**config)
        elif isinstance(config, DiscordConfig):
            self._config = config
        else:
            self._config = DiscordConfig(token=config) if config else None

        if not self._config or not self._config.token:
            raise ChannelConfigError("Discord token is required", "discord")

        self._on_message = on_message

        # Set up intents
        intents = Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.guild_messages = True

        # Create client
        self._client = Client(intents=intents)

        # Set up event handlers
        @self._client.event
        async def on_ready():
            logger.info("Discord bot connected as %s", self._client.user)
            self._status.running = True
            self._status.last_start = datetime.now(UTC)
            self._ready_event.set()

        @self._client.event
        async def on_message(message: Message):
            await self._handle_message(message)

        @self._client.event
        async def on_disconnect():
            logger.warning("Discord bot disconnected")
            self._status.running = False
            self._ready_event.clear()

        # Start client in background task
        self._task = asyncio.create_task(self._run_client())

        # Wait for ready
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            raise ChannelConnectionError(
                "Discord bot failed to connect within 30 seconds", "discord"
            )

    async def _run_client(self) -> None:
        """Run the Discord client."""
        try:
            await self._client.start(self._config.token)
        except discord.LoginFailure as e:
            self._status.last_error = str(e)
            raise ChannelConnectionError(f"Discord login failed: {e}", "discord")
        except Exception as e:
            self._status.last_error = str(e)
            logger.error("Discord client error: %s", e, exc_info=True)

    async def stop(self) -> None:
        """Stop the Discord bot."""
        if self._client:
            await self._client.close()
            self._client = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._status.running = False
        self._status.last_stop = datetime.now(UTC)
        logger.info("Discord bot stopped")

    async def send(self, message: OutboundMessage) -> SendResult:
        """
        Send a message through Discord.

        Args:
            message: The outbound message.

        Returns:
            SendResult indicating success/failure.
        """
        if not self._client or not self._client.is_ready():
            return SendResult(
                success=False,
                error="Discord client not ready",
            )

        try:
            # Find the target channel or user
            target = await self._resolve_target(message.target)
            if not target:
                return SendResult(
                    success=False,
                    error=f"Could not find Discord target: {message.target}",
                )

            # Chunk message if needed
            chunks = self._chunk_message(message.content)

            # Send all chunks
            sent_message = None
            for chunk in chunks:
                sent_message = await target.send(chunk)

            self._status.last_outbound = datetime.now(UTC)
            self._status.message_count_out += 1

            return SendResult(
                success=True,
                message_id=str(sent_message.id) if sent_message else None,
            )

        except discord.Forbidden as e:
            return SendResult(
                success=False,
                error=f"Permission denied: {e}",
            )
        except Exception as e:
            logger.error("Discord send error: %s", e, exc_info=True)
            return SendResult(success=False, error=str(e))

    async def check_health(self) -> bool:
        """Check if Discord is connected."""
        if not self._client:
            return False
        return self._client.is_ready()

    def get_status(self) -> ChannelStatus:
        """Get current channel status."""
        if self._client:
            self._status.healthy = self._client.is_ready()
        return self._status

    async def _resolve_target(self, target: str) -> Any:
        """
        Resolve a target identifier to a Discord object.

        Args:
            target: User ID, channel ID, or DM channel ID.

        Returns:
            A Discord object that can receive messages.
        """
        try:
            target_id = int(target)
        except ValueError:
            return None

        # Try as a channel first
        channel = self._client.get_channel(target_id)
        if channel:
            return channel

        # Try as a user (for DMs)
        user = self._client.get_user(target_id)
        if user:
            return await user.create_dm()

        # Fetch user if not cached
        try:
            user = await self._client.fetch_user(target_id)
            return await user.create_dm()
        except discord.NotFound:
            pass

        return None

    def _chunk_message(self, content: str) -> list[str]:
        """
        Chunk a message to fit Discord's length limit.

        Args:
            content: The message content.

        Returns:
            List of message chunks.
        """
        max_len = self._config.max_response_length

        if len(content) <= max_len:
            return [content]

        chunks = []
        while content:
            if len(content) <= max_len:
                chunks.append(content)
                break

            # Find a good break point
            break_point = content.rfind("\n", 0, max_len)
            if break_point == -1:
                break_point = content.rfind(" ", 0, max_len)
            if break_point == -1:
                break_point = max_len

            chunks.append(content[:break_point])
            content = content[break_point:].lstrip()

        return chunks

    async def _handle_message(self, message: Message) -> None:
        """
        Handle an incoming Discord message.

        Args:
            message: The Discord message.
        """
        # Ignore our own messages
        if message.author == self._client.user:
            return

        # Ignore bot messages
        if message.author.bot:
            return

        # Check if this is a DM or guild message
        is_dm = message.guild is None

        if is_dm:
            if not self._should_handle_dm(message):
                return
        else:
            if not self._should_handle_guild(message):
                return

        # Convert to InboundMessage
        inbound = self._message_to_inbound(message)

        # Update status
        self._status.last_inbound = datetime.now(UTC)
        self._status.message_count_in += 1

        # Dispatch to callback
        if self._on_message:
            try:
                await self._on_message(inbound)
            except Exception as e:
                logger.error("Error handling Discord message: %s", e, exc_info=True)

    def _should_handle_dm(self, message: Message) -> bool:
        """Check if we should handle this DM."""
        if not self._config.dm_enabled:
            return False

        policy = self._config.dm_policy

        if policy == "open":
            return True
        elif policy == "allowlist":
            return str(message.author.id) in self._config.dm_allowlist
        elif policy == "pairing":
            # Pairing mode: accept all DMs (user initiates)
            return True

        return False

    def _should_handle_guild(self, message: Message) -> bool:
        """Check if we should handle this guild message."""
        policy = self._config.guild_policy

        if policy == "disabled":
            return False

        # Check if bot was mentioned (unless mention not required)
        if self._config.mention_required:
            if self._client.user not in message.mentions:
                return False

        if policy == "open":
            return True
        elif policy == "allowlist":
            guild_id = str(message.guild.id)
            guild_config = self._config.guild_allowlist.get(guild_id, {})
            if not guild_config:
                return False

            # Check channel allowlist
            channels = guild_config.get("channels", [])
            if channels and message.channel.name not in channels:
                return False

            return True

        return False

    def _message_to_inbound(self, message: Message) -> InboundMessage:
        """
        Convert a Discord message to InboundMessage.

        Args:
            message: The Discord message.

        Returns:
            Normalized InboundMessage.
        """
        is_dm = message.guild is None

        # Get message content, removing bot mention
        content = message.content
        if self._client.user:
            content = content.replace(f"<@{self._client.user.id}>", "").strip()
            content = content.replace(f"<@!{self._client.user.id}>", "").strip()

        # Extract attachment URLs
        media_urls = [att.url for att in message.attachments] if message.attachments else []

        return InboundMessage.create(
            channel="discord",
            sender_id=str(message.author.id),
            sender_name=message.author.display_name,
            content=content,
            chat_type="direct" if is_dm else "group",
            group_id=str(message.channel.id) if not is_dm else None,
            group_name=message.channel.name if not is_dm else None,
            reply_to_id=str(message.reference.message_id) if message.reference else None,
            media_urls=media_urls if media_urls else None,
            metadata={
                "guild_id": str(message.guild.id) if message.guild else None,
                "guild_name": message.guild.name if message.guild else None,
                "channel_name": message.channel.name if hasattr(message.channel, "name") else None,
            },
        )
