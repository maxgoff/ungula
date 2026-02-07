"""
Event types and models for the event bus.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class EventType(str, Enum):
    """Known event types."""

    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    WEBHOOK_RECEIVED = "webhook.received"
    CRON_FIRED = "cron.fired"
    TOOL_EXECUTED = "tool.executed"
    CONVERSATION_CREATED = "conversation.created"
    NODE_CONNECTED = "node.connected"
    NODE_DISCONNECTED = "node.disconnected"


class ActionType(str, Enum):
    """Types of actions that rules can trigger."""

    RUN_AGENT = "run_agent"
    EXECUTE_TOOL = "execute_tool"
    SEND_MESSAGE = "send_message"
    CALL_WEBHOOK = "call_webhook"
    LOG = "log"


@dataclass
class Event:
    """An event emitted on the bus."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4())[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class EventRule:
    """A rule that maps an event type + optional filters to an action."""

    id: str = field(default_factory=lambda: str(uuid4())[:8])
    name: str = ""
    event_type: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    action: str = ""  # ActionType value
    action_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    fire_count: int = 0
    last_fired: datetime | None = None
