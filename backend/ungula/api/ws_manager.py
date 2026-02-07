"""
WebSocket Connection Manager.

Manages WebSocket connections per user/conversation, supports
broadcasting events like chat chunks, inbox notifications, and
channel status updates.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class WSConnection:
    """A tracked WebSocket connection."""

    websocket: WebSocket
    user_id: UUID | None = None
    conversation_id: UUID | None = None


class ConnectionManager:
    """
    Manages active WebSocket connections.

    Supports sending messages to specific users, conversations,
    or broadcasting to all connected clients.
    """

    def __init__(self, max_connections: int = 50):
        self.max_connections = max_connections
        self._connections: dict[str, WSConnection] = {}  # connection_id -> WSConnection
        self._user_connections: dict[str, set[str]] = {}  # user_id -> set of connection_ids
        self._conversation_connections: dict[str, set[str]] = {}  # conv_id -> set of connection_ids
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)

    async def connect(
        self,
        connection_id: str,
        websocket: WebSocket,
        user_id: UUID | None = None,
    ) -> bool:
        """
        Accept and register a WebSocket connection.

        Returns False if max connections exceeded.
        """
        async with self._lock:
            if len(self._connections) >= self.max_connections:
                logger.warning(
                    "Max WebSocket connections reached (%d), rejecting",
                    self.max_connections,
                )
                return False

            await websocket.accept()

            conn = WSConnection(websocket=websocket, user_id=user_id)
            self._connections[connection_id] = conn

            if user_id:
                uid_str = str(user_id)
                if uid_str not in self._user_connections:
                    self._user_connections[uid_str] = set()
                self._user_connections[uid_str].add(connection_id)

            logger.info(
                "WebSocket connected: %s (user=%s, total=%d)",
                connection_id,
                user_id,
                len(self._connections),
            )
            return True

    async def disconnect(self, connection_id: str) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            conn = self._connections.pop(connection_id, None)
            if conn is None:
                return

            # Clean up user mapping
            if conn.user_id:
                uid_str = str(conn.user_id)
                if uid_str in self._user_connections:
                    self._user_connections[uid_str].discard(connection_id)
                    if not self._user_connections[uid_str]:
                        del self._user_connections[uid_str]

            # Clean up conversation mapping
            if conn.conversation_id:
                cid_str = str(conn.conversation_id)
                if cid_str in self._conversation_connections:
                    self._conversation_connections[cid_str].discard(connection_id)
                    if not self._conversation_connections[cid_str]:
                        del self._conversation_connections[cid_str]

            logger.info(
                "WebSocket disconnected: %s (total=%d)",
                connection_id,
                len(self._connections),
            )

    async def subscribe_conversation(
        self, connection_id: str, conversation_id: UUID
    ) -> None:
        """Subscribe a connection to conversation events."""
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return

            # Unsubscribe from previous conversation
            if conn.conversation_id:
                old_cid = str(conn.conversation_id)
                if old_cid in self._conversation_connections:
                    self._conversation_connections[old_cid].discard(connection_id)

            conn.conversation_id = conversation_id
            cid_str = str(conversation_id)
            if cid_str not in self._conversation_connections:
                self._conversation_connections[cid_str] = set()
            self._conversation_connections[cid_str].add(connection_id)

    async def _send_json(self, connection_id: str, data: dict) -> bool:
        """Send JSON to a specific connection. Returns False if failed."""
        conn = self._connections.get(connection_id)
        if conn is None:
            return False
        try:
            await conn.websocket.send_json(data)
            return True
        except Exception:
            # Connection likely closed
            await self.disconnect(connection_id)
            return False

    async def send_to_user(self, user_id: UUID, event: str, data: dict) -> int:
        """Send an event to all connections for a user. Returns count sent."""
        uid_str = str(user_id)
        connection_ids = self._user_connections.get(uid_str, set()).copy()
        message = {"event": event, "data": data}
        sent = 0
        for cid in connection_ids:
            if await self._send_json(cid, message):
                sent += 1
        return sent

    async def send_to_conversation(
        self, conversation_id: UUID, event: str, data: dict
    ) -> int:
        """Send an event to all connections subscribed to a conversation."""
        cid_str = str(conversation_id)
        connection_ids = self._conversation_connections.get(cid_str, set()).copy()
        message = {"event": event, "data": data}
        sent = 0
        for cid in connection_ids:
            if await self._send_json(cid, message):
                sent += 1
        return sent

    async def broadcast(self, event: str, data: dict) -> int:
        """Send an event to all connected clients."""
        message = {"event": event, "data": data}
        connection_ids = list(self._connections.keys())
        sent = 0
        for cid in connection_ids:
            if await self._send_json(cid, message):
                sent += 1
        return sent
