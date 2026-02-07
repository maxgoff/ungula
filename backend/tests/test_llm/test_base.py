"""
Tests for LLM base classes.
"""

import pytest

from ungula.llm import (
    CompletionRequest,
    CompletionResponse,
    Message,
    MessageRole,
    ToolCall,
    ToolDefinition,
)


class TestMessage:
    """Tests for Message class."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = Message(role=MessageRole.USER, content="Hello")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"
        assert msg.name is None
        assert msg.tool_call_id is None
        assert msg.tool_calls is None

    def test_message_to_dict(self):
        """Test message to dictionary conversion."""
        msg = Message(role=MessageRole.USER, content="Hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "Hello"}

    def test_message_with_name(self):
        """Test message with name."""
        msg = Message(role=MessageRole.TOOL, content="result", name="my_tool")
        d = msg.to_dict()
        assert d["name"] == "my_tool"

    def test_message_with_tool_call_id(self):
        """Test message with tool call ID."""
        msg = Message(
            role=MessageRole.TOOL, content="result", tool_call_id="call_123"
        )
        d = msg.to_dict()
        assert d["tool_call_id"] == "call_123"

    def test_message_string_role(self):
        """Test message with string role."""
        msg = Message(role="custom", content="Hello")
        d = msg.to_dict()
        assert d["role"] == "custom"


class TestToolDefinition:
    """Tests for ToolDefinition class."""

    def test_tool_definition_creation(self):
        """Test creating a tool definition."""
        tool = ToolDefinition(
            name="get_weather",
            description="Get current weather",
            parameters={
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                },
                "required": ["location"],
            },
        )
        assert tool.name == "get_weather"
        assert tool.description == "Get current weather"

    def test_tool_definition_to_dict(self):
        """Test tool definition to dictionary conversion."""
        tool = ToolDefinition(
            name="get_weather",
            description="Get weather",
            parameters={"type": "object"},
        )
        d = tool.to_dict()
        assert d == {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object"},
            },
        }


class TestToolCall:
    """Tests for ToolCall class."""

    def test_tool_call_creation(self):
        """Test creating a tool call."""
        tc = ToolCall(
            id="call_123",
            name="get_weather",
            arguments='{"location": "NYC"}',
        )
        assert tc.id == "call_123"
        assert tc.name == "get_weather"
        assert tc.arguments == '{"location": "NYC"}'

    def test_tool_call_to_dict(self):
        """Test tool call to dictionary conversion."""
        tc = ToolCall(
            id="call_123",
            name="get_weather",
            arguments='{"location": "NYC"}',
        )
        d = tc.to_dict()
        assert d == {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"location": "NYC"}',
            },
        }


class TestCompletionRequest:
    """Tests for CompletionRequest class."""

    def test_completion_request_creation(self):
        """Test creating a completion request."""
        messages = [Message(role=MessageRole.USER, content="Hello")]
        request = CompletionRequest(messages=messages)
        assert len(request.messages) == 1
        assert request.temperature == 0.7
        assert request.max_tokens is None
        assert request.stream is False

    def test_completion_request_with_options(self):
        """Test completion request with options."""
        messages = [Message(role=MessageRole.USER, content="Hello")]
        request = CompletionRequest(
            messages=messages,
            model="gpt-4",
            temperature=0.5,
            max_tokens=100,
            stream=True,
        )
        assert request.model == "gpt-4"
        assert request.temperature == 0.5
        assert request.max_tokens == 100
        assert request.stream is True

    def test_completion_request_to_dict(self):
        """Test completion request to dictionary conversion."""
        messages = [Message(role=MessageRole.USER, content="Hello")]
        request = CompletionRequest(
            messages=messages,
            model="gpt-4",
            temperature=0.5,
        )
        d = request.to_dict()
        assert d["messages"] == [{"role": "user", "content": "Hello"}]
        assert d["model"] == "gpt-4"
        assert d["temperature"] == 0.5

    def test_completion_request_with_tools(self):
        """Test completion request with tools."""
        messages = [Message(role=MessageRole.USER, content="Hello")]
        tools = [
            ToolDefinition(
                name="test",
                description="Test tool",
                parameters={"type": "object"},
            )
        ]
        request = CompletionRequest(messages=messages, tools=tools)
        d = request.to_dict()
        assert "tools" in d
        assert len(d["tools"]) == 1


class TestCompletionResponse:
    """Tests for CompletionResponse class."""

    def test_completion_response_creation(self):
        """Test creating a completion response."""
        response = CompletionResponse(
            content="Hello!",
            model="gpt-4",
            provider="openai",
        )
        assert response.content == "Hello!"
        assert response.model == "gpt-4"
        assert response.provider == "openai"
        assert response.has_tool_calls is False

    def test_completion_response_with_tool_calls(self):
        """Test completion response with tool calls."""
        tool_calls = [
            ToolCall(id="call_1", name="test", arguments="{}"),
        ]
        response = CompletionResponse(
            content=None,
            model="gpt-4",
            provider="openai",
            tool_calls=tool_calls,
        )
        assert response.has_tool_calls is True
        assert len(response.tool_calls) == 1

    def test_completion_response_with_usage(self):
        """Test completion response with usage stats."""
        response = CompletionResponse(
            content="Hello!",
            model="gpt-4",
            provider="openai",
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        )
        assert response.usage["total_tokens"] == 15
