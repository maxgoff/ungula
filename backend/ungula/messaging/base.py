"""
Channel Provider Base Classes.

Defines the abstract interface for messaging channel integrations.
All channel providers (Discord, iMessage, etc.) must implement these interfaces.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable


def generate_message_id() -> str:
    """Generate a unique message ID."""
    return str(uuid.uuid4())


@dataclass
class InboundMessage:
    """
    Normalized inbound message from any channel.

    All channel providers normalize their messages to this format
    before dispatching to the message router.
    """

    id: str
    channel: str  # "discord" | "imessage"
    sender_id: str
    sender_name: str
    content: str
    timestamp: datetime
    chat_type: str = "direct"  # "direct" | "group"
    group_id: str | None = None
    group_name: str | None = None
    reply_to_id: str | None = None
    media_urls: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        channel: str,
        sender_id: str,
        sender_name: str,
        content: str,
        **kwargs: Any,
    ) -> "InboundMessage":
        """Create an InboundMessage with auto-generated ID and timestamp."""
        return cls(
            id=generate_message_id(),
            channel=channel,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            timestamp=datetime.now(UTC),
            **kwargs,
        )


@dataclass
class OutboundMessage:
    """
    Message to send through a channel.

    Used by the message router to send responses back to the source channel.
    """

    channel: str  # "discord" | "imessage"
    target: str  # Channel-specific target (channel ID, phone number, etc.)
    content: str
    reply_to_id: str | None = None
    media_urls: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SendResult:
    """Result of sending a message through a channel."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelStatus:
    """Runtime status of a channel provider."""

    channel: str
    healthy: bool = True
    running: bool = False
    last_start: datetime | None = None
    last_stop: datetime | None = None
    last_error: str | None = None
    last_inbound: datetime | None = None
    last_outbound: datetime | None = None
    message_count_in: int = 0
    message_count_out: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "channel": self.channel,
            "healthy": self.healthy,
            "running": self.running,
            "last_start": self.last_start.isoformat() if self.last_start else None,
            "last_stop": self.last_stop.isoformat() if self.last_stop else None,
            "last_error": self.last_error,
            "last_inbound": self.last_inbound.isoformat() if self.last_inbound else None,
            "last_outbound": self.last_outbound.isoformat() if self.last_outbound else None,
            "message_count_in": self.message_count_in,
            "message_count_out": self.message_count_out,
        }


# Type alias for message callback
MessageCallback = Callable[[InboundMessage], Awaitable[None]]


class ChannelProvider(ABC):
    """
    Abstract base class for messaging channel providers.

    Each channel (Discord, iMessage, etc.) implements this interface
    to integrate with the Ungula messaging system.
    """

    name: str  # "discord", "imessage", etc.
    display_name: str  # "Discord", "iMessage", etc.

    @abstractmethod
    async def start(
        self,
        config: Any,
        on_message: MessageCallback,
    ) -> None:
        """
        Start the channel monitor.

        Args:
            config: Channel-specific configuration object.
            on_message: Callback to invoke when a message is received.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel monitor and clean up resources."""
        pass

    @abstractmethod
    async def send(self, message: OutboundMessage) -> SendResult:
        """
        Send a message through this channel.

        Args:
            message: The outbound message to send.

        Returns:
            SendResult indicating success/failure.
        """
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """
        Check if the channel is healthy and operational.

        Returns:
            True if healthy, False otherwise.
        """
        pass

    @abstractmethod
    def get_status(self) -> ChannelStatus:
        """
        Get the current status of this channel.

        Returns:
            ChannelStatus with runtime information.
        """
        pass

    async def typing_start(self, target: str) -> None:
        """
        Send a typing indicator to the target.

        Default implementation is a no-op. Override in providers
        that support typing indicators (Discord, Slack, Telegram).
        """
        pass

    async def react(self, channel_id: str, message_id: str, emoji: str) -> None:
        """
        Add a reaction to a message.

        Default implementation is a no-op. Override in providers
        that support reactions (Discord, Slack).
        """
        pass


class ChannelError(Exception):
    """Base exception for channel errors."""

    def __init__(self, message: str, channel: str, retryable: bool = False):
        super().__init__(message)
        self.channel = channel
        self.retryable = retryable


class ChannelConnectionError(ChannelError):
    """Error connecting to a channel service."""

    def __init__(self, message: str, channel: str):
        super().__init__(message, channel, retryable=True)


class ChannelSendError(ChannelError):
    """Error sending a message through a channel."""

    def __init__(self, message: str, channel: str, retryable: bool = True):
        super().__init__(message, channel, retryable=retryable)


class ChannelConfigError(ChannelError):
    """Error in channel configuration."""

    def __init__(self, message: str, channel: str):
        super().__init__(message, channel, retryable=False)
