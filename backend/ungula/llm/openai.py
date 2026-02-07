"""
OpenAI LLM provider.

Direct integration with OpenAI's API.
"""

import logging
from typing import Any, AsyncIterator

import openai

from .base import (
    AuthenticationError,
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.2"


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider using the official SDK."""

    name = "openai"
    display_name = "OpenAI"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key.
            base_url: Base URL for API calls (optional, for Azure or proxies).
            default_model: Default model to use.
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model or DEFAULT_MODEL,
        )
        self._client: openai.AsyncOpenAI | None = None

    def _get_client(self) -> openai.AsyncOpenAI:
        """Get or create the OpenAI client."""
        if self._client is None:
            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    async def close(self) -> None:
        """Close the client."""
        if self._client:
            await self._client.close()
            self._client = None

    def _parse_tool_calls(
        self, tool_calls: list[Any] | None
    ) -> list[ToolCall] | None:
        """Parse tool calls from OpenAI response."""
        if not tool_calls:
            return None
        return [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for tc in tool_calls
        ]

    def _handle_error(self, e: Exception) -> None:
        """Handle OpenAI API errors."""
        if isinstance(e, openai.AuthenticationError):
            raise AuthenticationError(str(e), self.name)
        elif isinstance(e, openai.RateLimitError):
            raise RateLimitError(str(e), self.name)
        elif isinstance(e, openai.NotFoundError):
            raise ModelNotFoundError(str(e), self.name, model="unknown")
        elif isinstance(e, openai.APIError):
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

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in request.messages],
        }

        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        if request.stop:
            kwargs["stop"] = request.stop
        if request.tools:
            kwargs["tools"] = [t.to_dict() for t in request.tools]
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice

        # Apply provider-specific params
        pp = request.provider_params
        if pp.get("response_format"):
            kwargs["response_format"] = pp["response_format"]
        if pp.get("seed") is not None:
            kwargs["seed"] = pp["seed"]
        if pp.get("reasoning_effort"):
            kwargs["reasoning_effort"] = pp["reasoning_effort"]
        if pp.get("logprobs"):
            kwargs["logprobs"] = pp["logprobs"]

        logger.debug("OpenAI request: model=%s, messages=%d", model, len(request.messages))

        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as e:
            self._handle_error(e)
            raise  # Should not reach here

        choice = response.choices[0]
        message = choice.message

        return CompletionResponse(
            content=message.content,
            model=response.model,
            provider=self.name,
            tool_calls=self._parse_tool_calls(message.tool_calls),
            finish_reason=choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            if response.usage
            else None,
            raw_response=response.model_dump(),
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Stream a completion."""
        client = self._get_client()
        model = self.get_model(request.model)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in request.messages],
            "stream": True,
        }

        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        if request.stop:
            kwargs["stop"] = request.stop
        if request.tools:
            kwargs["tools"] = [t.to_dict() for t in request.tools]
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice

        # Apply provider-specific params
        pp = request.provider_params
        if pp.get("response_format"):
            kwargs["response_format"] = pp["response_format"]
        if pp.get("seed") is not None:
            kwargs["seed"] = pp["seed"]
        if pp.get("reasoning_effort"):
            kwargs["reasoning_effort"] = pp["reasoning_effort"]

        logger.debug("OpenAI stream: model=%s", model)

        try:
            stream = await client.chat.completions.create(**kwargs)

            accumulated_tool_calls: dict[int, dict[str, Any]] = {}

            async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                content = delta.content if delta else None

                # Handle tool calls
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.id:
                            accumulated_tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                accumulated_tool_calls[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                accumulated_tool_calls[idx][
                                    "arguments"
                                ] += tc.function.arguments

                finish_reason = choice.finish_reason

                # On finish, emit accumulated tool calls
                tool_calls = None
                if finish_reason and accumulated_tool_calls:
                    tool_calls = [
                        ToolCall(
                            id=tc["id"],
                            name=tc["name"],
                            arguments=tc["arguments"],
                        )
                        for tc in accumulated_tool_calls.values()
                    ]

                yield StreamChunk(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                    model=chunk.model,
                )
        except Exception as e:
            self._handle_error(e)

    async def list_models(self) -> list[str]:
        """List available models."""
        try:
            client = self._get_client()
            response = await client.models.list()
            return [m.id for m in response.data if "gpt" in m.id.lower()]
        except Exception as e:
            logger.warning("Failed to list OpenAI models: %s", e)
            # Return known models as fallback
            return [
                "gpt-5.2",
                "gpt-5",
                "gpt-4.1",
                "gpt-4o",
                "gpt-4o-mini",
            ]

    async def check_health(self) -> bool:
        """Check provider health."""
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception as e:
            logger.warning("OpenAI health check failed: %s", e)
            return False
