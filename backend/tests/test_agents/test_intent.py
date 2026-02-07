"""
Tests for intent classification.

Covers IntentType enum, IntentClassification dataclass,
IntentClassifier methods including classify, _parse_classification,
_default_classification, and _get_tools_description.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ungula.agents.intent import (
    IntentClassification,
    IntentClassifier,
    IntentType,
    SYSTEM_CONTEXT,
)
from ungula.llm.base import CompletionResponse
from ungula.tools.base import Tool, ToolParameter, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeTool(Tool):
    """A minimal Tool implementation for testing."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.parameters = []

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="ok")


def _make_registry_mock(content: str = "{}"):
    """Create a mocked ProviderRegistry that returns content."""
    mock_response = MagicMock(spec=CompletionResponse)
    mock_response.content = content
    registry = MagicMock()
    registry.complete = AsyncMock(return_value=mock_response)
    return registry


# ===========================================================================
# IntentType enum
# ===========================================================================


class TestIntentType:
    """Tests for the IntentType enum."""

    def test_system_inquiry_value(self):
        assert IntentType.SYSTEM_INQUIRY.value == "system_inquiry"

    def test_web_search_value(self):
        assert IntentType.WEB_SEARCH.value == "web_search"

    def test_general_conversation_value(self):
        assert IntentType.GENERAL_CONVERSATION.value == "general_conversation"

    def test_task_request_value(self):
        assert IntentType.TASK_REQUEST.value == "task_request"

    def test_clarification_needed_value(self):
        assert IntentType.CLARIFICATION_NEEDED.value == "clarification_needed"

    def test_unknown_value(self):
        assert IntentType.UNKNOWN.value == "unknown"

    def test_all_members_present(self):
        expected = {
            "SYSTEM_INQUIRY",
            "WEB_SEARCH",
            "GENERAL_CONVERSATION",
            "TASK_REQUEST",
            "CLARIFICATION_NEEDED",
            "UNKNOWN",
        }
        assert set(IntentType.__members__.keys()) == expected

    def test_from_string(self):
        assert IntentType("web_search") == IntentType.WEB_SEARCH

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            IntentType("nonexistent")


# ===========================================================================
# IntentClassification dataclass
# ===========================================================================


class TestIntentClassification:
    """Tests for the IntentClassification dataclass."""

    def test_creation_with_required_fields(self):
        ic = IntentClassification(
            primary_intent=IntentType.GENERAL_CONVERSATION,
            confidence=0.8,
        )
        assert ic.primary_intent == IntentType.GENERAL_CONVERSATION
        assert ic.confidence == 0.8

    def test_default_interpretations_empty(self):
        ic = IntentClassification(
            primary_intent=IntentType.UNKNOWN,
            confidence=0.5,
        )
        assert ic.interpretations == []

    def test_default_clarification_question_none(self):
        ic = IntentClassification(
            primary_intent=IntentType.UNKNOWN,
            confidence=0.5,
        )
        assert ic.clarification_question is None

    def test_default_reasoning_none(self):
        ic = IntentClassification(
            primary_intent=IntentType.UNKNOWN,
            confidence=0.5,
        )
        assert ic.reasoning is None

    def test_default_metadata_empty(self):
        ic = IntentClassification(
            primary_intent=IntentType.UNKNOWN,
            confidence=0.5,
        )
        assert ic.metadata == {}

    def test_full_creation(self):
        ic = IntentClassification(
            primary_intent=IntentType.CLARIFICATION_NEEDED,
            confidence=0.4,
            interpretations=[
                {"meaning": "system tools", "probability": 0.6},
                {"meaning": "dev tools", "probability": 0.4},
            ],
            clarification_question="Do you mean system tools or dev tools?",
            reasoning="Ambiguous use of 'tools'",
            metadata={"source": "test"},
        )
        assert ic.primary_intent == IntentType.CLARIFICATION_NEEDED
        assert len(ic.interpretations) == 2
        assert ic.clarification_question is not None
        assert ic.reasoning == "Ambiguous use of 'tools'"
        assert ic.metadata["source"] == "test"

    def test_separate_instances_have_independent_lists(self):
        ic1 = IntentClassification(
            primary_intent=IntentType.UNKNOWN, confidence=0.5
        )
        ic2 = IntentClassification(
            primary_intent=IntentType.UNKNOWN, confidence=0.5
        )
        ic1.interpretations.append({"meaning": "test"})
        assert len(ic2.interpretations) == 0


# ===========================================================================
# IntentClassifier._get_tools_description
# ===========================================================================


class TestGetToolsDescription:
    """Tests for IntentClassifier._get_tools_description."""

    def test_no_tool_registry(self):
        registry = _make_registry_mock()
        classifier = IntentClassifier(llm_registry=registry, tool_registry=None)
        result = classifier._get_tools_description()
        assert result == "No tools currently registered."

    def test_empty_tool_registry(self):
        registry = _make_registry_mock()
        tool_registry = ToolRegistry()
        classifier = IntentClassifier(
            llm_registry=registry, tool_registry=tool_registry
        )
        result = classifier._get_tools_description()
        assert result == "No tools currently registered."

    def test_with_tools(self):
        registry = _make_registry_mock()
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search the web"))
        tool_registry.register(_FakeTool("shell_exec", "Execute shell commands"))
        classifier = IntentClassifier(
            llm_registry=registry, tool_registry=tool_registry
        )
        result = classifier._get_tools_description()
        assert "web_search" in result
        assert "Search the web" in result
        assert "shell_exec" in result
        assert "Execute shell commands" in result

    def test_tools_description_format(self):
        registry = _make_registry_mock()
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("my_tool", "Does something"))
        classifier = IntentClassifier(
            llm_registry=registry, tool_registry=tool_registry
        )
        result = classifier._get_tools_description()
        assert result.startswith("- **my_tool**:")


# ===========================================================================
# IntentClassifier._parse_classification
# ===========================================================================


class TestParseClassification:
    """Tests for IntentClassifier._parse_classification."""

    def _make_classifier(self):
        registry = _make_registry_mock()
        return IntentClassifier(llm_registry=registry)

    def test_valid_json(self):
        classifier = self._make_classifier()
        response = json.dumps({
            "primary_intent": "web_search",
            "confidence": 0.9,
            "interpretations": [{"meaning": "search", "probability": 0.9}],
            "clarification_question": None,
            "reasoning": "User wants to search",
        })
        result = classifier._parse_classification(response, "test message")
        assert result.primary_intent == IntentType.WEB_SEARCH
        assert result.confidence == 0.9
        assert len(result.interpretations) == 1
        assert result.reasoning == "User wants to search"

    def test_code_block_wrapped_json(self):
        classifier = self._make_classifier()
        response = '```json\n{"primary_intent": "task_request", "confidence": 0.85}\n```'
        result = classifier._parse_classification(response, "test message")
        assert result.primary_intent == IntentType.TASK_REQUEST
        assert result.confidence == 0.85

    def test_code_block_without_language_tag(self):
        classifier = self._make_classifier()
        response = '```\n{"primary_intent": "general_conversation", "confidence": 0.7}\n```'
        result = classifier._parse_classification(response, "test message")
        assert result.primary_intent == IntentType.GENERAL_CONVERSATION

    def test_invalid_json_falls_back(self):
        classifier = self._make_classifier()
        result = classifier._parse_classification("not json at all", "what is the price of BTC")
        # Should fallback; "price" triggers web_search heuristic
        assert result.primary_intent == IntentType.WEB_SEARCH

    def test_invalid_json_default_conversation(self):
        classifier = self._make_classifier()
        result = classifier._parse_classification("not json at all", "hello there")
        assert result.primary_intent == IntentType.GENERAL_CONVERSATION

    def test_unknown_intent_value(self):
        classifier = self._make_classifier()
        response = json.dumps({
            "primary_intent": "nonexistent_intent",
            "confidence": 0.5,
        })
        result = classifier._parse_classification(response, "test")
        assert result.primary_intent == IntentType.UNKNOWN

    def test_missing_confidence_defaults(self):
        classifier = self._make_classifier()
        response = json.dumps({"primary_intent": "general_conversation"})
        result = classifier._parse_classification(response, "test")
        assert result.confidence == 0.5  # Default

    def test_missing_interpretations_defaults(self):
        classifier = self._make_classifier()
        response = json.dumps({
            "primary_intent": "general_conversation",
            "confidence": 0.8,
        })
        result = classifier._parse_classification(response, "test")
        assert result.interpretations == []

    def test_missing_clarification_question_defaults_none(self):
        classifier = self._make_classifier()
        response = json.dumps({
            "primary_intent": "general_conversation",
            "confidence": 0.8,
        })
        result = classifier._parse_classification(response, "test")
        assert result.clarification_question is None

    def test_whitespace_around_json(self):
        classifier = self._make_classifier()
        response = '  \n  {"primary_intent": "system_inquiry", "confidence": 0.95}  \n  '
        result = classifier._parse_classification(response, "test")
        assert result.primary_intent == IntentType.SYSTEM_INQUIRY
        assert result.confidence == 0.95


# ===========================================================================
# IntentClassifier._default_classification
# ===========================================================================


class TestDefaultClassification:
    """Tests for IntentClassifier._default_classification."""

    def _make_classifier(self):
        registry = _make_registry_mock()
        return IntentClassifier(llm_registry=registry)

    def test_keyword_price_triggers_web_search(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("What is the price of gold?")
        assert result.primary_intent == IntentType.WEB_SEARCH
        assert result.confidence == 0.6

    def test_keyword_weather_triggers_web_search(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("What's the weather like?")
        assert result.primary_intent == IntentType.WEB_SEARCH

    def test_keyword_news_triggers_web_search(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("Show me the latest news")
        assert result.primary_intent == IntentType.WEB_SEARCH

    def test_keyword_current_triggers_web_search(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("What are current events?")
        assert result.primary_intent == IntentType.WEB_SEARCH

    def test_keyword_latest_triggers_web_search(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("What's the latest update?")
        assert result.primary_intent == IntentType.WEB_SEARCH

    def test_keyword_today_triggers_web_search(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("What happened today?")
        assert result.primary_intent == IntentType.WEB_SEARCH

    def test_no_keyword_defaults_to_conversation(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("Tell me about Python programming")
        assert result.primary_intent == IntentType.GENERAL_CONVERSATION
        assert result.confidence == 0.5

    def test_default_has_reasoning(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("hello")
        assert result.reasoning is not None
        assert "fallback" in result.reasoning.lower()

    def test_web_search_fallback_has_reasoning(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("latest news")
        assert result.reasoning is not None
        assert "fallback" in result.reasoning.lower()

    def test_case_insensitive_keywords(self):
        classifier = self._make_classifier()
        result = classifier._default_classification("WHAT IS THE PRICE?")
        assert result.primary_intent == IntentType.WEB_SEARCH


# ===========================================================================
# IntentClassifier.classify
# ===========================================================================


class TestClassify:
    """Tests for IntentClassifier.classify."""

    async def test_successful_classification(self):
        response_data = json.dumps({
            "primary_intent": "task_request",
            "confidence": 0.85,
            "interpretations": [],
            "clarification_question": None,
            "reasoning": "User wants to perform an action",
        })
        registry = _make_registry_mock(response_data)
        classifier = IntentClassifier(llm_registry=registry)

        result = await classifier.classify("Run the tests")
        assert result.primary_intent == IntentType.TASK_REQUEST
        assert result.confidence == 0.85
        registry.complete.assert_called_once()

    async def test_empty_response_falls_back(self):
        mock_response = MagicMock()
        mock_response.content = None
        registry = MagicMock()
        registry.complete = AsyncMock(return_value=mock_response)
        classifier = IntentClassifier(llm_registry=registry)

        result = await classifier.classify("hello there")
        assert result.primary_intent == IntentType.GENERAL_CONVERSATION

    async def test_empty_string_response_falls_back(self):
        mock_response = MagicMock()
        mock_response.content = ""
        registry = MagicMock()
        registry.complete = AsyncMock(return_value=mock_response)
        classifier = IntentClassifier(llm_registry=registry)

        result = await classifier.classify("hello")
        # Empty string is falsy, so it falls back
        assert result.primary_intent == IntentType.GENERAL_CONVERSATION

    async def test_llm_exception_falls_back(self):
        registry = MagicMock()
        registry.complete = AsyncMock(side_effect=Exception("LLM unavailable"))
        classifier = IntentClassifier(llm_registry=registry)

        result = await classifier.classify("Tell me about the weather")
        # "weather" keyword -> WEB_SEARCH fallback
        assert result.primary_intent == IntentType.WEB_SEARCH

    async def test_llm_exception_no_keyword_falls_back_to_conversation(self):
        registry = MagicMock()
        registry.complete = AsyncMock(side_effect=RuntimeError("Connection failed"))
        classifier = IntentClassifier(llm_registry=registry)

        result = await classifier.classify("help me with something")
        assert result.primary_intent == IntentType.GENERAL_CONVERSATION

    async def test_provider_passed_to_registry(self):
        response_data = json.dumps({
            "primary_intent": "general_conversation",
            "confidence": 0.9,
        })
        registry = _make_registry_mock(response_data)
        classifier = IntentClassifier(
            llm_registry=registry, provider="anthropic"
        )

        await classifier.classify("hello")
        call_kwargs = registry.complete.call_args
        assert call_kwargs[1].get("provider") == "anthropic"

    async def test_request_uses_low_temperature(self):
        response_data = json.dumps({
            "primary_intent": "general_conversation",
            "confidence": 0.9,
        })
        registry = _make_registry_mock(response_data)
        classifier = IntentClassifier(llm_registry=registry)

        await classifier.classify("hello")
        call_args = registry.complete.call_args[0]
        request = call_args[0]
        assert request.temperature == 0.3

    async def test_classify_with_tool_registry(self):
        response_data = json.dumps({
            "primary_intent": "system_inquiry",
            "confidence": 0.95,
        })
        registry = _make_registry_mock(response_data)
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("web_search", "Search the web"))
        classifier = IntentClassifier(
            llm_registry=registry, tool_registry=tool_registry
        )

        result = await classifier.classify("What tools do you have?")
        assert result.primary_intent == IntentType.SYSTEM_INQUIRY


# ===========================================================================
# IntentClassifier._build_system_context
# ===========================================================================


class TestBuildSystemContext:
    """Tests for _build_system_context."""

    def test_includes_tools_description(self):
        registry = _make_registry_mock()
        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("search", "Search things"))
        classifier = IntentClassifier(
            llm_registry=registry, tool_registry=tool_registry
        )
        context = classifier._build_system_context()
        assert "search" in context
        assert "Search things" in context

    def test_no_tools_says_none_registered(self):
        registry = _make_registry_mock()
        classifier = IntentClassifier(llm_registry=registry, tool_registry=None)
        context = classifier._build_system_context()
        assert "No tools currently registered" in context
