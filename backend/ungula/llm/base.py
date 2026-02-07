"""
Base interface for LLM providers.

Defines the contract that all LLM providers must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator


class MessageRole(str, Enum):
    """Message role in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """A message in a conversation."""

    role: MessageRole | str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        result: dict[str, Any] = {
            "role": self.role.value if isinstance(self.role, MessageRole) else self.role,
            "content": self.content,
        }
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        return result


@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class CompletionRequest:
    """Request for a completion from an LLM."""

    messages: list[Message]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[ToolDefinition] | None = None
    tool_choice: str | dict[str, Any] | None = None
    stop: list[str] | None = None
    stream: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        result: dict[str, Any] = {
            "messages": [m.to_dict() for m in self.messages],
            "temperature": self.temperature,
        }
        if self.model:
            result["model"] = self.model
        if self.max_tokens:
            result["max_tokens"] = self.max_tokens
        if self.tools:
            result["tools"] = [t.to_dict() for t in self.tools]
        if self.tool_choice:
            result["tool_choice"] = self.tool_choice
        if self.stop:
            result["stop"] = self.stop
        if self.stream:
            result["stream"] = self.stream
        return result


@dataclass
class ToolCall:
    """A tool call made by the LLM."""

    id: str
    name: str
    arguments: str  # JSON string

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class CompletionResponse:
    """Response from an LLM completion request."""

    content: str | None
    model: str
    provider: str
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    raw_response: dict[str, Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return bool(self.tool_calls)


@dataclass
class StreamChunk:
    """A chunk from a streaming response."""

    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    # Extended fields for tool calling SSE events
    event_type: str | None = None  # "tool_call", "tool_result"
    event_data: dict[str, Any] | None = None

    @property
    def is_done(self) -> bool:
        """Check if this is the final chunk."""
        return self.finish_reason is not None


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class RateLimitError(ProviderError):
    """Rate limit exceeded."""

    def __init__(self, message: str, provider: str, retry_after: float | None = None):
        super().__init__(message, provider, status_code=429, retryable=True)
        self.retry_after = retry_after


class AuthenticationError(ProviderError):
    """Authentication failed."""

    def __init__(self, message: str, provider: str):
        super().__init__(message, provider, status_code=401, retryable=False)


class ModelNotFoundError(ProviderError):
    """Model not found."""

    def __init__(self, message: str, provider: str, model: str):
        super().__init__(message, provider, status_code=404, retryable=False)
        self.model = model


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    # Provider identification
    name: str = "base"
    display_name: str = "Base Provider"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        """
        Initialize the provider.

        Args:
            api_key: API key for authentication.
            base_url: Base URL for API calls.
            default_model: Default model to use if not specified.
        """
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """
        Generate a completion for the given request.

        Args:
            request: The completion request.

        Returns:
            The completion response.

        Raises:
            ProviderError: If the request fails.
        """
        pass

    @abstractmethod
    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """
        Stream a completion for the given request.

        Args:
            request: The completion request (stream=True will be set).

        Yields:
            Chunks of the streaming response.

        Raises:
            ProviderError: If the request fails.
        """
        pass

    @abstractmethod
    async def list_models(self) -> list[str]:
        """
        List available models for this provider.

        Returns:
            List of model identifiers.
        """
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """
        Check if the provider is healthy and accessible.

        Returns:
            True if healthy, False otherwise.
        """
        pass

    def get_model(self, request_model: str | None) -> str:
        """Get the model to use, falling back to default."""
        if request_model:
            return request_model
        if self.default_model:
            return self.default_model
        raise ValueError(f"No model specified and no default model set for {self.name}")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, default_model={self.default_model!r})"
