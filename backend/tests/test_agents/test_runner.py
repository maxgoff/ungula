"""
Tests for the AgentRunner.

Covers run(), _build_messages(), _execute_tool_call(),
_build_clarification_response(), _response_to_stream(),
_get_filtered_tool_definitions(), and tool loop behavior.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ungula.agents.intent import IntentClassification, IntentType
from ungula.agents.runner import AgentRunner
from ungula.llm.base import (
    CompletionResponse,
    Message as LLMMessage,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)
from ungula.storage.base import Message, MessageCreate
from ungula.tools.base import Tool, ToolParameter, ToolRegistry, ToolResult
from ungula.tools.policy import PolicyEngine, PolicyProfile, ToolPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage_message(
    role: str = "user",
    content: str = "Hello",
    conversation_id=None,
    metadata=None,
) -> Message:
    """Create a storage Message for testing."""
    now = datetime.now(UTC)
    return Message(
        id=uuid4(),
        conversation_id=conversation_id or uuid4(),
        role=role,
        content=content,
        created_at=now,
        metadata=metadata or {},
    )


class _FakeTool(Tool):
    """A minimal Tool for testing."""

    def __init__(self, name: str = "test_tool", description: str = "A test tool"):
        self.name = name
        self.description = description
        self.parameters = [
            ToolParameter(name="query", description="The query", type="string"),
        ]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output=f"Result for: {kwargs.get('query', '')}")


def _make_storage_mock(history=None, clarification_history=None):
    """Create an AsyncMock for StorageBackend."""
    storage = AsyncMock()
    storage.create_message = AsyncMock(
        return_value=_make_storage_message()
    )
    storage.list_messages = AsyncMock(
        return_value=history or []
    )
    storage.get_conversation = AsyncMock(return_value=None)
    storage.update_conversation = AsyncMock(return_value=None)
    return storage


def _make_registry_mock(content="Hello!", tool_calls=None):
    """Create a MagicMock for ProviderRegistry."""
    response = CompletionResponse(
        content=content,
        model="test-model",
        provider="test-provider",
        tool_calls=tool_calls,
        finish_reason="stop",
    )
    registry = MagicMock()
    registry.complete = AsyncMock(return_value=response)
    registry.list_providers = MagicMock(return_value=[])
    registry.list_models = AsyncMock(return_value={})
    return registry


def _make_runner(
    storage=None,
    registry=None,
    workspace_dir=None,
    tool_registry=None,
    skill_registry=None,
    policy_engine=None,
    max_tool_iterations=10,
):
    """Create an AgentRunner with sensible test defaults."""
    return AgentRunner(
        storage=storage or _make_storage_mock(),
        registry=registry or _make_registry_mock(),
        workspace_dir=workspace_dir or Path("/tmp/test_workspace"),
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        policy_engine=policy_engine,
        max_tool_iterations=max_tool_iterations,
    )


# ===========================================================================
# _build_messages
# ===========================================================================


class TestBuildMessages:
    """Tests for AgentRunner._build_messages."""

    def test_basic_messages(self):
        runner = _make_runner()
        messages = runner._build_messages(
            system_prompt="You are helpful.",
            history=[],
            current_user_message="Hello",
        )
        assert len(messages) == 2
        assert messages[0].role == MessageRole.SYSTEM
        assert messages[0].content == "You are helpful."
        assert messages[1].role == MessageRole.USER
        assert messages[1].content == "Hello"

    def test_with_history(self):
        runner = _make_runner()
        history = [
            _make_storage_message(role="user", content="Q1"),
            _make_storage_message(role="assistant", content="A1"),
        ]
        messages = runner._build_messages(
            system_prompt="System.",
            history=history,
            current_user_message="Q2",
        )
        # system + 2 history + current user
        assert len(messages) == 4
        assert messages[1].content == "Q1"
        assert messages[2].content == "A1"
        assert messages[3].content == "Q2"

    def test_history_filters_non_user_assistant(self):
        runner = _make_runner()
        history = [
            _make_storage_message(role="system", content="Init"),
            _make_storage_message(role="user", content="Q1"),
            _make_storage_message(role="tool", content="Result"),
            _make_storage_message(role="assistant", content="A1"),
        ]
        messages = runner._build_messages(
            system_prompt="System.",
            history=history,
            current_user_message=None,
        )
        # system + user Q1 + assistant A1 (system/tool from history excluded)
        assert len(messages) == 3

    def test_with_compaction_summary(self):
        runner = _make_runner()
        messages = runner._build_messages(
            system_prompt="System.",
            history=[],
            current_user_message="Hello",
            compaction_summary="Earlier we discussed Python.",
        )
        # system + compaction summary system msg + user
        assert len(messages) == 3
        assert messages[1].role == MessageRole.SYSTEM
        assert "Summary of earlier conversation" in messages[1].content
        assert "Earlier we discussed Python." in messages[1].content

    def test_compaction_summary_before_history(self):
        runner = _make_runner()
        history = [
            _make_storage_message(role="user", content="Q1"),
        ]
        messages = runner._build_messages(
            system_prompt="System.",
            history=history,
            current_user_message="Q2",
            compaction_summary="Summary here.",
        )
        # system + compaction + history(Q1) + current(Q2) = 4
        assert len(messages) == 4
        assert messages[0].role == MessageRole.SYSTEM  # main system prompt
        assert messages[1].role == MessageRole.SYSTEM  # compaction summary
        assert messages[2].role == MessageRole.USER    # Q1 from history
        assert messages[3].role == MessageRole.USER    # Q2 current

    def test_no_current_user_message(self):
        runner = _make_runner()
        messages = runner._build_messages(
            system_prompt="System.",
            history=[],
            current_user_message=None,
        )
        # Only system prompt
        assert len(messages) == 1
        assert messages[0].role == MessageRole.SYSTEM

    def test_empty_string_current_message_not_appended(self):
        runner = _make_runner()
        messages = runner._build_messages(
            system_prompt="System.",
            history=[],
            current_user_message="",
        )
        # Empty string is falsy, so not appended
        assert len(messages) == 1

    def test_no_compaction_summary_means_no_extra_system_msg(self):
        runner = _make_runner()
        messages = runner._build_messages(
            system_prompt="System.",
            history=[],
            current_user_message="Hello",
            compaction_summary=None,
        )
        # system + user only (no summary)
        assert len(messages) == 2


# ===========================================================================
# _execute_tool_call
# ===========================================================================


class TestExecuteToolCall:
    """Tests for AgentRunner._execute_tool_call."""

    async def test_valid_json_arguments(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool())
        runner = _make_runner(tool_registry=tool_registry)

        tc = ToolCall(id="tc-1", name="test_tool", arguments='{"query": "test"}')
        result, log = await runner._execute_tool_call(tc, iteration=1)

        assert result.success is True
        assert "Result for: test" in result.output
        assert log["name"] == "test_tool"
        assert log["success"] is True
        assert log["iteration"] == 1

    async def test_invalid_json_arguments(self):
        runner = _make_runner()
        tc = ToolCall(id="tc-2", name="test_tool", arguments="not valid json")
        result, log = await runner._execute_tool_call(tc, iteration=1)

        assert result.success is False
        assert "Invalid JSON arguments" in result.error
        assert log["success"] is False
        assert log["error"] == "Invalid JSON arguments"

    async def test_empty_arguments(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool())
        runner = _make_runner(tool_registry=tool_registry)

        tc = ToolCall(id="tc-3", name="test_tool", arguments="")
        result, log = await runner._execute_tool_call(tc, iteration=1)

        assert result.success is True
        assert log["arguments"] == {}

    async def test_none_arguments(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool())
        runner = _make_runner(tool_registry=tool_registry)

        tc = ToolCall(id="tc-4", name="test_tool", arguments=None)
        result, log = await runner._execute_tool_call(tc, iteration=2)

        assert result.success is True
        assert log["iteration"] == 2

    async def test_no_tool_registry(self):
        runner = _make_runner(tool_registry=None)
        tc = ToolCall(id="tc-5", name="test_tool", arguments='{"query": "test"}')
        result, log = await runner._execute_tool_call(tc, iteration=1)

        assert result.success is False
        assert "No tool registry available" in result.error

    async def test_unknown_tool(self):
        tool_registry = ToolRegistry()
        runner = _make_runner(tool_registry=tool_registry)
        tc = ToolCall(id="tc-6", name="nonexistent_tool", arguments='{}')
        result, log = await runner._execute_tool_call(tc, iteration=1)

        assert result.success is False
        assert "Unknown tool" in result.error

    async def test_log_entry_includes_output_preview(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool())
        runner = _make_runner(tool_registry=tool_registry)

        tc = ToolCall(id="tc-7", name="test_tool", arguments='{"query": "x"}')
        result, log = await runner._execute_tool_call(tc, iteration=1)

        assert "output_preview" in log
        assert log["output_preview"] is not None

    async def test_log_entry_truncates_long_output(self):
        class LongOutputTool(Tool):
            name = "long_tool"
            description = "Returns long output"
            parameters = []

            async def execute(self, **kwargs):
                return ToolResult(success=True, output="x" * 500)

        tool_registry = ToolRegistry()
        tool_registry.register(LongOutputTool())
        runner = _make_runner(tool_registry=tool_registry)

        tc = ToolCall(id="tc-8", name="long_tool", arguments='{}')
        result, log = await runner._execute_tool_call(tc, iteration=1)

        assert len(log["output_preview"]) == 200


# ===========================================================================
# _build_clarification_response
# ===========================================================================


class TestBuildClarificationResponse:
    """Tests for AgentRunner._build_clarification_response."""

    def test_basic_response(self):
        runner = _make_runner()
        intent = IntentClassification(
            primary_intent=IntentType.CLARIFICATION_NEEDED,
            confidence=0.4,
        )
        response = runner._build_clarification_response(intent)
        assert "make sure I understand" in response
        assert "Could you please clarify" in response

    def test_with_interpretations(self):
        runner = _make_runner()
        intent = IntentClassification(
            primary_intent=IntentType.CLARIFICATION_NEEDED,
            confidence=0.4,
            interpretations=[
                {"meaning": "System tools", "probability": 0.6},
                {"meaning": "Dev tools", "probability": 0.4},
            ],
        )
        response = runner._build_clarification_response(intent)
        assert "System tools" in response
        assert "Dev tools" in response
        assert "60%" in response
        assert "40%" in response

    def test_with_custom_clarification_question(self):
        runner = _make_runner()
        intent = IntentClassification(
            primary_intent=IntentType.CLARIFICATION_NEEDED,
            confidence=0.3,
            clarification_question="Are you asking about registered tools or dev tools?",
        )
        response = runner._build_clarification_response(intent)
        assert "Are you asking about registered tools or dev tools?" in response
        # Should NOT have the default question
        assert "Could you please clarify" not in response

    def test_interpretations_numbered(self):
        runner = _make_runner()
        intent = IntentClassification(
            primary_intent=IntentType.CLARIFICATION_NEEDED,
            confidence=0.5,
            interpretations=[
                {"meaning": "First", "probability": 0.5},
                {"meaning": "Second", "probability": 0.5},
            ],
        )
        response = runner._build_clarification_response(intent)
        assert "1. First" in response
        assert "2. Second" in response

    def test_empty_interpretations(self):
        runner = _make_runner()
        intent = IntentClassification(
            primary_intent=IntentType.CLARIFICATION_NEEDED,
            confidence=0.4,
            interpretations=[],
        )
        response = runner._build_clarification_response(intent)
        # Should not crash; should still have the opening and closing
        assert "make sure I understand" in response

    def test_response_is_string(self):
        runner = _make_runner()
        intent = IntentClassification(
            primary_intent=IntentType.CLARIFICATION_NEEDED,
            confidence=0.5,
        )
        response = runner._build_clarification_response(intent)
        assert isinstance(response, str)


# ===========================================================================
# _response_to_stream
# ===========================================================================


class TestResponseToStream:
    """Tests for AgentRunner._response_to_stream."""

    async def test_yields_single_chunk(self):
        runner = _make_runner()
        response = CompletionResponse(
            content="Hello!",
            model="test-model",
            provider="test-provider",
            finish_reason="stop",
        )
        chunks = []
        async for chunk in runner._response_to_stream(response):
            chunks.append(chunk)

        assert len(chunks) == 1

    async def test_chunk_content(self):
        runner = _make_runner()
        response = CompletionResponse(
            content="Hello!",
            model="test-model",
            provider="test-provider",
            finish_reason="stop",
        )
        chunks = []
        async for chunk in runner._response_to_stream(response):
            chunks.append(chunk)

        assert chunks[0].content == "Hello!"

    async def test_chunk_model(self):
        runner = _make_runner()
        response = CompletionResponse(
            content="Hi",
            model="gpt-4",
            provider="openai",
        )
        chunks = []
        async for chunk in runner._response_to_stream(response):
            chunks.append(chunk)

        assert chunks[0].model == "gpt-4"

    async def test_chunk_finish_reason(self):
        runner = _make_runner()
        response = CompletionResponse(
            content="Hi",
            model="m",
            provider="p",
            finish_reason="stop",
        )
        chunks = []
        async for chunk in runner._response_to_stream(response):
            chunks.append(chunk)

        assert chunks[0].finish_reason == "stop"

    async def test_none_finish_reason_defaults_to_stop(self):
        runner = _make_runner()
        response = CompletionResponse(
            content="Hi",
            model="m",
            provider="p",
            finish_reason=None,
        )
        chunks = []
        async for chunk in runner._response_to_stream(response):
            chunks.append(chunk)

        assert chunks[0].finish_reason == "stop"


# ===========================================================================
# _get_filtered_tool_definitions
# ===========================================================================


class TestGetFilteredToolDefinitions:
    """Tests for AgentRunner._get_filtered_tool_definitions."""

    def test_no_tool_registry_returns_empty(self):
        runner = _make_runner(tool_registry=None)
        result = runner._get_filtered_tool_definitions()
        assert result == []

    def test_with_tools_returns_definitions(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search the web"))
        runner = _make_runner(tool_registry=tool_registry)

        result = runner._get_filtered_tool_definitions()
        assert len(result) == 1
        assert isinstance(result[0], ToolDefinition)
        assert result[0].name == "web_search"
        assert result[0].description == "Search the web"

    def test_with_multiple_tools(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search"))
        tool_registry.register(_FakeTool("shell_exec", "Execute"))
        runner = _make_runner(tool_registry=tool_registry)

        result = runner._get_filtered_tool_definitions()
        assert len(result) == 2

    def test_policy_engine_filters_tools(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search"))
        tool_registry.register(_FakeTool("shell_exec", "Execute"))
        policy = ToolPolicy(profile=PolicyProfile.MESSAGING)
        policy_engine = PolicyEngine(default_policy=policy)
        runner = _make_runner(
            tool_registry=tool_registry, policy_engine=policy_engine
        )

        result = runner._get_filtered_tool_definitions()
        names = [d.name for d in result]
        assert "web_search" in names
        assert "shell_exec" not in names

    def test_policy_engine_minimal_blocks_all(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search"))
        policy = ToolPolicy(profile=PolicyProfile.MINIMAL)
        policy_engine = PolicyEngine(default_policy=policy)
        runner = _make_runner(
            tool_registry=tool_registry, policy_engine=policy_engine
        )

        result = runner._get_filtered_tool_definitions()
        assert result == []

    def test_no_policy_engine_returns_all(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("a", "Tool A"))
        tool_registry.register(_FakeTool("b", "Tool B"))
        runner = _make_runner(tool_registry=tool_registry, policy_engine=None)

        result = runner._get_filtered_tool_definitions()
        assert len(result) == 2

    def test_definitions_have_parameters(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search the web"))
        runner = _make_runner(tool_registry=tool_registry)

        result = runner._get_filtered_tool_definitions()
        assert "properties" in result[0].parameters
        assert "query" in result[0].parameters["properties"]


# ===========================================================================
# run() -- integration-style tests with mocked dependencies
# ===========================================================================


class TestRun:
    """Tests for AgentRunner.run()."""

    async def test_persists_user_message(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock("Response text")
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_classify_intent") as mock_classify, \
             patch.object(runner, "_get_history", new_callable=AsyncMock) as mock_hist, \
             patch("ungula.agents.runner.SystemPromptBuilder") as mock_builder:
            mock_classify.return_value = IntentClassification(
                primary_intent=IntentType.GENERAL_CONVERSATION,
                confidence=0.9,
            )
            mock_hist.return_value = []
            mock_builder_instance = MagicMock()
            mock_builder_instance.build.return_value = "System prompt"
            mock_builder.return_value = mock_builder_instance

            await runner.run(conv_id, "Hello!")

        # First call should be persisting the user message
        first_call = storage.create_message.call_args_list[0]
        msg_create = first_call[0][0]
        assert isinstance(msg_create, MessageCreate)
        assert msg_create.role == "user"
        assert msg_create.content == "Hello!"

    async def test_clarification_short_circuit(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock()
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_is_post_clarification", new_callable=AsyncMock) as mock_pc, \
             patch.object(runner, "_classify_intent") as mock_classify:
            mock_pc.return_value = False
            mock_classify.return_value = IntentClassification(
                primary_intent=IntentType.CLARIFICATION_NEEDED,
                confidence=0.4,
                interpretations=[{"meaning": "Option A", "probability": 0.5}],
                clarification_question="Which do you mean?",
            )

            result = await runner.run(conv_id, "tools")

        assert isinstance(result, CompletionResponse)
        assert result.provider == "ungula"
        assert result.model == "system"
        assert "make sure I understand" in result.content
        # LLM should NOT be called for the actual response
        registry.complete.assert_not_called()

    async def test_clarification_short_circuit_streaming(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock()
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_is_post_clarification", new_callable=AsyncMock) as mock_pc, \
             patch.object(runner, "_classify_intent") as mock_classify:
            mock_pc.return_value = False
            mock_classify.return_value = IntentClassification(
                primary_intent=IntentType.CLARIFICATION_NEEDED,
                confidence=0.3,
            )

            result = await runner.run(conv_id, "ambiguous", stream=True)

        # Should return an async iterator
        chunks = []
        async for chunk in result:
            chunks.append(chunk)
        assert len(chunks) == 1
        assert chunks[0].finish_reason is not None

    async def test_system_inquiry_short_circuit(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock()
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_is_post_clarification", new_callable=AsyncMock) as mock_pc, \
             patch.object(runner, "_classify_intent") as mock_classify:
            mock_pc.return_value = False
            mock_classify.return_value = IntentClassification(
                primary_intent=IntentType.SYSTEM_INQUIRY,
                confidence=0.95,
            )

            result = await runner.run(conv_id, "What can you do?")

        assert isinstance(result, CompletionResponse)
        assert result.model == "system"
        assert "Capabilities" in result.content
        registry.complete.assert_not_called()

    async def test_post_clarification_skips_intent(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock("I understood now, here's the answer.")
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_is_post_clarification", new_callable=AsyncMock) as mock_pc, \
             patch.object(runner, "_classify_intent") as mock_classify, \
             patch.object(runner, "_get_history", new_callable=AsyncMock) as mock_hist, \
             patch("ungula.agents.runner.SystemPromptBuilder") as mock_builder:
            mock_pc.return_value = True  # Previous msg was clarification
            mock_hist.return_value = []
            mock_builder_instance = MagicMock()
            mock_builder_instance.build.return_value = "System"
            mock_builder.return_value = mock_builder_instance

            await runner.run(conv_id, "Option A")

        # Intent classification should NOT be called
        mock_classify.assert_not_called()
        # But LLM should be called
        registry.complete.assert_called()

    async def test_normal_flow_calls_llm(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock("LLM response")
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_is_post_clarification", new_callable=AsyncMock) as mock_pc, \
             patch.object(runner, "_classify_intent") as mock_classify, \
             patch.object(runner, "_get_history", new_callable=AsyncMock) as mock_hist, \
             patch("ungula.agents.runner.SystemPromptBuilder") as mock_builder:
            mock_pc.return_value = False
            mock_classify.return_value = IntentClassification(
                primary_intent=IntentType.GENERAL_CONVERSATION,
                confidence=0.9,
            )
            mock_hist.return_value = []
            mock_builder_instance = MagicMock()
            mock_builder_instance.build.return_value = "System prompt"
            mock_builder.return_value = mock_builder_instance

            result = await runner.run(conv_id, "Tell me about Python")

        assert isinstance(result, CompletionResponse)
        assert result.content == "LLM response"
        registry.complete.assert_called()

    async def test_persists_assistant_response(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock("LLM response")
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_is_post_clarification", new_callable=AsyncMock) as mock_pc, \
             patch.object(runner, "_classify_intent") as mock_classify, \
             patch.object(runner, "_get_history", new_callable=AsyncMock) as mock_hist, \
             patch("ungula.agents.runner.SystemPromptBuilder") as mock_builder:
            mock_pc.return_value = False
            mock_classify.return_value = IntentClassification(
                primary_intent=IntentType.GENERAL_CONVERSATION,
                confidence=0.9,
            )
            mock_hist.return_value = []
            mock_builder_instance = MagicMock()
            mock_builder_instance.build.return_value = "System"
            mock_builder.return_value = mock_builder_instance

            await runner.run(conv_id, "Hello")

        # Two create_message calls: user + assistant
        assert storage.create_message.call_count == 2
        assistant_call = storage.create_message.call_args_list[1]
        msg = assistant_call[0][0]
        assert msg.role == "assistant"
        assert msg.content == "LLM response"

    async def test_compaction_history_tuple_handled(self):
        storage = _make_storage_mock()
        registry = _make_registry_mock("Response")
        runner = _make_runner(storage=storage, registry=registry)
        conv_id = uuid4()

        with patch.object(runner, "_is_post_clarification", new_callable=AsyncMock) as mock_pc, \
             patch.object(runner, "_classify_intent") as mock_classify, \
             patch.object(runner, "_get_history", new_callable=AsyncMock) as mock_hist, \
             patch("ungula.agents.runner.SystemPromptBuilder") as mock_builder, \
             patch.object(runner, "_build_messages") as mock_build_msgs:
            mock_pc.return_value = False
            mock_classify.return_value = IntentClassification(
                primary_intent=IntentType.GENERAL_CONVERSATION,
                confidence=0.9,
            )
            # Return compaction tuple
            mock_hist.return_value = ([], "Summary of earlier conversation")
            mock_builder_instance = MagicMock()
            mock_builder_instance.build.return_value = "System"
            mock_builder.return_value = mock_builder_instance
            mock_build_msgs.return_value = [
                LLMMessage(role=MessageRole.SYSTEM, content="System"),
                LLMMessage(role=MessageRole.USER, content="Hello"),
            ]

            await runner.run(conv_id, "Hello")

        # _build_messages should receive the compaction_summary
        mock_build_msgs.assert_called_once()
        call_args = mock_build_msgs.call_args
        assert call_args[0][3] == "Summary of earlier conversation" or \
               call_args[1].get("compaction_summary") == "Summary of earlier conversation"


# ===========================================================================
# Tool loop behavior
# ===========================================================================


class TestToolLoop:
    """Tests for tool loop execution via _run_tool_loop."""

    async def test_no_tool_calls_returns_immediately(self):
        registry = _make_registry_mock("Direct answer")
        runner = _make_runner(registry=registry)

        messages = [
            LLMMessage(role=MessageRole.SYSTEM, content="System"),
            LLMMessage(role=MessageRole.USER, content="Hello"),
        ]

        response, log = await runner._run_tool_loop(
            messages, provider=None, model=None, temperature=None, max_tokens=None
        )

        assert response.content == "Direct answer"
        assert log == []
        registry.complete.assert_called_once()

    async def test_tool_call_executes_and_loops(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search"))

        # First call returns tool call, second returns text
        first_response = CompletionResponse(
            content="",
            model="m",
            provider="p",
            tool_calls=[ToolCall(id="tc-1", name="web_search", arguments='{"query":"test"}')],
        )
        second_response = CompletionResponse(
            content="Final answer based on search",
            model="m",
            provider="p",
            tool_calls=None,
        )
        registry = MagicMock()
        registry.complete = AsyncMock(side_effect=[first_response, second_response])

        runner = _make_runner(registry=registry, tool_registry=tool_registry)

        messages = [
            LLMMessage(role=MessageRole.SYSTEM, content="System"),
            LLMMessage(role=MessageRole.USER, content="Search for X"),
        ]

        response, log = await runner._run_tool_loop(
            messages, provider=None, model=None, temperature=None, max_tokens=None
        )

        assert response.content == "Final answer based on search"
        assert len(log) == 1
        assert log[0]["name"] == "web_search"
        assert log[0]["success"] is True
        assert registry.complete.call_count == 2

    async def test_max_iterations_forces_text_response(self):
        # Every call returns a tool call
        tool_response = CompletionResponse(
            content="",
            model="m",
            provider="p",
            tool_calls=[ToolCall(id="tc", name="test_tool", arguments='{}')],
        )
        final_response = CompletionResponse(
            content="Forced text response",
            model="m",
            provider="p",
            tool_calls=None,
        )

        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("test_tool", "Test"))

        registry = MagicMock()
        # 3 iterations of tool calls, then forced text response
        registry.complete = AsyncMock(
            side_effect=[tool_response, tool_response, tool_response, final_response]
        )

        runner = _make_runner(
            registry=registry,
            tool_registry=tool_registry,
            max_tool_iterations=3,
        )

        messages = [
            LLMMessage(role=MessageRole.SYSTEM, content="S"),
            LLMMessage(role=MessageRole.USER, content="Q"),
        ]

        response, log = await runner._run_tool_loop(
            messages, provider=None, model=None, temperature=None, max_tokens=None
        )

        assert response.content == "Forced text response"
        assert len(log) == 3  # 3 tool calls
        # 3 tool-call iterations + 1 forced text = 4 total calls
        assert registry.complete.call_count == 4

    async def test_tool_results_appended_to_messages(self):
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search"))

        first_response = CompletionResponse(
            content="",
            model="m",
            provider="p",
            tool_calls=[ToolCall(id="tc-1", name="web_search", arguments='{"query":"test"}')],
        )
        second_response = CompletionResponse(
            content="Answer",
            model="m",
            provider="p",
            tool_calls=None,
        )
        registry = MagicMock()
        registry.complete = AsyncMock(side_effect=[first_response, second_response])

        runner = _make_runner(registry=registry, tool_registry=tool_registry)

        messages = [
            LLMMessage(role=MessageRole.USER, content="Search"),
        ]

        await runner._run_tool_loop(
            messages, provider=None, model=None, temperature=None, max_tokens=None
        )

        # Messages should have grown: original + assistant(tool_call) + tool_result
        assert len(messages) == 3
        assert messages[1].role == MessageRole.ASSISTANT
        assert messages[2].role == MessageRole.TOOL
        assert messages[2].tool_call_id == "tc-1"


# ===========================================================================
# _is_post_clarification
# ===========================================================================


class TestIsPostClarification:
    """Tests for AgentRunner._is_post_clarification."""

    async def test_returns_true_for_clarification_intent(self):
        storage = _make_storage_mock(history=[
            _make_storage_message(role="user", content="tools"),
            _make_storage_message(
                role="assistant",
                content="What do you mean?",
                metadata={"intent": "clarification"},
            ),
            _make_storage_message(role="user", content="system tools"),
        ])
        runner = _make_runner(storage=storage)

        result = await runner._is_post_clarification(uuid4())
        assert result is True

    async def test_returns_false_for_normal_history(self):
        storage = _make_storage_mock(history=[
            _make_storage_message(role="user", content="hello"),
            _make_storage_message(
                role="assistant",
                content="Hi!",
                metadata={},
            ),
        ])
        runner = _make_runner(storage=storage)

        result = await runner._is_post_clarification(uuid4())
        assert result is False

    async def test_returns_false_for_empty_history(self):
        storage = _make_storage_mock(history=[])
        runner = _make_runner(storage=storage)

        result = await runner._is_post_clarification(uuid4())
        assert result is False

    async def test_returns_true_for_clarification_followup(self):
        storage = _make_storage_mock(history=[
            _make_storage_message(
                role="assistant",
                content="Follow up",
                metadata={"intent": "clarification_followup"},
            ),
        ])
        runner = _make_runner(storage=storage)

        result = await runner._is_post_clarification(uuid4())
        assert result is True
