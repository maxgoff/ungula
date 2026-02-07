"""
Agent module for Ungula.

Provides the agent runtime for processing chat messages through LLM providers.
Uses intent classification for semantic understanding of user queries.
"""

from .base import AgentContext, ChatResult, StreamEvent
from .context import SystemPromptBuilder, build_context
from .intent import IntentClassification, IntentClassifier, IntentType
from .runner import AgentRunner

__all__ = [
    "AgentContext",
    "AgentRunner",
    "ChatResult",
    "IntentClassification",
    "IntentClassifier",
    "IntentType",
    "StreamEvent",
    "SystemPromptBuilder",
    "build_context",
]
