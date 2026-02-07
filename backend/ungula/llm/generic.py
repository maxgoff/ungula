"""
Generic OpenAI-compatible LLM provider.

Can be instantiated dynamically with a name, base URL, API key, and default model
to connect to any OpenAI-compatible API endpoint.
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


class GenericOpenAIProvider(LLMProvider):
    """
    OpenAI-compatible LLM provider for arbitrary endpoints.

    Unlike built-in providers, name and display_name are set at instantiation
    rather than being class-level constants.
    """

    def __init__(
        self,
        *,
        name: str,
        display_name: str,
        api_key: str,
        base_url: str,
        default_model: str | None = None,
    ):
        self.name = name
        self.display_name = display_name
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model or "default",
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
        """Handle error responses."""
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

        if "max_tokens" not in payload or payload["max_tokens"] is None:
            payload["max_tokens"] = 4096

        logger.debug("%s request: model=%s", self.display_name, model)

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

        if "max_tokens" not in payload or payload["max_tokens"] is None:
            payload["max_tokens"] = 4096

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

                data = line[6:]
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
                                accumulated_tool_calls[idx]["function"]["name"] = tc["function"]["name"]
                            if "arguments" in tc["function"]:
                                accumulated_tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]

                finish_reason = choice.get("finish_reason")

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
        return [self.default_model] if self.default_model else []

    async def check_health(self) -> bool:
        """Check provider health with a minimal request."""
        try:
            client = await self._get_client()
            response = await client.post(
                "/chat/completions",
                json={
                    "model": self.default_model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("%s health check failed: %s", self.display_name, e)
            return False
