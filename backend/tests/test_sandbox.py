"""
Tests for the Docker sandbox module.

Covers SandboxConfig, ExecutionResult, and DockerSandbox (with mocked Docker).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ungula.sandbox.config import SandboxConfig
from ungula.sandbox.docker import DockerSandbox, ExecutionResult


# ---------------------------------------------------------------------------
# SandboxConfig
# ---------------------------------------------------------------------------


class TestSandboxConfig:
    """Tests for SandboxConfig defaults and overrides."""

    def test_defaults(self):
        """SandboxConfig has sensible defaults."""
        cfg = SandboxConfig()
        assert cfg.enabled is False
        assert cfg.image == "python:3.11-slim"
        assert cfg.mount_mode == "readonly"
        assert cfg.working_dir == "/workspace"
        assert cfg.memory_limit == "256m"
        assert cfg.cpu_limit == 1.0
        assert cfg.timeout == 30
        assert cfg.network_enabled is False
        assert cfg.auto_cleanup is True

    def test_override_all_fields(self):
        """All fields can be explicitly overridden."""
        cfg = SandboxConfig(
            enabled=True,
            image="ubuntu:22.04",
            mount_mode="readwrite",
            working_dir="/app",
            memory_limit="512m",
            cpu_limit=2.0,
            timeout=60,
            network_enabled=True,
            auto_cleanup=False,
        )
        assert cfg.enabled is True
        assert cfg.image == "ubuntu:22.04"
        assert cfg.mount_mode == "readwrite"
        assert cfg.working_dir == "/app"
        assert cfg.memory_limit == "512m"
        assert cfg.cpu_limit == 2.0
        assert cfg.timeout == 60
        assert cfg.network_enabled is True
        assert cfg.auto_cleanup is False

    def test_mount_mode_none_string(self):
        """mount_mode accepts 'none' to disable mounts."""
        cfg = SandboxConfig(mount_mode="none")
        assert cfg.mount_mode == "none"

    def test_pydantic_model_serialization(self):
        """SandboxConfig is a Pydantic model and can be serialized."""
        cfg = SandboxConfig()
        d = cfg.model_dump()
        assert isinstance(d, dict)
        assert d["image"] == "python:3.11-slim"
        assert d["timeout"] == 30


# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionResult:
    """Tests for the ExecutionResult dataclass."""

    def test_basic_creation(self):
        result = ExecutionResult(exit_code=0, stdout="hello", stderr="")
        assert result.exit_code == 0
        assert result.stdout == "hello"
        assert result.stderr == ""
        assert result.timed_out is False

    def test_timed_out_flag(self):
        result = ExecutionResult(exit_code=124, stdout="", stderr="timeout", timed_out=True)
        assert result.timed_out is True
        assert result.exit_code == 124

    def test_error_result(self):
        result = ExecutionResult(exit_code=1, stdout="", stderr="command not found")
        assert result.exit_code == 1
        assert result.stderr == "command not found"


# ---------------------------------------------------------------------------
# DockerSandbox._build_container_config
# ---------------------------------------------------------------------------


class TestBuildContainerConfig:
    """Tests for DockerSandbox._build_container_config."""

    def _make_sandbox(
        self,
        workspace: Path | None = None,
        **config_overrides,
    ) -> DockerSandbox:
        cfg = SandboxConfig(**config_overrides)
        return DockerSandbox(config=cfg, workspace_path=workspace)

    def test_basic_config(self):
        """Minimal config produces correct base settings."""
        sandbox = self._make_sandbox()
        result = sandbox._build_container_config("echo hello")

        assert result["image"] == "python:3.11-slim"
        assert result["command"] == ["sh", "-c", "echo hello"]
        assert result["working_dir"] == "/workspace"
        assert result["detach"] is True
        assert result["mem_limit"] == "256m"
        assert result["nano_cpus"] == int(1.0 * 1e9)
        assert result["auto_remove"] is False

    def test_network_disabled(self):
        """When network_enabled=False, network_mode is 'none'."""
        sandbox = self._make_sandbox(network_enabled=False)
        result = sandbox._build_container_config("ls")
        assert result["network_mode"] == "none"

    def test_network_enabled(self):
        """When network_enabled=True, network_mode is not set."""
        sandbox = self._make_sandbox(network_enabled=True)
        result = sandbox._build_container_config("curl example.com")
        assert "network_mode" not in result

    def test_env_vars_passed(self):
        """Environment variables are forwarded when provided."""
        sandbox = self._make_sandbox()
        result = sandbox._build_container_config("env", env={"FOO": "bar", "BAZ": "1"})
        assert result["environment"] == {"FOO": "bar", "BAZ": "1"}

    def test_env_vars_omitted_when_none(self):
        """No environment key when env is None."""
        sandbox = self._make_sandbox()
        result = sandbox._build_container_config("echo hi", env=None)
        assert "environment" not in result

    def test_mount_readonly(self):
        """Readonly mount mode produces 'ro' volume binding."""
        ws = Path("/tmp/test-workspace")
        sandbox = self._make_sandbox(workspace=ws, mount_mode="readonly")
        result = sandbox._build_container_config("cat file.py")

        assert "volumes" in result
        assert str(ws) in result["volumes"]
        vol = result["volumes"][str(ws)]
        assert vol["bind"] == "/workspace"
        assert vol["mode"] == "ro"

    def test_mount_readwrite(self):
        """Readwrite mount mode produces 'rw' volume binding."""
        ws = Path("/tmp/test-workspace")
        sandbox = self._make_sandbox(workspace=ws, mount_mode="readwrite")
        result = sandbox._build_container_config("touch file.txt")

        vol = result["volumes"][str(ws)]
        assert vol["mode"] == "rw"

    def test_mount_none(self):
        """mount_mode='none' produces no volumes even with workspace_path."""
        ws = Path("/tmp/test-workspace")
        sandbox = self._make_sandbox(workspace=ws, mount_mode="none")
        result = sandbox._build_container_config("echo hi")
        assert "volumes" not in result

    def test_no_workspace_path_no_volumes(self):
        """Without workspace_path, no volumes are created regardless of mount mode."""
        sandbox = self._make_sandbox(workspace=None, mount_mode="readwrite")
        result = sandbox._build_container_config("pwd")
        assert "volumes" not in result

    def test_custom_image_and_working_dir(self):
        """Custom image and working_dir are reflected in config."""
        sandbox = self._make_sandbox(image="node:20-slim", working_dir="/app")
        result = sandbox._build_container_config("node -e 'console.log(1)'")

        assert result["image"] == "node:20-slim"
        assert result["working_dir"] == "/app"

    def test_cpu_limit_conversion(self):
        """cpu_limit is converted to nano_cpus correctly."""
        sandbox = self._make_sandbox(cpu_limit=0.5)
        result = sandbox._build_container_config("echo")
        assert result["nano_cpus"] == int(0.5 * 1e9)

        sandbox2 = self._make_sandbox(cpu_limit=4.0)
        result2 = sandbox2._build_container_config("echo")
        assert result2["nano_cpus"] == int(4.0 * 1e9)


# ---------------------------------------------------------------------------
# DockerSandbox.execute
# ---------------------------------------------------------------------------


class TestDockerSandboxExecute:
    """Tests for DockerSandbox.execute with mocked Docker client."""

    @pytest.mark.asyncio
    async def test_execute_without_client(self):
        """Returns error when Docker client is not initialised."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)
        # _client is None by default

        result = await sandbox.execute("echo hello")

        assert result.exit_code == 1
        assert result.stderr == "Docker client not initialized"
        assert result.stdout == ""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Successful command execution returns stdout/stderr and exit code."""
        cfg = SandboxConfig(timeout=10)
        sandbox = DockerSandbox(config=cfg)

        # Mock the _run_container to return a success result
        expected = ExecutionResult(exit_code=0, stdout="hello world\n", stderr="")

        with patch.object(sandbox, "_run_container", return_value=expected):
            sandbox._client = MagicMock()  # Pretend client is initialised
            result = await sandbox.execute("echo hello world")

        assert result.exit_code == 0
        assert result.stdout == "hello world\n"
        assert result.stderr == ""
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """Command that exceeds timeout returns timed_out=True."""
        cfg = SandboxConfig(timeout=1)
        sandbox = DockerSandbox(config=cfg)
        sandbox._client = MagicMock()

        # Simulate asyncio.wait_for raising TimeoutError
        async def slow_executor(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await sandbox.execute("sleep 999")

        assert result.exit_code == 124
        assert result.timed_out is True
        assert "timed out" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_execute_general_exception(self):
        """Generic exceptions are caught and returned as errors."""
        cfg = SandboxConfig(timeout=10)
        sandbox = DockerSandbox(config=cfg)
        sandbox._client = MagicMock()

        with patch.object(sandbox, "_run_container", side_effect=RuntimeError("Docker crashed")):
            # We need to also make sure the event loop executor runs our mock.
            # Patch the entire wait_for path:
            async def run_and_raise(*args, **kwargs):
                raise RuntimeError("Docker crashed")

            with patch("asyncio.wait_for", side_effect=RuntimeError("Docker crashed")):
                result = await sandbox.execute("bad command")

        assert result.exit_code == 1
        assert "Docker crashed" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_uses_override_timeout(self):
        """When timeout is passed to execute(), it overrides config timeout."""
        cfg = SandboxConfig(timeout=30)
        sandbox = DockerSandbox(config=cfg)
        sandbox._client = MagicMock()

        expected = ExecutionResult(exit_code=0, stdout="ok", stderr="")

        with patch("asyncio.get_event_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop

            with patch("asyncio.wait_for", return_value=expected) as mock_wait:
                result = await sandbox.execute("echo ok", timeout=5)

                # wait_for should be called with timeout = 5 + 5 = 10
                call_kwargs = mock_wait.call_args
                assert call_kwargs[1]["timeout"] == 10  # 5 + 5 overhead

        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_uses_config_timeout_by_default(self):
        """When no timeout override, config.timeout is used."""
        cfg = SandboxConfig(timeout=20)
        sandbox = DockerSandbox(config=cfg)
        sandbox._client = MagicMock()

        expected = ExecutionResult(exit_code=0, stdout="", stderr="")

        with patch("asyncio.get_event_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop_fn.return_value = mock_loop

            with patch("asyncio.wait_for", return_value=expected) as mock_wait:
                await sandbox.execute("ls")

                call_kwargs = mock_wait.call_args
                assert call_kwargs[1]["timeout"] == 25  # 20 + 5 overhead

    @pytest.mark.asyncio
    async def test_execute_passes_env(self):
        """Environment variables are included in the container config."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)
        sandbox._client = MagicMock()

        with patch.object(sandbox, "_build_container_config", wraps=sandbox._build_container_config) as mock_build:
            expected = ExecutionResult(exit_code=0, stdout="", stderr="")
            with patch.object(sandbox, "_run_container", return_value=expected):
                with patch("asyncio.wait_for", return_value=expected):
                    await sandbox.execute("env", env={"MY_VAR": "123"})

            mock_build.assert_called_once_with("env", {"MY_VAR": "123"})


# ---------------------------------------------------------------------------
# DockerSandbox._run_container
# ---------------------------------------------------------------------------


class TestRunContainer:
    """Tests for DockerSandbox._run_container (synchronous helper)."""

    def test_successful_run(self):
        """Successful container run returns stdout/stderr/exit code."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [
            b"output line\n",  # stdout=True, stderr=False
            b"",               # stdout=False, stderr=True
        ]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        sandbox._client = mock_client

        container_config = sandbox._build_container_config("echo output line")
        result = sandbox._run_container(container_config)

        assert result.exit_code == 0
        assert result.stdout == "output line\n"
        assert result.stderr == ""

        # Container should be removed when auto_cleanup=True
        mock_container.remove.assert_called_once_with(force=True)

    def test_failed_run(self):
        """Non-zero exit code is captured."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 127}
        mock_container.logs.side_effect = [
            b"",
            b"sh: command not found\n",
        ]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        sandbox._client = mock_client

        container_config = sandbox._build_container_config("nonexistent_cmd")
        result = sandbox._run_container(container_config)

        assert result.exit_code == 127
        assert "command not found" in result.stderr

    def test_exception_during_run(self):
        """Docker exceptions are caught and returned as errors."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)

        mock_client = MagicMock()
        mock_client.containers.run.side_effect = Exception("Image not found")
        sandbox._client = mock_client

        container_config = sandbox._build_container_config("echo")
        result = sandbox._run_container(container_config)

        assert result.exit_code == 1
        assert "Image not found" in result.stderr

    def test_auto_cleanup_disabled(self):
        """Container.remove() is not called when auto_cleanup=False."""
        cfg = SandboxConfig(auto_cleanup=False)
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [b"", b""]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        sandbox._client = mock_client

        container_config = sandbox._build_container_config("echo")
        sandbox._run_container(container_config)

        mock_container.remove.assert_not_called()

    def test_cleanup_error_is_swallowed(self):
        """If container.remove() raises, it does not propagate."""
        cfg = SandboxConfig(auto_cleanup=True)
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [b"ok\n", b""]
        mock_container.remove.side_effect = Exception("remove failed")

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        sandbox._client = mock_client

        container_config = sandbox._build_container_config("echo ok")
        result = sandbox._run_container(container_config)

        # The result should still be successful despite remove() failing
        assert result.exit_code == 0
        assert result.stdout == "ok\n"

    def test_missing_status_code_defaults_to_1(self):
        """If StatusCode is missing from wait(), default to 1."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)

        mock_container = MagicMock()
        mock_container.wait.return_value = {}  # No StatusCode key
        mock_container.logs.side_effect = [b"", b""]

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        sandbox._client = mock_client

        container_config = sandbox._build_container_config("echo")
        result = sandbox._run_container(container_config)

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# DockerSandbox.initialize
# ---------------------------------------------------------------------------


class TestDockerSandboxInitialize:
    """Tests for DockerSandbox.initialize."""

    @pytest.mark.asyncio
    async def test_initialize_docker_available(self):
        """Returns True and sets _client when Docker is available."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)

        mock_client = MagicMock()
        mock_client.ping.return_value = True

        # Inject a fake 'docker' module into sys.modules
        mock_docker_module = MagicMock()
        mock_docker_module.from_env.return_value = mock_client

        saved = sys.modules.get("docker")
        sys.modules["docker"] = mock_docker_module
        try:
            result = await sandbox.initialize()
        finally:
            if saved is not None:
                sys.modules["docker"] = saved
            else:
                sys.modules.pop("docker", None)

        assert result is True
        assert sandbox._client is mock_client
        mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_docker_not_installed(self):
        """Returns False when docker package is not installed."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)

        # Setting sys.modules["docker"] = None causes import to raise ImportError
        saved = sys.modules.get("docker")
        sys.modules["docker"] = None  # type: ignore[assignment]
        try:
            result = await sandbox.initialize()
        finally:
            if saved is not None:
                sys.modules["docker"] = saved
            else:
                sys.modules.pop("docker", None)

        assert result is False
        assert sandbox._client is None

    @pytest.mark.asyncio
    async def test_initialize_docker_not_running(self):
        """Returns False when Docker daemon is not running."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)

        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("Connection refused")

        mock_docker_module = MagicMock()
        mock_docker_module.from_env.return_value = mock_client

        saved = sys.modules.get("docker")
        sys.modules["docker"] = mock_docker_module
        try:
            result = await sandbox.initialize()
        finally:
            if saved is not None:
                sys.modules["docker"] = saved
            else:
                sys.modules.pop("docker", None)

        assert result is False


# ---------------------------------------------------------------------------
# DockerSandbox.cleanup
# ---------------------------------------------------------------------------


class TestDockerSandboxCleanup:
    """Tests for DockerSandbox.cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_closes_client(self):
        """cleanup() calls close() on the Docker client and sets it to None."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)
        mock_client = MagicMock()
        sandbox._client = mock_client

        await sandbox.cleanup()

        mock_client.close.assert_called_once()
        assert sandbox._client is None

    @pytest.mark.asyncio
    async def test_cleanup_without_client(self):
        """cleanup() is safe to call when _client is None."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)
        assert sandbox._client is None

        # Should not raise
        await sandbox.cleanup()
        assert sandbox._client is None

    @pytest.mark.asyncio
    async def test_cleanup_swallows_close_error(self):
        """If client.close() raises, it does not propagate."""
        cfg = SandboxConfig()
        sandbox = DockerSandbox(config=cfg)
        mock_client = MagicMock()
        mock_client.close.side_effect = Exception("close error")
        sandbox._client = mock_client

        await sandbox.cleanup()

        assert sandbox._client is None
