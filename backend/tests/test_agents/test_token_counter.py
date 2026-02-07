"""
Tests for token counting utilities.

Covers estimate_tokens and estimate_messages_tokens with both the
tiktoken path and the heuristic fallback.
"""

from unittest.mock import patch

import pytest

from ungula.agents.token_counter import estimate_messages_tokens, estimate_tokens


# ===========================================================================
# estimate_tokens
# ===========================================================================


class TestEstimateTokens:
    """Tests for the estimate_tokens function."""

    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_none_returns_zero(self):
        """None is falsy, should return 0."""
        assert estimate_tokens(None) == 0

    def test_non_empty_returns_positive(self):
        result = estimate_tokens("Hello, world!")
        assert result > 0

    def test_short_text(self):
        result = estimate_tokens("hi")
        assert isinstance(result, int)
        assert result >= 1

    def test_longer_text_has_more_tokens(self):
        short = estimate_tokens("hi")
        long_text = estimate_tokens(
            "This is a significantly longer sentence with many more words and tokens."
        )
        assert long_text > short

    def test_single_character(self):
        result = estimate_tokens("a")
        assert result >= 1

    def test_whitespace_only(self):
        result = estimate_tokens("   ")
        assert result >= 1

    def test_deterministic(self):
        text = "The quick brown fox jumps over the lazy dog."
        assert estimate_tokens(text) == estimate_tokens(text)

    def test_unicode_text(self):
        result = estimate_tokens("Bonjour le monde! Hola mundo!")
        assert result > 0

    def test_very_long_text(self):
        text = "word " * 5000
        result = estimate_tokens(text)
        assert result > 500
        assert result < 50_000

    def test_newlines_counted(self):
        result = estimate_tokens("line1\nline2\nline3")
        assert result > 0

    def test_code_text(self):
        code = "def foo(x):\n    return x * 2\n"
        result = estimate_tokens(code)
        assert result > 0


class TestEstimateTokensFallback:
    """Test the heuristic fallback when tiktoken is unavailable."""

    def test_fallback_char_division(self):
        with patch(
            "ungula.agents.token_counter._get_tiktoken_encoding", return_value=None
        ):
            result = estimate_tokens("abcdefghijklmnop")  # 16 chars
            assert result == 4  # 16 // 4

    def test_fallback_minimum_one_token(self):
        with patch(
            "ungula.agents.token_counter._get_tiktoken_encoding", return_value=None
        ):
            result = estimate_tokens("ab")  # 2 chars -> max(1, 0) = 1
            assert result == 1

    def test_fallback_empty_string(self):
        with patch(
            "ungula.agents.token_counter._get_tiktoken_encoding", return_value=None
        ):
            assert estimate_tokens("") == 0

    def test_fallback_exactly_four_chars(self):
        with patch(
            "ungula.agents.token_counter._get_tiktoken_encoding", return_value=None
        ):
            result = estimate_tokens("abcd")  # 4 chars -> 4 // 4 = 1
            assert result == 1

    def test_fallback_100_chars(self):
        with patch(
            "ungula.agents.token_counter._get_tiktoken_encoding", return_value=None
        ):
            result = estimate_tokens("a" * 100)  # 100 // 4 = 25
            assert result == 25


class TestEstimateTokensWithTiktoken:
    """Test tiktoken integration when available."""

    def test_tiktoken_returns_int(self):
        try:
            import tiktoken  # noqa: F401
        except ImportError:
            pytest.skip("tiktoken not installed")
        result = estimate_tokens("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_tiktoken_known_value(self):
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            expected = len(enc.encode("Hello, world!"))
        except ImportError:
            pytest.skip("tiktoken not installed")
        assert estimate_tokens("Hello, world!") == expected


# ===========================================================================
# estimate_messages_tokens
# ===========================================================================


class TestEstimateMessagesTokens:
    """Tests for the estimate_messages_tokens function."""

    def test_empty_list(self):
        result = estimate_messages_tokens([])
        # Only priming tokens (2)
        assert result == 2

    def test_single_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = estimate_messages_tokens(messages)
        # Should be: tokens("Hello") + 4 overhead + 2 priming
        assert result > 2  # More than just priming tokens

    def test_multiple_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = estimate_messages_tokens(messages)
        single = estimate_messages_tokens([messages[0]])
        # Two messages should be more tokens than one
        assert result > single

    def test_overhead_per_message(self):
        """Each message adds 4 tokens of overhead."""
        # With fallback, we can compute exactly
        with patch(
            "ungula.agents.token_counter._get_tiktoken_encoding", return_value=None
        ):
            messages = [{"role": "user", "content": ""}]
            result = estimate_messages_tokens(messages)
            # Empty content = 0 tokens + 4 overhead + 2 priming = 6
            assert result == 6

    def test_priming_tokens(self):
        """Empty list should have 2 priming tokens."""
        result = estimate_messages_tokens([])
        assert result == 2

    def test_message_without_content_key(self):
        """Messages without 'content' key should use empty string."""
        messages = [{"role": "user"}]
        result = estimate_messages_tokens(messages)
        # 0 content tokens + 4 overhead + 2 priming = 6
        assert result >= 6

    def test_messages_with_system_role(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = estimate_messages_tokens(messages)
        assert result > 2

    def test_messages_tokens_increases_with_content_length(self):
        short = estimate_messages_tokens(
            [{"role": "user", "content": "Hi"}]
        )
        long = estimate_messages_tokens(
            [{"role": "user", "content": "This is a much longer message with many words."}]
        )
        assert long > short

    def test_consistent_results(self):
        messages = [
            {"role": "user", "content": "test message"},
            {"role": "assistant", "content": "response"},
        ]
        assert estimate_messages_tokens(messages) == estimate_messages_tokens(messages)

    def test_many_messages(self):
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"}
            for i in range(100)
        ]
        result = estimate_messages_tokens(messages)
        # At least 100 * 4 overhead + 2 priming = 402
        assert result >= 402

    def test_fallback_calculation(self):
        """Verify exact calculation in fallback mode."""
        with patch(
            "ungula.agents.token_counter._get_tiktoken_encoding", return_value=None
        ):
            messages = [
                {"role": "user", "content": "a" * 40},  # 40 chars -> 10 tokens
                {"role": "assistant", "content": "b" * 20},  # 20 chars -> 5 tokens
            ]
            result = estimate_messages_tokens(messages)
            # 10 + 4 + 5 + 4 + 2 = 25
            assert result == 25
