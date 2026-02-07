"""
Node registry.

Tracks connected nodes, their capabilities, and online/offline state.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ConnectedNode:
    """A currently connected node."""

    node_id: str
    name: str
    platform: str
    capabilities: list[str]
    websocket: WebSocket
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    # Extended metadata (WI 4)
    declared_commands: list[str] = field(default_factory=list)
    device_family: str = ""
    version: str = ""
    os_version: str = ""
    path_env: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.node_id,
            "name": self.name,
            "platform": self.platform,
            "capabilities": self.capabilities,
            "status": "online",
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "declared_commands": self.declared_commands,
            "device_family": self.device_family,
            "version": self.version,
            "os_version": self.os_version,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


class NodeRegistry:
    """Tracks connected nodes and their capabilities."""

    def __init__(self, max_nodes: int = 10):
        self.max_nodes = max_nodes
        self._nodes: dict[str, ConnectedNode] = {}

    def register(
        self,
        node_id: str,
        name: str,
        platform: str,
        capabilities: list[str],
        websocket: WebSocket,
        declared_commands: list[str] | None = None,
        device_family: str = "",
        version: str = "",
        os_version: str = "",
        path_env: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ConnectedNode:
        """Register a connected node."""
        if len(self._nodes) >= self.max_nodes and node_id not in self._nodes:
            raise RuntimeError(f"Max nodes ({self.max_nodes}) reached")

        # If no declared_commands, derive from capabilities using legacy map
        if declared_commands is None:
            from .policy import COMMAND_CAPABILITY_MAP
            declared_commands = [
                cmd for cmd, cap in COMMAND_CAPABILITY_MAP.items()
                if cap in capabilities
            ]

        node = ConnectedNode(
            node_id=node_id,
            name=name,
            platform=platform,
            capabilities=capabilities,
            websocket=websocket,
            declared_commands=declared_commands,
            device_family=device_family,
            version=version,
            os_version=os_version,
            path_env=path_env,
            metadata=metadata or {},
        )
        self._nodes[node_id] = node
        logger.info("Node registered: %s (%s, %s)", name, platform, node_id)
        return node

    def unregister(self, node_id: str) -> ConnectedNode | None:
        """Unregister a node (e.g., on disconnect)."""
        node = self._nodes.pop(node_id, None)
        if node:
            logger.info("Node unregistered: %s (%s)", node.name, node_id)
        return node

    def get(self, node_id: str) -> ConnectedNode | None:
        return self._nodes.get(node_id)

    def get_by_capability(self, capability: str) -> list[ConnectedNode]:
        """Get all online nodes that have a specific capability."""
        return [n for n in self._nodes.values() if capability in n.capabilities]

    def find_capable(self, capability: str) -> ConnectedNode | None:
        """Find the first online node capable of a given capability."""
        nodes = self.get_by_capability(capability)
        return nodes[0] if nodes else None

    def list_online(self) -> list[dict[str, Any]]:
        return [n.to_dict() for n in self._nodes.values()]

    def update_heartbeat(self, node_id: str) -> bool:
        """Update last heartbeat time."""
        node = self._nodes.get(node_id)
        if node:
            node.last_heartbeat = datetime.utcnow()
            return True
        return False

    def get_stale_nodes(self, timeout_seconds: int) -> list[ConnectedNode]:
        """Get nodes whose last heartbeat is older than timeout_seconds."""
        now = datetime.utcnow()
        stale = []
        for node in self._nodes.values():
            elapsed = (now - node.last_heartbeat).total_seconds()
            if elapsed > timeout_seconds:
                stale.append(node)
        return stale

    @property
    def online_count(self) -> int:
        return len(self._nodes)
