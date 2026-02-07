"""
Tests for the node system: protocol, policy, pairing, registry.

Covers protocol message construction, capability-based command policy,
pairing lifecycle with TTL, and node registry tracking.
"""

import time
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ungula.nodes.pairing import NodePairingStore, PairRequest
from ungula.nodes.policy import COMMAND_CAPABILITY_MAP, NodeCommandPolicy
from ungula.nodes.protocol import (
    NodeEvent,
    NodeMessage,
    auth_error_message,
    auth_message,
    auth_ok_message,
    error_message,
    heartbeat_message,
    invoke_message,
    result_message,
)
from ungula.nodes.registry import ConnectedNode, NodeRegistry


# ===========================================================================
# Protocol messages
# ===========================================================================


class TestNodeEvent:
    """Tests for NodeEvent enum."""

    def test_auth_event(self):
        assert NodeEvent.AUTH == "node.auth"

    def test_invoke_event(self):
        assert NodeEvent.INVOKE == "node.invoke"

    def test_result_event(self):
        assert NodeEvent.RESULT == "node.result"

    def test_heartbeat_event(self):
        assert NodeEvent.HEARTBEAT == "node.heartbeat"

    def test_auth_ok_event(self):
        assert NodeEvent.AUTH_OK == "node.auth.ok"

    def test_auth_error_event(self):
        assert NodeEvent.AUTH_ERROR == "node.auth.error"

    def test_error_event(self):
        assert NodeEvent.ERROR == "node.error"

    def test_register_capabilities(self):
        assert NodeEvent.REGISTER_CAPABILITIES == "node.register_capabilities"


class TestNodeMessage:
    """Tests for NodeMessage dataclass."""

    def test_to_dict(self):
        msg = NodeMessage(event="test", data={"key": "val"})
        d = msg.to_dict()
        assert d == {"event": "test", "data": {"key": "val"}}

    def test_from_dict(self):
        d = {"event": "node.auth", "data": {"token": "abc"}}
        msg = NodeMessage.from_dict(d)
        assert msg.event == "node.auth"
        assert msg.data["token"] == "abc"

    def test_from_dict_defaults(self):
        msg = NodeMessage.from_dict({})
        assert msg.event == ""
        assert msg.data == {}

    def test_roundtrip(self):
        original = NodeMessage(event="node.invoke", data={"cmd": "test"})
        restored = NodeMessage.from_dict(original.to_dict())
        assert restored.event == original.event
        assert restored.data == original.data


class TestProtocolFactories:
    """Tests for protocol message factory functions."""

    def test_auth_message(self):
        msg = auth_message("token123", "macos", ["camera", "notify"])
        assert msg.event == NodeEvent.AUTH
        assert msg.data["token"] == "token123"
        assert msg.data["platform"] == "macos"
        assert msg.data["capabilities"] == ["camera", "notify"]

    def test_auth_ok_message(self):
        msg = auth_ok_message("node-id-1")
        assert msg.event == NodeEvent.AUTH_OK
        assert msg.data["node_id"] == "node-id-1"

    def test_auth_error_message(self):
        msg = auth_error_message("Bad token")
        assert msg.event == NodeEvent.AUTH_ERROR
        assert msg.data["message"] == "Bad token"

    def test_invoke_message(self):
        msg = invoke_message("camera.capture", {"resolution": "1080p"}, "req-1")
        assert msg.event == NodeEvent.INVOKE
        assert msg.data["command"] == "camera.capture"
        assert msg.data["args"] == {"resolution": "1080p"}
        assert msg.data["request_id"] == "req-1"

    def test_result_message(self):
        msg = result_message("req-1", True, "photo captured", {"path": "/tmp/photo.jpg"})
        assert msg.event == NodeEvent.RESULT
        assert msg.data["request_id"] == "req-1"
        assert msg.data["success"] is True
        assert msg.data["output"] == "photo captured"
        assert msg.data["data"]["path"] == "/tmp/photo.jpg"

    def test_result_message_no_data(self):
        msg = result_message("req-2", False, "failed")
        assert msg.event == NodeEvent.RESULT
        assert "data" not in msg.data

    def test_heartbeat_message(self):
        msg = heartbeat_message()
        assert msg.event == NodeEvent.HEARTBEAT
        assert msg.data == {}

    def test_error_message(self):
        msg = error_message("Something broke")
        assert msg.event == NodeEvent.ERROR
        assert msg.data["message"] == "Something broke"


# ===========================================================================
# NodeCommandPolicy
# ===========================================================================


class TestNodeCommandPolicy:
    """Tests for capability-based command policy."""

    @pytest.fixture
    def policy(self) -> NodeCommandPolicy:
        return NodeCommandPolicy()

    def test_known_command_with_capability(self, policy: NodeCommandPolicy):
        assert policy.can_execute("camera.capture", ["camera"]) is True

    def test_known_command_without_capability(self, policy: NodeCommandPolicy):
        assert policy.can_execute("camera.capture", ["notify"]) is False

    def test_unknown_command_denied(self, policy: NodeCommandPolicy):
        assert policy.can_execute("hack.system", ["camera"]) is False

    def test_system_run(self, policy: NodeCommandPolicy):
        assert policy.can_execute("system.run", ["system.run"]) is True
        assert policy.can_execute("system.run", ["camera"]) is False

    def test_notify_send(self, policy: NodeCommandPolicy):
        assert policy.can_execute("notify.send", ["notify"]) is True

    def test_sms_send(self, policy: NodeCommandPolicy):
        assert policy.can_execute("sms.send", ["sms.send"]) is True

    def test_clipboard_operations(self, policy: NodeCommandPolicy):
        assert policy.can_execute("clipboard.get", ["clipboard"]) is True
        assert policy.can_execute("clipboard.set", ["clipboard"]) is True

    def test_audio_operations(self, policy: NodeCommandPolicy):
        assert policy.can_execute("audio.play", ["audio"]) is True
        assert policy.can_execute("audio.record", ["audio"]) is True

    def test_list_commands_for_capabilities(self, policy: NodeCommandPolicy):
        commands = policy.list_commands_for_capabilities(["camera", "notify"])
        assert "camera.capture" in commands
        assert "camera.stream" in commands
        assert "notify.send" in commands
        assert "system.run" not in commands

    def test_list_commands_empty_capabilities(self, policy: NodeCommandPolicy):
        commands = policy.list_commands_for_capabilities([])
        assert commands == []

    def test_get_required_capability(self, policy: NodeCommandPolicy):
        assert policy.get_required_capability("camera.capture") == "camera"
        assert policy.get_required_capability("system.run") == "system.run"
        assert policy.get_required_capability("unknown") is None

    def test_extra_mappings(self):
        policy = NodeCommandPolicy(extra_mappings={"custom.cmd": "custom_cap"})
        assert policy.can_execute("custom.cmd", ["custom_cap"]) is True
        # Original mappings still work
        assert policy.can_execute("camera.capture", ["camera"]) is True

    def test_command_capability_map_completeness(self):
        """All commands should map to a capability string."""
        for cmd, cap in COMMAND_CAPABILITY_MAP.items():
            assert isinstance(cmd, str) and len(cmd) > 0
            assert isinstance(cap, str) and len(cap) > 0


# ===========================================================================
# NodePairingStore
# ===========================================================================


class TestNodePairingStore:
    """Tests for node pairing lifecycle."""

    @pytest.fixture
    def store(self) -> NodePairingStore:
        return NodePairingStore(ttl=300)

    def test_create_request(self, store: NodePairingStore):
        req = store.create_request("node-1", "MyMac", "macos", ["camera", "notify"])
        assert req.node_id == "node-1"
        assert req.name == "MyMac"
        assert req.platform == "macos"
        assert req.capabilities == ["camera", "notify"]
        assert len(req.token) > 20  # token_urlsafe(32) gives ~43 chars

    def test_get_pending(self, store: NodePairingStore):
        store.create_request("node-1", "Mac1", "macos", ["camera"])
        store.create_request("node-2", "Mac2", "macos", ["notify"])
        pending = store.get_pending()
        assert len(pending) == 2
        ids = {r.node_id for r in pending}
        assert ids == {"node-1", "node-2"}

    def test_get_request(self, store: NodePairingStore):
        store.create_request("node-1", "Mac1", "macos", [])
        req = store.get_request("node-1")
        assert req is not None
        assert req.node_id == "node-1"

    def test_get_request_nonexistent(self, store: NodePairingStore):
        assert store.get_request("bogus") is None

    def test_approve(self, store: NodePairingStore):
        store.create_request("node-1", "Mac1", "macos", ["camera"])
        req = store.approve("node-1")
        assert req is not None
        assert req.node_id == "node-1"
        # Should be removed from pending
        assert store.get_request("node-1") is None

    def test_approve_nonexistent(self, store: NodePairingStore):
        assert store.approve("bogus") is None

    def test_reject(self, store: NodePairingStore):
        store.create_request("node-1", "Mac1", "macos", [])
        assert store.reject("node-1") is True
        assert store.get_request("node-1") is None

    def test_reject_nonexistent(self, store: NodePairingStore):
        assert store.reject("bogus") is False

    def test_ttl_expiry(self):
        """Expired requests should be cleaned up."""
        store = NodePairingStore(ttl=1)
        store.create_request("node-1", "Mac1", "macos", [])
        # Manually backdate the request
        store._pending["node-1"].created_at = time.time() - 10
        pending = store.get_pending()
        assert len(pending) == 0

    def test_approve_expired_returns_none(self):
        store = NodePairingStore(ttl=1)
        req = store.create_request("node-1", "Mac1", "macos", [])
        # Backdate it
        store._pending["node-1"].created_at = time.time() - 10
        assert store.approve("node-1") is None

    def test_duplicate_node_overwrites(self, store: NodePairingStore):
        """Creating a request for the same node_id replaces the old one."""
        req1 = store.create_request("node-1", "Mac1", "macos", [])
        req2 = store.create_request("node-1", "Mac1-v2", "macos", ["camera"])
        assert store.get_request("node-1").name == "Mac1-v2"
        assert len(store.get_pending()) == 1


class TestPairRequest:
    """Tests for the PairRequest dataclass."""

    def test_is_expired_false(self):
        req = PairRequest(node_id="1", name="N", platform="p", capabilities=[], token="t")
        assert req.is_expired(300) is False

    def test_is_expired_true(self):
        req = PairRequest(
            node_id="1", name="N", platform="p", capabilities=[], token="t",
            created_at=time.time() - 400,
        )
        assert req.is_expired(300) is True


# ===========================================================================
# NodeRegistry
# ===========================================================================


class TestNodeRegistry:
    """Tests for node registry tracking."""

    @pytest.fixture
    def registry(self) -> NodeRegistry:
        return NodeRegistry(max_nodes=5)

    @pytest.fixture
    def mock_ws(self) -> MagicMock:
        ws = MagicMock()
        ws.send_json = AsyncMock()
        return ws

    def test_register_node(self, registry: NodeRegistry, mock_ws: MagicMock):
        node = registry.register("n1", "Mac1", "macos", ["camera"], mock_ws)
        assert node.node_id == "n1"
        assert node.name == "Mac1"
        assert node.platform == "macos"
        assert node.capabilities == ["camera"]
        assert node.websocket is mock_ws

    def test_register_max_limit(self, mock_ws: MagicMock):
        registry = NodeRegistry(max_nodes=2)
        registry.register("n1", "N1", "macos", [], mock_ws)
        registry.register("n2", "N2", "macos", [], mock_ws)
        with pytest.raises(RuntimeError, match="Max nodes"):
            registry.register("n3", "N3", "macos", [], mock_ws)

    def test_register_same_id_no_limit_error(self, mock_ws: MagicMock):
        """Re-registering the same node_id should succeed (replaces)."""
        registry = NodeRegistry(max_nodes=1)
        registry.register("n1", "N1", "macos", [], mock_ws)
        # Re-register same ID should work
        node = registry.register("n1", "N1-v2", "macos", ["camera"], mock_ws)
        assert node.name == "N1-v2"

    def test_unregister(self, registry: NodeRegistry, mock_ws: MagicMock):
        registry.register("n1", "Mac1", "macos", [], mock_ws)
        removed = registry.unregister("n1")
        assert removed is not None
        assert removed.node_id == "n1"
        assert registry.get("n1") is None

    def test_unregister_nonexistent(self, registry: NodeRegistry):
        assert registry.unregister("bogus") is None

    def test_get(self, registry: NodeRegistry, mock_ws: MagicMock):
        registry.register("n1", "Mac1", "macos", [], mock_ws)
        assert registry.get("n1") is not None
        assert registry.get("n2") is None

    def test_get_by_capability(self, registry: NodeRegistry, mock_ws: MagicMock):
        registry.register("n1", "Mac1", "macos", ["camera", "notify"], mock_ws)
        registry.register("n2", "Mac2", "linux", ["notify"], mock_ws)
        camera_nodes = registry.get_by_capability("camera")
        assert len(camera_nodes) == 1
        assert camera_nodes[0].node_id == "n1"

        notify_nodes = registry.get_by_capability("notify")
        assert len(notify_nodes) == 2

    def test_find_capable(self, registry: NodeRegistry, mock_ws: MagicMock):
        registry.register("n1", "Mac1", "macos", ["camera"], mock_ws)
        found = registry.find_capable("camera")
        assert found is not None
        assert found.node_id == "n1"

        assert registry.find_capable("nonexistent") is None

    def test_list_online(self, registry: NodeRegistry, mock_ws: MagicMock):
        registry.register("n1", "Mac1", "macos", ["camera"], mock_ws)
        registry.register("n2", "Mac2", "linux", ["notify"], mock_ws)
        online = registry.list_online()
        assert len(online) == 2
        assert all(n["status"] == "online" for n in online)

    def test_update_heartbeat(self, registry: NodeRegistry, mock_ws: MagicMock):
        registry.register("n1", "Mac1", "macos", [], mock_ws)
        old_hb = registry.get("n1").last_heartbeat
        assert registry.update_heartbeat("n1") is True
        new_hb = registry.get("n1").last_heartbeat
        assert new_hb >= old_hb

    def test_update_heartbeat_nonexistent(self, registry: NodeRegistry):
        assert registry.update_heartbeat("bogus") is False

    def test_online_count(self, registry: NodeRegistry, mock_ws: MagicMock):
        assert registry.online_count == 0
        registry.register("n1", "N1", "macos", [], mock_ws)
        assert registry.online_count == 1
        registry.register("n2", "N2", "linux", [], mock_ws)
        assert registry.online_count == 2
        registry.unregister("n1")
        assert registry.online_count == 1


class TestConnectedNode:
    """Tests for ConnectedNode dataclass."""

    def test_to_dict(self):
        ws = MagicMock()
        node = ConnectedNode(
            node_id="n1", name="Mac1", platform="macos",
            capabilities=["camera"], websocket=ws,
        )
        d = node.to_dict()
        assert d["id"] == "n1"
        assert d["name"] == "Mac1"
        assert d["platform"] == "macos"
        assert d["capabilities"] == ["camera"]
        assert d["status"] == "online"
        assert "connected_at" in d
        assert "last_heartbeat" in d
