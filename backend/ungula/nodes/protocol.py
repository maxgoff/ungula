"""
Node WebSocket protocol message types.

Defines the structured message types exchanged between the gateway (hub)
and companion device nodes.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeEvent(str, Enum):
    """Events in the node protocol."""

    # Node → Gateway
    AUTH = "node.auth"
    REGISTER_CAPABILITIES = "node.register_capabilities"
    RESULT = "node.result"
    HEARTBEAT = "node.heartbeat"

    # Node → Gateway: pairing
    PAIR_REQUEST = "node.pair.request"

    # Node → Gateway: event reporting
    NODE_EVENT = "node.event"

    # Gateway → Node
    INVOKE = "node.invoke"
    AUTH_OK = "node.auth.ok"
    AUTH_ERROR = "node.auth.error"
    ERROR = "node.error"

    # Gateway → Node: pairing
    PAIR_PENDING = "node.pair.pending"
    PAIR_APPROVED = "node.pair.approved"
    PAIR_REJECTED = "node.pair.rejected"


@dataclass
class NodeMessage:
    """A message in the node protocol."""

    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"event": self.event, "data": self.data}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NodeMessage":
        return cls(event=d.get("event", ""), data=d.get("data", {}))


def auth_message(token: str, platform: str, capabilities: list[str]) -> NodeMessage:
    """Create a node.auth message."""
    return NodeMessage(
        event=NodeEvent.AUTH,
        data={"token": token, "platform": platform, "capabilities": capabilities},
    )


def auth_ok_message(node_id: str) -> NodeMessage:
    """Create a node.auth.ok response."""
    return NodeMessage(event=NodeEvent.AUTH_OK, data={"node_id": node_id})


def auth_error_message(message: str) -> NodeMessage:
    """Create a node.auth.error response."""
    return NodeMessage(event=NodeEvent.AUTH_ERROR, data={"message": message})


def invoke_message(command: str, args: dict[str, Any], request_id: str) -> NodeMessage:
    """Create a node.invoke command."""
    return NodeMessage(
        event=NodeEvent.INVOKE,
        data={"command": command, "args": args, "request_id": request_id},
    )


def result_message(request_id: str, success: bool, output: str, data: dict[str, Any] | None = None) -> NodeMessage:
    """Create a node.result response."""
    return NodeMessage(
        event=NodeEvent.RESULT,
        data={
            "request_id": request_id,
            "success": success,
            "output": output,
            **({"data": data} if data else {}),
        },
    )


def heartbeat_message() -> NodeMessage:
    """Create a node.heartbeat message."""
    return NodeMessage(event=NodeEvent.HEARTBEAT, data={})


def error_message(message: str) -> NodeMessage:
    """Create a node.error message."""
    return NodeMessage(event=NodeEvent.ERROR, data={"message": message})


# --- Pairing protocol messages ---

def pair_request_message(name: str, platform: str, capabilities: list[str], metadata: dict[str, Any] | None = None) -> NodeMessage:
    """Create a node.pair.request message (Node → Gateway)."""
    return NodeMessage(
        event=NodeEvent.PAIR_REQUEST,
        data={
            "name": name,
            "platform": platform,
            "capabilities": capabilities,
            **({"metadata": metadata} if metadata else {}),
        },
    )


def pair_pending_message(node_id: str) -> NodeMessage:
    """Create a node.pair.pending response (Gateway → Node)."""
    return NodeMessage(
        event=NodeEvent.PAIR_PENDING,
        data={"node_id": node_id, "message": "Waiting for operator approval"},
    )


def pair_approved_message(node_id: str, token: str) -> NodeMessage:
    """Create a node.pair.approved response (Gateway → Node)."""
    return NodeMessage(
        event=NodeEvent.PAIR_APPROVED,
        data={"node_id": node_id, "token": token},
    )


def pair_rejected_message(node_id: str) -> NodeMessage:
    """Create a node.pair.rejected response (Gateway → Node)."""
    return NodeMessage(
        event=NodeEvent.PAIR_REJECTED,
        data={"node_id": node_id, "message": "Pairing request rejected"},
    )


# --- Node event message ---

def node_event_message(event_type: str, payload: dict[str, Any] | None = None) -> NodeMessage:
    """Create a node.event message (Node → Gateway)."""
    return NodeMessage(
        event=NodeEvent.NODE_EVENT,
        data={
            "event_type": event_type,
            **({"payload": payload} if payload else {}),
        },
    )
