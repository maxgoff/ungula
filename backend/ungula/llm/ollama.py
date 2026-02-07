"""
Ollama LLM provider.

Integration with local Ollama server for running models locally.
"""

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    Message,
    MessageRole,
    ModelNotFoundError,
    ProviderError,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


class OllamaProvider(LLMProvider):
    """Ollama LLM provider for local models."""

    name = "ollama"
    display_name = "Ollama (Local)"

    def __init__(
        self,
        api_key: str | None = None,  # Not used, included for interface compatibility
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        """
        Initialize Ollama provider.

        Args:
            api_key: Not used for Ollama.
            base_url: Ollama server URL (default: http://localhost:11434).
            default_model: Default model to use.
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            default_model=default_model or DEFAULT_MODEL,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(300.0, connect=10.0),  # Long timeout for local inference
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert messages to Ollama format."""
        converted = []
        for msg in messages:
            role = msg.role.value if isinstance(msg.role, MessageRole) else msg.role
            converted.append({"role": role, "content": msg.content})
        return converted

    def _convert_tools(self, tools: list[Any] | None) -> list[dict[str, Any]] | None:
        """Convert tools to Ollama format (same as OpenAI)."""
        if not tools:
            return None
        return [t.to_dict() for t in tools]

    def _parse_tool_calls(
        self, tool_calls_data: list[dict[str, Any]] | None
    ) -> list[ToolCall] | None:
        """Parse tool calls from Ollama response."""
        if not tool_calls_data:
            return None
        return [
            ToolCall(
                id=tc.get("id", f"call_{i}"),
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"]
                if isinstance(tc["function"]["arguments"], str)
                else json.dumps(tc["function"]["arguments"]),
            )
            for i, tc in enumerate(tool_calls_data)
        ]

    def _handle_error(self, response: httpx.Response, body: dict[str, Any]) -> None:
        """Handle error responses from Ollama."""
        status_code = response.status_code
        error_msg = body.get("error", str(body))

        if status_code == 404:
            raise ModelNotFoundError(error_msg, self.name, model="unknown")
        else:
            raise ProviderError(
                error_msg,
                self.name,
                status_code=status_code,
                retryable=status_code >= 500,
            )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion."""
        client = await self._get_client()
        model = self.get_model(request.model)

        messages = self._convert_messages(request.messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {},
        }

        if request.temperature is not None:
            payload["options"]["temperature"] = request.temperature
        if request.max_tokens:
            payload["options"]["num_predict"] = request.max_tokens

        tools = self._convert_tools(request.tools)
        if tools:
            payload["tools"] = tools

        logger.debug("Ollama request: model=%s, messages=%d", model, len(messages))

        response = await client.post("/api/chat", json=payload)

        try:
            body = response.json()
        except json.JSONDecodeError:
            raise ProviderError(
                f"Invalid JSON response: {response.text[:200]}",
                self.name,
                status_code=response.status_code,
            )

        if response.status_code != 200:
            self._handle_error(response, body)

        message = body.get("message", {})

        return CompletionResponse(
            content=message.get("content"),
            model=body.get("model", model),
            provider=self.name,
            tool_calls=self._parse_tool_calls(message.get("tool_calls")),
            finish_reason=body.get("done_reason", "stop") if body.get("done") else None,
            usage={
                "prompt_tokens": body.get("prompt_eval_count", 0),
                "completion_tokens": body.get("eval_count", 0),
                "total_tokens": body.get("prompt_eval_count", 0)
                + body.get("eval_count", 0),
            },
            raw_response=body,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Stream a completion."""
        client = await self._get_client()
        model = self.get_model(request.model)

        messages = self._convert_messages(request.messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {},
        }

        if request.temperature is not None:
            payload["options"]["temperature"] = request.temperature
        if request.max_tokens:
            payload["options"]["num_predict"] = request.max_tokens

        tools = self._convert_tools(request.tools)
        if tools:
            payload["tools"] = tools

        logger.debug("Ollama stream: model=%s", model)

        async with client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code != 200:
                body_bytes = await response.aread()
                try:
                    error_body = json.loads(body_bytes)
                except json.JSONDecodeError:
                    error_body = {"error": body_bytes.decode()[:200]}
                self._handle_error(response, error_body)

            async for line in response.aiter_lines():
                if not line:
                    continue

                try:
                    chunk_data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message = chunk_data.get("message", {})
                content = message.get("content")
                tool_calls = self._parse_tool_calls(message.get("tool_calls"))

                done = chunk_data.get("done", False)
                finish_reason = chunk_data.get("done_reason") if done else None

                yield StreamChunk(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason or ("stop" if done else None),
                    model=chunk_data.get("model"),
                )

    async def list_models(self) -> list[str]:
        """List available models."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")

            if response.status_code != 200:
                logger.warning("Failed to list Ollama models: %s", response.text)
                return []

            body = response.json()
            models = body.get("models", [])
            return [m["name"] for m in models if "name" in m]
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)
            return []

    async def check_health(self) -> bool:
        """Check provider health."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.warning("Ollama health check failed: %s", e)
            return False

    async def pull_model(self, model: str) -> bool:
        """
        Pull a model from the Ollama library.

        Args:
            model: Model name to pull.

        Returns:
            True if successful.
        """
        try:
            client = await self._get_client()
            response = await client.post(
                "/api/pull",
                json={"name": model},
                timeout=httpx.Timeout(600.0),  # Models can take a while to download
            )
            return response.status_code == 200
        except Exception as e:
            logger.error("Failed to pull Ollama model %s: %s", model, e)
            return False
