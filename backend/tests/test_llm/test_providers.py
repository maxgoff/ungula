"""
Tests for LLM provider initialization and basic attributes.

Covers all eight providers: OpenRouter, Anthropic, OpenAI, Google, xAI,
Ollama, NVIDIA, and GenericOpenAI.  Tests only initialization, class
attributes, and synchronous helper methods -- no actual API calls.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ungula.llm.anthropic import AnthropicProvider
from ungula.llm.base import (
    AuthenticationError,
    LLMProvider,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
)
from ungula.llm.generic import GenericOpenAIProvider
from ungula.llm.google import GoogleProvider
from ungula.llm.nvidia import NVIDIAProvider
from ungula.llm.ollama import OllamaProvider
from ungula.llm.openai import OpenAIProvider
from ungula.llm.openrouter import OpenRouterProvider
from ungula.llm.xai import XAIProvider


# ---------------------------------------------------------------------------
# OpenRouterProvider
# ---------------------------------------------------------------------------


class TestOpenRouterProvider:
    """Tests for OpenRouterProvider."""

    def test_name_and_display_name(self):
        p = OpenRouterProvider(api_key="test-key")
        assert p.name == "openrouter"
        assert p.display_name == "OpenRouter"

    def test_default_model(self):
        p = OpenRouterProvider(api_key="test-key")
        assert p.default_model == "anthropic/claude-opus-4.5"

    def test_custom_model(self):
        p = OpenRouterProvider(api_key="k", default_model="meta/llama-3")
        assert p.default_model == "meta/llama-3"

    def test_api_key_stored(self):
        p = OpenRouterProvider(api_key="my-secret-key")
        assert p.api_key == "my-secret-key"

    def test_default_base_url(self):
        p = OpenRouterProvider(api_key="k")
        assert p.base_url == "https://openrouter.ai/api/v1"

    def test_custom_base_url(self):
        p = OpenRouterProvider(api_key="k", base_url="https://custom.api/v1")
        assert p.base_url == "https://custom.api/v1"

    def test_app_name_default(self):
        p = OpenRouterProvider(api_key="k")
        assert p.app_name == "Ungula"

    def test_app_name_custom(self):
        p = OpenRouterProvider(api_key="k", app_name="MyApp")
        assert p.app_name == "MyApp"

    def test_client_initially_none(self):
        p = OpenRouterProvider(api_key="k")
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = OpenRouterProvider(api_key="k")
        # Simulate a client being created
        p._client = httpx.AsyncClient()
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(OpenRouterProvider, LLMProvider)

    def test_has_required_methods(self):
        p = OpenRouterProvider(api_key="k")
        assert hasattr(p, "complete")
        assert hasattr(p, "stream")
        assert hasattr(p, "list_models")
        assert hasattr(p, "check_health")
        assert hasattr(p, "close")

    # --- _parse_tool_calls ---

    def test_parse_tool_calls_valid(self):
        p = OpenRouterProvider(api_key="k")
        data = [
            {
                "id": "call_1",
                "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'},
            },
            {
                "id": "call_2",
                "function": {"name": "search", "arguments": '{"q":"test"}'},
            },
        ]
        result = p._parse_tool_calls(data)
        assert result is not None
        assert len(result) == 2
        assert result[0].id == "call_1"
        assert result[0].name == "get_weather"
        assert result[0].arguments == '{"city":"NYC"}'
        assert result[1].id == "call_2"

    def test_parse_tool_calls_none(self):
        p = OpenRouterProvider(api_key="k")
        assert p._parse_tool_calls(None) is None

    def test_parse_tool_calls_empty_list(self):
        p = OpenRouterProvider(api_key="k")
        assert p._parse_tool_calls([]) is None

    # --- _handle_error ---

    def _make_response(self, status_code: int, headers: dict | None = None) -> httpx.Response:
        """Build a mock httpx.Response."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.headers = headers or {}
        return resp

    def test_handle_error_401(self):
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(401)
        body = {"error": {"message": "Invalid API key"}}
        with pytest.raises(AuthenticationError) as exc_info:
            p._handle_error(resp, body)
        assert exc_info.value.provider == "openrouter"
        assert exc_info.value.status_code == 401

    def test_handle_error_429(self):
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(429, headers={"retry-after": "30"})
        body = {"error": {"message": "Rate limit exceeded"}}
        with pytest.raises(RateLimitError) as exc_info:
            p._handle_error(resp, body)
        assert exc_info.value.retry_after == 30.0
        assert exc_info.value.retryable is True

    def test_handle_error_429_no_retry_after(self):
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(429)
        body = {"error": {"message": "Rate limit"}}
        with pytest.raises(RateLimitError) as exc_info:
            p._handle_error(resp, body)
        assert exc_info.value.retry_after is None

    def test_handle_error_404(self):
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(404)
        body = {"error": {"message": "Model not found"}}
        with pytest.raises(ModelNotFoundError) as exc_info:
            p._handle_error(resp, body)
        assert exc_info.value.status_code == 404

    def test_handle_error_500(self):
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(500)
        body = {"error": {"message": "Internal error"}}
        with pytest.raises(ProviderError) as exc_info:
            p._handle_error(resp, body)
        assert exc_info.value.status_code == 500
        assert exc_info.value.retryable is True

    def test_handle_error_502_retryable(self):
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(502)
        body = {"error": {"message": "Bad gateway"}}
        with pytest.raises(ProviderError) as exc_info:
            p._handle_error(resp, body)
        assert exc_info.value.retryable is True

    def test_handle_error_400_not_retryable(self):
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(400)
        body = {"error": {"message": "Bad request"}}
        with pytest.raises(ProviderError) as exc_info:
            p._handle_error(resp, body)
        assert exc_info.value.retryable is False

    def test_handle_error_string_error_body(self):
        """error field can be a string instead of a dict."""
        p = OpenRouterProvider(api_key="k")
        resp = self._make_response(500)
        body = {"error": "Something went wrong"}
        with pytest.raises(ProviderError) as exc_info:
            p._handle_error(resp, body)
        assert "Something went wrong" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AnthropicProvider
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    def test_name_and_display_name(self):
        p = AnthropicProvider(api_key="test-key")
        assert p.name == "anthropic"
        assert p.display_name == "Anthropic"

    def test_default_model(self):
        p = AnthropicProvider(api_key="k")
        assert p.default_model == "claude-opus-4-5-20250514"

    def test_custom_model(self):
        p = AnthropicProvider(api_key="k", default_model="claude-sonnet-4-20250514")
        assert p.default_model == "claude-sonnet-4-20250514"

    def test_api_key_stored(self):
        p = AnthropicProvider(api_key="my-key")
        assert p.api_key == "my-key"

    def test_default_base_url(self):
        p = AnthropicProvider(api_key="k")
        assert p.base_url is None

    def test_custom_base_url(self):
        p = AnthropicProvider(api_key="k", base_url="https://proxy.example.com")
        assert p.base_url == "https://proxy.example.com"

    def test_client_initially_none(self):
        p = AnthropicProvider(api_key="k")
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = AnthropicProvider(api_key="k")
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        p._client = mock_client
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(AnthropicProvider, LLMProvider)


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    def test_name_and_display_name(self):
        p = OpenAIProvider(api_key="k")
        assert p.name == "openai"
        assert p.display_name == "OpenAI"

    def test_default_model(self):
        p = OpenAIProvider(api_key="k")
        assert p.default_model == "gpt-5.2"

    def test_custom_model(self):
        p = OpenAIProvider(api_key="k", default_model="gpt-4o")
        assert p.default_model == "gpt-4o"

    def test_api_key_stored(self):
        p = OpenAIProvider(api_key="sk-test")
        assert p.api_key == "sk-test"

    def test_default_base_url(self):
        p = OpenAIProvider(api_key="k")
        assert p.base_url is None

    def test_custom_base_url(self):
        p = OpenAIProvider(api_key="k", base_url="https://azure.proxy.com")
        assert p.base_url == "https://azure.proxy.com"

    def test_client_initially_none(self):
        p = OpenAIProvider(api_key="k")
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = OpenAIProvider(api_key="k")
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        p._client = mock_client
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(OpenAIProvider, LLMProvider)


# ---------------------------------------------------------------------------
# GoogleProvider
# ---------------------------------------------------------------------------


class TestGoogleProvider:
    """Tests for GoogleProvider."""

    def test_name_and_display_name(self):
        p = GoogleProvider(api_key="k")
        assert p.name == "google"
        assert p.display_name == "Google Gemini"

    def test_default_model(self):
        p = GoogleProvider(api_key="k")
        assert p.default_model == "gemini-3-pro-preview"

    def test_custom_model(self):
        p = GoogleProvider(api_key="k", default_model="gemini-2.5-pro")
        assert p.default_model == "gemini-2.5-pro"

    def test_api_key_stored(self):
        p = GoogleProvider(api_key="goog-key")
        assert p.api_key == "goog-key"

    def test_default_base_url(self):
        p = GoogleProvider(api_key="k")
        assert p.base_url is None

    def test_client_initially_none(self):
        p = GoogleProvider(api_key="k")
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = GoogleProvider(api_key="k")
        p._client = MagicMock()
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(GoogleProvider, LLMProvider)


# ---------------------------------------------------------------------------
# XAIProvider
# ---------------------------------------------------------------------------


class TestXAIProvider:
    """Tests for XAIProvider."""

    def test_name_and_display_name(self):
        p = XAIProvider(api_key="k")
        assert p.name == "xai"
        assert p.display_name == "X.ai (Grok)"

    def test_default_model(self):
        p = XAIProvider(api_key="k")
        assert p.default_model == "grok-4-1-fast-reasoning"

    def test_custom_model(self):
        p = XAIProvider(api_key="k", default_model="grok-3")
        assert p.default_model == "grok-3"

    def test_api_key_stored(self):
        p = XAIProvider(api_key="xai-key")
        assert p.api_key == "xai-key"

    def test_default_base_url(self):
        p = XAIProvider(api_key="k")
        assert p.base_url == "https://api.x.ai/v1"

    def test_custom_base_url(self):
        p = XAIProvider(api_key="k", base_url="https://custom.xai.com")
        assert p.base_url == "https://custom.xai.com"

    def test_client_initially_none(self):
        p = XAIProvider(api_key="k")
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = XAIProvider(api_key="k")
        p._client = httpx.AsyncClient()
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(XAIProvider, LLMProvider)

    def test_has_known_models_method(self):
        p = XAIProvider(api_key="k")
        known = p._get_known_models()
        assert isinstance(known, list)
        assert len(known) > 0
        assert "grok-4-1-fast-reasoning" in known


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------


class TestOllamaProvider:
    """Tests for OllamaProvider."""

    def test_name_and_display_name(self):
        p = OllamaProvider()
        assert p.name == "ollama"
        assert p.display_name == "Ollama (Local)"

    def test_default_model(self):
        p = OllamaProvider()
        assert p.default_model == "llama3.2"

    def test_custom_model(self):
        p = OllamaProvider(default_model="mistral")
        assert p.default_model == "mistral"

    def test_api_key_not_required(self):
        """Ollama does not require an API key."""
        p = OllamaProvider()
        assert p.api_key is None

    def test_default_base_url(self):
        p = OllamaProvider()
        assert p.base_url == "http://localhost:11434"

    def test_custom_base_url(self):
        p = OllamaProvider(base_url="http://192.168.1.100:11434")
        assert p.base_url == "http://192.168.1.100:11434"

    def test_client_initially_none(self):
        p = OllamaProvider()
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = OllamaProvider()
        p._client = httpx.AsyncClient()
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(OllamaProvider, LLMProvider)

    def test_has_pull_model_method(self):
        """Ollama has a unique pull_model method."""
        p = OllamaProvider()
        assert hasattr(p, "pull_model")


# ---------------------------------------------------------------------------
# NVIDIAProvider
# ---------------------------------------------------------------------------


class TestNVIDIAProvider:
    """Tests for NVIDIAProvider (NIM)."""

    def test_name_and_display_name(self):
        p = NVIDIAProvider(api_key="nvapi-test")
        assert p.name == "nvidia"
        assert p.display_name == "NVIDIA NIM"

    def test_default_model(self):
        p = NVIDIAProvider(api_key="k")
        assert p.default_model == "meta/llama-3.3-70b-instruct"

    def test_custom_model(self):
        p = NVIDIAProvider(api_key="k", default_model="deepseek-ai/deepseek-r1")
        assert p.default_model == "deepseek-ai/deepseek-r1"

    def test_api_key_stored(self):
        p = NVIDIAProvider(api_key="nvapi-abc123")
        assert p.api_key == "nvapi-abc123"

    def test_default_base_url(self):
        p = NVIDIAProvider(api_key="k")
        assert p.base_url == "https://integrate.api.nvidia.com/v1"

    def test_custom_base_url(self):
        p = NVIDIAProvider(api_key="k", base_url="https://custom.nvidia.com/v1")
        assert p.base_url == "https://custom.nvidia.com/v1"

    def test_client_initially_none(self):
        p = NVIDIAProvider(api_key="k")
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = NVIDIAProvider(api_key="k")
        p._client = httpx.AsyncClient()
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(NVIDIAProvider, LLMProvider)

    def test_known_models_list(self):
        p = NVIDIAProvider(api_key="k")
        known = p._get_known_models()
        assert isinstance(known, list)
        assert "meta/llama-3.3-70b-instruct" in known


# ---------------------------------------------------------------------------
# GenericOpenAIProvider
# ---------------------------------------------------------------------------


class TestGenericOpenAIProvider:
    """Tests for GenericOpenAIProvider."""

    def test_name_and_display_name(self):
        p = GenericOpenAIProvider(
            name="custom-llm",
            display_name="Custom LLM",
            api_key="key",
            base_url="https://llm.example.com/v1",
        )
        assert p.name == "custom-llm"
        assert p.display_name == "Custom LLM"

    def test_default_model_when_none(self):
        p = GenericOpenAIProvider(
            name="g",
            display_name="G",
            api_key="key",
            base_url="https://example.com",
        )
        assert p.default_model == "default"

    def test_custom_model(self):
        p = GenericOpenAIProvider(
            name="g",
            display_name="G",
            api_key="key",
            base_url="https://example.com",
            default_model="my-model-v2",
        )
        assert p.default_model == "my-model-v2"

    def test_api_key_stored(self):
        p = GenericOpenAIProvider(
            name="g",
            display_name="G",
            api_key="secret-key",
            base_url="https://example.com",
        )
        assert p.api_key == "secret-key"

    def test_base_url_stored(self):
        p = GenericOpenAIProvider(
            name="g",
            display_name="G",
            api_key="key",
            base_url="https://custom.endpoint.com/v1",
        )
        assert p.base_url == "https://custom.endpoint.com/v1"

    def test_client_initially_none(self):
        p = GenericOpenAIProvider(
            name="g", display_name="G", api_key="key", base_url="https://example.com"
        )
        assert p._client is None

    @pytest.mark.asyncio
    async def test_close_resets_client(self):
        p = GenericOpenAIProvider(
            name="g", display_name="G", api_key="key", base_url="https://example.com"
        )
        p._client = httpx.AsyncClient()
        await p.close()
        assert p._client is None

    def test_is_llm_provider_subclass(self):
        assert issubclass(GenericOpenAIProvider, LLMProvider)

    def test_requires_keyword_only_args(self):
        """GenericOpenAIProvider __init__ uses keyword-only parameters."""
        with pytest.raises(TypeError):
            GenericOpenAIProvider("g", "G", "key", "https://example.com")


# ---------------------------------------------------------------------------
# Cross-cutting: get_model() fallback
# ---------------------------------------------------------------------------


class TestGetModelFallback:
    """Test the get_model() method inherited from LLMProvider."""

    def test_uses_request_model_when_provided(self):
        p = OpenRouterProvider(api_key="k")
        assert p.get_model("custom/model") == "custom/model"

    def test_falls_back_to_default(self):
        p = OpenRouterProvider(api_key="k")
        assert p.get_model(None) == "anthropic/claude-opus-4.5"

    def test_raises_when_no_model(self):
        """If no request model and no default, should raise ValueError."""
        p = OpenRouterProvider(api_key="k")
        p.default_model = None
        with pytest.raises(ValueError, match="No model specified"):
            p.get_model(None)


# ---------------------------------------------------------------------------
# Cross-cutting: __repr__
# ---------------------------------------------------------------------------


class TestProviderRepr:
    """Test __repr__ from LLMProvider base class."""

    def test_openrouter_repr(self):
        p = OpenRouterProvider(api_key="k")
        r = repr(p)
        assert "OpenRouterProvider" in r
        assert "openrouter" in r

    def test_anthropic_repr(self):
        p = AnthropicProvider(api_key="k")
        r = repr(p)
        assert "AnthropicProvider" in r
        assert "anthropic" in r

    def test_ollama_repr(self):
        p = OllamaProvider()
        r = repr(p)
        assert "OllamaProvider" in r
        assert "llama3.2" in r

    def test_generic_repr(self):
        p = GenericOpenAIProvider(
            name="my-custom",
            display_name="My Custom",
            api_key="k",
            base_url="https://example.com",
        )
        r = repr(p)
        assert "GenericOpenAIProvider" in r
        assert "my-custom" in r
