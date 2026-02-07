"""
Slack Channel Provider.

Implements the ChannelProvider interface using slack-bolt
with Socket Mode for real-time messaging.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from ..base import (
    ChannelConfigError,
    ChannelProvider,
    ChannelStatus,
    InboundMessage,
    MessageCallback,
    OutboundMessage,
    SendResult,
)
from .format import markdown_to_mrkdwn, to_blocks, truncate_message
from .threading import ThreadTracker

logger = logging.getLogger(__name__)


class SlackProvider(ChannelProvider):
    """Slack channel provider using slack-bolt Socket Mode."""

    name = "slack"
    display_name = "Slack"

    def __init__(self):
        self._app = None
        self._handler = None
        self._on_message: MessageCallback | None = None
        self._config: dict[str, Any] = {}
        self._status = ChannelStatus(channel="slack")
        self._threads = ThreadTracker()
        self._task: asyncio.Task | None = None

    async def start(self, config: Any, on_message: MessageCallback, **kwargs) -> None:
        """Start the Slack provider with Socket Mode."""
        if isinstance(config, dict):
            self._config = config
        else:
            self._config = {}

        bot_token = self._config.get("bot_token")
        app_token = self._config.get("app_token")

        if not bot_token or not app_token:
            raise ChannelConfigError(
                "Slack requires both bot_token and app_token",
                channel="slack",
            )

        self._on_message = on_message

        try:
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
            from slack_bolt.async_app import AsyncApp
        except ImportError:
            raise ChannelConfigError(
                "slack-bolt not installed. Install with: pip install slack-bolt",
                channel="slack",
            )

        # Create Slack app
        self._app = AsyncApp(token=bot_token)

        # Register message handler
        @self._app.event("message")
        async def handle_message(event, say):
            await self._handle_slack_message(event, say)

        # Register app_mention handler
        @self._app.event("app_mention")
        async def handle_mention(event, say):
            await self._handle_slack_message(event, say)

        # Start Socket Mode
        self._handler = AsyncSocketModeHandler(self._app, app_token)
        self._task = asyncio.create_task(self._handler.start_async())

        self._status.running = True
        self._status.last_start = datetime.now(UTC)
        logger.info("Slack provider started (Socket Mode)")

    async def stop(self) -> None:
        """Stop the Slack provider."""
        if self._handler:
            try:
                await self._handler.close_async()
            except Exception as e:
                logger.warning("Error stopping Slack handler: %s", e)

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._status.running = False
        self._status.last_stop = datetime.now(UTC)
        logger.info("Slack provider stopped")

    async def send(self, message: OutboundMessage) -> SendResult:
        """Send a message to Slack."""
        if not self._app:
            return SendResult(success=False, error="Slack app not initialized")

        try:
            text = markdown_to_mrkdwn(message.content)
            text = truncate_message(text)

            kwargs: dict[str, Any] = {
                "channel": message.target,
                "text": text,
            }

            # Use blocks for richer formatting
            blocks = to_blocks(message.content)
            if blocks:
                kwargs["blocks"] = blocks

            # Thread reply if we have a thread_ts
            reply_to = message.reply_to_id
            if reply_to:
                kwargs["thread_ts"] = reply_to

            result = await self._app.client.chat_postMessage(**kwargs)

            if result["ok"]:
                msg_ts = result["ts"]
                self._status.message_count_out += 1
                self._status.last_outbound = datetime.now(UTC)
                return SendResult(success=True, message_id=msg_ts)
            else:
                error = result.get("error", "Unknown Slack error")
                return SendResult(success=False, error=error)

        except Exception as e:
            self._status.last_error = str(e)
            logger.error("Slack send error: %s", e)
            return SendResult(success=False, error=str(e))

    async def check_health(self) -> bool:
        """Check if Slack connection is healthy."""
        if not self._app:
            self._status.healthy = False
            return False
        try:
            result = await self._app.client.auth_test()
            self._status.healthy = result["ok"]
            return result["ok"]
        except Exception:
            self._status.healthy = False
            return False

    def get_status(self) -> ChannelStatus:
        """Get channel status."""
        return self._status

    async def _handle_slack_message(self, event: dict, say) -> None:
        """Handle an incoming Slack message event."""
        if self._on_message is None:
            return

        # Skip bot messages
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        text = event.get("text", "")
        if not text.strip():
            return

        user_id = event.get("user", "unknown")
        channel_id = event.get("channel", "unknown")
        thread_ts = event.get("thread_ts") or event.get("ts", "")

        # Determine chat type
        # Channel types: C = public, G = private, D = DM
        is_dm = channel_id.startswith("D")
        chat_type = "direct" if is_dm else "group"

        message = InboundMessage.create(
            channel="slack",
            sender_id=user_id,
            sender_name=user_id,  # Would need users.info API call for real name
            content=text,
            chat_type=chat_type,
            group_id=channel_id if not is_dm else None,
            metadata={
                "thread_ts": thread_ts,
                "channel_id": channel_id,
                "ts": event.get("ts", ""),
            },
        )
        # Use the thread_ts as reply_to_id so responses thread correctly
        message.reply_to_id = thread_ts

        self._status.message_count_in += 1
        self._status.last_inbound = datetime.now(UTC)

        await self._on_message(message)
