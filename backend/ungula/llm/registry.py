"""
LLM Provider Registry.

Manages multiple LLM providers with support for failover, model routing,
and provider health tracking.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator

from ..config import LLMConfig, LLMProviderConfig
from .anthropic import AnthropicProvider
from .base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ProviderError,
    RateLimitError,
    StreamChunk,
)
from .google import GoogleProvider
from .nvidia import NVIDIAProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .xai import XAIProvider

logger = logging.getLogger(__name__)


@dataclass
class ProviderStatus:
    """Status tracking for a provider."""

    healthy: bool = True
    last_check: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    backoff_until: datetime | None = None


@dataclass
class ProviderRegistry:
    """
    Registry for LLM providers with failover support.

    Manages multiple providers, tracks their health, and provides
    automatic failover when a provider fails.
    """

    providers: dict[str, LLMProvider] = field(default_factory=dict)
    status: dict[str, ProviderStatus] = field(default_factory=dict)
    default_provider: str = "openrouter"
    failover_order: list[str] = field(default_factory=list)
    max_retries: int = 3
    base_backoff: float = 1.0
    max_backoff: float = 60.0

    def register(self, provider: LLMProvider) -> None:
        """Register a provider."""
        self.providers[provider.name] = provider
        self.status[provider.name] = ProviderStatus()
        if provider.name not in self.failover_order:
            self.failover_order.append(provider.name)
        logger.info("Registered LLM provider: %s", provider.name)

    def unregister(self, name: str) -> None:
        """Unregister a provider."""
        if name in self.providers:
            del self.providers[name]
        if name in self.status:
            del self.status[name]
        if name in self.failover_order:
            self.failover_order.remove(name)
        logger.info("Unregistered LLM provider: %s", name)

    def get(self, name: str) -> LLMProvider | None:
        """Get a provider by name."""
        return self.providers.get(name)

    def list_providers(self) -> list[str]:
        """List all registered provider names."""
        return list(self.providers.keys())

    def is_available(self, name: str) -> bool:
        """Check if a provider is available (registered and not in backoff)."""
        if name not in self.providers:
            return False
        status = self.status.get(name)
        if status and status.backoff_until:
            if datetime.now(UTC) < status.backoff_until:
                return False
        return True

    def _get_available_providers(self) -> list[str]:
        """Get list of available providers in failover order."""
        return [p for p in self.failover_order if self.is_available(p)]

    def _record_success(self, name: str) -> None:
        """Record a successful request to a provider."""
        if name in self.status:
            self.status[name].healthy = True
            self.status[name].consecutive_failures = 0
            self.status[name].backoff_until = None
            self.status[name].last_error = None

    def _record_failure(self, name: str, error: Exception) -> None:
        """Record a failed request to a provider."""
        if name not in self.status:
            return

        status = self.status[name]
        status.consecutive_failures += 1
        status.last_error = str(error)

        # Calculate backoff
        if isinstance(error, RateLimitError) and error.retry_after:
            backoff = error.retry_after
        else:
            backoff = min(
                self.base_backoff * (2 ** (status.consecutive_failures - 1)),
                self.max_backoff,
            )

        status.backoff_until = datetime.now(UTC) + timedelta(seconds=backoff)
        logger.warning(
            "Provider %s failed (attempt %d), backing off for %.1f seconds: %s",
            name,
            status.consecutive_failures,
            backoff,
            error,
        )

    async def complete(
        self,
        request: CompletionRequest,
        provider: str | None = None,
        allow_failover: bool = True,
    ) -> CompletionResponse:
        """
        Generate a completion, with optional failover.

        Args:
            request: The completion request.
            provider: Specific provider to use (overrides default).
            allow_failover: Whether to try other providers on failure.

        Returns:
            The completion response.

        Raises:
            ProviderError: If all providers fail.
        """
        providers_to_try = []

        if provider:
            if provider not in self.providers:
                raise ProviderError(f"Unknown provider: {provider}", "registry")
            providers_to_try.append(provider)
            if allow_failover:
                providers_to_try.extend(
                    [p for p in self._get_available_providers() if p != provider]
                )
        else:
            providers_to_try = self._get_available_providers()
            if not providers_to_try:
                raise ProviderError("No providers available", "registry")

        last_error: Exception | None = None

        for provider_name in providers_to_try:
            provider_instance = self.providers.get(provider_name)
            if not provider_instance:
                continue

            try:
                response = await provider_instance.complete(request)
                self._record_success(provider_name)
                return response
            except ProviderError as e:
                self._record_failure(provider_name, e)
                last_error = e
                if not allow_failover or not e.retryable:
                    raise
            except Exception as e:
                self._record_failure(provider_name, e)
                last_error = e
                if not allow_failover:
                    raise ProviderError(str(e), provider_name)

        raise ProviderError(
            f"All providers failed. Last error: {last_error}",
            "registry",
        )

    async def stream(
        self,
        request: CompletionRequest,
        provider: str | None = None,
        allow_failover: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream a completion, with optional failover.

        Note: Failover only happens before streaming starts, not during.

        Args:
            request: The completion request.
            provider: Specific provider to use.
            allow_failover: Whether to try other providers on initial failure.

        Yields:
            Stream chunks.

        Raises:
            ProviderError: If connection fails.
        """
        providers_to_try = []

        if provider:
            if provider not in self.providers:
                raise ProviderError(f"Unknown provider: {provider}", "registry")
            providers_to_try.append(provider)
            if allow_failover:
                providers_to_try.extend(
                    [p for p in self._get_available_providers() if p != provider]
                )
        else:
            providers_to_try = self._get_available_providers()
            if not providers_to_try:
                raise ProviderError("No providers available", "registry")

        last_error: Exception | None = None

        for provider_name in providers_to_try:
            provider_instance = self.providers.get(provider_name)
            if not provider_instance:
                continue

            try:
                async for chunk in provider_instance.stream(request):
                    yield chunk
                self._record_success(provider_name)
                return
            except ProviderError as e:
                self._record_failure(provider_name, e)
                last_error = e
                if not allow_failover or not e.retryable:
                    raise
            except Exception as e:
                self._record_failure(provider_name, e)
                last_error = e
                if not allow_failover:
                    raise ProviderError(str(e), provider_name)

        raise ProviderError(
            f"All providers failed. Last error: {last_error}",
            "registry",
        )

    async def check_health(self, name: str | None = None) -> dict[str, bool]:
        """
        Check health of providers.

        Args:
            name: Specific provider to check, or None for all.

        Returns:
            Dictionary mapping provider names to health status.
        """
        providers_to_check = [name] if name else list(self.providers.keys())
        results = {}

        async def check_one(provider_name: str) -> tuple[str, bool]:
            provider = self.providers.get(provider_name)
            if not provider:
                return provider_name, False
            try:
                healthy = await provider.check_health()
                self.status[provider_name].healthy = healthy
                self.status[provider_name].last_check = datetime.now(UTC)
                return provider_name, healthy
            except Exception as e:
                logger.warning("Health check failed for %s: %s", provider_name, e)
                self.status[provider_name].healthy = False
                self.status[provider_name].last_check = datetime.now(UTC)
                return provider_name, False

        checks = await asyncio.gather(*[check_one(p) for p in providers_to_check])
        results = dict(checks)
        return results

    async def list_models(self, provider: str | None = None) -> dict[str, list[str]]:
        """
        List available models.

        Args:
            provider: Specific provider, or None for all.

        Returns:
            Dictionary mapping provider names to model lists.
        """
        providers_to_query = [provider] if provider else list(self.providers.keys())
        results = {}

        for provider_name in providers_to_query:
            provider_instance = self.providers.get(provider_name)
            if provider_instance:
                try:
                    models = await provider_instance.list_models()
                    results[provider_name] = models
                except Exception as e:
                    logger.warning("Failed to list models for %s: %s", provider_name, e)
                    results[provider_name] = []

        return results

    async def close(self) -> None:
        """Close all providers."""
        for provider in self.providers.values():
            try:
                await provider.close()
            except Exception as e:
                logger.warning("Error closing provider %s: %s", provider.name, e)

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all providers."""
        result = {}
        for name, status in self.status.items():
            result[name] = {
                "healthy": status.healthy,
                "last_check": status.last_check.isoformat() if status.last_check else None,
                "last_error": status.last_error,
                "consecutive_failures": status.consecutive_failures,
                "backoff_until": status.backoff_until.isoformat()
                if status.backoff_until
                else None,
                "available": self.is_available(name),
            }
        return result


def create_registry_from_config(config: LLMConfig) -> ProviderRegistry:
    """
    Create a provider registry from configuration.

    Args:
        config: LLM configuration.

    Returns:
        Configured provider registry.
    """
    registry = ProviderRegistry(default_provider=config.default_provider)

    def create_if_enabled(
        name: str,
        provider_config: LLMProviderConfig,
        provider_class: type[LLMProvider],
    ) -> None:
        if provider_config.enabled and provider_config.api_key:
            provider = provider_class(
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
                default_model=provider_config.default_model,
            )
            registry.register(provider)

    # Register providers
    create_if_enabled("openrouter", config.openrouter, OpenRouterProvider)
    create_if_enabled("anthropic", config.anthropic, AnthropicProvider)
    create_if_enabled("openai", config.openai, OpenAIProvider)
    create_if_enabled("google", config.google, GoogleProvider)
    create_if_enabled("xai", config.xai, XAIProvider)
    create_if_enabled("nvidia", config.nvidia, NVIDIAProvider)

    # Ollama doesn't require API key
    if config.ollama.enabled:
        provider = OllamaProvider(
            base_url=config.ollama.base_url,
            default_model=config.ollama.default_model,
        )
        registry.register(provider)

    # Register custom OpenAI-compatible providers
    from .generic import GenericOpenAIProvider

    for custom in config.custom_providers:
        if custom.enabled and custom.api_key:
            provider = GenericOpenAIProvider(
                name=custom.name,
                display_name=custom.display_name,
                api_key=custom.api_key,
                base_url=custom.base_url,
                default_model=custom.default_model,
            )
            registry.register(provider)

    # Set failover order: user-configured > auto (default provider first)
    if config.failover_order:
        # Use user-configured order, filtered to actually registered providers
        user_order = [p for p in config.failover_order if p in registry.providers]
        # Append any registered providers not in user list (safety net)
        for p in registry.failover_order:
            if p not in user_order:
                user_order.append(p)
        registry.failover_order = user_order
    elif config.default_provider in registry.providers:
        registry.failover_order.remove(config.default_provider)
        registry.failover_order.insert(0, config.default_provider)

    return registry
