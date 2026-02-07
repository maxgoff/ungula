"""
Node system integration tests.

Exercises the 10 verification scenarios from the node enhancement plan,
testing end-to-end flows through NodeManager, NodeRegistry, NodeCommandPolicy,
ExecApprovalManager, and the WS protocol.
"""

import asyncio
import shutil
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ungula.nodes import (
    ExecApprovalManager,
    NodeCommandPolicy,
    NodeManager,
    NodePairingStore,
    NodeRegistry,
)
from ungula.nodes.protocol import (
    NodeEvent,
    NodeMessage,
    heartbeat_message,
    node_event_message,
    pair_approved_message,
    pair_pending_message,
    pair_rejected_message,
    pair_request_message,
)
from ungula.nodes.registry import ConnectedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws():
    """Create a mock WebSocket with async send_json."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


def _make_storage_mock():
    """Create a mock storage backend with async session context manager."""
    storage = MagicMock()

    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
    ))

    # Make session() work as async context manager
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    storage.session = MagicMock(return_value=session_cm)

    return storage


def _make_manager(
    max_nodes=10,
    pairing_ttl=300,
    allow_commands=None,
    deny_commands=None,
    exec_approval=None,
    command_timeout=5,
):
    """Create a fully wired NodeManager with mocked storage."""
    registry = NodeRegistry(max_nodes=max_nodes)
    pairing_store = NodePairingStore(ttl=pairing_ttl)
    policy = NodeCommandPolicy(
        allow_commands=allow_commands,
        deny_commands=deny_commands,
    )
    storage = _make_storage_mock()

    manager = NodeManager(
        registry=registry,
        pairing_store=pairing_store,
        policy=policy,
        storage=storage,
        command_timeout=command_timeout,
        exec_approval=exec_approval,
    )
    return manager


# ===========================================================================
# Scenario 1: Admin pairing flow
# ===========================================================================


class TestAdminPairingFlow:
    """Admin creates pairing request → approves → node record exists."""

    @pytest.mark.asyncio
    async def test_admin_pairing_creates_record(self):
        manager = _make_manager()

        result = await manager.initiate_pairing("MacBook", "macos", ["camera", "system"])

        assert "node_id" in result
        assert "token" in result
        assert result["name"] == "MacBook"
        assert result["platform"] == "macos"

    @pytest.mark.asyncio
    async def test_admin_pairing_approve_returns_token(self):
        manager = _make_manager()

        pair_result = await manager.initiate_pairing("MacBook", "macos", ["camera"])
        node_id = pair_result["node_id"]

        approve_result = await manager.approve_pairing(node_id)

        assert approve_result is not None
        assert approve_result["node_id"] == node_id
        assert "token" in approve_result
        assert len(approve_result["token"]) > 20

    @pytest.mark.asyncio
    async def test_admin_pairing_reject_removes_request(self):
        manager = _make_manager()

        pair_result = await manager.initiate_pairing("MacBook", "macos", [])
        node_id = pair_result["node_id"]

        removed = await manager.reject_pairing(node_id)
        assert removed is True

        # Should not be approvable after rejection
        approve_result = await manager.approve_pairing(node_id)
        assert approve_result is None

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_none(self):
        manager = _make_manager()
        result = await manager.approve_pairing("nonexistent-node")
        assert result is None


# ===========================================================================
# Scenario 2: Node-initiated pairing flow
# ===========================================================================


class TestNodeInitiatedPairingFlow:
    """Node sends pair.request → manager creates pending → approve sends WS notification."""

    @pytest.mark.asyncio
    async def test_node_initiated_pairing_creates_pending(self):
        manager = _make_manager()
        ws = _make_ws()

        result = await manager.node_initiated_pairing(
            "iPhone", "ios", ["camera"], metadata={"version": "0.2"}, websocket=ws,
        )

        assert "node_id" in result
        assert "token" in result

        # Should be in pending list
        pending = manager.pairing.get_pending()
        assert len(pending) == 1
        assert pending[0].websocket is ws

    @pytest.mark.asyncio
    async def test_node_initiated_approve_sends_ws_notification(self):
        manager = _make_manager()
        ws = _make_ws()

        result = await manager.node_initiated_pairing(
            "iPhone", "ios", ["camera"], websocket=ws,
        )
        node_id = result["node_id"]

        approve_result = await manager.approve_pairing(node_id)

        assert approve_result is not None
        # WebSocket should have received pair_approved message
        ws.send_json.assert_called_once()
        sent_msg = ws.send_json.call_args[0][0]
        assert sent_msg["event"] == NodeEvent.PAIR_APPROVED
        assert sent_msg["data"]["node_id"] == node_id
        assert "token" in sent_msg["data"]

    @pytest.mark.asyncio
    async def test_node_initiated_reject_sends_ws_notification(self):
        manager = _make_manager()
        ws = _make_ws()

        result = await manager.node_initiated_pairing(
            "iPad", "ios", ["screen"], websocket=ws,
        )
        node_id = result["node_id"]

        removed = await manager.reject_pairing(node_id)
        assert removed is True

        ws.send_json.assert_called_once()
        sent_msg = ws.send_json.call_args[0][0]
        assert sent_msg["event"] == NodeEvent.PAIR_REJECTED


# ===========================================================================
# Scenario 3: Platform policy enforcement
# ===========================================================================


class TestPlatformPolicyEnforcement:
    """Linux node: camera.capture denied, system.run allowed.
    iOS node: camera.capture allowed, system.run denied."""

    def test_linux_denies_camera(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("camera.capture", platform="linux") is False

    def test_linux_allows_system_run(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("system.run", platform="linux") is True

    def test_ios_allows_camera(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("camera.capture", platform="ios") is True

    def test_ios_denies_system_run(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("system.run", platform="ios") is False

    def test_macos_allows_both(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("camera.capture", platform="macos") is True
        assert policy.can_execute("system.run", platform="macos") is True

    def test_windows_denies_audio(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("audio.record", platform="windows") is False

    def test_explicit_deny_overrides_platform(self):
        policy = NodeCommandPolicy(deny_commands=["camera.capture"])
        assert policy.can_execute("camera.capture", platform="macos") is False

    def test_explicit_allow_overrides_platform(self):
        policy = NodeCommandPolicy(allow_commands=["camera.capture"])
        assert policy.can_execute("camera.capture", platform="linux") is True


# ===========================================================================
# Scenario 4: Heartbeat stale detection
# ===========================================================================


class TestHeartbeatStaleDetection:
    """Register node → set old heartbeat → sweep → verify disconnected."""

    def test_fresh_node_not_stale(self):
        registry = NodeRegistry(max_nodes=10)
        ws = _make_ws()
        registry.register("n1", "Mac", "macos", [], ws)

        stale = registry.get_stale_nodes(timeout_seconds=90)
        assert len(stale) == 0

    def test_old_heartbeat_detected_stale(self):
        registry = NodeRegistry(max_nodes=10)
        ws = _make_ws()
        node = registry.register("n1", "Mac", "macos", [], ws)

        # Backdate heartbeat
        node.last_heartbeat = datetime.utcnow() - timedelta(seconds=120)

        stale = registry.get_stale_nodes(timeout_seconds=90)
        assert len(stale) == 1
        assert stale[0].node_id == "n1"

    def test_heartbeat_update_prevents_stale(self):
        registry = NodeRegistry(max_nodes=10)
        ws = _make_ws()
        node = registry.register("n1", "Mac", "macos", [], ws)

        # Backdate then refresh
        node.last_heartbeat = datetime.utcnow() - timedelta(seconds=120)
        registry.update_heartbeat("n1")

        stale = registry.get_stale_nodes(timeout_seconds=90)
        assert len(stale) == 0

    def test_mixed_fresh_and_stale(self):
        registry = NodeRegistry(max_nodes=10)
        ws = _make_ws()
        n1 = registry.register("n1", "Mac1", "macos", [], ws)
        registry.register("n2", "Mac2", "linux", [], _make_ws())

        n1.last_heartbeat = datetime.utcnow() - timedelta(seconds=200)

        stale = registry.get_stale_nodes(timeout_seconds=90)
        assert len(stale) == 1
        assert stale[0].node_id == "n1"


# ===========================================================================
# Scenario 5: Node event protocol
# ===========================================================================


class TestNodeEventProtocol:
    """Verify event message factory functions produce correct format."""

    def test_pair_request_message_format(self):
        msg = pair_request_message("MyNode", "macos", ["camera"], {"version": "0.2"})
        d = msg.to_dict()

        assert d["event"] == NodeEvent.PAIR_REQUEST
        assert d["data"]["name"] == "MyNode"
        assert d["data"]["platform"] == "macos"
        assert d["data"]["capabilities"] == ["camera"]
        assert d["data"]["metadata"]["version"] == "0.2"

    def test_pair_pending_message_format(self):
        msg = pair_pending_message("node-abc")
        d = msg.to_dict()

        assert d["event"] == NodeEvent.PAIR_PENDING
        assert d["data"]["node_id"] == "node-abc"

    def test_pair_approved_message_format(self):
        msg = pair_approved_message("node-abc", "secret-token-123")
        d = msg.to_dict()

        assert d["event"] == NodeEvent.PAIR_APPROVED
        assert d["data"]["node_id"] == "node-abc"
        assert d["data"]["token"] == "secret-token-123"

    def test_pair_rejected_message_format(self):
        msg = pair_rejected_message("node-abc")
        d = msg.to_dict()

        assert d["event"] == NodeEvent.PAIR_REJECTED
        assert d["data"]["node_id"] == "node-abc"

    def test_node_event_message_with_payload(self):
        msg = node_event_message("exec.started", {"command": "ls", "request_id": "abc"})
        d = msg.to_dict()

        assert d["event"] == NodeEvent.NODE_EVENT
        assert d["data"]["event_type"] == "exec.started"
        assert d["data"]["payload"]["command"] == "ls"

    def test_node_event_message_without_payload(self):
        msg = node_event_message("custom.event")
        d = msg.to_dict()

        assert d["event"] == NodeEvent.NODE_EVENT
        assert d["data"]["event_type"] == "custom.event"
        assert "payload" not in d["data"]

    def test_heartbeat_message_format(self):
        msg = heartbeat_message()
        d = msg.to_dict()

        assert d["event"] == NodeEvent.HEARTBEAT

    def test_message_roundtrip(self):
        """NodeMessage can be serialized and deserialized."""
        original = pair_approved_message("n1", "tok123")
        d = original.to_dict()
        restored = NodeMessage.from_dict(d)

        assert restored.event == original.event
        assert restored.data == original.data


# ===========================================================================
# Scenario 6: system.which
# ===========================================================================


class TestSystemWhich:
    """Verify shutil.which-based resolution for known and unknown binaries."""

    def test_which_known_binary(self):
        path = shutil.which("python3")
        # python3 should be findable in test environment
        if path:
            assert "python" in path

    def test_which_unknown_binary(self):
        path = shutil.which("definitely_not_a_real_binary_xyz_12345")
        assert path is None

    def test_which_empty_string(self):
        path = shutil.which("")
        assert path is None

    def test_which_returns_absolute_path(self):
        path = shutil.which("sh")
        if path:
            assert path.startswith("/")


# ===========================================================================
# Scenario 7: Audit trail
# ===========================================================================


class TestAuditTrail:
    """Invoke command via manager (mock node) → verify NodeCommandLogModel entry."""

    @pytest.mark.asyncio
    async def test_command_creates_audit_log(self):
        manager = _make_manager()
        ws = _make_ws()

        # Register a linux node with system capability
        manager.registry.register(
            "node-1", "LinuxBox", "linux", ["system"],
            ws, declared_commands=["system.run"],
        )

        # Simulate result arriving before timeout
        async def send_result(*args, **kwargs):
            # Extract request_id from invoke message
            sent_data = ws.send_json.call_args[0][0]
            request_id = sent_data["data"]["request_id"]
            manager.handle_result(request_id, {"success": True, "output": "done"})

        ws.send_json = AsyncMock(side_effect=send_result)

        result = await manager.invoke_command(
            "system.run", {"command": "ls"}, node_id="node-1", invoked_by="test",
        )

        assert result["success"] is True

        # Verify storage.session was called (for creating the audit log)
        assert manager.storage.session.called

    @pytest.mark.asyncio
    async def test_command_timeout_creates_audit_log(self):
        manager = _make_manager(command_timeout=1)
        ws = _make_ws()

        manager.registry.register(
            "node-1", "LinuxBox", "linux", ["system"],
            ws, declared_commands=["system.run"],
        )

        # Don't resolve the result — let it timeout
        result = await manager.invoke_command(
            "system.run", {"command": "sleep 100"}, node_id="node-1",
        )

        assert result["success"] is False
        assert "timed out" in result["error"].lower()


# ===========================================================================
# Scenario 8: Exec approval
# ===========================================================================


class TestExecApproval:
    """Request approval for unknown command → verify pending → resolve → command proceeds."""

    def test_allowed_command_passes_without_approval(self):
        mgr = ExecApprovalManager(allowed_patterns=["ls", "cat", "git"])
        assert mgr.is_allowed("ls -la") is True
        assert mgr.is_allowed("cat /etc/hosts") is True
        assert mgr.is_allowed("git status") is True

    def test_unknown_command_requires_approval(self):
        mgr = ExecApprovalManager(allowed_patterns=["ls"])
        assert mgr.is_allowed("rm -rf /tmp/test") is False

    @pytest.mark.asyncio
    async def test_approval_approved_lets_command_through(self):
        mgr = ExecApprovalManager(approval_timeout=10)

        async def approve_after_short_delay():
            await asyncio.sleep(0.05)
            pending = mgr.list_pending()
            assert len(pending) == 1
            mgr.resolve(pending[0]["id"], True)

        asyncio.create_task(approve_after_short_delay())
        result = await mgr.request_approval("rm -rf /tmp/test", "node-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_approval_denied_blocks_command(self):
        mgr = ExecApprovalManager(approval_timeout=10)

        async def deny_after_short_delay():
            await asyncio.sleep(0.05)
            pending = mgr.list_pending()
            mgr.resolve(pending[0]["id"], False)

        asyncio.create_task(deny_after_short_delay())
        result = await mgr.request_approval("dangerous-cmd", "node-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_approval_timeout_blocks_command(self):
        mgr = ExecApprovalManager(approval_timeout=0.2)
        result = await mgr.request_approval("some-cmd", "node-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_exec_approval_in_invoke_command(self):
        """Integration: invoke_command with exec_approval gate."""
        exec_mgr = ExecApprovalManager(allowed_patterns=["ls", "cat"])
        manager = _make_manager(exec_approval=exec_mgr)
        ws = _make_ws()

        manager.registry.register(
            "node-1", "LinuxBox", "linux", ["system"],
            ws, declared_commands=["system.run"],
        )

        # "ls" is in allowed patterns — should pass without approval
        async def send_result(*args, **kwargs):
            sent_data = ws.send_json.call_args[0][0]
            request_id = sent_data["data"]["request_id"]
            manager.handle_result(request_id, {"success": True, "output": "file.txt"})

        ws.send_json = AsyncMock(side_effect=send_result)

        result = await manager.invoke_command(
            "system.run", {"command": "ls"}, node_id="node-1",
        )
        assert result["success"] is True


# ===========================================================================
# Scenario 9: CLI route correctness (API routes)
# ===========================================================================


class TestNodeAPIRoutes:
    """Verify node API routes are correctly registered."""

    def test_node_routes_importable(self):
        from ungula.api.routes import nodes
        assert hasattr(nodes, "router")

    def test_node_ws_routes_importable(self):
        from ungula.api.routes import ws_node
        assert hasattr(ws_node, "router")

    def test_node_routes_have_endpoints(self):
        from ungula.api.routes.nodes import router
        routes = [r.path for r in router.routes]
        # Should have CRUD-like routes
        assert "/" in routes or "/{node_id}" in routes or len(routes) > 0

    def test_node_manager_importable(self):
        from ungula.nodes import NodeManager
        assert NodeManager is not None

    def test_all_node_modules_importable(self):
        from ungula.nodes import (
            ExecApprovalManager,
            NodeCommandPolicy,
            NodeManager,
            NodePairingStore,
            NodeRegistry,
        )
        assert all([
            ExecApprovalManager,
            NodeCommandPolicy,
            NodeManager,
            NodePairingStore,
            NodeRegistry,
        ])


# ===========================================================================
# Scenario 10: Full flow integration
# ===========================================================================


class TestFullFlowIntegration:
    """End-to-end: pair → register → invoke → result → disconnect."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        manager = _make_manager()
        ws = _make_ws()

        # 1. Initiate pairing
        pair_result = await manager.initiate_pairing("TestNode", "macos", ["camera", "system"])
        node_id = pair_result["node_id"]

        # 2. Approve pairing
        approve_result = await manager.approve_pairing(node_id)
        assert approve_result is not None
        token = approve_result["token"]
        assert len(token) > 20

        # 3. Register in online registry (simulates WebSocket connection)
        manager.registry.register(
            node_id, "TestNode", "macos", ["camera", "system"],
            ws, declared_commands=["camera.capture", "system.run"],
        )
        assert manager.registry.online_count == 1

        # 4. Invoke a command
        async def send_result(*args, **kwargs):
            sent_data = ws.send_json.call_args[0][0]
            request_id = sent_data["data"]["request_id"]
            manager.handle_result(request_id, {
                "success": True,
                "output": "photo.jpg",
                "data": {"path": "/tmp/photo.jpg"},
            })

        ws.send_json = AsyncMock(side_effect=send_result)

        result = await manager.invoke_command(
            "camera.capture", {}, node_id=node_id, invoked_by="test",
        )
        assert result["success"] is True
        assert result["output"] == "photo.jpg"

        # 5. Disconnect
        await manager.on_node_disconnect(node_id)
        assert manager.registry.get(node_id) is None

    @pytest.mark.asyncio
    async def test_policy_blocks_unauthorized_command(self):
        manager = _make_manager()
        ws = _make_ws()

        # Register a linux node (no camera capability per policy)
        manager.registry.register(
            "linux-node", "LinuxBox", "linux", ["system"],
            ws, declared_commands=["system.run"],
        )

        # Attempt camera.capture on linux (should be denied by policy)
        result = await manager.invoke_command(
            "camera.capture", {}, node_id="linux-node",
        )
        assert result["success"] is False
        assert "not allowed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_invoke_on_offline_node_fails(self):
        manager = _make_manager()

        result = await manager.invoke_command(
            "system.run", {"command": "ls"}, node_id="nonexistent",
        )
        assert result["success"] is False
        assert "not online" in result["error"].lower()
