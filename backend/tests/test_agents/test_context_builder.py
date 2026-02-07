"""
Tests for context assembly.

Covers SystemPromptBuilder, build_context, and _convert_to_llm_messages.
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ungula.agents.context import (
    SystemPromptBuilder,
    _convert_to_llm_messages,
    build_context,
)
from ungula.agents.prompt_sections import PromptMode
from ungula.llm.base import Message as LLMMessage, MessageRole
from ungula.storage.base import Message, StorageBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    role: str = "user",
    content: str = "Hello",
    conversation_id=None,
) -> Message:
    """Create a storage Message for testing."""
    now = datetime.now(UTC)
    return Message(
        id=uuid4(),
        conversation_id=conversation_id or uuid4(),
        role=role,
        content=content,
        created_at=now,
        metadata={},
    )


def _make_workspace(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """Create a temporary workspace with optional files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    if files:
        for name, content in files.items():
            (workspace / name).write_text(content)
    return workspace


# ===========================================================================
# SystemPromptBuilder
# ===========================================================================


class TestSystemPromptBuilder:
    """Tests for the SystemPromptBuilder class."""

    def test_build_with_soul_file(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "You are Ungula."})
        builder = SystemPromptBuilder(workspace)
        prompt = builder.build()
        assert "You are Ungula." in prompt

    def test_build_with_identity_file(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"IDENTITY.md": "I am an agent."})
        builder = SystemPromptBuilder(workspace)
        prompt = builder.build()
        assert "I am an agent." in prompt

    def test_build_with_empty_workspace(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        builder = SystemPromptBuilder(workspace)
        prompt = builder.build()
        # Should still produce a prompt (safety + runtime sections always render)
        assert isinstance(prompt, str)

    def test_build_with_skills_prompt(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Test soul."})
        builder = SystemPromptBuilder(workspace, skills_prompt="Skill: web_search")
        prompt = builder.build()
        assert "web_search" in prompt

    def test_build_with_tools_info(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Test."})
        tools = [{"name": "shell_exec", "description": "Execute shell commands"}]
        builder = SystemPromptBuilder(workspace, tools_info=tools)
        prompt = builder.build()
        assert "shell_exec" in prompt

    def test_build_with_memory_context(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Test."})
        memory = ["User prefers concise answers", "User is a Python developer"]
        builder = SystemPromptBuilder(workspace, memory_context=memory)
        prompt = builder.build()
        assert "concise answers" in prompt
        assert "Python developer" in prompt

    def test_build_minimal_mode(self, tmp_path):
        workspace = _make_workspace(
            tmp_path,
            {
                "SOUL.md": "You are Ungula.",
                "USER.md": "User context here.",
            },
        )
        builder = SystemPromptBuilder(workspace, mode=PromptMode.MINIMAL)
        prompt = builder.build()
        # Identity should be included in minimal mode
        assert "You are Ungula." in prompt
        # USER.md is only in FULL mode
        assert "User context here." not in prompt

    def test_build_none_mode(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Test."})
        builder = SystemPromptBuilder(workspace, mode=PromptMode.NONE)
        prompt = builder.build()
        assert prompt == ""

    def test_build_includes_safety_section(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Test."})
        builder = SystemPromptBuilder(workspace)
        prompt = builder.build()
        assert "Safety" in prompt

    def test_build_includes_runtime_section(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Test."})
        builder = SystemPromptBuilder(workspace)
        prompt = builder.build()
        assert "Runtime Context" in prompt

    def test_delegates_to_build_prompt_from_workspace(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Soul content."})
        with patch("ungula.agents.context.build_prompt_from_workspace") as mock_build:
            mock_build.return_value = "mocked prompt"
            builder = SystemPromptBuilder(workspace)
            result = builder.build()
            assert result == "mocked prompt"
            mock_build.assert_called_once_with(
                workspace_dir=workspace,
                mode=PromptMode.FULL,
                skills_prompt=None,
                tools_info=None,
                memory_context=None,
            )

    def test_delegates_with_all_args(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        with patch("ungula.agents.context.build_prompt_from_workspace") as mock_build:
            mock_build.return_value = "full prompt"
            builder = SystemPromptBuilder(
                workspace,
                skills_prompt="skills",
                tools_info=[{"name": "t", "description": "d"}],
                memory_context=["mem1"],
                mode=PromptMode.MINIMAL,
            )
            result = builder.build()
            mock_build.assert_called_once_with(
                workspace_dir=workspace,
                mode=PromptMode.MINIMAL,
                skills_prompt="skills",
                tools_info=[{"name": "t", "description": "d"}],
                memory_context=["mem1"],
            )


# ===========================================================================
# _convert_to_llm_messages
# ===========================================================================


class TestConvertToLLMMessages:
    """Tests for _convert_to_llm_messages."""

    def test_empty_list(self):
        result = _convert_to_llm_messages([])
        assert result == []

    def test_user_message_included(self):
        messages = [_make_message(role="user", content="Hello")]
        result = _convert_to_llm_messages(messages)
        assert len(result) == 1
        assert result[0].role == MessageRole.USER
        assert result[0].content == "Hello"

    def test_assistant_message_included(self):
        messages = [_make_message(role="assistant", content="Hi there")]
        result = _convert_to_llm_messages(messages)
        assert len(result) == 1
        assert result[0].role == MessageRole.ASSISTANT
        assert result[0].content == "Hi there"

    def test_system_message_excluded(self):
        messages = [_make_message(role="system", content="System message")]
        result = _convert_to_llm_messages(messages)
        assert len(result) == 0

    def test_tool_message_excluded(self):
        messages = [_make_message(role="tool", content="Tool output")]
        result = _convert_to_llm_messages(messages)
        assert len(result) == 0

    def test_mixed_roles(self):
        messages = [
            _make_message(role="system", content="Init"),
            _make_message(role="user", content="Q1"),
            _make_message(role="assistant", content="A1"),
            _make_message(role="tool", content="Result"),
            _make_message(role="user", content="Q2"),
            _make_message(role="assistant", content="A2"),
        ]
        result = _convert_to_llm_messages(messages)
        assert len(result) == 4
        assert result[0].content == "Q1"
        assert result[1].content == "A1"
        assert result[2].content == "Q2"
        assert result[3].content == "A2"

    def test_preserves_order(self):
        messages = [
            _make_message(role="user", content="First"),
            _make_message(role="assistant", content="Second"),
            _make_message(role="user", content="Third"),
        ]
        result = _convert_to_llm_messages(messages)
        assert [m.content for m in result] == ["First", "Second", "Third"]

    def test_returns_llm_message_type(self):
        messages = [_make_message(role="user", content="Test")]
        result = _convert_to_llm_messages(messages)
        assert isinstance(result[0], LLMMessage)

    def test_role_is_message_role_enum(self):
        messages = [
            _make_message(role="user", content="Hi"),
            _make_message(role="assistant", content="Hey"),
        ]
        result = _convert_to_llm_messages(messages)
        assert result[0].role == MessageRole.USER
        assert result[1].role == MessageRole.ASSISTANT

    def test_empty_content_preserved(self):
        messages = [_make_message(role="user", content="")]
        result = _convert_to_llm_messages(messages)
        assert len(result) == 1
        assert result[0].content == ""


# ===========================================================================
# build_context
# ===========================================================================


class TestBuildContext:
    """Tests for the build_context function."""

    async def test_returns_system_prompt_and_messages(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "You are Ungula."})
        conv_id = uuid4()
        storage = MagicMock()
        storage.list_messages = AsyncMock(return_value=[
            _make_message(role="user", content="Hello", conversation_id=conv_id),
            _make_message(role="assistant", content="Hi!", conversation_id=conv_id),
        ])

        system_prompt, llm_messages = await build_context(
            storage=storage,
            conversation_id=conv_id,
            workspace_dir=workspace,
        )

        assert "You are Ungula." in system_prompt
        assert len(llm_messages) == 2

    async def test_history_filtered_to_user_assistant(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Soul."})
        conv_id = uuid4()
        storage = MagicMock()
        storage.list_messages = AsyncMock(return_value=[
            _make_message(role="system", content="System msg"),
            _make_message(role="user", content="Question"),
            _make_message(role="assistant", content="Answer"),
        ])

        _, llm_messages = await build_context(
            storage=storage,
            conversation_id=conv_id,
            workspace_dir=workspace,
        )

        assert len(llm_messages) == 2  # system excluded

    async def test_max_history_passed_to_storage(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Soul."})
        conv_id = uuid4()
        storage = MagicMock()
        storage.list_messages = AsyncMock(return_value=[])

        await build_context(
            storage=storage,
            conversation_id=conv_id,
            workspace_dir=workspace,
            max_history=25,
        )

        storage.list_messages.assert_called_once_with(conv_id, limit=25)

    async def test_default_max_history(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Soul."})
        conv_id = uuid4()
        storage = MagicMock()
        storage.list_messages = AsyncMock(return_value=[])

        await build_context(
            storage=storage,
            conversation_id=conv_id,
            workspace_dir=workspace,
        )

        storage.list_messages.assert_called_once_with(conv_id, limit=50)

    async def test_empty_history(self, tmp_path):
        workspace = _make_workspace(tmp_path, {"SOUL.md": "Soul."})
        conv_id = uuid4()
        storage = MagicMock()
        storage.list_messages = AsyncMock(return_value=[])

        system_prompt, llm_messages = await build_context(
            storage=storage,
            conversation_id=conv_id,
            workspace_dir=workspace,
        )

        assert isinstance(system_prompt, str)
        assert llm_messages == []

    async def test_system_prompt_built_from_workspace(self, tmp_path):
        workspace = _make_workspace(
            tmp_path,
            {
                "SOUL.md": "You are a helpful agent.",
                "IDENTITY.md": "Your name is Ungula.",
            },
        )
        conv_id = uuid4()
        storage = MagicMock()
        storage.list_messages = AsyncMock(return_value=[])

        system_prompt, _ = await build_context(
            storage=storage,
            conversation_id=conv_id,
            workspace_dir=workspace,
        )

        assert "helpful agent" in system_prompt
        assert "Ungula" in system_prompt
