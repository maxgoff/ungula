"""
Channel Provider Registry.

Manages multiple messaging channel providers with lifecycle management,
health tracking, and message routing.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .base import (
    ChannelError,
    ChannelProvider,
    ChannelStatus,
    InboundMessage,
    MessageCallback,
    OutboundMessage,
    SendResult,
)

logger = logging.getLogger(__name__)


@dataclass
class ChannelRegistry:
    """
    Registry for messaging channel providers with lifecycle management.

    Manages multiple channels, tracks their health, and provides
    unified message sending across channels.
    """

    channels: dict[str, ChannelProvider] = field(default_factory=dict)
    status: dict[str, ChannelStatus] = field(default_factory=dict)
    _tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    _on_message: MessageCallback | None = None
    _running: bool = False

    def register(self, provider: ChannelProvider) -> None:
        """
        Register a channel provider.

        Args:
            provider: The channel provider to register.
        """
        self.channels[provider.name] = provider
        self.status[provider.name] = ChannelStatus(channel=provider.name)
        logger.info("Registered channel provider: %s", provider.name)

    def unregister(self, name: str) -> None:
        """
        Unregister a channel provider.

        Args:
            name: The name of the channel to unregister.
        """
        if name in self.channels:
            del self.channels[name]
        if name in self.status:
            del self.status[name]
        if name in self._tasks:
            task = self._tasks.pop(name)
            if not task.done():
                task.cancel()
        logger.info("Unregistered channel provider: %s", name)

    def get(self, name: str) -> ChannelProvider | None:
        """
        Get a channel provider by name.

        Args:
            name: The channel name.

        Returns:
            The channel provider or None if not found.
        """
        return self.channels.get(name)

    def list_channels(self) -> list[str]:
        """
        List all registered channel names.

        Returns:
            List of channel names.
        """
        return list(self.channels.keys())

    def is_running(self, name: str) -> bool:
        """
        Check if a channel is currently running.

        Args:
            name: The channel name.

        Returns:
            True if running, False otherwise.
        """
        status = self.status.get(name)
        return status.running if status else False

    async def start_all(self, on_message: MessageCallback) -> None:
        """
        Start all registered channel monitors.

        Args:
            on_message: Callback to invoke when a message is received.
        """
        self._on_message = on_message
        self._running = True

        for name in self.channels:
            try:
                await self.start_channel(name)
            except Exception as e:
                logger.error("Failed to start channel %s: %s", name, e)

    async def stop_all(self) -> None:
        """Stop all running channel monitors."""
        self._running = False

        for name in list(self._tasks.keys()):
            try:
                await self.stop_channel(name)
            except Exception as e:
                logger.error("Failed to stop channel %s: %s", name, e)

        self._on_message = None

    async def start_channel(self, name: str, config: Any = None) -> None:
        """
        Start a specific channel monitor.

        Args:
            name: The channel name.
            config: Optional channel-specific configuration.
        """
        provider = self.channels.get(name)
        if not provider:
            raise ChannelError(f"Unknown channel: {name}", name)

        if name in self._tasks and not self._tasks[name].done():
            logger.warning("Channel %s is already running", name)
            return

        if not self._on_message:
            raise ChannelError("No message callback registered", name)

        try:
            # Start the provider with its config
            await provider.start(config, self._on_message)
            self.status[name].running = True
            self.status[name].last_start = datetime.now(UTC)
            self.status[name].last_error = None
            logger.info("Started channel: %s", name)
        except Exception as e:
            self.status[name].running = False
            self.status[name].last_error = str(e)
            logger.error("Failed to start channel %s: %s", name, e)
            raise

    async def stop_channel(self, name: str) -> None:
        """
        Stop a specific channel monitor.

        Args:
            name: The channel name.
        """
        provider = self.channels.get(name)
        if not provider:
            logger.warning("Unknown channel: %s", name)
            return

        # Cancel the task if running
        if name in self._tasks:
            task = self._tasks.pop(name)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        try:
            await provider.stop()
            self.status[name].running = False
            self.status[name].last_stop = datetime.now(UTC)
            logger.info("Stopped channel: %s", name)
        except Exception as e:
            self.status[name].last_error = str(e)
            logger.error("Error stopping channel %s: %s", name, e)

    async def send(self, message: OutboundMessage) -> SendResult:
        """
        Send a message through the appropriate channel.

        Args:
            message: The outbound message.

        Returns:
            SendResult indicating success/failure.
        """
        provider = self.channels.get(message.channel)
        if not provider:
            return SendResult(
                success=False,
                error=f"Unknown channel: {message.channel}",
            )

        if not self.status.get(message.channel, ChannelStatus(channel=message.channel)).running:
            return SendResult(
                success=False,
                error=f"Channel not running: {message.channel}",
            )

        try:
            result = await provider.send(message)
            if result.success:
                self.status[message.channel].last_outbound = datetime.now(UTC)
                self.status[message.channel].message_count_out += 1
            return result
        except Exception as e:
            logger.error("Failed to send message via %s: %s", message.channel, e)
            return SendResult(success=False, error=str(e))

    async def check_health(self, name: str | None = None) -> dict[str, bool]:
        """
        Check health of channels.

        Args:
            name: Specific channel to check, or None for all.

        Returns:
            Dictionary mapping channel names to health status.
        """
        channels_to_check = [name] if name else list(self.channels.keys())
        results = {}

        async def check_one(channel_name: str) -> tuple[str, bool]:
            provider = self.channels.get(channel_name)
            if not provider:
                return channel_name, False
            try:
                healthy = await provider.check_health()
                self.status[channel_name].healthy = healthy
                return channel_name, healthy
            except Exception as e:
                logger.warning("Health check failed for %s: %s", channel_name, e)
                self.status[channel_name].healthy = False
                return channel_name, False

        checks = await asyncio.gather(*[check_one(c) for c in channels_to_check])
        results = dict(checks)
        return results

    def get_status(self) -> dict[str, dict[str, Any]]:
        """
        Get status of all channels.

        Returns:
            Dictionary mapping channel names to status dictionaries.
        """
        result = {}
        for name, status in self.status.items():
            result[name] = status.to_dict()
        return result

    def record_inbound(self, channel: str) -> None:
        """
        Record an inbound message for statistics.

        Args:
            channel: The channel name.
        """
        if channel in self.status:
            self.status[channel].last_inbound = datetime.now(UTC)
            self.status[channel].message_count_in += 1

    async def close(self) -> None:
        """Close all channels and clean up."""
        await self.stop_all()
        self.channels.clear()
        self.status.clear()
        logger.info("Channel registry closed")
