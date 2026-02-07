"""
NVIDIA NIM LLM provider.

Integration with NVIDIA's NIM API, which uses an OpenAI-compatible interface.
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

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"


class NVIDIAProvider(LLMProvider):
    """NVIDIA NIM LLM provider."""

    name = "nvidia"
    display_name = "NVIDIA NIM"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        """
        Initialize NVIDIA NIM provider.

        Args:
            api_key: NVIDIA API key (starts with nvapi-).
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
        """Handle error responses from NVIDIA NIM."""
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

        # NVIDIA NIM may return incomplete responses without max_tokens
        if "max_tokens" not in payload or payload["max_tokens"] is None:
            payload["max_tokens"] = 1024

        logger.debug("NVIDIA NIM request: model=%s, messages=%d", model, len(request.messages))

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

        # NVIDIA NIM may return incomplete responses without max_tokens
        if "max_tokens" not in payload or payload["max_tokens"] is None:
            payload["max_tokens"] = 1024

        logger.debug("NVIDIA NIM stream: model=%s", model)

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
        return self._get_known_models()

    def _get_known_models(self) -> list[str]:
        """Return list of known NVIDIA NIM models."""
        return [
            # Meta Llama
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-405b-instruct",
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            # Moonshot AI Kimi
            "moonshotai/kimi-k2-instruct",
            "moonshotai/kimi-k2-instruct-0905",
            "moonshotai/kimi-k2-thinking",
            "moonshotai/kimi-k2.5",
            # Mistral
            "mistralai/mistral-large-2-instruct",
            "mistralai/mixtral-8x22b-instruct-v0.1",
            # DeepSeek
            "deepseek-ai/deepseek-r1",
            # Google
            "google/gemma-2-27b-it",
            # Qwen
            "qwen/qwen2.5-72b-instruct",
            # NVIDIA
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ]

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
            logger.warning("NVIDIA NIM health check failed: %s", e)
            return False
