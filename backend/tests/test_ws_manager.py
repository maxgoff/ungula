"""
Tests for the WebSocket ConnectionManager.

Covers connection lifecycle (connect/disconnect), user and conversation
subscription tracking, targeted and broadcast messaging, connection limits,
and error handling for failed send operations.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from ungula.api.ws_manager import ConnectionManager, WSConnection


# ---------------------------------------------------------------------------
# MockWebSocket
# ---------------------------------------------------------------------------


class MockWebSocket:
    """
    Minimal mock of FastAPI's WebSocket for testing the ConnectionManager.

    Records all calls to accept() and send_json() for assertion.
    """

    def __init__(self, *, accept_raises: bool = False, send_raises: bool = False):
        self._accept_raises = accept_raises
        self._send_raises = send_raises
        self.accepted = False
        self.sent_messages: list[dict] = []
        self.accept_call_count = 0
        self.send_call_count = 0

    async def accept(self) -> None:
        self.accept_call_count += 1
        if self._accept_raises:
            raise RuntimeError("accept failed")
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        self.send_call_count += 1
        if self._send_raises:
            raise RuntimeError("send failed")
        self.sent_messages.append(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws(**kwargs) -> MockWebSocket:
    """Create a MockWebSocket with optional overrides."""
    return MockWebSocket(**kwargs)


def _make_user_id() -> UUID:
    """Generate a fresh UUID for a user."""
    return uuid4()


# ---------------------------------------------------------------------------
# WSConnection dataclass
# ---------------------------------------------------------------------------


class TestWSConnection:
    """Tests for the WSConnection dataclass."""

    def test_default_fields(self):
        """WSConnection defaults user_id and conversation_id to None."""
        ws = _make_ws()
        conn = WSConnection(websocket=ws)
        assert conn.websocket is ws
        assert conn.user_id is None
        assert conn.conversation_id is None

    def test_with_user_id(self):
        """WSConnection can be created with a user_id."""
        uid = _make_user_id()
        conn = WSConnection(websocket=_make_ws(), user_id=uid)
        assert conn.user_id == uid

    def test_with_conversation_id(self):
        """WSConnection can be created with a conversation_id."""
        cid = uuid4()
        conn = WSConnection(websocket=_make_ws(), conversation_id=cid)
        assert conn.conversation_id == cid


# ---------------------------------------------------------------------------
# ConnectionManager: basic properties
# ---------------------------------------------------------------------------


class TestManagerBasics:
    """Tests for ConnectionManager initialization and properties."""

    def test_default_max_connections(self):
        """Default max_connections is 50."""
        mgr = ConnectionManager()
        assert mgr.max_connections == 50

    def test_custom_max_connections(self):
        """max_connections can be set via constructor."""
        mgr = ConnectionManager(max_connections=10)
        assert mgr.max_connections == 10

    def test_active_count_starts_at_zero(self):
        """active_count is 0 when no connections exist."""
        mgr = ConnectionManager()
        assert mgr.active_count == 0

    def test_internal_structures_empty(self):
        """Internal tracking dicts start empty."""
        mgr = ConnectionManager()
        assert len(mgr._connections) == 0
        assert len(mgr._user_connections) == 0
        assert len(mgr._conversation_connections) == 0


# ---------------------------------------------------------------------------
# ConnectionManager: connect
# ---------------------------------------------------------------------------


class TestConnect:
    """Tests for the connect() method."""

    async def test_connect_returns_true(self):
        """connect() returns True on successful connection."""
        mgr = ConnectionManager()
        ws = _make_ws()
        result = await mgr.connect("conn-1", ws)
        assert result is True

    async def test_connect_accepts_websocket(self):
        """connect() calls websocket.accept()."""
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect("conn-1", ws)
        assert ws.accepted is True
        assert ws.accept_call_count == 1

    async def test_connect_increments_active_count(self):
        """active_count increases with each connection."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())
        assert mgr.active_count == 1
        await mgr.connect("c2", _make_ws())
        assert mgr.active_count == 2

    async def test_connect_with_user_id(self):
        """connect() with user_id tracks the user mapping."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        await mgr.connect("conn-1", _make_ws(), user_id=uid)

        uid_str = str(uid)
        assert uid_str in mgr._user_connections
        assert "conn-1" in mgr._user_connections[uid_str]

    async def test_connect_without_user_id(self):
        """connect() without user_id does not add to user mapping."""
        mgr = ConnectionManager()
        await mgr.connect("conn-1", _make_ws())
        assert len(mgr._user_connections) == 0

    async def test_connect_multiple_per_user(self):
        """Multiple connections for the same user are tracked."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        await mgr.connect("c1", _make_ws(), user_id=uid)
        await mgr.connect("c2", _make_ws(), user_id=uid)

        uid_str = str(uid)
        assert mgr._user_connections[uid_str] == {"c1", "c2"}

    async def test_connect_at_max_returns_false(self):
        """connect() returns False when max_connections is reached."""
        mgr = ConnectionManager(max_connections=2)
        await mgr.connect("c1", _make_ws())
        await mgr.connect("c2", _make_ws())

        ws3 = _make_ws()
        result = await mgr.connect("c3", ws3)

        assert result is False
        assert mgr.active_count == 2
        # Websocket should NOT have been accepted
        assert ws3.accepted is False

    async def test_connect_exactly_at_max_succeeds(self):
        """connect() succeeds when active_count == max_connections - 1."""
        mgr = ConnectionManager(max_connections=2)
        await mgr.connect("c1", _make_ws())

        result = await mgr.connect("c2", _make_ws())

        assert result is True
        assert mgr.active_count == 2

    async def test_connect_stores_connection(self):
        """connect() stores the WSConnection in _connections."""
        mgr = ConnectionManager()
        ws = _make_ws()
        uid = _make_user_id()
        await mgr.connect("conn-1", ws, user_id=uid)

        assert "conn-1" in mgr._connections
        conn = mgr._connections["conn-1"]
        assert conn.websocket is ws
        assert conn.user_id == uid


# ---------------------------------------------------------------------------
# ConnectionManager: disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    """Tests for the disconnect() method."""

    async def test_disconnect_removes_connection(self):
        """disconnect() removes the connection from _connections."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())
        assert mgr.active_count == 1

        await mgr.disconnect("c1")
        assert mgr.active_count == 0
        assert "c1" not in mgr._connections

    async def test_disconnect_cleans_user_mapping(self):
        """disconnect() removes connection from user mapping."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        await mgr.connect("c1", _make_ws(), user_id=uid)

        await mgr.disconnect("c1")

        uid_str = str(uid)
        # User mapping should be fully cleaned up
        assert uid_str not in mgr._user_connections

    async def test_disconnect_cleans_user_mapping_partial(self):
        """disconnect() only removes the specific connection from user mapping."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        await mgr.connect("c1", _make_ws(), user_id=uid)
        await mgr.connect("c2", _make_ws(), user_id=uid)

        await mgr.disconnect("c1")

        uid_str = str(uid)
        assert uid_str in mgr._user_connections
        assert mgr._user_connections[uid_str] == {"c2"}

    async def test_disconnect_cleans_conversation_mapping(self):
        """disconnect() removes connection from conversation mapping."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())
        conv_id = uuid4()
        await mgr.subscribe_conversation("c1", conv_id)

        await mgr.disconnect("c1")

        cid_str = str(conv_id)
        assert cid_str not in mgr._conversation_connections

    async def test_disconnect_nonexistent_is_noop(self):
        """disconnect() for a non-existent connection is a no-op."""
        mgr = ConnectionManager()
        await mgr.disconnect("nonexistent")  # should not raise
        assert mgr.active_count == 0

    async def test_disconnect_idempotent(self):
        """Disconnecting the same connection twice does not raise."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())

        await mgr.disconnect("c1")
        await mgr.disconnect("c1")  # second call should be a no-op

        assert mgr.active_count == 0


# ---------------------------------------------------------------------------
# ConnectionManager: subscribe_conversation
# ---------------------------------------------------------------------------


class TestSubscribeConversation:
    """Tests for subscribe_conversation()."""

    async def test_subscribe_adds_to_tracking(self):
        """subscribe_conversation() adds the connection to conversation mapping."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())
        conv_id = uuid4()

        await mgr.subscribe_conversation("c1", conv_id)

        cid_str = str(conv_id)
        assert cid_str in mgr._conversation_connections
        assert "c1" in mgr._conversation_connections[cid_str]

    async def test_subscribe_sets_conversation_on_connection(self):
        """subscribe_conversation() sets conversation_id on the WSConnection."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())
        conv_id = uuid4()

        await mgr.subscribe_conversation("c1", conv_id)

        assert mgr._connections["c1"].conversation_id == conv_id

    async def test_subscribe_replaces_previous(self):
        """Subscribing to a new conversation unsubscribes from the old one."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())
        conv1 = uuid4()
        conv2 = uuid4()

        await mgr.subscribe_conversation("c1", conv1)
        await mgr.subscribe_conversation("c1", conv2)

        # Old conversation should no longer track this connection
        assert "c1" not in mgr._conversation_connections.get(str(conv1), set())
        # New conversation tracks it
        assert "c1" in mgr._conversation_connections[str(conv2)]
        # Connection's conversation_id is updated
        assert mgr._connections["c1"].conversation_id == conv2

    async def test_subscribe_multiple_connections_same_conversation(self):
        """Multiple connections can subscribe to the same conversation."""
        mgr = ConnectionManager()
        await mgr.connect("c1", _make_ws())
        await mgr.connect("c2", _make_ws())
        conv_id = uuid4()

        await mgr.subscribe_conversation("c1", conv_id)
        await mgr.subscribe_conversation("c2", conv_id)

        cid_str = str(conv_id)
        assert mgr._conversation_connections[cid_str] == {"c1", "c2"}

    async def test_subscribe_nonexistent_connection_noop(self):
        """subscribe_conversation for a non-existent connection is a no-op."""
        mgr = ConnectionManager()
        conv_id = uuid4()

        await mgr.subscribe_conversation("nonexistent", conv_id)

        # Nothing should be tracked
        assert str(conv_id) not in mgr._conversation_connections


# ---------------------------------------------------------------------------
# ConnectionManager: send_to_user
# ---------------------------------------------------------------------------


class TestSendToUser:
    """Tests for send_to_user()."""

    async def test_send_to_user_single_connection(self):
        """send_to_user sends to all of a user's connections."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        ws = _make_ws()
        await mgr.connect("c1", ws, user_id=uid)

        sent = await mgr.send_to_user(uid, "chat.message", {"text": "hello"})

        assert sent == 1
        assert len(ws.sent_messages) == 1
        assert ws.sent_messages[0]["event"] == "chat.message"
        assert ws.sent_messages[0]["data"]["text"] == "hello"

    async def test_send_to_user_multiple_connections(self):
        """send_to_user sends to every connection for the user."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect("c1", ws1, user_id=uid)
        await mgr.connect("c2", ws2, user_id=uid)

        sent = await mgr.send_to_user(uid, "notification", {"type": "alert"})

        assert sent == 2
        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 1

    async def test_send_to_user_no_connections(self):
        """send_to_user returns 0 when user has no connections."""
        mgr = ConnectionManager()
        uid = _make_user_id()

        sent = await mgr.send_to_user(uid, "event", {"data": True})

        assert sent == 0

    async def test_send_to_user_does_not_affect_other_users(self):
        """send_to_user only sends to the specified user's connections."""
        mgr = ConnectionManager()
        uid1 = _make_user_id()
        uid2 = _make_user_id()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect("c1", ws1, user_id=uid1)
        await mgr.connect("c2", ws2, user_id=uid2)

        await mgr.send_to_user(uid1, "event", {})

        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 0

    async def test_send_to_user_message_format(self):
        """Messages are sent as {event: ..., data: ...} dicts."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        ws = _make_ws()
        await mgr.connect("c1", ws, user_id=uid)

        await mgr.send_to_user(uid, "stream.chunk", {"chunk": "part 1"})

        msg = ws.sent_messages[0]
        assert set(msg.keys()) == {"event", "data"}
        assert msg["event"] == "stream.chunk"
        assert msg["data"] == {"chunk": "part 1"}


# ---------------------------------------------------------------------------
# ConnectionManager: send_to_conversation
# ---------------------------------------------------------------------------


class TestSendToConversation:
    """Tests for send_to_conversation()."""

    async def test_send_to_conversation_single(self):
        """send_to_conversation sends to subscribed connections."""
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect("c1", ws)
        conv_id = uuid4()
        await mgr.subscribe_conversation("c1", conv_id)

        sent = await mgr.send_to_conversation(conv_id, "chat.token", {"token": "Hi"})

        assert sent == 1
        assert len(ws.sent_messages) == 1
        assert ws.sent_messages[0]["event"] == "chat.token"

    async def test_send_to_conversation_multiple(self):
        """send_to_conversation sends to all subscribed connections."""
        mgr = ConnectionManager()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect("c1", ws1)
        await mgr.connect("c2", ws2)
        conv_id = uuid4()
        await mgr.subscribe_conversation("c1", conv_id)
        await mgr.subscribe_conversation("c2", conv_id)

        sent = await mgr.send_to_conversation(conv_id, "event", {"k": "v"})

        assert sent == 2
        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 1

    async def test_send_to_conversation_no_subscribers(self):
        """send_to_conversation returns 0 when no one is subscribed."""
        mgr = ConnectionManager()
        conv_id = uuid4()

        sent = await mgr.send_to_conversation(conv_id, "event", {})

        assert sent == 0

    async def test_send_to_conversation_only_subscribed(self):
        """send_to_conversation only reaches subscribed connections."""
        mgr = ConnectionManager()
        ws_sub = _make_ws()
        ws_other = _make_ws()
        await mgr.connect("c1", ws_sub)
        await mgr.connect("c2", ws_other)
        conv_id = uuid4()
        await mgr.subscribe_conversation("c1", conv_id)

        await mgr.send_to_conversation(conv_id, "event", {})

        assert len(ws_sub.sent_messages) == 1
        assert len(ws_other.sent_messages) == 0

    async def test_send_to_different_conversations(self):
        """Messages only go to the correct conversation's subscribers."""
        mgr = ConnectionManager()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect("c1", ws1)
        await mgr.connect("c2", ws2)
        conv1 = uuid4()
        conv2 = uuid4()
        await mgr.subscribe_conversation("c1", conv1)
        await mgr.subscribe_conversation("c2", conv2)

        await mgr.send_to_conversation(conv1, "event", {"for": "conv1"})

        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 0


# ---------------------------------------------------------------------------
# ConnectionManager: broadcast
# ---------------------------------------------------------------------------


class TestBroadcast:
    """Tests for broadcast()."""

    async def test_broadcast_to_all(self):
        """broadcast sends to every connected client."""
        mgr = ConnectionManager()
        ws1 = _make_ws()
        ws2 = _make_ws()
        ws3 = _make_ws()
        await mgr.connect("c1", ws1)
        await mgr.connect("c2", ws2)
        await mgr.connect("c3", ws3)

        sent = await mgr.broadcast("system.alert", {"message": "maintenance"})

        assert sent == 3
        for ws in (ws1, ws2, ws3):
            assert len(ws.sent_messages) == 1
            assert ws.sent_messages[0]["event"] == "system.alert"

    async def test_broadcast_no_connections(self):
        """broadcast returns 0 when no connections exist."""
        mgr = ConnectionManager()

        sent = await mgr.broadcast("event", {"data": True})

        assert sent == 0

    async def test_broadcast_message_format(self):
        """Broadcast messages use the standard {event, data} format."""
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect("c1", ws)

        await mgr.broadcast("status.update", {"status": "online"})

        msg = ws.sent_messages[0]
        assert msg == {"event": "status.update", "data": {"status": "online"}}

    async def test_broadcast_to_single(self):
        """broadcast works correctly with a single connection."""
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect("c1", ws)

        sent = await mgr.broadcast("ping", {})

        assert sent == 1
        assert ws.sent_messages[0] == {"event": "ping", "data": {}}


# ---------------------------------------------------------------------------
# ConnectionManager: error handling on send
# ---------------------------------------------------------------------------


class TestSendErrorHandling:
    """Tests for error handling when send_json fails."""

    async def test_send_json_failure_triggers_disconnect(self):
        """If send_json raises, the connection is disconnected."""
        mgr = ConnectionManager()
        ws = _make_ws(send_raises=True)
        uid = _make_user_id()
        await mgr.connect("c1", ws, user_id=uid)

        sent = await mgr.send_to_user(uid, "event", {})

        assert sent == 0
        # Connection should have been removed
        assert mgr.active_count == 0

    async def test_broadcast_partial_failure(self):
        """If one connection fails, others still receive the broadcast."""
        mgr = ConnectionManager()
        ws_ok = _make_ws()
        ws_bad = _make_ws(send_raises=True)
        await mgr.connect("c-ok", ws_ok)
        await mgr.connect("c-bad", ws_bad)

        sent = await mgr.broadcast("event", {"data": 1})

        assert sent == 1
        assert len(ws_ok.sent_messages) == 1
        # Bad connection should have been disconnected
        assert mgr.active_count == 1

    async def test_send_to_conversation_partial_failure(self):
        """If one subscriber's send fails, others still get the message."""
        mgr = ConnectionManager()
        ws_ok = _make_ws()
        ws_bad = _make_ws(send_raises=True)
        await mgr.connect("c-ok", ws_ok)
        await mgr.connect("c-bad", ws_bad)
        conv_id = uuid4()
        await mgr.subscribe_conversation("c-ok", conv_id)
        await mgr.subscribe_conversation("c-bad", conv_id)

        sent = await mgr.send_to_conversation(conv_id, "event", {})

        assert sent == 1
        assert len(ws_ok.sent_messages) == 1

    async def test_send_to_removed_connection_returns_false(self):
        """_send_json for a connection that no longer exists returns False."""
        mgr = ConnectionManager()
        result = await mgr._send_json("nonexistent", {"event": "test", "data": {}})
        assert result is False

    async def test_failed_send_cleans_user_mapping(self):
        """When send fails and triggers disconnect, user mapping is cleaned."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        ws = _make_ws(send_raises=True)
        await mgr.connect("c1", ws, user_id=uid)

        await mgr.send_to_user(uid, "event", {})

        uid_str = str(uid)
        assert uid_str not in mgr._user_connections


# ---------------------------------------------------------------------------
# ConnectionManager: integration scenarios
# ---------------------------------------------------------------------------


class TestIntegrationScenarios:
    """End-to-end scenarios combining multiple operations."""

    async def test_connect_subscribe_send_disconnect_full_lifecycle(self):
        """Full lifecycle: connect, subscribe, send, disconnect."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        ws = _make_ws()
        conv_id = uuid4()

        # Connect
        assert await mgr.connect("c1", ws, user_id=uid) is True
        assert mgr.active_count == 1

        # Subscribe to conversation
        await mgr.subscribe_conversation("c1", conv_id)
        assert str(conv_id) in mgr._conversation_connections

        # Send to user
        sent = await mgr.send_to_user(uid, "welcome", {"msg": "hi"})
        assert sent == 1

        # Send to conversation
        sent = await mgr.send_to_conversation(conv_id, "chat.token", {"token": "hello"})
        assert sent == 1

        # Broadcast
        sent = await mgr.broadcast("announcement", {"info": "update"})
        assert sent == 1

        # Verify all 3 messages arrived
        assert len(ws.sent_messages) == 3

        # Disconnect
        await mgr.disconnect("c1")
        assert mgr.active_count == 0
        assert str(uid) not in mgr._user_connections
        assert str(conv_id) not in mgr._conversation_connections

    async def test_multiple_users_multiple_conversations(self):
        """Multiple users subscribed to different conversations."""
        mgr = ConnectionManager()
        uid1 = _make_user_id()
        uid2 = _make_user_id()
        ws1 = _make_ws()
        ws2 = _make_ws()
        ws3 = _make_ws()
        conv_a = uuid4()
        conv_b = uuid4()

        await mgr.connect("c1", ws1, user_id=uid1)
        await mgr.connect("c2", ws2, user_id=uid2)
        await mgr.connect("c3", ws3, user_id=uid1)  # user1's second connection

        await mgr.subscribe_conversation("c1", conv_a)
        await mgr.subscribe_conversation("c2", conv_b)
        await mgr.subscribe_conversation("c3", conv_a)  # also watches conv_a

        # Send to conv_a: should reach c1 and c3
        sent = await mgr.send_to_conversation(conv_a, "msg", {"text": "a"})
        assert sent == 2
        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 0
        assert len(ws3.sent_messages) == 1

        # Send to user1: should reach c1 and c3
        sent = await mgr.send_to_user(uid1, "notification", {})
        assert sent == 2

        # Broadcast: should reach all 3
        sent = await mgr.broadcast("system", {})
        assert sent == 3

    async def test_disconnect_during_multi_connection_scenario(self):
        """Disconnecting one connection does not affect other connections."""
        mgr = ConnectionManager()
        uid = _make_user_id()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await mgr.connect("c1", ws1, user_id=uid)
        await mgr.connect("c2", ws2, user_id=uid)

        await mgr.disconnect("c1")

        assert mgr.active_count == 1
        sent = await mgr.send_to_user(uid, "event", {"after": "disconnect"})
        assert sent == 1
        assert len(ws2.sent_messages) == 1
        assert len(ws1.sent_messages) == 0  # ws1 was disconnected, no new messages

    async def test_resubscribe_to_different_conversation(self):
        """Re-subscribing moves the connection to the new conversation."""
        mgr = ConnectionManager()
        ws = _make_ws()
        await mgr.connect("c1", ws)
        conv1 = uuid4()
        conv2 = uuid4()

        await mgr.subscribe_conversation("c1", conv1)
        await mgr.subscribe_conversation("c1", conv2)

        # Should only receive messages for conv2, not conv1
        sent1 = await mgr.send_to_conversation(conv1, "event", {"for": "conv1"})
        sent2 = await mgr.send_to_conversation(conv2, "event", {"for": "conv2"})

        assert sent1 == 0
        assert sent2 == 1
        assert len(ws.sent_messages) == 1
        assert ws.sent_messages[0]["data"]["for"] == "conv2"
