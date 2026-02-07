"""
LLM Provider module for Ungula.

Provides abstraction layer for multiple LLM providers with failover support.
"""

from .anthropic import AnthropicProvider
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
    ToolDefinition,
)
from .google import GoogleProvider
from .nvidia import NVIDIAProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .registry import ProviderRegistry, create_registry_from_config
from .xai import XAIProvider

__all__ = [
    # Base classes
    "LLMProvider",
    "Message",
    "MessageRole",
    "ToolDefinition",
    "ToolCall",
    "CompletionRequest",
    "CompletionResponse",
    "StreamChunk",
    # Errors
    "ProviderError",
    "AuthenticationError",
    "RateLimitError",
    "ModelNotFoundError",
    # Providers
    "OpenRouterProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "GoogleProvider",
    "NVIDIAProvider",
    "OllamaProvider",
    "XAIProvider",
    # Registry
    "ProviderRegistry",
    "create_registry_from_config",
]
