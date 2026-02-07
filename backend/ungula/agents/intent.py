"""
Intent Classification for Ungula.

Uses an LLM to understand user intent and route queries appropriately.
Handles semantic disambiguation and asks for clarification when needed.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..llm.base import CompletionRequest, Message as LLMMessage, MessageRole
from ..llm.registry import ProviderRegistry
from ..tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Types of user intent."""
    SYSTEM_INQUIRY = "system_inquiry"  # Asking about Ungula's capabilities/tools
    WEB_SEARCH = "web_search"  # Needs real-time information
    GENERAL_CONVERSATION = "general_conversation"  # Normal chat
    TASK_REQUEST = "task_request"  # Asking to perform an action
    CLARIFICATION_NEEDED = "clarification_needed"  # Ambiguous, need to ask user
    UNKNOWN = "unknown"


@dataclass
class IntentClassification:
    """Result of intent classification."""
    primary_intent: IntentType
    confidence: float  # 0.0 to 1.0
    interpretations: list[dict[str, Any]] = field(default_factory=list)
    clarification_question: str | None = None
    reasoning: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


SYSTEM_CONTEXT = """
# About Ungula

Ungula is an autonomous AI agent platform. It consists of:

## Architecture
- **Backend**: Python/FastAPI server that orchestrates AI capabilities
- **LLM Providers**: Connects to multiple LLM providers (xAI/Grok, Ollama, OpenAI, Anthropic, etc.)
- **Tool Registry**: Extensible system for adding capabilities
- **Messaging Channels**: Telegram, Discord integration for communication

## Currently Registered Tools
{tools_description}

## What Ungula Can Do
- Answer questions using connected LLM providers
- Perform web searches for real-time information (via web_search tool)
- Maintain conversation context and memory
- Process messages from multiple channels (Telegram, Discord)

## What "Tools" Means in This Context
When a user asks about "tools" in Ungula, they could mean:
1. **Ungula's registered tools** - Actual capabilities like web_search that extend the system
2. **LLM capabilities** - What the underlying AI model can do (translate, summarize, etc.)
3. **Development tools** - If they're a developer asking about the codebase
4. **Something else entirely** - Tools in a different domain context
"""

INTENT_CLASSIFICATION_PROMPT = """
You are an intent classifier for Ungula, an AI agent platform.

Given the system context and user message, classify the user's intent.

{system_context}

## User Message
"{user_message}"

## Your Task
Analyze what the user is really asking. Consider:
1. What do ambiguous terms like "tools", "we", "you" refer to?
2. Is this a question about the Ungula system itself, or a general query?
3. Does this require real-time information (web search)?
4. Is the intent clear or ambiguous?

Respond with a JSON object:
{{
    "primary_intent": "system_inquiry" | "web_search" | "general_conversation" | "task_request" | "clarification_needed",
    "confidence": 0.0-1.0,
    "interpretations": [
        {{"meaning": "what user might mean", "probability": 0.0-1.0}}
    ],
    "clarification_question": "question to ask if ambiguous (or null)",
    "reasoning": "brief explanation of your classification"
}}

IMPORTANT RULES:
- Default to "general_conversation" when in doubt. Most messages are just conversation.
- Only use "clarification_needed" when the message is truly unintelligible or dangerously ambiguous (e.g., could cause harm if misinterpreted). This should be extremely rare.
- Do NOT use "clarification_needed" for requests the system can't fulfill — just classify as "general_conversation" and let the LLM explain what it can/can't do.
- "system_inquiry" is ONLY for explicit questions about Ungula's capabilities, features, or tools.
- "web_search" is for questions needing real-time data (prices, weather, news, current events).

Respond ONLY with the JSON object, no other text.
"""


class IntentClassifier:
    """
    Classifies user intent using an LLM.

    Uses semantic understanding to route queries appropriately
    and asks for clarification when intent is ambiguous.
    """

    def __init__(
        self,
        llm_registry: ProviderRegistry,
        tool_registry: ToolRegistry | None = None,
        provider: str | None = None,
        model: str | None = None,
    ):
        """
        Initialize intent classifier.

        Args:
            llm_registry: Registry of LLM providers.
            tool_registry: Registry of available tools.
            provider: LLM provider to use for classification.
            model: Model to use (defaults to provider's default).
        """
        self.llm_registry = llm_registry
        self.tool_registry = tool_registry
        self.provider = provider
        self.model = model

    def _get_tools_description(self) -> str:
        """Get description of registered tools."""
        if not self.tool_registry:
            return "No tools currently registered."

        tools = self.tool_registry.get_all()
        if not tools:
            return "No tools currently registered."

        lines = []
        for tool in tools:
            lines.append(f"- **{tool.name}**: {tool.description}")

        return "\n".join(lines)

    def _build_system_context(self) -> str:
        """Build the system context for intent classification."""
        tools_desc = self._get_tools_description()
        return SYSTEM_CONTEXT.format(tools_description=tools_desc)

    async def classify(self, user_message: str) -> IntentClassification:
        """
        Classify the user's intent.

        Args:
            user_message: The user's message to classify.

        Returns:
            IntentClassification with the classified intent and metadata.
        """
        system_context = self._build_system_context()

        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            system_context=system_context,
            user_message=user_message,
        )

        messages = [
            LLMMessage(role=MessageRole.USER, content=prompt)
        ]

        request = CompletionRequest(
            messages=messages,
            temperature=0.3,  # Lower temperature for more consistent classification
            max_tokens=500,
        )

        try:
            response = await self.llm_registry.complete(
                request,
                provider=self.provider,
            )

            if not response.content:
                logger.warning("Empty response from intent classifier")
                return self._default_classification(user_message)

            return self._parse_classification(response.content, user_message)

        except Exception as e:
            logger.error("Intent classification failed: %s", e, exc_info=True)
            return self._default_classification(user_message)

    def _parse_classification(self, response: str, user_message: str) -> IntentClassification:
        """Parse the LLM response into an IntentClassification."""
        try:
            # Try to extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                # Remove markdown code blocks
                lines = response.split("\n")
                response = "\n".join(lines[1:-1])

            data = json.loads(response)

            intent_str = data.get("primary_intent", "unknown")
            try:
                intent = IntentType(intent_str)
            except ValueError:
                intent = IntentType.UNKNOWN

            return IntentClassification(
                primary_intent=intent,
                confidence=float(data.get("confidence", 0.5)),
                interpretations=data.get("interpretations", []),
                clarification_question=data.get("clarification_question"),
                reasoning=data.get("reasoning"),
            )

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse intent classification JSON: %s", e)
            return self._default_classification(user_message)

    def _default_classification(self, user_message: str) -> IntentClassification:
        """Return a default classification when parsing fails."""
        # Simple heuristic fallback
        msg_lower = user_message.lower()

        if any(word in msg_lower for word in ["price", "weather", "news", "current", "latest", "today"]):
            return IntentClassification(
                primary_intent=IntentType.WEB_SEARCH,
                confidence=0.6,
                reasoning="Fallback: detected keywords suggesting real-time info needed",
            )

        return IntentClassification(
            primary_intent=IntentType.GENERAL_CONVERSATION,
            confidence=0.5,
            reasoning="Fallback: defaulting to general conversation",
        )
