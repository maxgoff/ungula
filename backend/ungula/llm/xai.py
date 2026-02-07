"""
X.ai (Grok) LLM provider.

Integration with X.ai's Grok API, which uses an OpenAI-compatible interface.
"""

import json
import logging
from typing import Any, AsyncIterator

import httpx

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

DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4-1-fast-reasoning"


class XAIProvider(LLMProvider):
    """X.ai (Grok) LLM provider."""

    name = "xai"
    display_name = "X.ai (Grok)"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        """
        Initialize X.ai provider.

        Args:
            api_key: X.ai API key.
            base_url: Base URL for API calls.
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
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _handle_error(self, response: httpx.Response, body: dict[str, Any]) -> None:
        """Handle error responses from X.ai."""
        status_code = response.status_code
        error_msg = body.get("error", {})
        if isinstance(error_msg, dict):
            message = error_msg.get("message", str(body))
        else:
            message = str(error_msg)

        if status_code == 401:
            raise AuthenticationError(message, self.name)
        elif status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise RateLimitError(
                message,
                self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        elif status_code == 404:
            raise ModelNotFoundError(message, self.name, model="unknown")
        else:
            raise ProviderError(
                message,
                self.name,
                status_code=status_code,
                retryable=status_code >= 500,
            )

    def _parse_tool_calls(
        self, tool_calls_data: list[dict[str, Any]] | None
    ) -> list[ToolCall] | None:
        """Parse tool calls from response."""
        if not tool_calls_data:
            return None
        return [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            )
            for tc in tool_calls_data
        ]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion."""
        client = await self._get_client()
        model = self.get_model(request.model)

        payload = request.to_dict()
        payload["model"] = model
        payload["stream"] = False

        logger.debug("X.ai request: model=%s, messages=%d", model, len(request.messages))

        response = await client.post("/chat/completions", json=payload)

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

        choice = body["choices"][0]
        message = choice["message"]

        return CompletionResponse(
            content=message.get("content"),
            model=body.get("model", model),
            provider=self.name,
            tool_calls=self._parse_tool_calls(message.get("tool_calls")),
            finish_reason=choice.get("finish_reason"),
            usage=body.get("usage"),
            raw_response=body,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Stream a completion."""
        client = await self._get_client()
        model = self.get_model(request.model)

        payload = request.to_dict()
        payload["model"] = model
        payload["stream"] = True

        logger.debug("X.ai stream: model=%s", model)

        async with client.stream("POST", "/chat/completions", json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                try:
                    error_body = json.loads(body)
                except json.JSONDecodeError:
                    error_body = {"error": body.decode()[:200]}
                self._handle_error(response, error_body)

            accumulated_tool_calls: dict[int, dict[str, Any]] = {}

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data = line[6:]  # Remove "data: " prefix
                if data == "[DONE]":
                    break

                try:
                    chunk_data = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if "choices" not in chunk_data or not chunk_data["choices"]:
                    continue

                choice = chunk_data["choices"][0]
                delta = choice.get("delta", {})

                content = delta.get("content")

                # Handle tool calls
                tool_calls_delta = delta.get("tool_calls")
                tool_calls = None
                if tool_calls_delta:
                    for tc in tool_calls_delta:
                        idx = tc.get("index", 0)
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": tc.get("id", ""),
                                "function": {"name": "", "arguments": ""},
                            }
                        if "id" in tc and tc["id"]:
                            accumulated_tool_calls[idx]["id"] = tc["id"]
                        if "function" in tc:
                            if "name" in tc["function"]:
                                accumulated_tool_calls[idx]["function"]["name"] = tc[
                                    "function"
                                ]["name"]
                            if "arguments" in tc["function"]:
                                accumulated_tool_calls[idx]["function"][
                                    "arguments"
                                ] += tc["function"]["arguments"]

                finish_reason = choice.get("finish_reason")

                # On finish, emit accumulated tool calls
                if finish_reason and accumulated_tool_calls:
                    tool_calls = [
                        ToolCall(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        )
                        for tc in accumulated_tool_calls.values()
                    ]

                yield StreamChunk(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                    model=chunk_data.get("model"),
                )

    async def list_models(self) -> list[str]:
        """List available models."""
        try:
            client = await self._get_client()
            response = await client.get("/models")

            if response.status_code != 200:
                logger.warning("Failed to list X.ai models: %s", response.text)
                return self._get_known_models()

            body = response.json()
            models = body.get("data", [])
            return [m["id"] for m in models if "id" in m]
        except Exception as e:
            logger.warning("Failed to list X.ai models: %s", e)
            return self._get_known_models()

    def _get_known_models(self) -> list[str]:
        """Return list of known Grok models."""
        return [
            "grok-4-1-fast-reasoning",
            "grok-4-1",
            "grok-3",
            "grok-3-vision",
            "grok-beta",
        ]

    async def check_health(self) -> bool:
        """Check provider health."""
        try:
            client = await self._get_client()
            response = await client.get("/models")
            return response.status_code == 200
        except Exception as e:
            logger.warning("X.ai health check failed: %s", e)
            return False
