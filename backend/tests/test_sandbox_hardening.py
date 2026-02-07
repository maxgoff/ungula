"""
Tests for Docker sandbox hardening.

Verifies that the new security-hardening fields in SandboxConfig produce
correct Docker container configurations, and tests container reuse and
stale container pruning.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ungula.sandbox.config import SandboxConfig
from ungula.sandbox.docker import DockerSandbox


# ---------------------------------------------------------------------------
# SandboxConfig — new security fields
# ---------------------------------------------------------------------------


class TestSandboxConfigHardening:
    """Tests for new security-hardening fields on SandboxConfig."""

    def test_hardening_defaults(self):
        cfg = SandboxConfig()
        assert cfg.read_only_root is True
        assert cfg.cap_drop == ["ALL"]
        assert cfg.no_new_privileges is True
        assert cfg.pids_limit == 100
        assert cfg.tmpfs_mounts == ["/tmp", "/var/tmp", "/run"]
        assert cfg.user is None
        assert cfg.seccomp_profile is None
        assert cfg.dns == []
        assert cfg.extra_binds == []

    def test_container_management_defaults(self):
        cfg = SandboxConfig()
        assert cfg.container_prefix == "ungula-sbx-"
        assert cfg.max_idle_hours == 24
        assert cfg.reuse_containers is False

    def test_override_hardening_fields(self):
        cfg = SandboxConfig(
            read_only_root=False,
            cap_drop=["NET_RAW"],
            no_new_privileges=False,
            pids_limit=50,
            tmpfs_mounts=["/tmp"],
            user="1000:1000",
            seccomp_profile="/path/to/profile.json",
            dns=["8.8.8.8"],
            extra_binds=["/data:/data:ro"],
            container_prefix="test-sbx-",
            max_idle_hours=12,
            reuse_containers=True,
        )
        assert cfg.read_only_root is False
        assert cfg.cap_drop == ["NET_RAW"]
        assert cfg.no_new_privileges is False
        assert cfg.pids_limit == 50
        assert cfg.tmpfs_mounts == ["/tmp"]
        assert cfg.user == "1000:1000"
        assert cfg.seccomp_profile == "/path/to/profile.json"
        assert cfg.dns == ["8.8.8.8"]
        assert cfg.extra_binds == ["/data:/data:ro"]
        assert cfg.container_prefix == "test-sbx-"
        assert cfg.max_idle_hours == 12
        assert cfg.reuse_containers is True

    def test_serialization_includes_new_fields(self):
        cfg = SandboxConfig()
        d = cfg.model_dump()
        assert "read_only_root" in d
        assert "cap_drop" in d
        assert "no_new_privileges" in d
        assert "pids_limit" in d
        assert "tmpfs_mounts" in d
        assert "container_prefix" in d
        assert "reuse_containers" in d


# ---------------------------------------------------------------------------
# _build_container_config — hardened output
# ---------------------------------------------------------------------------


class TestBuildContainerConfigHardened:
    """Tests that _build_container_config applies security hardening options."""

    def _make_sandbox(self, workspace=None, **overrides):
        cfg = SandboxConfig(**overrides)
        return DockerSandbox(config=cfg, workspace_path=workspace)

    def test_read_only_root(self):
        sandbox = self._make_sandbox(read_only_root=True)
        config = sandbox._build_container_config("echo hi")
        assert config["read_only"] is True

    def test_read_only_root_disabled(self):
        sandbox = self._make_sandbox(read_only_root=False)
        config = sandbox._build_container_config("echo hi")
        assert "read_only" not in config

    def test_cap_drop_all(self):
        sandbox = self._make_sandbox(cap_drop=["ALL"])
        config = sandbox._build_container_config("echo hi")
        assert config["cap_drop"] == ["ALL"]

    def test_cap_drop_empty(self):
        sandbox = self._make_sandbox(cap_drop=[])
        config = sandbox._build_container_config("echo hi")
        assert "cap_drop" not in config

    def test_no_new_privileges(self):
        sandbox = self._make_sandbox(no_new_privileges=True)
        config = sandbox._build_container_config("echo hi")
        assert "no-new-privileges" in config["security_opt"]

    def test_no_new_privileges_disabled(self):
        sandbox = self._make_sandbox(no_new_privileges=False)
        config = sandbox._build_container_config("echo hi")
        assert "security_opt" not in config

    def test_seccomp_profile(self):
        sandbox = self._make_sandbox(seccomp_profile="/path/profile.json")
        config = sandbox._build_container_config("echo hi")
        assert "seccomp=/path/profile.json" in config["security_opt"]

    def test_pids_limit(self):
        sandbox = self._make_sandbox(pids_limit=100)
        config = sandbox._build_container_config("echo hi")
        assert config["pids_limit"] == 100

    def test_pids_limit_zero_skips(self):
        sandbox = self._make_sandbox(pids_limit=0)
        config = sandbox._build_container_config("echo hi")
        assert "pids_limit" not in config

    def test_tmpfs_mounts_with_read_only(self):
        sandbox = self._make_sandbox(
            read_only_root=True,
            tmpfs_mounts=["/tmp", "/var/tmp"],
        )
        config = sandbox._build_container_config("echo hi")
        assert "/tmp" in config["tmpfs"]
        assert "/var/tmp" in config["tmpfs"]
        # Each tmpfs mount should have size and noexec options
        assert "size=64m" in config["tmpfs"]["/tmp"]
        assert "noexec" in config["tmpfs"]["/tmp"]

    def test_tmpfs_mounts_without_read_only(self):
        sandbox = self._make_sandbox(
            read_only_root=False,
            tmpfs_mounts=["/tmp"],
        )
        config = sandbox._build_container_config("echo hi")
        # tmpfs only applied when read_only_root is True
        assert "tmpfs" not in config

    def test_user_set(self):
        sandbox = self._make_sandbox(user="1000:1000")
        config = sandbox._build_container_config("echo hi")
        assert config["user"] == "1000:1000"

    def test_user_not_set(self):
        sandbox = self._make_sandbox(user=None)
        config = sandbox._build_container_config("echo hi")
        assert "user" not in config

    def test_dns_servers(self):
        sandbox = self._make_sandbox(dns=["8.8.8.8", "1.1.1.1"])
        config = sandbox._build_container_config("echo hi")
        assert config["dns"] == ["8.8.8.8", "1.1.1.1"]

    def test_dns_empty(self):
        sandbox = self._make_sandbox(dns=[])
        config = sandbox._build_container_config("echo hi")
        assert "dns" not in config

    def test_extra_binds(self):
        ws = Path("/tmp/ws")
        sandbox = self._make_sandbox(
            workspace=ws,
            mount_mode="readonly",
            extra_binds=["/data:/mnt/data:ro", "/logs:/mnt/logs:rw"],
        )
        config = sandbox._build_container_config("echo hi")
        assert "/data" in config["volumes"]
        assert config["volumes"]["/data"]["bind"] == "/mnt/data"
        assert config["volumes"]["/data"]["mode"] == "ro"
        assert "/logs" in config["volumes"]
        assert config["volumes"]["/logs"]["mode"] == "rw"

    def test_labels_present(self):
        sandbox = self._make_sandbox()
        config = sandbox._build_container_config("echo hi")
        assert config["labels"]["ungula.sandbox"] == "1"
        assert "ungula.created_at" in config["labels"]
        assert "ungula.config_hash" in config["labels"]


# ---------------------------------------------------------------------------
# Config hash
# ---------------------------------------------------------------------------


class TestConfigHash:
    """Tests for _config_hash used in container reuse."""

    def test_same_config_same_hash(self):
        s1 = DockerSandbox(config=SandboxConfig())
        s2 = DockerSandbox(config=SandboxConfig())
        assert s1._config_hash() == s2._config_hash()

    def test_different_image_different_hash(self):
        s1 = DockerSandbox(config=SandboxConfig(image="python:3.11-slim"))
        s2 = DockerSandbox(config=SandboxConfig(image="node:20-slim"))
        assert s1._config_hash() != s2._config_hash()

    def test_hash_is_short(self):
        s = DockerSandbox(config=SandboxConfig())
        assert len(s._config_hash()) == 12


# ---------------------------------------------------------------------------
# Prune stale containers
# ---------------------------------------------------------------------------


class TestPruneStaleContainers:
    """Tests for prune_stale_containers method."""

    def test_prune_without_client(self):
        sandbox = DockerSandbox(config=SandboxConfig())
        assert sandbox.prune_stale_containers() == 0

    def test_prune_removes_old_containers(self):
        sandbox = DockerSandbox(config=SandboxConfig(max_idle_hours=1))

        old_time = str(int(time.time()) - 7200)  # 2 hours ago

        mock_container = MagicMock()
        mock_container.labels = {
            "ungula.sandbox": "1",
            "ungula.created_at": old_time,
        }
        mock_container.name = "old-container"

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        sandbox._client = mock_client

        pruned = sandbox.prune_stale_containers()
        assert pruned == 1
        mock_container.remove.assert_called_once_with(force=True)

    def test_prune_keeps_fresh_containers(self):
        sandbox = DockerSandbox(config=SandboxConfig(max_idle_hours=24))

        fresh_time = str(int(time.time()) - 3600)  # 1 hour ago (under 24h)

        mock_container = MagicMock()
        mock_container.labels = {
            "ungula.sandbox": "1",
            "ungula.created_at": fresh_time,
        }

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        sandbox._client = mock_client

        pruned = sandbox.prune_stale_containers()
        assert pruned == 0
        mock_container.remove.assert_not_called()


# ---------------------------------------------------------------------------
# Reusable container
# ---------------------------------------------------------------------------


class TestReusableContainer:
    """Tests for container reuse support."""

    def test_reuse_container_finds_existing(self):
        cfg = SandboxConfig(reuse_containers=True)
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.status = "running"

        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        sandbox._client = mock_client

        container = sandbox._get_or_create_container()
        assert container is mock_container
        mock_container.start.assert_not_called()  # Already running

    def test_reuse_container_starts_stopped(self):
        cfg = SandboxConfig(reuse_containers=True)
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.status = "exited"

        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        sandbox._client = mock_client

        container = sandbox._get_or_create_container()
        assert container is mock_container
        mock_container.start.assert_called_once()

    def test_reuse_container_creates_new_when_not_found(self):
        cfg = SandboxConfig(reuse_containers=True)
        sandbox = DockerSandbox(config=cfg)

        new_container = MagicMock()

        mock_client = MagicMock()
        mock_client.containers.get.side_effect = Exception("Not found")
        mock_client.containers.run.return_value = new_container
        sandbox._client = mock_client

        container = sandbox._get_or_create_container()
        assert container is new_container
        mock_client.containers.run.assert_called_once()

    def test_reusable_container_exec(self):
        """Verify _run_in_reusable_container uses exec_run."""
        cfg = SandboxConfig(reuse_containers=True)
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.status = "running"
        mock_container.exec_run.return_value = MagicMock(
            exit_code=0,
            output=(b"hello\n", b""),
        )

        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        sandbox._client = mock_client

        result = sandbox._run_in_reusable_container("echo hello", None, 30)

        assert result.exit_code == 0
        assert result.stdout == "hello\n"
        mock_container.exec_run.assert_called_once()


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    """Verify SandboxConfig is wired into UngulaConfig."""

    def test_sandbox_config_in_ungula_config(self):
        from ungula.config import UngulaConfig
        cfg = UngulaConfig()
        assert hasattr(cfg, "sandbox")
        assert isinstance(cfg.sandbox, SandboxConfig)
        assert cfg.sandbox.enabled is False

    def test_agent_runtime_config_in_ungula_config(self):
        from ungula.config import UngulaConfig, AgentRuntimeConfig
        cfg = UngulaConfig()
        assert hasattr(cfg, "agent_runtime")
        assert isinstance(cfg.agent_runtime, AgentRuntimeConfig)
        assert cfg.agent_runtime.max_context_tokens == 200_000
