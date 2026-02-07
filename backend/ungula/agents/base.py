"""
Agent runtime data structures.

Defines the core types used by the agent system.
"""

from dataclasses import dataclass, field
from typing import Any

from ..llm.base import Message as LLMMessage


@dataclass
class AgentContext:
    """
    Assembled context for an agent invocation.

    Contains the system prompt built from workspace files and
    the conversation history messages.
    """

    system_prompt: str
    messages: list[LLMMessage] = field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None


@dataclass
class ChatResult:
    """
    Result of a chat invocation.

    For non-streaming responses, contains the complete response.
    For streaming, this is returned after streaming completes.
    """

    message_id: str
    content: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


@dataclass
class StreamEvent:
    """
    An event emitted during streaming.

    Used to serialize SSE events to the client.
    """

    event: str  # start, chunk, done, error
    data: dict[str, Any]

    def to_sse(self) -> str:
        """Format as SSE string."""
        import json

        return f"event: {self.event}\ndata: {json.dumps(self.data)}\n\n"
