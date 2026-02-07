"""
Tests for context window compaction.

Covers token estimation (with tiktoken and fallback), threshold logic,
and the compact_if_needed async function with mocked LLM calls.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ungula.agents.token_counter import estimate_tokens
from ungula.agents.compaction import (
    COMPACTION_THRESHOLD_RATIO,
    DEFAULT_MAX_CONTEXT_TOKENS,
    MIN_RECENT_MESSAGES,
    SAFETY_MARGIN,
    SUMMARY_SYSTEM_PROMPT,
    compact_if_needed,
)
from ungula.storage.base import Conversation, Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(
    role: str = "user",
    content: str = "Hello",
    conversation_id=None,
) -> Message:
    """Create a storage Message for testing."""
    now = datetime.now(UTC)
    return Message(
        id=uuid4(),
        conversation_id=conversation_id or uuid4(),
        role=role,
        content=content,
        created_at=now,
        metadata={},
    )


def _make_conversation(conversation_id=None, metadata=None) -> Conversation:
    """Create a storage Conversation for testing."""
    now = datetime.now(UTC)
    return Conversation(
        id=conversation_id or uuid4(),
        title="Test",
        created_at=now,
        updated_at=now,
        metadata=metadata or {},
    )


def _make_messages(n: int, content: str = "Test message", conversation_id=None):
    """Create n messages with the given content."""
    cid = conversation_id or uuid4()
    messages = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(_make_message(role=role, content=content, conversation_id=cid))
    return messages


# ===========================================================================
# estimate_tokens
# ===========================================================================


class TestEstimateTokens:
    """Tests for the estimate_tokens function."""

    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_none_returns_zero(self):
        """None is falsy; estimate_tokens should return 0."""
        assert estimate_tokens(None) == 0

    def test_short_text(self):
        result = estimate_tokens("hello")
        assert isinstance(result, int)
        assert result > 0

    def test_longer_text_more_tokens(self):
        short = estimate_tokens("hi")
        long = estimate_tokens("This is a much longer sentence with many words in it.")
        assert long > short

    def test_single_character(self):
        result = estimate_tokens("a")
        assert result >= 1

    def test_whitespace_only(self):
        result = estimate_tokens("   ")
        assert result >= 1  # Whitespace has tokens

    def test_very_long_text(self):
        text = "word " * 10_000  # ~50k characters
        result = estimate_tokens(text)
        # Should be a large number but finite
        assert result > 1000
        assert result < 100_000

    def test_unicode_text(self):
        result = estimate_tokens("Hello world! Bonjour le monde!")
        assert result > 0

    def test_deterministic(self):
        """Same input should give same output."""
        text = "The quick brown fox jumps over the lazy dog."
        assert estimate_tokens(text) == estimate_tokens(text)


class TestTokenCounterFallback:
    """Test the heuristic fallback when tiktoken is unavailable."""

    def test_fallback_uses_char_division(self):
        """When tiktoken is unavailable, fallback divides by 4."""
        with patch("ungula.agents.token_counter._get_tiktoken_encoding", return_value=None):
            result = estimate_tokens("abcdefghijklmnop")  # 16 chars
            assert result == 4  # 16 // 4

    def test_fallback_minimum_one_token(self):
        """Fallback returns at least 1 for non-empty strings."""
        with patch("ungula.agents.token_counter._get_tiktoken_encoding", return_value=None):
            result = estimate_tokens("ab")  # 2 chars -> 2 // 4 = 0 -> max(1, 0) = 1
            assert result == 1

    def test_fallback_empty_string(self):
        """Empty string returns 0 even in fallback."""
        with patch("ungula.agents.token_counter._get_tiktoken_encoding", return_value=None):
            assert estimate_tokens("") == 0

    def test_fallback_longer_text(self):
        with patch("ungula.agents.token_counter._get_tiktoken_encoding", return_value=None):
            text = "a" * 100  # 100 chars -> 25 tokens
            assert estimate_tokens(text) == 25


class TestTokenCounterWithTiktoken:
    """Test that tiktoken integration works when available."""

    def test_tiktoken_returns_int(self):
        """If tiktoken is available, estimate_tokens should return an int."""
        try:
            import tiktoken  # noqa: F401
        except ImportError:
            pytest.skip("tiktoken not installed")
        result = estimate_tokens("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_tiktoken_known_value(self):
        """Test against a known token count for a simple string."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            expected = len(enc.encode("Hello, world!"))
        except ImportError:
            pytest.skip("tiktoken not installed")
        result = estimate_tokens("Hello, world!")
        assert result == expected


# ===========================================================================
# compact_if_needed
# ===========================================================================


class TestCompactIfNeeded:
    """Tests for the compact_if_needed async function."""

    def _make_registry_mock(self, summary_text: str = "This is a summary."):
        """Create a mocked ProviderRegistry that returns a summary."""
        mock_response = MagicMock()
        mock_response.content = summary_text
        registry = MagicMock()
        registry.complete = AsyncMock(return_value=mock_response)
        return registry

    def _make_storage_mock(self, conversation=None):
        """Create a mocked StorageBackend."""
        storage = MagicMock()
        storage.get_conversation = AsyncMock(return_value=conversation)
        storage.update_conversation = AsyncMock(return_value=conversation)
        return storage

    async def test_no_compaction_when_few_messages(self):
        """Messages <= MIN_RECENT_MESSAGES should return as-is."""
        messages = _make_messages(MIN_RECENT_MESSAGES)
        registry = self._make_registry_mock()
        storage = self._make_storage_mock()

        result = await compact_if_needed(
            messages=messages,
            system_prompt="You are helpful.",
            registry=registry,
            storage=storage,
            conversation_id=uuid4(),
        )

        assert result == messages
        registry.complete.assert_not_called()

    async def test_no_compaction_when_under_threshold(self):
        """If total tokens are under threshold, no compaction occurs."""
        # MIN_RECENT_MESSAGES + 1 short messages should stay under threshold
        messages = _make_messages(MIN_RECENT_MESSAGES + 1, content="Hi")
        registry = self._make_registry_mock()
        storage = self._make_storage_mock()

        result = await compact_if_needed(
            messages=messages,
            system_prompt="Short prompt",
            registry=registry,
            storage=storage,
            conversation_id=uuid4(),
        )

        assert result == messages
        registry.complete.assert_not_called()

    async def test_compaction_triggered_over_threshold(self):
        """When tokens exceed threshold, compaction should trigger."""
        conv_id = uuid4()
        conversation = _make_conversation(conversation_id=conv_id)
        registry = self._make_registry_mock("Summarized conversation.")
        storage = self._make_storage_mock(conversation=conversation)

        # Create many long messages to exceed the threshold
        # Threshold = max_context * 0.4 * 1.2 = 100000 * 0.48 = 48000 tokens
        # Each message ~250 tokens -> need ~200 messages
        long_content = "This is a reasonably long message. " * 50  # ~250 tokens
        messages = _make_messages(30, content=long_content, conversation_id=conv_id)

        result = await compact_if_needed(
            messages=messages,
            system_prompt="System prompt here.",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            max_context_tokens=1000,  # Low threshold so we trigger compaction
        )

        # Result should be a tuple (recent_messages, summary)
        assert isinstance(result, tuple)
        recent_messages, summary = result
        assert summary == "Summarized conversation."
        assert len(recent_messages) >= MIN_RECENT_MESSAGES
        assert len(recent_messages) < len(messages)

        # Registry should have been called for summarization
        registry.complete.assert_called_once()

    async def test_compaction_stores_metadata(self):
        """Compaction should persist the summary to conversation metadata."""
        conv_id = uuid4()
        conversation = _make_conversation(conversation_id=conv_id)
        registry = self._make_registry_mock("The summary.")
        storage = self._make_storage_mock(conversation=conversation)

        long_content = "Verbose message content. " * 100
        messages = _make_messages(20, content=long_content, conversation_id=conv_id)

        await compact_if_needed(
            messages=messages,
            system_prompt="Prompt",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            max_context_tokens=500,  # Very low to force compaction
        )

        storage.get_conversation.assert_called_once_with(conv_id)
        storage.update_conversation.assert_called_once()
        call_kwargs = storage.update_conversation.call_args
        metadata = call_kwargs[1]["metadata"] if "metadata" in call_kwargs[1] else call_kwargs[0][1]
        assert "compaction_summary" in metadata
        assert metadata["compaction_summary"] == "The summary."

    async def test_compaction_returns_original_on_empty_summary(self):
        """If LLM returns empty summary, keep full history."""
        conv_id = uuid4()
        # Registry returns None (failure)
        mock_response = MagicMock()
        mock_response.content = None
        registry = MagicMock()
        registry.complete = AsyncMock(return_value=mock_response)

        storage = self._make_storage_mock()

        long_content = "Very long message " * 100
        messages = _make_messages(20, content=long_content, conversation_id=conv_id)

        result = await compact_if_needed(
            messages=messages,
            system_prompt="Prompt",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            max_context_tokens=100,
        )

        # Should return original messages since summary was empty/None
        assert result == messages

    async def test_compaction_handles_llm_exception(self):
        """If LLM raises an exception, return original messages."""
        conv_id = uuid4()
        registry = MagicMock()
        registry.complete = AsyncMock(side_effect=Exception("LLM error"))
        storage = self._make_storage_mock()

        long_content = "Long message content " * 100
        messages = _make_messages(20, content=long_content, conversation_id=conv_id)

        result = await compact_if_needed(
            messages=messages,
            system_prompt="Prompt",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            max_context_tokens=100,
        )

        # _summarize_messages catches exceptions and returns None
        # compact_if_needed then returns original messages
        assert result == messages

    async def test_compaction_keeps_min_recent_messages(self):
        """At least MIN_RECENT_MESSAGES should be kept after compaction."""
        conv_id = uuid4()
        conversation = _make_conversation(conversation_id=conv_id)
        registry = self._make_registry_mock("Summary")
        storage = self._make_storage_mock(conversation=conversation)

        long_content = "Message content " * 80
        messages = _make_messages(20, content=long_content, conversation_id=conv_id)

        result = await compact_if_needed(
            messages=messages,
            system_prompt="Prompt",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            max_context_tokens=100,
        )

        assert isinstance(result, tuple)
        recent, summary = result
        assert len(recent) >= MIN_RECENT_MESSAGES

    async def test_compaction_with_custom_max_tokens(self):
        """max_context_tokens parameter should control the threshold."""
        conv_id = uuid4()
        conversation = _make_conversation(conversation_id=conv_id)
        registry = self._make_registry_mock("Summary")
        storage = self._make_storage_mock(conversation=conversation)

        # Use a very small max to force compaction with moderate messages
        content = "This is a test message with some content."
        messages = _make_messages(15, content=content, conversation_id=conv_id)

        result = await compact_if_needed(
            messages=messages,
            system_prompt="Short",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            max_context_tokens=50,  # Very low threshold
        )

        # Should trigger compaction
        assert isinstance(result, tuple)
        registry.complete.assert_called_once()

    async def test_compaction_storage_failure_still_returns(self):
        """Even if storage update fails, compaction result is returned."""
        conv_id = uuid4()
        conversation = _make_conversation(conversation_id=conv_id)
        registry = self._make_registry_mock("Summary text")

        storage = MagicMock()
        storage.get_conversation = AsyncMock(return_value=conversation)
        storage.update_conversation = AsyncMock(side_effect=Exception("DB error"))

        long_content = "Long repeated content. " * 100
        messages = _make_messages(20, content=long_content, conversation_id=conv_id)

        result = await compact_if_needed(
            messages=messages,
            system_prompt="Prompt",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            max_context_tokens=100,
        )

        # Should still return compacted result despite storage failure
        assert isinstance(result, tuple)
        recent, summary = result
        assert summary == "Summary text"

    async def test_compaction_with_provider_kwarg(self):
        """Provider kwarg should be forwarded to registry.complete."""
        conv_id = uuid4()
        conversation = _make_conversation(conversation_id=conv_id)
        registry = self._make_registry_mock("Summary")
        storage = self._make_storage_mock(conversation=conversation)

        long_content = "Verbose " * 200
        messages = _make_messages(20, content=long_content, conversation_id=conv_id)

        await compact_if_needed(
            messages=messages,
            system_prompt="Prompt",
            registry=registry,
            storage=storage,
            conversation_id=conv_id,
            provider="anthropic",
            max_context_tokens=100,
        )

        # Check that provider was passed to registry.complete
        registry.complete.assert_called_once()
        call_kwargs = registry.complete.call_args
        assert call_kwargs[1].get("provider") == "anthropic" or (
            len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "anthropic"
        )


# ===========================================================================
# Constants
# ===========================================================================


class TestCompactionConstants:
    """Tests that compaction constants have sensible values."""

    def test_default_max_context_tokens(self):
        assert DEFAULT_MAX_CONTEXT_TOKENS == 100_000

    def test_compaction_threshold_ratio(self):
        assert 0.0 < COMPACTION_THRESHOLD_RATIO < 1.0

    def test_min_recent_messages(self):
        assert MIN_RECENT_MESSAGES >= 1

    def test_safety_margin(self):
        assert SAFETY_MARGIN >= 1.0

    def test_summary_system_prompt_is_nonempty(self):
        assert len(SUMMARY_SYSTEM_PROMPT) > 0
        assert "summarize" in SUMMARY_SYSTEM_PROMPT.lower()
