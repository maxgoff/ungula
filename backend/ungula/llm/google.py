"""
Google (Gemini) LLM provider.

Direct integration with Google's Generative AI API using the google-genai SDK.
"""

import json
import logging
from typing import Any, AsyncIterator

from google import genai
from google.genai import types

from .base import (
    AuthenticationError,
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    Message,
    MessageRole,
    ProviderError,
    RateLimitError,
    StreamChunk,
    ToolCall,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3-pro-preview"


class GoogleProvider(LLMProvider):
    """Google Gemini LLM provider using the google-genai SDK."""

    name = "google"
    display_name = "Google Gemini"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model or DEFAULT_MODEL,
        )
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        """Get or create the genai client."""
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def close(self) -> None:
        """Close the provider."""
        self._client = None

    def _convert_messages(
        self, messages: list[Message]
    ) -> tuple[str | None, list[types.Content]]:
        """
        Convert messages to google-genai Content format.

        Returns:
            Tuple of (system_instruction, contents)
        """
        system_instruction = None
        contents: list[types.Content] = []

        for msg in messages:
            role = msg.role.value if isinstance(msg.role, MessageRole) else msg.role

            if role == "system":
                system_instruction = msg.content
            elif role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=msg.content)],
                    )
                )
            elif role == "assistant":
                parts: list[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        parts.append(
                            types.Part.from_function_call(
                                name=tc["function"]["name"],
                                args=json.loads(tc["function"]["arguments"]),
                            )
                        )
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                contents.append(
                    types.Content(
                        role="tool",
                        parts=[
                            types.Part.from_function_response(
                                name=msg.name or "function",
                                response={"result": msg.content},
                            )
                        ],
                    )
                )

        return system_instruction, contents

    def _build_config(
        self,
        request: CompletionRequest,
        system_instruction: str | None,
    ) -> types.GenerateContentConfig:
        """Build GenerateContentConfig from request parameters."""
        config_kwargs: dict[str, Any] = {
            "temperature": request.temperature,
        }
        if request.max_tokens:
            config_kwargs["max_output_tokens"] = request.max_tokens
        if request.stop:
            config_kwargs["stop_sequences"] = request.stop
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if request.tools:
            config_kwargs["tools"] = [
                {
                    "function_declarations": [
                        {
                            "name": td.name,
                            "description": td.description,
                            "parameters": td.parameters,
                        }
                        for td in request.tools
                    ]
                }
            ]

        # Apply provider-specific params
        pp = request.provider_params
        if pp.get("safety_settings"):
            config_kwargs["safety_settings"] = pp["safety_settings"]
        # Allow extra generation config keys (top_p, top_k, etc.)
        for key in ("top_p", "top_k", "presence_penalty", "frequency_penalty"):
            if pp.get(key) is not None:
                config_kwargs[key] = pp[key]

        return types.GenerateContentConfig(**config_kwargs)

    def _parse_tool_calls(self, parts: list[Any]) -> list[ToolCall] | None:
        """Parse tool calls from response parts."""
        tool_calls = []
        for i, part in enumerate(parts):
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(
                    ToolCall(
                        id=f"call_{i}",
                        name=fc.name,
                        arguments=json.dumps(dict(fc.args)),
                    )
                )
        return tool_calls if tool_calls else None

    def _extract_text(self, parts: list[Any]) -> str | None:
        """Extract text content from response parts."""
        texts = []
        for part in parts:
            if hasattr(part, "text") and part.text:
                texts.append(part.text)
        return "\n".join(texts) if texts else None

    def _handle_error(self, e: Exception) -> None:
        """Handle Google API errors."""
        error_str = str(e).lower()
        if "api key" in error_str or "authentication" in error_str:
            raise AuthenticationError(str(e), self.name)
        elif "quota" in error_str or "rate" in error_str:
            raise RateLimitError(str(e), self.name)
        else:
            raise ProviderError(str(e), self.name)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion."""
        client = self._get_client()
        model_name = self.get_model(request.model)
        system_instruction, contents = self._convert_messages(request.messages)
        config = self._build_config(request, system_instruction)

        logger.debug("Google request: model=%s, messages=%d", model_name, len(contents))

        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            self._handle_error(e)
            raise

        candidate = response.candidates[0]
        parts = candidate.content.parts

        finish_reason = None
        if candidate.finish_reason:
            fr = candidate.finish_reason
            finish_reason = fr.name.lower() if hasattr(fr, "name") else str(fr).lower()

        usage = None
        if response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, "prompt_token_count", 0),
                "completion_tokens": getattr(um, "candidates_token_count", 0),
                "total_tokens": getattr(um, "total_token_count", 0),
            }

        return CompletionResponse(
            content=self._extract_text(parts),
            model=model_name,
            provider=self.name,
            tool_calls=self._parse_tool_calls(parts),
            finish_reason=finish_reason,
            usage=usage,
            raw_response={"candidates": [{"content": {"parts": [str(p) for p in parts]}}]},
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Stream a completion."""
        client = self._get_client()
        model_name = self.get_model(request.model)
        system_instruction, contents = self._convert_messages(request.messages)
        config = self._build_config(request, system_instruction)

        logger.debug("Google stream: model=%s", model_name)

        try:
            async for chunk in await client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=config,
            ):
                if chunk.candidates:
                    candidate = chunk.candidates[0]
                    parts = candidate.content.parts

                    content = self._extract_text(parts)
                    tool_calls = self._parse_tool_calls(parts)

                    finish_reason = None
                    if candidate.finish_reason:
                        fr = candidate.finish_reason
                        finish_reason = (
                            fr.name.lower() if hasattr(fr, "name") else str(fr).lower()
                        )

                    yield StreamChunk(
                        content=content,
                        tool_calls=tool_calls,
                        finish_reason=finish_reason,
                        model=model_name,
                    )
        except Exception as e:
            self._handle_error(e)

    async def list_models(self) -> list[str]:
        """List available models."""
        client = self._get_client()
        try:
            models = []
            async for m in await client.aio.models.list():
                name = getattr(m, "name", "")
                if name:
                    models.append(name.replace("models/", ""))
            return models
        except Exception as e:
            logger.warning("Failed to list Google models: %s", e)
            return [
                "gemini-3-pro-preview",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
            ]

    async def check_health(self) -> bool:
        """Check provider health."""
        try:
            client = self._get_client()
            pager = await client.aio.models.list(config={"page_size": 1})
            _ = pager[0]
            return True
        except Exception as e:
            logger.warning("Google health check failed: %s", e)
            return False
