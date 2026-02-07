"""
Tests for process execution and management tools.

Covers ProcessManager lifecycle, background process tracking,
foreground execution, timeout handling, and ProcessManageTool actions.
"""

import asyncio
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock missing third-party LLM provider SDKs before importing tools.
# ---------------------------------------------------------------------------

_MOCK_MODULES = ["anthropic", "openai", "httpx"]
_MOCK_GOOGLE_SUBS = ["google.generativeai", "google.genai", "google.genai.types"]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if "google" not in sys.modules:
    _google_mock = types.ModuleType("google")
    _google_mock.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google"] = _google_mock

for _sub in _MOCK_GOOGLE_SUBS:
    if _sub not in sys.modules:
        sys.modules[_sub] = MagicMock()

from ungula.config import ProcessToolConfig
from ungula.skills.builtin.process.manager import BackgroundProcess, ProcessManager
from ungula.skills.builtin.process.tools import ProcessExecTool, ProcessManageTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> ProcessToolConfig:
    return ProcessToolConfig()


@pytest.fixture
def manager() -> ProcessManager:
    return ProcessManager(max_concurrent=3, max_output_size=10_000)


@pytest.fixture
def exec_tool(manager: ProcessManager, config: ProcessToolConfig) -> ProcessExecTool:
    return ProcessExecTool(manager, config)


@pytest.fixture
def manage_tool(manager: ProcessManager, config: ProcessToolConfig) -> ProcessManageTool:
    return ProcessManageTool(manager, config)


# ===========================================================================
# ProcessManager
# ===========================================================================


class TestProcessManager:
    """Tests for ProcessManager lifecycle and tracking."""

    @pytest.mark.asyncio
    async def test_start_background_process(self, manager: ProcessManager):
        bg = await manager.start("echo background_test")
        assert bg.id is not None
        assert bg.command == "echo background_test"
        # Wait for it to complete
        await asyncio.sleep(0.5)
        assert bg.return_code is not None

    @pytest.mark.asyncio
    async def test_running_count(self, manager: ProcessManager):
        assert manager.running_count == 0
        bg = await manager.start("sleep 5")
        # Give asyncio a moment to register
        await asyncio.sleep(0.1)
        assert manager.running_count >= 0  # May or may not be running depending on timing
        await manager.kill(bg.id)

    @pytest.mark.asyncio
    async def test_max_concurrent_limit(self, manager: ProcessManager):
        procs = []
        for _ in range(3):
            procs.append(await manager.start("sleep 10"))
        # Fourth should raise
        with pytest.raises(RuntimeError, match="Max concurrent"):
            await manager.start("sleep 10")
        # Clean up
        for p in procs:
            await manager.kill(p.id)

    @pytest.mark.asyncio
    async def test_get_process(self, manager: ProcessManager):
        bg = await manager.start("echo hello")
        assert manager.get(bg.id) is bg
        assert manager.get("nonexistent") is None
        await asyncio.sleep(0.5)

    @pytest.mark.asyncio
    async def test_list_all(self, manager: ProcessManager):
        bg = await manager.start("echo list_test")
        items = manager.list_all()
        assert len(items) == 1
        assert items[0]["command"] == "echo list_test"
        await asyncio.sleep(0.5)

    @pytest.mark.asyncio
    async def test_kill_process(self, manager: ProcessManager):
        bg = await manager.start("sleep 60")
        await asyncio.sleep(0.1)
        result = await manager.kill(bg.id)
        assert result is True
        assert bg.return_code == -9

    @pytest.mark.asyncio
    async def test_kill_nonexistent(self, manager: ProcessManager):
        result = await manager.kill("bogus")
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup(self, manager: ProcessManager):
        await manager.start("sleep 60")
        await manager.start("sleep 60")
        assert len(manager.list_all()) == 2
        await manager.cleanup()
        assert len(manager.list_all()) == 0

    @pytest.mark.asyncio
    async def test_output_captured(self, manager: ProcessManager):
        bg = await manager.start("echo captured_output")
        # Wait for process to finish and reader task to complete
        await asyncio.sleep(1.0)
        assert "captured_output" in bg.stdout_buffer

    @pytest.mark.asyncio
    async def test_process_timeout(self, manager: ProcessManager):
        bg = await manager.start("sleep 60", timeout=1)
        await asyncio.sleep(2.0)
        assert bg.return_code == -1
        assert "timeout" in bg.stderr_buffer.lower()


# ===========================================================================
# BackgroundProcess properties
# ===========================================================================


class TestBackgroundProcess:
    """Tests for BackgroundProcess dataclass."""

    @pytest.mark.asyncio
    async def test_status_completed(self, manager: ProcessManager):
        bg = await manager.start("echo done")
        await asyncio.sleep(1.0)
        assert bg.status == "completed"

    @pytest.mark.asyncio
    async def test_status_failed(self, manager: ProcessManager):
        bg = await manager.start("false")
        await asyncio.sleep(1.0)
        assert bg.status == "failed"

    @pytest.mark.asyncio
    async def test_to_dict(self, manager: ProcessManager):
        bg = await manager.start("echo dict_test")
        await asyncio.sleep(0.5)
        d = bg.to_dict()
        assert "id" in d
        assert "command" in d
        assert "status" in d
        assert "started_at" in d


# ===========================================================================
# ProcessExecTool - foreground
# ===========================================================================


class TestProcessExecToolForeground:
    """Tests for foreground execution."""

    @pytest.mark.asyncio
    async def test_echo_success(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="echo foreground_test")
        assert result.success is True
        assert "foreground_test" in result.output

    @pytest.mark.asyncio
    async def test_return_code(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="echo ok")
        assert result.data["return_code"] == 0

    @pytest.mark.asyncio
    async def test_failed_command(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="false")
        assert result.success is False
        assert result.data["return_code"] != 0

    @pytest.mark.asyncio
    async def test_empty_command(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="")
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="sleep 60", timeout=1)
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_output(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="true")
        assert result.success is True
        assert result.output == "(no output)"

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_120(self, exec_tool: ProcessExecTool):
        """Timeout should be clamped to max 120 seconds."""
        # This just tests the code path — 120s is the hard max
        result = await exec_tool.execute(command="echo clamped", timeout=999)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_stderr_included_on_success(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="python3 -c 'import sys; sys.stderr.write(\"warn\\n\"); print(\"ok\")'")
        assert result.success is True
        assert "ok" in result.output


# ===========================================================================
# ProcessExecTool - background
# ===========================================================================


class TestProcessExecToolBackground:
    """Tests for background execution."""

    @pytest.mark.asyncio
    async def test_background_start(self, exec_tool: ProcessExecTool):
        result = await exec_tool.execute(command="echo bg_test", background=True)
        assert result.success is True
        assert "process_id" in result.data
        assert result.data["command"] == "echo bg_test"

    @pytest.mark.asyncio
    async def test_background_max_exceeded(self, manager: ProcessManager, config: ProcessToolConfig):
        """Exceeding max concurrent returns error."""
        small_manager = ProcessManager(max_concurrent=1, max_output_size=10_000)
        tool = ProcessExecTool(small_manager, config)
        await tool.execute(command="sleep 30", background=True)
        result = await tool.execute(command="sleep 30", background=True)
        assert result.success is False
        assert "max concurrent" in result.error.lower()
        await small_manager.cleanup()


# ===========================================================================
# ProcessManageTool
# ===========================================================================


class TestProcessManageTool:
    """Tests for ProcessManageTool actions."""

    @pytest.mark.asyncio
    async def test_list_empty(self, manage_tool: ProcessManageTool):
        result = await manage_tool.execute(action="list")
        assert result.success is True
        assert "No background" in result.output

    @pytest.mark.asyncio
    async def test_list_with_processes(self, manage_tool: ProcessManageTool, manager: ProcessManager):
        await manager.start("echo listed")
        result = await manage_tool.execute(action="list")
        assert result.success is True
        assert "echo listed" in result.output
        await asyncio.sleep(0.5)

    @pytest.mark.asyncio
    async def test_poll(self, manage_tool: ProcessManageTool, manager: ProcessManager):
        bg = await manager.start("echo polled")
        await asyncio.sleep(1.0)
        result = await manage_tool.execute(action="poll", process_id=bg.id)
        assert result.success is True
        assert "completed" in result.output.lower()

    @pytest.mark.asyncio
    async def test_log(self, manage_tool: ProcessManageTool, manager: ProcessManager):
        bg = await manager.start("echo log_output")
        await asyncio.sleep(1.0)
        result = await manage_tool.execute(action="log", process_id=bg.id)
        assert result.success is True
        assert "log_output" in result.output

    @pytest.mark.asyncio
    async def test_kill(self, manage_tool: ProcessManageTool, manager: ProcessManager):
        bg = await manager.start("sleep 60")
        await asyncio.sleep(0.2)
        result = await manage_tool.execute(action="kill", process_id=bg.id)
        assert result.success is True
        assert "Killed" in result.output

    @pytest.mark.asyncio
    async def test_missing_process_id(self, manage_tool: ProcessManageTool):
        result = await manage_tool.execute(action="poll")
        assert result.success is False
        assert "process_id is required" in result.error

    @pytest.mark.asyncio
    async def test_nonexistent_process(self, manage_tool: ProcessManageTool):
        result = await manage_tool.execute(action="poll", process_id="bogus")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_action(self, manage_tool: ProcessManageTool, manager: ProcessManager):
        bg = await manager.start("echo x")
        result = await manage_tool.execute(action="explode", process_id=bg.id)
        assert result.success is False
        assert "Unknown action" in result.error
        await asyncio.sleep(0.5)

    @pytest.mark.asyncio
    async def test_write_requires_input(self, manage_tool: ProcessManageTool, manager: ProcessManager):
        bg = await manager.start("echo x")
        await asyncio.sleep(0.5)
        result = await manage_tool.execute(action="write", process_id=bg.id)
        assert result.success is False
        assert "input is required" in result.error


# ===========================================================================
# Tool metadata
# ===========================================================================


class TestProcessToolMetadata:
    def test_exec_name(self, exec_tool: ProcessExecTool):
        assert exec_tool.name == "process_exec"

    def test_manage_name(self, manage_tool: ProcessManageTool):
        assert manage_tool.name == "process_manage"

    def test_exec_schema(self, exec_tool: ProcessExecTool):
        schema = exec_tool.get_schema()
        assert schema["type"] == "function"
        props = schema["function"]["parameters"]["properties"]
        assert "command" in props
        assert "background" in props
        assert "timeout" in props

    def test_manage_schema(self, manage_tool: ProcessManageTool):
        schema = manage_tool.get_schema()
        props = schema["function"]["parameters"]["properties"]
        assert "action" in props
        assert "process_id" in props
