"""
Tests for agent base types.

Covers AgentContext, ChatResult, and StreamEvent dataclasses.
"""

import json

import pytest

from ungula.agents.base import AgentContext, ChatResult, StreamEvent
from ungula.llm.base import Message as LLMMessage, MessageRole


# ===========================================================================
# AgentContext
# ===========================================================================


class TestAgentContext:
    """Tests for the AgentContext dataclass."""

    def test_creation_with_required_fields(self):
        ctx = AgentContext(system_prompt="You are helpful.")
        assert ctx.system_prompt == "You are helpful."

    def test_messages_default_empty(self):
        ctx = AgentContext(system_prompt="Test")
        assert ctx.messages == []

    def test_model_default_none(self):
        ctx = AgentContext(system_prompt="Test")
        assert ctx.model is None

    def test_provider_default_none(self):
        ctx = AgentContext(system_prompt="Test")
        assert ctx.provider is None

    def test_temperature_default(self):
        ctx = AgentContext(system_prompt="Test")
        assert ctx.temperature == 0.7

    def test_max_tokens_default_none(self):
        ctx = AgentContext(system_prompt="Test")
        assert ctx.max_tokens is None

    def test_creation_with_all_fields(self):
        messages = [
            LLMMessage(role=MessageRole.USER, content="Hi"),
            LLMMessage(role=MessageRole.ASSISTANT, content="Hello"),
        ]
        ctx = AgentContext(
            system_prompt="You are an AI.",
            messages=messages,
            model="gpt-4",
            provider="openai",
            temperature=0.3,
            max_tokens=1000,
        )
        assert ctx.system_prompt == "You are an AI."
        assert len(ctx.messages) == 2
        assert ctx.model == "gpt-4"
        assert ctx.provider == "openai"
        assert ctx.temperature == 0.3
        assert ctx.max_tokens == 1000

    def test_messages_list_is_mutable(self):
        ctx = AgentContext(system_prompt="Test")
        msg = LLMMessage(role=MessageRole.USER, content="Hello")
        ctx.messages.append(msg)
        assert len(ctx.messages) == 1

    def test_separate_instances_have_independent_message_lists(self):
        ctx1 = AgentContext(system_prompt="A")
        ctx2 = AgentContext(system_prompt="B")
        ctx1.messages.append(LLMMessage(role=MessageRole.USER, content="msg"))
        assert len(ctx2.messages) == 0

    def test_temperature_can_be_zero(self):
        ctx = AgentContext(system_prompt="Test", temperature=0.0)
        assert ctx.temperature == 0.0


# ===========================================================================
# ChatResult
# ===========================================================================


class TestChatResult:
    """Tests for the ChatResult dataclass."""

    def test_creation_with_required_fields(self):
        result = ChatResult(
            message_id="msg-123",
            content="Hello!",
            model="gpt-4",
            provider="openai",
        )
        assert result.message_id == "msg-123"
        assert result.content == "Hello!"
        assert result.model == "gpt-4"
        assert result.provider == "openai"

    def test_finish_reason_default_none(self):
        result = ChatResult(
            message_id="1", content="Hi", model="m", provider="p"
        )
        assert result.finish_reason is None

    def test_usage_default_none(self):
        result = ChatResult(
            message_id="1", content="Hi", model="m", provider="p"
        )
        assert result.usage is None

    def test_creation_with_all_fields(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        result = ChatResult(
            message_id="msg-456",
            content="Response text",
            model="claude-3",
            provider="anthropic",
            finish_reason="stop",
            usage=usage,
        )
        assert result.finish_reason == "stop"
        assert result.usage == usage
        assert result.usage["total_tokens"] == 30

    def test_empty_content(self):
        result = ChatResult(
            message_id="1", content="", model="m", provider="p"
        )
        assert result.content == ""

    def test_finish_reason_values(self):
        for reason in ("stop", "length", "tool_calls", "max_iterations"):
            result = ChatResult(
                message_id="1",
                content="text",
                model="m",
                provider="p",
                finish_reason=reason,
            )
            assert result.finish_reason == reason


# ===========================================================================
# StreamEvent
# ===========================================================================


class TestStreamEvent:
    """Tests for the StreamEvent dataclass."""

    def test_creation(self):
        event = StreamEvent(event="chunk", data={"content": "Hello"})
        assert event.event == "chunk"
        assert event.data == {"content": "Hello"}

    def test_to_sse_format(self):
        event = StreamEvent(event="chunk", data={"content": "Hello"})
        sse = event.to_sse()
        assert sse.startswith("event: chunk\n")
        assert "data: " in sse
        assert sse.endswith("\n\n")

    def test_to_sse_contains_valid_json_data(self):
        data = {"content": "Hello", "model": "gpt-4"}
        event = StreamEvent(event="chunk", data=data)
        sse = event.to_sse()
        # Extract the data line
        lines = sse.strip().split("\n")
        data_line = [l for l in lines if l.startswith("data: ")][0]
        json_str = data_line[len("data: "):]
        parsed = json.loads(json_str)
        assert parsed == data

    def test_to_sse_start_event(self):
        event = StreamEvent(event="start", data={"model": "gpt-4"})
        sse = event.to_sse()
        assert "event: start\n" in sse

    def test_to_sse_done_event(self):
        event = StreamEvent(
            event="done",
            data={"finish_reason": "stop", "usage": {"total_tokens": 50}},
        )
        sse = event.to_sse()
        assert "event: done\n" in sse
        parsed_data = json.loads(sse.split("data: ")[1].strip())
        assert parsed_data["finish_reason"] == "stop"

    def test_to_sse_error_event(self):
        event = StreamEvent(event="error", data={"message": "Rate limit exceeded"})
        sse = event.to_sse()
        assert "event: error\n" in sse

    def test_to_sse_empty_data(self):
        event = StreamEvent(event="chunk", data={})
        sse = event.to_sse()
        assert "data: {}" in sse

    def test_to_sse_nested_data(self):
        data = {"content": "Hi", "metadata": {"tokens": 5, "model": "gpt-4"}}
        event = StreamEvent(event="chunk", data=data)
        sse = event.to_sse()
        parsed = json.loads(sse.split("data: ")[1].strip())
        assert parsed["metadata"]["tokens"] == 5

    def test_to_sse_special_characters_in_data(self):
        data = {"content": 'Hello "world"\nNew line'}
        event = StreamEvent(event="chunk", data=data)
        sse = event.to_sse()
        # Should be valid JSON despite special chars
        parsed = json.loads(sse.split("data: ")[1].strip())
        assert parsed["content"] == 'Hello "world"\nNew line'

    def test_event_types_are_strings(self):
        for event_type in ("start", "chunk", "done", "error"):
            event = StreamEvent(event=event_type, data={})
            assert isinstance(event.event, str)
