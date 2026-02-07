"""
Signal Channel Provider.

Implements the ChannelProvider interface for Signal messaging
via the signal-cli daemon.
"""

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
from .daemon import SignalDaemon
from .format import format_for_signal, truncate_message

logger = logging.getLogger(__name__)


class SignalProvider(ChannelProvider):
    """Signal channel provider via signal-cli."""

    name = "signal"
    display_name = "Signal"

    def __init__(self):
        self._daemon: SignalDaemon | None = None
        self._on_message: MessageCallback | None = None
        self._config: dict[str, Any] = {}
        self._status = ChannelStatus(channel="signal")

    async def start(self, config: Any, on_message: MessageCallback, **kwargs) -> None:
        """Start the Signal provider."""
        if isinstance(config, dict):
            self._config = config
        else:
            self._config = {}

        account = self._config.get("account")
        if not account:
            raise ChannelConfigError(
                "Signal requires an 'account' (phone number) in config",
                channel="signal",
            )

        cli_path = self._config.get("cli_path", "signal-cli")
        self._on_message = on_message

        self._daemon = SignalDaemon(
            cli_path=cli_path,
            account=account,
        )

        try:
            await self._daemon.start(on_message=self._handle_raw_message)
        except RuntimeError as e:
            raise ChannelConfigError(str(e), channel="signal")

        self._status.running = True
        self._status.last_start = datetime.now(UTC)
        logger.info("Signal provider started (account=%s)", account)

    async def stop(self) -> None:
        """Stop the Signal provider."""
        if self._daemon:
            await self._daemon.stop()
            self._daemon = None

        self._status.running = False
        self._status.last_stop = datetime.now(UTC)
        logger.info("Signal provider stopped")

    async def send(self, message: OutboundMessage) -> SendResult:
        """Send a Signal message."""
        if not self._daemon:
            return SendResult(success=False, error="Signal daemon not running")

        try:
            text = format_for_signal(message.content)
            text = truncate_message(text)

            # Check if target is a group ID or phone number
            is_group = message.metadata.get("is_group", False)

            if is_group:
                success = await self._daemon.send_group_message(
                    group_id=message.target,
                    message=text,
                )
            else:
                success = await self._daemon.send_message(
                    recipient=message.target,
                    message=text,
                )

            if success:
                self._status.message_count_out += 1
                self._status.last_outbound = datetime.now(UTC)
                return SendResult(success=True)
            else:
                return SendResult(success=False, error="Failed to send Signal message")

        except Exception as e:
            self._status.last_error = str(e)
            logger.error("Signal send error: %s", e)
            return SendResult(success=False, error=str(e))

    async def check_health(self) -> bool:
        """Check if Signal daemon is running."""
        if not self._daemon or not self._daemon._process:
            self._status.healthy = False
            return False

        # Check if process is still alive
        is_alive = self._daemon._process.returncode is None
        self._status.healthy = is_alive
        return is_alive

    def get_status(self) -> ChannelStatus:
        """Get channel status."""
        return self._status

    async def _handle_raw_message(self, data: dict) -> None:
        """Convert raw Signal data to InboundMessage and dispatch."""
        if self._on_message is None:
            return

        sender = data["sender"]
        allowed_users = self._config.get("allowed_users", [])

        # Check allowlist (empty = allow all)
        if allowed_users and sender not in allowed_users:
            logger.debug("Signal message from %s rejected (not in allowlist)", sender)
            return

        group_id = data.get("group_id")
        chat_type = "group" if group_id else "direct"

        # Check group allowlist
        if group_id:
            allowed_groups = self._config.get("allowed_groups", [])
            if allowed_groups and group_id not in allowed_groups:
                logger.debug("Signal group %s rejected (not in allowlist)", group_id)
                return

        message = InboundMessage.create(
            channel="signal",
            sender_id=sender,
            sender_name=sender,
            content=data["text"],
            chat_type=chat_type,
            group_id=group_id,
            group_name=data.get("group_name"),
        )

        self._status.message_count_in += 1
        self._status.last_inbound = datetime.now(UTC)

        await self._on_message(message)
