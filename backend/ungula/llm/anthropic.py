"""
Anthropic LLM provider.

Direct integration with Anthropic's Claude API.
"""

import logging
from typing import Any, AsyncIterator

import anthropic

from .base import (
    AuthenticationError,
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    Message,
    MessageRole,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-5-20250514"


class AnthropicProvider(LLMProvider):
    """Anthropic LLM provider using the official SDK."""

    name = "anthropic"
    display_name = "Anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        """
        Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key.
            base_url: Base URL for API calls (optional).
            default_model: Default model to use.
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model or DEFAULT_MODEL,
        )
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        """Get or create the Anthropic client."""
        if self._client is None:
            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    async def close(self) -> None:
        """Close the client."""
        if self._client:
            await self._client.close()
            self._client = None

    def _convert_messages(
        self, messages: list[Message]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """
        Convert messages to Anthropic format.

        Anthropic requires system message to be separate from messages.

        Returns:
            Tuple of (system_prompt, messages)
        """
        system_prompt = None
        converted = []

        for msg in messages:
            role = msg.role.value if isinstance(msg.role, MessageRole) else msg.role

            if role == "system":
                system_prompt = msg.content
            elif role == "tool":
                # Anthropic uses tool_result content blocks
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content,
                            }
                        ],
                    }
                )
            else:
                content: Any = msg.content
                # Handle assistant messages with tool calls
                if role == "assistant" and msg.tool_calls:
                    content = []
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "input": tc["function"]["arguments"],
                            }
                        )

                converted.append({"role": role, "content": content})

        return system_prompt, converted

    def _convert_tools(
        self, tools: list[Any] | None
    ) -> list[dict[str, Any]] | None:
        """Convert tools to Anthropic format."""
        if not tools:
            return None
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    def _parse_tool_calls(self, content: list[Any]) -> list[ToolCall] | None:
        """Parse tool calls from Anthropic response content."""
        tool_calls = []
        for block in content:
            if hasattr(block, "type") and block.type == "tool_use":
                import json

                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=json.dumps(block.input)
                        if isinstance(block.input, dict)
                        else str(block.input),
                    )
                )
        return tool_calls if tool_calls else None

    def _extract_text(self, content: list[Any]) -> str | None:
        """Extract text content from Anthropic response."""
        texts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                texts.append(block.text)
        return "\n".join(texts) if texts else None

    def _handle_error(self, e: Exception) -> None:
        """Handle Anthropic API errors."""
        if isinstance(e, anthropic.AuthenticationError):
            raise AuthenticationError(str(e), self.name)
        elif isinstance(e, anthropic.RateLimitError):
            raise RateLimitError(str(e), self.name)
        elif isinstance(e, anthropic.NotFoundError):
            raise ModelNotFoundError(str(e), self.name, model="unknown")
        elif isinstance(e, anthropic.APIError):
            raise ProviderError(
                str(e),
                self.name,
                status_code=getattr(e, "status_code", None),
                retryable=getattr(e, "status_code", 0) >= 500,
            )
        else:
            raise ProviderError(str(e), self.name)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion."""
        client = self._get_client()
        model = self.get_model(request.model)

        system_prompt, messages = self._convert_messages(request.messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
        }

        if system_prompt:
            kwargs["system"] = system_prompt
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop:
            kwargs["stop_sequences"] = request.stop

        tools = self._convert_tools(request.tools)
        if tools:
            kwargs["tools"] = tools

        # Apply provider-specific params
        pp = request.provider_params
        if pp.get("thinking"):
            budget = pp["thinking"] if isinstance(pp["thinking"], int) else 10000
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if pp.get("top_k") is not None:
            kwargs["top_k"] = pp["top_k"]

        logger.debug("Anthropic request: model=%s, messages=%d", model, len(messages))

        try:
            response = await client.messages.create(**kwargs)
        except Exception as e:
            self._handle_error(e)
            raise  # Should not reach here

        return CompletionResponse(
            content=self._extract_text(response.content),
            model=response.model,
            provider=self.name,
            tool_calls=self._parse_tool_calls(response.content),
            finish_reason=response.stop_reason,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens
                + response.usage.output_tokens,
            },
            raw_response=response.model_dump(),
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Stream a completion."""
        client = self._get_client()
        model = self.get_model(request.model)

        system_prompt, messages = self._convert_messages(request.messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
        }

        if system_prompt:
            kwargs["system"] = system_prompt
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop:
            kwargs["stop_sequences"] = request.stop

        tools = self._convert_tools(request.tools)
        if tools:
            kwargs["tools"] = tools

        # Apply provider-specific params
        pp = request.provider_params
        if pp.get("thinking"):
            budget = pp["thinking"] if isinstance(pp["thinking"], int) else 10000
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if pp.get("top_k") is not None:
            kwargs["top_k"] = pp["top_k"]

        logger.debug("Anthropic stream: model=%s", model)

        try:
            async with client.messages.stream(**kwargs) as stream:
                current_tool: dict[str, Any] | None = None
                stream_usage: dict[str, int] | None = None

                async for event in stream:
                    if event.type == "content_block_start":
                        if hasattr(event.content_block, "type"):
                            if event.content_block.type == "tool_use":
                                current_tool = {
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "arguments": "",
                                }
                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            yield StreamChunk(content=event.delta.text)
                        elif hasattr(event.delta, "partial_json"):
                            if current_tool:
                                current_tool["arguments"] += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool:
                            yield StreamChunk(
                                tool_calls=[
                                    ToolCall(
                                        id=current_tool["id"],
                                        name=current_tool["name"],
                                        arguments=current_tool["arguments"],
                                    )
                                ]
                            )
                            current_tool = None
                    elif event.type == "message_delta":
                        # Capture usage from message_delta event
                        if hasattr(event, "usage") and event.usage:
                            stream_usage = {
                                "completion_tokens": getattr(event.usage, "output_tokens", 0),
                            }
                    elif event.type == "message_stop":
                        # Build final usage from accumulated stream data
                        final_msg = stream.current_message_snapshot
                        usage = None
                        if final_msg and hasattr(final_msg, "usage") and final_msg.usage:
                            usage = {
                                "prompt_tokens": final_msg.usage.input_tokens,
                                "completion_tokens": final_msg.usage.output_tokens,
                                "total_tokens": final_msg.usage.input_tokens + final_msg.usage.output_tokens,
                            }
                        yield StreamChunk(finish_reason="stop", model=model, usage=usage)
        except Exception as e:
            self._handle_error(e)

    async def list_models(self) -> list[str]:
        """List available models."""
        # Anthropic doesn't have a models endpoint, return known models
        return [
            "claude-opus-4-5-20250514",
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ]

    async def check_health(self) -> bool:
        """Check provider health."""
        try:
            client = self._get_client()
            # Make a minimal request to verify credentials
            await client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except Exception as e:
            logger.warning("Anthropic health check failed: %s", e)
            return False
