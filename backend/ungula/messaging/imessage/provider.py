"""
iMessage Channel Provider.

Implements the ChannelProvider interface for iMessage on macOS.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
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
from .monitor import IMessageMonitor
from .probe import probe_imessage
from .sender import send_via_applescript, send_via_cli

logger = logging.getLogger(__name__)


class IMessageProvider(ChannelProvider):
    """iMessage channel provider (macOS only)."""

    name = "imessage"
    display_name = "iMessage"

    def __init__(self):
        self._monitor: IMessageMonitor | None = None
        self._on_message: MessageCallback | None = None
        self._config: dict[str, Any] = {}
        self._status = ChannelStatus(channel="imessage")
        self._cli_path = "imsg"
        self._use_cli = False

    async def start(self, config: Any, on_message: MessageCallback, **kwargs) -> None:
        """Start the iMessage provider."""
        if isinstance(config, dict):
            self._config = config
        else:
            self._config = {}

        self._cli_path = self._config.get("cli_path", "imsg")
        self._on_message = on_message

        # Probe availability
        probe = probe_imessage(self._cli_path)
        if not probe["available"]:
            raise ChannelConfigError(
                f"iMessage not available: {probe['reason']}",
                channel="imessage",
            )

        self._use_cli = probe["has_cli"]
        db_path = Path(probe["db_path"])

        # Start monitor
        self._monitor = IMessageMonitor(
            db_path=db_path,
            on_message=self._handle_raw_message,
        )
        await self._monitor.start()

        self._status.running = True
        self._status.last_start = datetime.now(UTC)
        logger.info("iMessage provider started (cli=%s)", self._use_cli)

    async def stop(self) -> None:
        """Stop the iMessage provider."""
        if self._monitor:
            await self._monitor.stop()
            self._monitor = None

        self._status.running = False
        self._status.last_stop = datetime.now(UTC)
        logger.info("iMessage provider stopped")

    async def send(self, message: OutboundMessage) -> SendResult:
        """Send an iMessage."""
        try:
            if self._use_cli:
                success = await send_via_cli(
                    target=message.target,
                    content=message.content,
                    cli_path=self._cli_path,
                )
            else:
                success = await send_via_applescript(
                    target=message.target,
                    content=message.content,
                )

            if success:
                self._status.message_count_out += 1
                self._status.last_outbound = datetime.now(UTC)
                return SendResult(success=True)
            else:
                return SendResult(success=False, error="Failed to send iMessage")

        except Exception as e:
            self._status.last_error = str(e)
            return SendResult(success=False, error=str(e))

    async def check_health(self) -> bool:
        """Check if iMessage is healthy."""
        probe = probe_imessage(self._cli_path)
        self._status.healthy = probe["available"]
        return probe["available"]

    def get_status(self) -> ChannelStatus:
        """Get channel status."""
        return self._status

    async def _handle_raw_message(self, data: dict) -> None:
        """Convert raw iMessage data to InboundMessage and dispatch."""
        if self._on_message is None:
            return

        # Check allowlist
        dm_policy = self._config.get("dm_policy", "open")
        dm_allowlist = self._config.get("dm_allowlist", [])

        sender = data["sender"]
        if dm_policy == "allowlist" and sender not in dm_allowlist:
            logger.debug("iMessage from %s rejected (not in allowlist)", sender)
            return

        message = InboundMessage.create(
            channel="imessage",
            sender_id=sender,
            sender_name=sender,  # iMessage doesn't easily provide names
            content=data["text"],
        )

        self._status.message_count_in += 1
        self._status.last_inbound = datetime.now(UTC)

        await self._on_message(message)
