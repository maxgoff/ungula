"""
Tests for LLM Provider Registry.
"""

from datetime import UTC, datetime, timedelta
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from ungula.llm import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    Message,
    MessageRole,
    ProviderError,
    RateLimitError,
    StreamChunk,
)
from ungula.llm.registry import ProviderRegistry, ProviderStatus


class MockProvider(LLMProvider):
    """Mock provider for testing."""

    name = "mock"
    display_name = "Mock Provider"

    def __init__(self, should_fail: bool = False, fail_count: int = 0):
        super().__init__(api_key="test", default_model="mock-model")
        self.should_fail = should_fail
        self.fail_count = fail_count
        self.call_count = 0

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.call_count += 1
        if self.should_fail or (self.fail_count > 0 and self.call_count <= self.fail_count):
            raise ProviderError("Mock failure", self.name, retryable=True)
        return CompletionResponse(
            content="Mock response",
            model=self.default_model,
            provider=self.name,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        if self.should_fail:
            raise ProviderError("Mock failure", self.name, retryable=True)
        yield StreamChunk(content="Mock ")
        yield StreamChunk(content="response")
        yield StreamChunk(finish_reason="stop")

    async def list_models(self) -> list[str]:
        return ["mock-model"]

    async def check_health(self) -> bool:
        return not self.should_fail

    async def close(self) -> None:
        pass


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def test_register_provider(self):
        """Test registering a provider."""
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register(provider)

        assert "mock" in registry.providers
        assert "mock" in registry.status
        assert "mock" in registry.failover_order

    def test_unregister_provider(self):
        """Test unregistering a provider."""
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register(provider)
        registry.unregister("mock")

        assert "mock" not in registry.providers
        assert "mock" not in registry.status
        assert "mock" not in registry.failover_order

    def test_get_provider(self):
        """Test getting a provider by name."""
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register(provider)

        retrieved = registry.get("mock")
        assert retrieved is provider

        missing = registry.get("nonexistent")
        assert missing is None

    def test_list_providers(self):
        """Test listing provider names."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        providers = registry.list_providers()
        assert "mock" in providers

    def test_is_available(self):
        """Test checking provider availability."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        assert registry.is_available("mock") is True
        assert registry.is_available("nonexistent") is False

    def test_is_available_during_backoff(self):
        """Test provider is not available during backoff."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        # Set backoff
        registry.status["mock"].backoff_until = datetime.now(UTC) + timedelta(seconds=60)

        assert registry.is_available("mock") is False

    def test_is_available_after_backoff(self):
        """Test provider is available after backoff expires."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        # Set expired backoff
        registry.status["mock"].backoff_until = datetime.now(UTC) - timedelta(seconds=1)

        assert registry.is_available("mock") is True

    @pytest.mark.asyncio
    async def test_complete_success(self):
        """Test successful completion."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )
        response = await registry.complete(request, provider="mock")

        assert response.content == "Mock response"
        assert response.provider == "mock"

    @pytest.mark.asyncio
    async def test_complete_with_default_provider(self):
        """Test completion uses default provider."""
        registry = ProviderRegistry(default_provider="mock")
        registry.register(MockProvider())

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )
        response = await registry.complete(request)

        assert response.provider == "mock"

    @pytest.mark.asyncio
    async def test_complete_failover(self):
        """Test failover to another provider."""
        registry = ProviderRegistry()
        failing_provider = MockProvider(should_fail=True)
        failing_provider.name = "failing"
        working_provider = MockProvider()
        working_provider.name = "working"

        registry.register(failing_provider)
        registry.register(working_provider)
        registry.failover_order = ["failing", "working"]

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )
        response = await registry.complete(request)

        assert response.provider == "working"

    @pytest.mark.asyncio
    async def test_complete_no_failover(self):
        """Test without failover enabled."""
        registry = ProviderRegistry()
        failing_provider = MockProvider(should_fail=True)
        registry.register(failing_provider)

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )

        with pytest.raises(ProviderError):
            await registry.complete(request, provider="mock", allow_failover=False)

    @pytest.mark.asyncio
    async def test_complete_unknown_provider(self):
        """Test requesting unknown provider raises error."""
        registry = ProviderRegistry()

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )

        with pytest.raises(ProviderError) as exc_info:
            await registry.complete(request, provider="nonexistent")
        assert "Unknown provider" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_complete_no_providers(self):
        """Test with no providers available."""
        registry = ProviderRegistry()

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )

        with pytest.raises(ProviderError) as exc_info:
            await registry.complete(request)
        assert "No providers available" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_stream_success(self):
        """Test successful streaming."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )

        chunks = []
        async for chunk in registry.stream(request, provider="mock"):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].content == "Mock "
        assert chunks[1].content == "response"
        assert chunks[2].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_record_success_resets_failures(self):
        """Test successful request resets failure count."""
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register(provider)

        # Set up failed state
        registry.status["mock"].consecutive_failures = 3
        registry.status["mock"].backoff_until = datetime.now(UTC) + timedelta(seconds=60)

        request = CompletionRequest(
            messages=[Message(role=MessageRole.USER, content="Hello")]
        )
        await registry.complete(request, provider="mock")

        assert registry.status["mock"].consecutive_failures == 0
        assert registry.status["mock"].backoff_until is None

    @pytest.mark.asyncio
    async def test_check_health(self):
        """Test health check."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        results = await registry.check_health()

        assert results["mock"] is True
        assert registry.status["mock"].healthy is True
        assert registry.status["mock"].last_check is not None

    @pytest.mark.asyncio
    async def test_check_health_failure(self):
        """Test health check failure."""
        registry = ProviderRegistry()
        registry.register(MockProvider(should_fail=True))

        results = await registry.check_health()

        assert results["mock"] is False
        assert registry.status["mock"].healthy is False

    @pytest.mark.asyncio
    async def test_list_models(self):
        """Test listing models."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        models = await registry.list_models()

        assert "mock" in models
        assert "mock-model" in models["mock"]

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing all providers."""
        registry = ProviderRegistry()
        provider = MockProvider()
        provider.close = AsyncMock()
        registry.register(provider)

        await registry.close()

        provider.close.assert_called_once()

    def test_get_status(self):
        """Test getting provider status."""
        registry = ProviderRegistry()
        registry.register(MockProvider())

        status = registry.get_status()

        assert "mock" in status
        assert "healthy" in status["mock"]
        assert "available" in status["mock"]


class TestProviderStatus:
    """Tests for ProviderStatus."""

    def test_default_status(self):
        """Test default status values."""
        status = ProviderStatus()
        assert status.healthy is True
        assert status.last_check is None
        assert status.last_error is None
        assert status.consecutive_failures == 0
        assert status.backoff_until is None
