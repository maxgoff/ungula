"""
Node pairing store.

Manages pending pair requests with TTL and approval queue.
"""

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PairRequest:
    """A pending pairing request from a node."""

    node_id: str
    name: str
    platform: str
    capabilities: list[str]
    token: str  # The pairing token (plaintext, shown once)
    created_at: float = field(default_factory=time.time)
    websocket: Any | None = None  # WebSocket ref for node-initiated pairing

    def is_expired(self, ttl: int) -> bool:
        return (time.time() - self.created_at) > ttl


class NodePairingStore:
    """Manages pending node pairing requests."""

    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._pending: dict[str, PairRequest] = {}  # keyed by node_id

    def create_request(self, node_id: str, name: str, platform: str, capabilities: list[str]) -> PairRequest:
        """Create a new pairing request. Returns the request with a one-time token."""
        self._cleanup_expired()

        token = secrets.token_urlsafe(32)
        request = PairRequest(
            node_id=node_id,
            name=name,
            platform=platform,
            capabilities=capabilities,
            token=token,
        )
        self._pending[node_id] = request
        logger.info("Created pairing request for node %s (%s)", name, node_id)
        return request

    def create_node_initiated_request(
        self,
        node_id: str,
        name: str,
        platform: str,
        capabilities: list[str],
        websocket: Any | None = None,
    ) -> PairRequest:
        """Create a node-initiated pairing request with WebSocket reference."""
        self._cleanup_expired()

        token = secrets.token_urlsafe(32)
        request = PairRequest(
            node_id=node_id,
            name=name,
            platform=platform,
            capabilities=capabilities,
            token=token,
            websocket=websocket,
        )
        self._pending[node_id] = request
        logger.info("Created node-initiated pairing request for %s (%s)", name, node_id)
        return request

    def get_pending(self) -> list[PairRequest]:
        """Get all non-expired pending requests."""
        self._cleanup_expired()
        return list(self._pending.values())

    def get_request(self, node_id: str) -> PairRequest | None:
        """Get a specific pending request."""
        self._cleanup_expired()
        return self._pending.get(node_id)

    def approve(self, node_id: str) -> PairRequest | None:
        """Approve a pairing request. Returns the request (with token) or None."""
        request = self._pending.pop(node_id, None)
        if request and not request.is_expired(self.ttl):
            logger.info("Approved pairing for node %s", node_id)
            return request
        return None

    def reject(self, node_id: str) -> bool:
        """Reject a pairing request."""
        removed = self._pending.pop(node_id, None)
        if removed:
            logger.info("Rejected pairing for node %s", node_id)
            return True
        return False

    def _cleanup_expired(self) -> None:
        """Remove expired requests."""
        expired = [nid for nid, req in self._pending.items() if req.is_expired(self.ttl)]
        for nid in expired:
            del self._pending[nid]
