"""
Ungula Messaging Module.

Provides channel integrations for Discord, iMessage, and other messaging platforms.
"""

from .base import (
    ChannelConfigError,
    ChannelConnectionError,
    ChannelError,
    ChannelProvider,
    ChannelSendError,
    ChannelStatus,
    InboundMessage,
    MessageCallback,
    OutboundMessage,
    SendResult,
)
from .registry import ChannelRegistry

__all__ = [
    # Base classes
    "ChannelProvider",
    "ChannelRegistry",
    "ChannelStatus",
    # Message types
    "InboundMessage",
    "OutboundMessage",
    "SendResult",
    "MessageCallback",
    # Exceptions
    "ChannelError",
    "ChannelConnectionError",
    "ChannelSendError",
    "ChannelConfigError",
]
