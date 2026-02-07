"""
Tests for the KIU (Know Its User) learning loop.

Covers:
- Session memory (slug generation, file writing, message formatting)
- Boot execution (empty BOOT.md, task parsing)
- Bootstrap detection (template markers, fresh workspace)
- Context isolation (SUBAGENT mode filtering)
- DailyMemorySection (file discovery, date filtering)
- Workspace write tool (allowlist, denylist, memory/ paths)
- Heartbeat memory review prompt
"""

import asyncio
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory with standard files."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "SOUL.md").write_text("You are a helpful assistant.")
    (ws / "IDENTITY.md").write_text("Name: TestBot")
    (ws / "USER.md").write_text("The user likes Python.")
    (ws / "AGENTS.md").write_text("## Agents Guide\nUse tools wisely.")
    (ws / "TOOLS.md").write_text("## Tools Notes")
    (ws / "MEMORY.md").write_text("## Long Term Memory")
    (ws / "HEARTBEAT.md").write_text("- [ ] Check status\n- [x] Done task\n- [ ] Review logs")
    return ws


@pytest.fixture
def mock_storage():
    """Create a mock storage backend."""
    storage = AsyncMock()
    storage.list_messages = AsyncMock(return_value=[])
    storage.list_conversations = AsyncMock(return_value=[])
    storage.create_conversation = AsyncMock()
    return storage


@pytest.fixture
def mock_registry():
    """Create a mock LLM provider registry."""
    registry = AsyncMock()
    response = MagicMock()
    response.content = "bug-fix"
    registry.complete = AsyncMock(return_value=response)
    return registry


@pytest.fixture
def mock_messages():
    """Create mock message objects."""
    msgs = []
    for i in range(5):
        msg = MagicMock()
        msg.role = "user" if i % 2 == 0 else "assistant"
        msg.content = f"Message {i} content"
        msgs.append(msg)
    return msgs


# ============================================================
# Slug Generator Tests
# ============================================================

class TestSlugGenerator:
    """Tests for slug_generator.py."""

    @pytest.mark.asyncio
    async def test_generate_slug_success(self, mock_registry):
        from ungula.hooks.slug_generator import generate_slug

        mock_registry.complete.return_value.content = "vendor-pitch"
        slug = await generate_slug("Some conversation content", mock_registry)
        assert slug == "vendor-pitch"

    @pytest.mark.asyncio
    async def test_generate_slug_sanitizes_output(self, mock_registry):
        from ungula.hooks.slug_generator import generate_slug

        mock_registry.complete.return_value.content = "  Bug Fix!!  "
        slug = await generate_slug("Some content", mock_registry)
        assert slug == "bugfix"  # Special chars stripped

    @pytest.mark.asyncio
    async def test_generate_slug_timeout(self, mock_registry):
        from ungula.hooks.slug_generator import generate_slug

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(15)  # Exceeds 10s timeout
            return MagicMock(content="late-slug")

        mock_registry.complete = slow_complete
        slug = await generate_slug("Content", mock_registry)
        assert slug is None

    @pytest.mark.asyncio
    async def test_generate_slug_exception(self, mock_registry):
        from ungula.hooks.slug_generator import generate_slug

        mock_registry.complete.side_effect = Exception("LLM down")
        slug = await generate_slug("Content", mock_registry)
        assert slug is None

    @pytest.mark.asyncio
    async def test_generate_slug_empty_response(self, mock_registry):
        from ungula.hooks.slug_generator import generate_slug

        mock_registry.complete.return_value.content = ""
        slug = await generate_slug("Content", mock_registry)
        assert slug is None

    @pytest.mark.asyncio
    async def test_generate_slug_too_long(self, mock_registry):
        from ungula.hooks.slug_generator import generate_slug

        mock_registry.complete.return_value.content = "a" * 50  # > 40 chars
        slug = await generate_slug("Content", mock_registry)
        assert slug is None


# ============================================================
# Session Memory Tests
# ============================================================

class TestSessionMemory:
    """Tests for session_memory.py."""

    @pytest.mark.asyncio
    async def test_save_session_memory_success(self, workspace, mock_storage, mock_messages):
        from ungula.hooks.session_memory import save_session_memory

        mock_storage.list_messages.return_value = mock_messages
        filepath = await save_session_memory(
            storage=mock_storage,
            conversation_id=uuid4(),
            workspace_dir=workspace,
        )

        assert filepath is not None
        assert filepath.endswith(".md")
        assert (workspace / "memory").exists()

        # Check file was created with today's date
        memory_files = list((workspace / "memory").glob("*.md"))
        assert len(memory_files) == 1
        assert date.today().isoformat() in memory_files[0].name

    @pytest.mark.asyncio
    async def test_save_session_memory_too_few_messages(self, workspace, mock_storage):
        from ungula.hooks.session_memory import save_session_memory

        # Only 1 message — should skip
        msg = MagicMock()
        msg.role = "user"
        msg.content = "Hi"
        mock_storage.list_messages.return_value = [msg]

        filepath = await save_session_memory(
            storage=mock_storage,
            conversation_id=uuid4(),
            workspace_dir=workspace,
        )
        assert filepath is None

    @pytest.mark.asyncio
    async def test_save_session_memory_with_slug(self, workspace, mock_storage, mock_messages, mock_registry):
        from ungula.hooks.session_memory import save_session_memory

        mock_storage.list_messages.return_value = mock_messages
        mock_registry.complete.return_value.content = "api-design"

        filepath = await save_session_memory(
            storage=mock_storage,
            conversation_id=uuid4(),
            workspace_dir=workspace,
            registry=mock_registry,
        )

        assert filepath is not None
        assert "api-design" in filepath

    @pytest.mark.asyncio
    async def test_save_session_memory_creates_memory_dir(self, tmp_path, mock_storage, mock_messages):
        from ungula.hooks.session_memory import save_session_memory

        ws = tmp_path / "fresh_workspace"
        ws.mkdir()
        # No memory/ subdirectory exists yet

        mock_storage.list_messages.return_value = mock_messages
        filepath = await save_session_memory(
            storage=mock_storage,
            conversation_id=uuid4(),
            workspace_dir=ws,
        )

        assert filepath is not None
        assert (ws / "memory").is_dir()

    def test_format_messages_for_summary(self, mock_messages):
        from ungula.hooks.session_memory import format_messages_for_summary

        result = format_messages_for_summary(mock_messages)
        assert "**USER**:" in result
        assert "**ASSISTANT**:" in result
        assert "Message 0 content" in result

    def test_format_memory_file(self, mock_messages):
        from ungula.hooks.session_memory import format_memory_file

        conv_id = uuid4()
        result = format_memory_file(conv_id, mock_messages)
        assert "# Session Memory" in result
        assert str(conv_id) in result
        assert "Messages**: 5" in result


# ============================================================
# Boot Execution Tests
# ============================================================

class TestBootExecution:
    """Tests for boot.py."""

    @pytest.mark.asyncio
    async def test_boot_no_file(self, tmp_path):
        from ungula.hooks.boot import run_boot_tasks

        result = await run_boot_tasks(tmp_path, None)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_boot_file"

    @pytest.mark.asyncio
    async def test_boot_empty_file(self, workspace):
        from ungula.hooks.boot import run_boot_tasks

        (workspace / "BOOT.md").write_text("# Boot\n")
        result = await run_boot_tasks(workspace, None)
        assert result["status"] == "skipped"
        assert result["reason"] == "empty_content"

    @pytest.mark.asyncio
    async def test_boot_only_comments(self, workspace):
        from ungula.hooks.boot import run_boot_tasks

        (workspace / "BOOT.md").write_text("# Boot Tasks\n# Nothing here\n")
        result = await run_boot_tasks(workspace, None)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_boot_with_tasks(self, workspace, mock_storage):
        from ungula.hooks.boot import run_boot_tasks

        (workspace / "BOOT.md").write_text("# Boot\nCheck system health\nVerify connections")

        mock_runner = AsyncMock()
        mock_runner.storage = mock_storage
        conv = MagicMock()
        conv.id = uuid4()
        mock_storage.create_conversation.return_value = conv

        response = MagicMock()
        response.content = "All systems healthy. BOOT_OK"
        mock_runner.run = AsyncMock(return_value=response)

        result = await run_boot_tasks(workspace, mock_runner)
        assert result["status"] == "completed_ok"
        assert "conversation_id" in result

    @pytest.mark.asyncio
    async def test_boot_failure(self, workspace, mock_storage):
        from ungula.hooks.boot import run_boot_tasks

        (workspace / "BOOT.md").write_text("# Boot\nDo something important")

        mock_runner = AsyncMock()
        mock_runner.storage = mock_storage
        mock_storage.create_conversation.side_effect = Exception("DB error")

        result = await run_boot_tasks(workspace, mock_runner)
        assert result["status"] == "failed"
        assert "error" in result


# ============================================================
# Bootstrap Detection Tests
# ============================================================

class TestBootstrap:
    """Tests for bootstrap.py."""

    def test_no_bootstrap_file(self, workspace):
        from ungula.hooks.bootstrap import check_bootstrap_needed

        assert check_bootstrap_needed(workspace) is False

    def test_bootstrap_with_template_identity(self, workspace):
        from ungula.hooks.bootstrap import check_bootstrap_needed

        (workspace / "BOOTSTRAP.md").write_text("Hey. I just came online. Who am I?")
        (workspace / "IDENTITY.md").write_text("# Identity\n[Your name here]\nFill in your details")
        assert check_bootstrap_needed(workspace) is True

    def test_bootstrap_with_filled_identity(self, workspace):
        from ungula.hooks.bootstrap import check_bootstrap_needed

        (workspace / "BOOTSTRAP.md").write_text("Hey. I just came online. Who am I?")
        (workspace / "IDENTITY.md").write_text("# Identity\nI am Max's assistant.\nI help with coding.")
        assert check_bootstrap_needed(workspace) is False

    def test_bootstrap_no_identity_file(self, tmp_path):
        from ungula.hooks.bootstrap import check_bootstrap_needed

        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "BOOTSTRAP.md").write_text("Hey. I just came online.")
        # No IDENTITY.md at all
        assert check_bootstrap_needed(ws) is True

    def test_bootstrap_empty_bootstrap_file(self, workspace):
        from ungula.hooks.bootstrap import check_bootstrap_needed

        (workspace / "BOOTSTRAP.md").write_text("")
        assert check_bootstrap_needed(workspace) is False

    @pytest.mark.asyncio
    async def test_run_bootstrap(self, workspace, mock_storage):
        from ungula.hooks.bootstrap import run_bootstrap

        (workspace / "BOOTSTRAP.md").write_text("Who am I?")

        mock_runner = AsyncMock()
        mock_runner.storage = mock_storage
        conv = MagicMock()
        conv.id = uuid4()
        mock_storage.create_conversation.return_value = conv
        response = MagicMock()
        response.content = "Bootstrap complete"
        mock_runner.run = AsyncMock(return_value=response)

        result = await run_bootstrap(workspace, mock_runner)
        assert result["status"] == "completed"


# ============================================================
# Context Isolation Tests (SUBAGENT mode)
# ============================================================

class TestContextIsolation:
    """Tests for PromptMode.SUBAGENT filtering."""

    def test_subagent_mode_exists(self):
        from ungula.agents.prompt_sections import PromptMode

        assert hasattr(PromptMode, "SUBAGENT")
        assert PromptMode.SUBAGENT.value == "subagent"

    def test_identity_not_in_subagent(self, workspace):
        from ungula.agents.prompt_sections import IdentitySection, PromptMode

        section = IdentitySection(workspace)
        assert section.is_active(PromptMode.FULL)
        assert section.is_active(PromptMode.MINIMAL)
        assert not section.is_active(PromptMode.SUBAGENT)

    def test_user_not_in_subagent(self, workspace):
        from ungula.agents.prompt_sections import UserSection, PromptMode

        section = UserSection(workspace)
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.SUBAGENT)
        assert not section.is_active(PromptMode.MINIMAL)

    def test_agents_in_subagent(self, workspace):
        from ungula.agents.prompt_sections import AgentsSection, PromptMode

        section = AgentsSection(workspace)
        assert section.is_active(PromptMode.FULL)
        assert section.is_active(PromptMode.SUBAGENT)

    def test_memory_not_in_subagent(self):
        from ungula.agents.prompt_sections import MemorySection, PromptMode

        section = MemorySection()
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.SUBAGENT)

    def test_daily_memory_not_in_subagent(self, workspace):
        from ungula.agents.prompt_sections import DailyMemorySection, PromptMode

        section = DailyMemorySection(workspace)
        assert section.is_active(PromptMode.FULL)
        assert not section.is_active(PromptMode.SUBAGENT)

    def test_subagent_prompt_excludes_personal(self, workspace):
        from ungula.agents.prompt_sections import build_prompt_from_workspace, PromptMode

        full_prompt = build_prompt_from_workspace(workspace, mode=PromptMode.FULL)
        subagent_prompt = build_prompt_from_workspace(workspace, mode=PromptMode.SUBAGENT)

        # Full includes user content
        assert "The user likes Python" in full_prompt
        assert "You are a helpful assistant" in full_prompt

        # Subagent excludes personal context but includes agents
        assert "The user likes Python" not in subagent_prompt
        assert "Use tools wisely" in subagent_prompt

    def test_session_type_mapping(self):
        from ungula.agents.context import _SESSION_TYPE_MAP, SystemPromptBuilder
        from ungula.agents.prompt_sections import PromptMode

        assert _SESSION_TYPE_MAP["main"] == PromptMode.FULL
        assert _SESSION_TYPE_MAP["subagent"] == PromptMode.SUBAGENT
        assert _SESSION_TYPE_MAP["group"] == PromptMode.SUBAGENT

    def test_system_prompt_builder_session_type(self, workspace):
        from ungula.agents.context import SystemPromptBuilder
        from ungula.agents.prompt_sections import PromptMode

        builder = SystemPromptBuilder(workspace, session_type="subagent")
        assert builder.mode == PromptMode.SUBAGENT

        prompt = builder.build()
        assert "The user likes Python" not in prompt
        assert "Use tools wisely" in prompt


# ============================================================
# DailyMemorySection Tests
# ============================================================

class TestDailyMemorySection:
    """Tests for DailyMemorySection prompt section."""

    def test_no_memory_dir(self, workspace):
        from ungula.agents.prompt_sections import DailyMemorySection

        section = DailyMemorySection(workspace)
        # No memory/ directory exists
        result = section.render()
        assert result is None

    def test_empty_memory_dir(self, workspace):
        from ungula.agents.prompt_sections import DailyMemorySection

        (workspace / "memory").mkdir()
        section = DailyMemorySection(workspace)
        result = section.render()
        assert result is None

    def test_today_memory_file(self, workspace):
        from ungula.agents.prompt_sections import DailyMemorySection

        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        today = date.today().isoformat()
        (memory_dir / f"{today}-test.md").write_text("Today's session notes")

        section = DailyMemorySection(workspace)
        result = section.render()
        assert result is not None
        assert "## Recent Memory" in result
        assert "Today's session notes" in result

    def test_yesterday_memory_file(self, workspace):
        from ungula.agents.prompt_sections import DailyMemorySection

        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        (memory_dir / f"{yesterday}-review.md").write_text("Yesterday's review")

        section = DailyMemorySection(workspace)
        result = section.render()
        assert result is not None
        assert "Yesterday's review" in result

    def test_old_memory_file_excluded(self, workspace):
        from ungula.agents.prompt_sections import DailyMemorySection

        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        old_date = (date.today() - timedelta(days=5)).isoformat()
        (memory_dir / f"{old_date}-old.md").write_text("Old notes")

        section = DailyMemorySection(workspace)
        result = section.render()
        assert result is None  # Old files excluded

    def test_mixed_dates(self, workspace):
        from ungula.agents.prompt_sections import DailyMemorySection

        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        today = date.today().isoformat()
        old_date = (date.today() - timedelta(days=5)).isoformat()
        (memory_dir / f"{today}-recent.md").write_text("Recent notes")
        (memory_dir / f"{old_date}-old.md").write_text("Old notes")

        section = DailyMemorySection(workspace)
        result = section.render()
        assert result is not None
        assert "Recent notes" in result
        assert "Old notes" not in result

    def test_included_in_full_prompt(self, workspace):
        from ungula.agents.prompt_sections import build_prompt_from_workspace, PromptMode

        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        today = date.today().isoformat()
        (memory_dir / f"{today}-session.md").write_text("Session context here")

        prompt = build_prompt_from_workspace(workspace, mode=PromptMode.FULL)
        assert "Recent Memory" in prompt
        assert "Session context here" in prompt


# ============================================================
# BootstrapSection Tests
# ============================================================

class TestBootstrapSection:
    """Tests for BootstrapSection prompt section."""

    def test_no_bootstrap_file(self, workspace):
        from ungula.agents.prompt_sections import BootstrapSection

        section = BootstrapSection(workspace)
        result = section.render()
        assert result is None

    def test_bootstrap_file_present(self, workspace):
        from ungula.agents.prompt_sections import BootstrapSection

        (workspace / "BOOTSTRAP.md").write_text("Hey. I just came online. Who am I?")
        section = BootstrapSection(workspace)
        result = section.render()
        assert result is not None
        assert "Bootstrap — First Run" in result
        assert "Who am I?" in result

    def test_bootstrap_priority(self, workspace):
        from ungula.agents.prompt_sections import BootstrapSection

        section = BootstrapSection(workspace)
        assert section.priority == 5  # Before identity (10)


# ============================================================
# Workspace Write Tool Tests
# ============================================================

class TestWorkspaceWriteTool:
    """Tests for workspace_write tool."""

    @pytest.fixture
    def tool(self, workspace):
        from ungula.skills.builtin.workspace_write.tool import WorkspaceWriteTool

        return WorkspaceWriteTool(workspace)

    @pytest.mark.asyncio
    async def test_write_allowed_file(self, tool, workspace):
        result = await tool.execute(file="USER.md", content="New user info")
        assert result.success
        assert (workspace / "USER.md").read_text() == "New user info"

    @pytest.mark.asyncio
    async def test_write_memory_md(self, tool, workspace):
        result = await tool.execute(file="MEMORY.md", content="New memory")
        assert result.success
        assert (workspace / "MEMORY.md").read_text() == "New memory"

    @pytest.mark.asyncio
    async def test_write_identity_md(self, tool, workspace):
        result = await tool.execute(file="IDENTITY.md", content="I am TestBot v2")
        assert result.success

    @pytest.mark.asyncio
    async def test_append_mode(self, tool, workspace):
        (workspace / "MEMORY.md").write_text("Existing content\n")
        result = await tool.execute(file="MEMORY.md", content="Appended content", mode="append")
        assert result.success
        assert "Existing content\nAppended content" in (workspace / "MEMORY.md").read_text()

    @pytest.mark.asyncio
    async def test_denied_agents_md(self, tool):
        result = await tool.execute(file="AGENTS.md", content="overwrite")
        assert not result.success
        assert "protected" in result.error

    @pytest.mark.asyncio
    async def test_denied_bootstrap_md(self, tool):
        result = await tool.execute(file="BOOTSTRAP.md", content="overwrite")
        assert not result.success
        assert "protected" in result.error

    @pytest.mark.asyncio
    async def test_write_memory_file(self, tool, workspace):
        result = await tool.execute(
            file="memory/2026-01-15-bug-fix.md",
            content="Fixed the auth bug",
        )
        assert result.success
        assert (workspace / "memory" / "2026-01-15-bug-fix.md").exists()

    @pytest.mark.asyncio
    async def test_write_memory_file_creates_dir(self, tmp_path):
        from ungula.skills.builtin.workspace_write.tool import WorkspaceWriteTool

        ws = tmp_path / "fresh"
        ws.mkdir()
        tool = WorkspaceWriteTool(ws)
        result = await tool.execute(
            file="memory/2026-02-01-test.md",
            content="Test content",
        )
        assert result.success
        assert (ws / "memory" / "2026-02-01-test.md").exists()

    @pytest.mark.asyncio
    async def test_invalid_file_rejected(self, tool):
        result = await tool.execute(file="config.yaml", content="bad")
        assert not result.success
        assert "Cannot write" in result.error

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, tool):
        result = await tool.execute(file="../../../etc/passwd", content="bad")
        assert not result.success

    @pytest.mark.asyncio
    async def test_missing_content(self, tool):
        result = await tool.execute(file="USER.md", content="")
        assert not result.success
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_invalid_mode(self, tool):
        result = await tool.execute(file="USER.md", content="test", mode="delete")
        assert not result.success
        assert "Mode must be" in result.error

    @pytest.mark.asyncio
    async def test_invalid_memory_path_rejected(self, tool):
        result = await tool.execute(file="memory/invalid.txt", content="bad")
        assert not result.success

    @pytest.mark.asyncio
    async def test_memory_path_with_date_only(self, tool, workspace):
        result = await tool.execute(
            file="memory/2026-03-15.md",
            content="Just a date",
        )
        assert result.success


# ============================================================
# Heartbeat Memory Review Tests
# ============================================================

class TestHeartbeatMemoryReview:
    """Tests for build_heartbeat_prompt."""

    @pytest.mark.asyncio
    async def test_heartbeat_with_tasks(self, workspace):
        from ungula.cron.heartbeat import build_heartbeat_prompt

        prompt = await build_heartbeat_prompt(workspace)
        assert prompt is not None
        assert "Heartbeat Tasks" in prompt
        assert "Check status" in prompt

    @pytest.mark.asyncio
    async def test_heartbeat_with_memory_review(self, workspace):
        from ungula.cron.heartbeat import build_heartbeat_prompt

        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        today = date.today().isoformat()
        (memory_dir / f"{today}-session.md").write_text("Session notes")

        prompt = await build_heartbeat_prompt(workspace)
        assert prompt is not None
        assert "Memory Review" in prompt
        assert f"{today}-session.md" in prompt

    @pytest.mark.asyncio
    async def test_heartbeat_no_tasks_no_memory(self, tmp_path):
        from ungula.cron.heartbeat import build_heartbeat_prompt

        ws = tmp_path / "workspace"
        ws.mkdir()
        prompt = await build_heartbeat_prompt(ws)
        assert prompt is None

    @pytest.mark.asyncio
    async def test_heartbeat_old_memory_excluded(self, workspace):
        from ungula.cron.heartbeat import build_heartbeat_prompt

        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        old_date = (date.today() - timedelta(days=10)).isoformat()
        (memory_dir / f"{old_date}-old.md").write_text("Old notes")

        # Remove heartbeat tasks
        (workspace / "HEARTBEAT.md").write_text("# Heartbeat")

        prompt = await build_heartbeat_prompt(workspace)
        # No tasks and no recent memory = None
        assert prompt is None

    @pytest.mark.asyncio
    async def test_run_heartbeat_basic(self, workspace):
        from ungula.cron.heartbeat import run_heartbeat

        result = await run_heartbeat(workspace)
        assert result["content"] is not None
        assert len(result["tasks"]) == 2  # "Check status" and "Review logs"
        assert "Check status" in result["tasks"]
        assert "Review logs" in result["tasks"]
