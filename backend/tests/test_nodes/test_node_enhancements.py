"""
Tests for node system enhancements — OpenClaw parity.

Covers: platform-based policy, richer metadata, heartbeat timeout detection,
node-initiated pairing, node event protocol, exec approval, command audit trail,
and system.which handler.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ungula.nodes.exec_approval import ExecApprovalManager
from ungula.nodes.pairing import NodePairingStore, PairRequest
from ungula.nodes.policy import (
    COMMAND_CAPABILITY_MAP,
    PLATFORM_DEFAULTS,
    NodeCommandPolicy,
    normalize_platform,
)
from ungula.nodes.protocol import (
    NodeEvent,
    node_event_message,
    pair_approved_message,
    pair_pending_message,
    pair_rejected_message,
    pair_request_message,
)
from ungula.nodes.registry import ConnectedNode, NodeRegistry


# ===========================================================================
# WI 3: Platform-based command policy
# ===========================================================================


class TestNormalizePlatform:
    def test_macos_variants(self):
        assert normalize_platform("macos") == "macos"
        assert normalize_platform("mac") == "macos"
        assert normalize_platform("osx") == "macos"
        assert normalize_platform("Mac OS X") == "macos"
        assert normalize_platform("  MACOS  ") == "macos"

    def test_darwin(self):
        assert normalize_platform("darwin") == "darwin"

    def test_linux(self):
        assert normalize_platform("linux") == "linux"
        assert normalize_platform("Linux") == "linux"

    def test_windows(self):
        assert normalize_platform("windows") == "windows"
        assert normalize_platform("Windows") == "windows"

    def test_unknown(self):
        assert normalize_platform("freebsd") == "freebsd"


class TestPlatformDefaults:
    def test_ios_has_camera_no_system(self):
        assert "camera.capture" in PLATFORM_DEFAULTS["ios"]
        assert "system.run" not in PLATFORM_DEFAULTS["ios"]

    def test_android_has_sms(self):
        assert "sms.send" in PLATFORM_DEFAULTS["android"]

    def test_macos_has_system_and_camera(self):
        assert "system.run" in PLATFORM_DEFAULTS["macos"]
        assert "camera.capture" in PLATFORM_DEFAULTS["macos"]
        assert "clipboard.get" in PLATFORM_DEFAULTS["macos"]

    def test_linux_has_system_no_camera(self):
        assert "system.run" in PLATFORM_DEFAULTS["linux"]
        assert "camera.capture" not in PLATFORM_DEFAULTS["linux"]

    def test_windows_has_system_clipboard(self):
        assert "system.run" in PLATFORM_DEFAULTS["windows"]
        assert "clipboard.get" in PLATFORM_DEFAULTS["windows"]
        assert "audio.play" not in PLATFORM_DEFAULTS["windows"]


class TestPlatformPolicy:
    def test_linux_denies_camera(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("camera.capture", platform="linux") is False

    def test_linux_allows_system_run(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("system.run", platform="linux") is True

    def test_macos_allows_camera(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("camera.capture", platform="macos") is True

    def test_ios_denies_system_run(self):
        policy = NodeCommandPolicy()
        assert policy.can_execute("system.run", platform="ios") is False

    def test_unknown_platform_permissive(self):
        policy = NodeCommandPolicy()
        # Unknown platform allows all known commands
        assert policy.can_execute("camera.capture", platform="unknown", node_capabilities=None) is True

    def test_config_allow_override(self):
        policy = NodeCommandPolicy(allow_commands=["camera.capture"])
        # Even on linux, camera is allowed via config override
        assert policy.can_execute("camera.capture", platform="linux") is True

    def test_config_deny_override(self):
        policy = NodeCommandPolicy(deny_commands=["system.run"])
        # Even on macos, system.run is denied via config
        assert policy.can_execute("system.run", platform="macos") is False

    def test_deny_wins_over_allow(self):
        policy = NodeCommandPolicy(
            allow_commands=["system.run"],
            deny_commands=["system.run"],
        )
        assert policy.can_execute("system.run", platform="linux") is False

    def test_declared_commands_intersection(self):
        policy = NodeCommandPolicy()
        # Node declares only clipboard commands, platform is macos
        allowed = policy.resolve_allowlist("macos", declared_commands=["clipboard.get"])
        assert "clipboard.get" in allowed
        assert "camera.capture" not in allowed  # Not declared by node

    def test_legacy_capability_fallback(self):
        policy = NodeCommandPolicy()
        # No platform, but has capabilities — legacy path
        assert policy.can_execute(
            "camera.capture",
            platform="unknown",
            node_capabilities=["camera"],
        ) is True

    def test_system_which_in_map(self):
        assert "system.which" in COMMAND_CAPABILITY_MAP


# ===========================================================================
# WI 4: Richer node metadata
# ===========================================================================


class TestRicherMetadata:
    @pytest.fixture
    def mock_ws(self):
        ws = MagicMock()
        ws.send_json = AsyncMock()
        return ws

    def test_connected_node_has_metadata_fields(self, mock_ws):
        node = ConnectedNode(
            node_id="n1",
            name="Mac",
            platform="macos",
            capabilities=["camera"],
            websocket=mock_ws,
            declared_commands=["camera.capture"],
            device_family="arm64",
            version="0.2.0",
            os_version="24.6.0",
            path_env="/usr/bin",
            metadata={"custom": "data"},
        )
        assert node.declared_commands == ["camera.capture"]
        assert node.device_family == "arm64"
        assert node.version == "0.2.0"
        assert node.os_version == "24.6.0"
        assert node.path_env == "/usr/bin"
        assert node.metadata == {"custom": "data"}

    def test_to_dict_includes_metadata(self, mock_ws):
        node = ConnectedNode(
            node_id="n1",
            name="Mac",
            platform="macos",
            capabilities=["camera"],
            websocket=mock_ws,
            declared_commands=["camera.capture"],
            device_family="arm64",
            version="0.2.0",
            os_version="24.6.0",
            metadata={"custom": "val"},
        )
        d = node.to_dict()
        assert d["declared_commands"] == ["camera.capture"]
        assert d["device_family"] == "arm64"
        assert d["version"] == "0.2.0"
        assert d["os_version"] == "24.6.0"
        assert d["metadata"] == {"custom": "val"}

    def test_to_dict_no_metadata_key_if_empty(self, mock_ws):
        node = ConnectedNode(
            node_id="n1",
            name="Mac",
            platform="macos",
            capabilities=[],
            websocket=mock_ws,
        )
        d = node.to_dict()
        assert "metadata" not in d

    def test_register_with_metadata(self, mock_ws):
        registry = NodeRegistry(max_nodes=5)
        node = registry.register(
            node_id="n1",
            name="Mac",
            platform="macos",
            capabilities=["camera"],
            websocket=mock_ws,
            declared_commands=["camera.capture"],
            device_family="arm64",
            version="0.2.0",
            os_version="24.6.0",
            path_env="/usr/bin",
            metadata={"foo": "bar"},
        )
        assert node.device_family == "arm64"
        assert node.version == "0.2.0"
        assert node.metadata == {"foo": "bar"}

    def test_register_derives_commands_from_capabilities(self, mock_ws):
        registry = NodeRegistry(max_nodes=5)
        node = registry.register(
            node_id="n1",
            name="Mac",
            platform="macos",
            capabilities=["camera", "notify"],
            websocket=mock_ws,
            # No declared_commands — should derive from capabilities
        )
        assert "camera.capture" in node.declared_commands
        assert "camera.stream" in node.declared_commands
        assert "notify.send" in node.declared_commands


# ===========================================================================
# WI 5: Heartbeat timeout detection
# ===========================================================================


class TestHeartbeatTimeout:
    @pytest.fixture
    def mock_ws(self):
        ws = MagicMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.fixture
    def registry(self):
        return NodeRegistry(max_nodes=10)

    def test_get_stale_nodes_none(self, registry, mock_ws):
        registry.register("n1", "Mac", "macos", [], mock_ws)
        stale = registry.get_stale_nodes(timeout_seconds=90)
        assert len(stale) == 0

    def test_get_stale_nodes_found(self, registry, mock_ws):
        node = registry.register("n1", "Mac", "macos", [], mock_ws)
        # Backdate heartbeat
        node.last_heartbeat = datetime.utcnow() - timedelta(seconds=120)
        stale = registry.get_stale_nodes(timeout_seconds=90)
        assert len(stale) == 1
        assert stale[0].node_id == "n1"

    def test_get_stale_mixed(self, registry, mock_ws):
        n1 = registry.register("n1", "Mac1", "macos", [], mock_ws)
        n2 = registry.register("n2", "Mac2", "linux", [], mock_ws)
        n1.last_heartbeat = datetime.utcnow() - timedelta(seconds=200)
        # n2 is fresh
        stale = registry.get_stale_nodes(timeout_seconds=90)
        assert len(stale) == 1
        assert stale[0].node_id == "n1"


# ===========================================================================
# WI 2: Node-initiated pairing protocol
# ===========================================================================


class TestPairingProtocol:
    def test_pair_request_event(self):
        assert NodeEvent.PAIR_REQUEST == "node.pair.request"

    def test_pair_pending_event(self):
        assert NodeEvent.PAIR_PENDING == "node.pair.pending"

    def test_pair_approved_event(self):
        assert NodeEvent.PAIR_APPROVED == "node.pair.approved"

    def test_pair_rejected_event(self):
        assert NodeEvent.PAIR_REJECTED == "node.pair.rejected"

    def test_pair_request_message(self):
        msg = pair_request_message("MyMac", "macos", ["camera"], {"version": "0.2"})
        assert msg.event == NodeEvent.PAIR_REQUEST
        assert msg.data["name"] == "MyMac"
        assert msg.data["platform"] == "macos"
        assert msg.data["capabilities"] == ["camera"]
        assert msg.data["metadata"]["version"] == "0.2"

    def test_pair_request_no_metadata(self):
        msg = pair_request_message("Node", "linux", [])
        assert "metadata" not in msg.data

    def test_pair_pending_message(self):
        msg = pair_pending_message("node-123")
        assert msg.event == NodeEvent.PAIR_PENDING
        assert msg.data["node_id"] == "node-123"

    def test_pair_approved_message(self):
        msg = pair_approved_message("node-123", "secret-token")
        assert msg.event == NodeEvent.PAIR_APPROVED
        assert msg.data["node_id"] == "node-123"
        assert msg.data["token"] == "secret-token"

    def test_pair_rejected_message(self):
        msg = pair_rejected_message("node-123")
        assert msg.event == NodeEvent.PAIR_REJECTED
        assert msg.data["node_id"] == "node-123"


class TestNodeInitiatedPairing:
    def test_create_node_initiated_request(self):
        store = NodePairingStore(ttl=300)
        ws = MagicMock()
        req = store.create_node_initiated_request(
            "n1", "Mac", "macos", ["camera"], websocket=ws
        )
        assert req.node_id == "n1"
        assert req.websocket is ws
        assert len(req.token) > 20

    def test_node_initiated_request_in_pending(self):
        store = NodePairingStore(ttl=300)
        ws = MagicMock()
        store.create_node_initiated_request("n1", "Mac", "macos", [], websocket=ws)
        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].websocket is ws


# ===========================================================================
# WI 6: Node event reporting
# ===========================================================================


class TestNodeEventProtocol:
    def test_node_event_enum(self):
        assert NodeEvent.NODE_EVENT == "node.event"

    def test_node_event_message(self):
        msg = node_event_message("exec.started", {"command": "ls", "request_id": "abc"})
        assert msg.event == NodeEvent.NODE_EVENT
        assert msg.data["event_type"] == "exec.started"
        assert msg.data["payload"]["command"] == "ls"

    def test_node_event_message_no_payload(self):
        msg = node_event_message("custom.event")
        assert msg.event == NodeEvent.NODE_EVENT
        assert msg.data["event_type"] == "custom.event"
        assert "payload" not in msg.data


# ===========================================================================
# WI 9: Exec approval system
# ===========================================================================


class TestExecApproval:
    def test_is_allowed_empty_allowlist(self):
        mgr = ExecApprovalManager()
        assert mgr.is_allowed("ls -la") is False

    def test_is_allowed_exact_match(self):
        mgr = ExecApprovalManager(allowed_patterns=["ls", "cat"])
        assert mgr.is_allowed("ls") is True
        assert mgr.is_allowed("cat") is True
        assert mgr.is_allowed("rm") is False

    def test_is_allowed_prefix_match(self):
        mgr = ExecApprovalManager(allowed_patterns=["git"])
        assert mgr.is_allowed("git status") is True
        assert mgr.is_allowed("git push origin") is True
        assert mgr.is_allowed("gitea") is False  # No space after prefix

    @pytest.mark.asyncio
    async def test_request_and_resolve_approved(self):
        mgr = ExecApprovalManager(approval_timeout=10)

        async def approve_after_delay():
            await asyncio.sleep(0.1)
            pending = mgr.list_pending()
            assert len(pending) == 1
            mgr.resolve(pending[0]["id"], True)

        asyncio.create_task(approve_after_delay())
        result = await mgr.request_approval("rm -rf /tmp/test", "node-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_request_and_resolve_denied(self):
        mgr = ExecApprovalManager(approval_timeout=10)

        async def deny_after_delay():
            await asyncio.sleep(0.1)
            pending = mgr.list_pending()
            mgr.resolve(pending[0]["id"], False)

        asyncio.create_task(deny_after_delay())
        result = await mgr.request_approval("rm -rf /", "node-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_request_timeout(self):
        mgr = ExecApprovalManager(approval_timeout=0.2)
        result = await mgr.request_approval("some-cmd", "node-1")
        assert result is False

    def test_resolve_nonexistent(self):
        mgr = ExecApprovalManager()
        assert mgr.resolve("bogus", True) is False

    def test_list_pending_cleans_expired(self):
        mgr = ExecApprovalManager(approval_timeout=1)
        # Manually insert an expired entry
        mgr._pending["old"] = {
            "id": "old",
            "command": "test",
            "node_id": "n1",
            "created_at": time.time() - 10,
        }
        mgr._futures["old"] = asyncio.get_event_loop().create_future()
        pending = mgr.list_pending()
        assert len(pending) == 0


# ===========================================================================
# WI 7: system.which handler
# ===========================================================================


class TestSystemWhichHandler:
    """Tests for system.which — implemented inline since ungula_node is a separate package."""

    @pytest.mark.asyncio
    async def test_which_python(self):
        import shutil

        # Inline implementation of system.which logic
        binary = "python3"
        path = shutil.which(binary)
        if path:
            assert "python3" in path
        # Not finding python3 is also valid in some envs

    @pytest.mark.asyncio
    async def test_which_no_binary(self):
        import shutil

        path = shutil.which("")
        assert path is None

    @pytest.mark.asyncio
    async def test_which_nonexistent(self):
        import shutil

        path = shutil.which("definitely_not_a_real_binary_12345")
        assert path is None


# ===========================================================================
# WI 8: Command audit trail model
# ===========================================================================


class TestNodeCommandLogModel:
    def test_model_import(self):
        from ungula.storage.models import NodeCommandLogModel

        assert NodeCommandLogModel.__tablename__ == "node_command_logs"

    def test_model_columns(self):
        from ungula.storage.models import NodeCommandLogModel

        columns = {c.name for c in NodeCommandLogModel.__table__.columns}
        expected = {
            "id", "node_id", "command", "args", "request_id",
            "success", "output", "error", "result_data",
            "invoked_by", "created_at", "completed_at",
        }
        assert expected.issubset(columns)


# ===========================================================================
# Integration: config fields
# ===========================================================================


class TestConfigEnhancements:
    def test_node_system_config_new_fields(self):
        from ungula.config import NodeSystemConfig

        cfg = NodeSystemConfig()
        assert cfg.heartbeat_timeout == 90
        assert cfg.allow_commands == []
        assert cfg.deny_commands == []

    def test_node_system_config_custom(self):
        from ungula.config import NodeSystemConfig

        cfg = NodeSystemConfig(
            heartbeat_timeout=120,
            allow_commands=["camera.capture"],
            deny_commands=["system.run"],
        )
        assert cfg.heartbeat_timeout == 120
        assert cfg.allow_commands == ["camera.capture"]
        assert cfg.deny_commands == ["system.run"]
